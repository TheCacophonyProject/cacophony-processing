"""
cacophony-processing - this is a server side component that runs alongside
the Cacophony Project API, performing post-upload processing tasks.
Copyright (C) 2019, The Cacophony Project

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import json
import mimetypes
import subprocess
import tempfile
from pathlib import Path

from . import API
from . import logs
from .processutils import HandleCalledProcessError
from .tagger import UNIDENTIFIED
from .thermal import Prediction

MAX_FRQUENCY = 48000 / 2


def track_analyse(recording, jwtKey, conf):
    """Reprocess the audio file.

    Downloads the file, runs the AI model on tracks that have been made by users and dont yet have an AI tag

    Args:
        recording: The recording to process.
        jwtKey: The JWT key to use for the API.
        conf: The configuration object.

    Returns:
        The API response.
    """

    # this used to work by default then  just stopped, so will explicitly add it
    mimetypes.add_type("audio/mp4", ".m4a")

    logger = logs.worker_logger("audio.track_analysis", recording["id"])

    api = API(conf.api_url, conf.user, conf.password, logger)

    input_extension = mimetypes.guess_extension(recording["rawMimeType"])

    if not input_extension:
        # Unsupported mimetype. If needed more mimetypes can be added above.
        logger.error(
            "unsupported mimetype. Not processing %s", recording["rawMimeType"]
        )
        api.report_done(recording, recording["rawFileKey"], recording["rawMimeType"])
        return
    new_metadata = {"additionalMetadata": {}}
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        input_filename = temp_path / ("recording" + input_extension)
        logger.debug("downloading recording to %s", input_filename)

        api.download_file(jwtKey, str(input_filename))
        track_info = api.get_track_info(recording["id"]).get("tracks")
        track_info = [
            t
            for t in track_info
            if not any(tag for tag in t["tags"] if tag["automatic"])
        ]
        recording["Tracks"] = track_info
        filename = input_filename.with_suffix(".txt")
        if "location" in recording:
            location = recording["location"]
            if (
                location is not None
                and "lat" not in location
                and "lng" not in location
                and "coordinates" in location
            ):
                coords = location["coordinates"]
                location["lng"] = coords[0]
                location["lat"] = coords[1]

        with filename.open("w") as f:
            json.dump(recording, f)

        metadata = analyse(input_filename, conf, analyse_tracks=True)
        analysis = AudioResult.load(metadata, metadata.get("duration"), conf.master_tag)
        algorithm_meta = {"algorithm": "sliding_window"}
        if analysis.species_identify_version is not None:
            algorithm_meta["version"] = analysis.species_identify_version
        algorithm_id = api.get_algorithm_id(algorithm_meta)
        for track in analysis.tracks:
            api.add_track_tags(recording, track.id, track.all_predictions())
        # add_tracks_and_tags(api, recording, analysis.tracks, algorithm_id, logger)

    api.report_done(recording, metadata=new_metadata)
    logger.info("Completed classifying for file: %s", recording["id"])


SPECIFIC_NOISE = ["insect"]


def process(recording, jwtKey, conf):
    logger = logs.worker_logger("audio.analysis", recording["id"])
    api = API(conf.api_url, conf.user, conf.password, logger)
    return process_with_api(recording, jwtKey, api, conf, logger)


def process_with_api(recording, jwtKey, api, conf, logger=None):
    """Process the audio file.

    Downloads the file, runs the AI models & cacophony index algorithm,
    and uploads the results to the API.

    Args:
        recording: The recording to process.
        jwtKey: The JWT key to use for the API.
        conf: The configuration object.

    Returns:
        The API response.
    """

    # this used to work by default then  just stopped, so will explicitly add it
    mimetypes.add_type("audio/mp4", ".m4a")
    if logger is None:
        logger = logs.worker_logger("audio.analysis", recording["id"])

    input_extension = mimetypes.guess_extension(recording["rawMimeType"])

    if not input_extension:
        # Unsupported mimetype. If needed more mimetypes can be added above.
        logger.error(
            "unsupported mimetype. Not processing %s", recording["rawMimeType"]
        )
        api.report_done(recording, recording["rawFileKey"], recording["rawMimeType"])
        return

    new_metadata = {"additionalMetadata": {}}
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        input_filename = temp_path / ("recording" + input_extension)
        logger.debug("downloading recording to %s", input_filename)
        api.download_file(jwtKey, str(input_filename))

        filename = input_filename.with_suffix(".txt")
        if "location" in recording:
            location = recording["location"]
            if (
                location is not None
                and "lat" not in location
                and "lng" not in location
                and "coordinates" in location
            ):
                coords = location["coordinates"]
                location["lng"] = coords[0]
                location["lat"] = coords[1]
        if "tracks" in recording:
            del recording["tracks"]
        with filename.open("w") as f:
            json.dump(recording, f)
        metadata = analyse(input_filename, conf)
        new_metadata = {"additionalMetadata": {}}
        duration = recording.get("duration")
        if duration is not None:
            new_metadata["duration"] = duration
        else:
            duration = metadata.get("analysis_result", {}).get("duration")
        analysis = AudioResult.load(metadata, duration, conf.master_tag)
        algorithm_meta = {"algorithm": "sliding_window"}
        if analysis.species_identify_version is not None:
            algorithm_meta["version"] = analysis.species_identify_version
        algorithm_id = api.get_algorithm_id(algorithm_meta)

        add_tracks_and_tags(api, recording, analysis.tracks, algorithm_id, logger)

        if analysis.cacophony_index is not None:
            new_metadata["cacophonyIndex"] = analysis.cacophony_index
            new_metadata["additionalMetadata"][
                "cacophony_index_version"
            ] = analysis.cacophony_index_version
        if analysis.chirp_index is not None:
            new_metadata["additionalMetadata"]["chirpIndex"] = analysis.chirp_index
        if analysis.region_code is not None:
            new_metadata["additionalMetadata"]["regionCode"] = analysis.region_code
        # is there anyhting missing...
        # new_metadata["additionalMetadata"] = analysis
    api.report_done(recording, metadata=new_metadata)
    logger.info("Completed processing for file: %s", recording["id"])


def add_tracks_and_tags(api, recording, tracks, algorithm_id, logger):
    tracks_data = [track.post_data(predictions=True) for track in tracks]
    print("Tracks data is ", tracks_data)
    track_ids = api.add_tracks(recording, tracks_data, algorithm_id)
    for track_id, track in zip(track_ids, tracks):
        track.id = track_id


def analyse(filename, conf, analyse_tracks=False):
    command = conf.audio_analysis_cmd.format(
        folder=filename.parent,
        basename=filename.name,
        tag=conf.audio_analysis_tag,
        analyse_tracks=analyse_tracks,
    )
    with HandleCalledProcessError():
        proc = subprocess.run(
            command,
            shell=True,
            stderr=subprocess.PIPE,
            timeout=conf.subprocess_timeout,
            check=True,
        )
    meta_f = Path(filename).with_suffix(".txt")
    with meta_f.open("r") as f:
        classify_info = json.load(f)
    return classify_info


import attr

NON_BIRD = ["human", "noise", "insect"]


@attr.s
class AudioResult:
    tracks = attr.ib()
    duration = attr.ib()
    cacophony_index = attr.ib()
    cacophony_index_version = attr.ib()
    chirp_index = attr.ib()
    region_code = attr.ib()
    species_identify_version = attr.ib()
    non_bird_tags = attr.ib()

    @classmethod
    def load(cls, result, duration, master_name):
        tracks = []
        analysis = result.get("analysis_result", {})
        for track in analysis.get("species_identify", []):
            tracks.append(AudioTrack.load(track, duration, master_name))

        return cls(
            tracks=tracks,
            duration=duration,
            cacophony_index=analysis.get("cacophony_index"),
            chirp_index=analysis.get("chirps"),
            cacophony_index_version=analysis.get("cacophony_index_version"),
            region_code=analysis.get("region_code"),
            species_identify_version=analysis.get("species_identify_version"),
            non_bird_tags=analysis.get("non_bird_tags", NON_BIRD),
        )


@attr.s
class AudioTrack:
    id = attr.ib()
    predictions = attr.ib()
    min_freq = attr.ib()
    max_freq = attr.ib()
    start_s = attr.ib()
    end_s = attr.ib()
    scale = attr.ib()
    master_tag = attr.ib(default=None)
    positions = attr.ib(default=None)

    def all_predictions(self):
        preds = self.predictions
        if self.master_tag is not None:
            preds.append(self.master_tag)
        return preds

    @classmethod
    def load(cls, raw_track, duration, master_name):
        preds = []
        raw_master = raw_track.get("master_tag")
        if raw_master is not None:
            # master_below_thresh = master_tag.get("below_thresh", False)
            raw_pred = raw_master["prediction"]
            if "label" not in raw_pred:
                raw_pred["label"] = raw_pred["what"]
            if "threshold_used" not in raw_pred:
                raw_pred["threshold_used"] = 0.7

            master_tag = Prediction.load(raw_pred)

            master_tag.model_name = master_name
            master_tag.model_used = raw_master["model"]
        else:
            master_tag = Prediction(UNIDENTIFIED)
            master_tag.model_name = master_name

        for model_result in raw_track.get("model_results"):
            predictions = model_result["predictions"]
            model_name = model_result["model"]
            if len(predictions) == 0 and "raw_prediction" in model_result:
                raw_pred = model_result["raw_prediction"]
                if "label" not in raw_pred:
                    raw_pred["label"] = raw_pred["what"]
                if "threshold_used" not in raw_pred:
                    raw_pred["threshold_used"] = 0.7
                pred = Prediction.load(raw_pred)
                pred.model_name = model_name
                preds.append(pred)
            else:
                for raw_pred in predictions:
                    if "label" not in raw_pred:
                        raw_pred["label"] = raw_pred["what"]
                    if "threshold_used" not in raw_pred:
                        raw_pred["threshold_used"] = 0.7
                    pred = Prediction.load(raw_pred)
                    pred.model_name = model_name
                    preds.append(pred)

        track = cls(
            id=raw_track.get("track_id"),
            predictions=preds,
            start_s=raw_track.get("begin_s"),
            end_s=raw_track.get("end_s"),
            min_freq=int(raw_track.get("freq_start")),
            max_freq=int(raw_track.get("freq_end")),
            scale="linear",
            master_tag=master_tag,
        )

        # dont think we need this anymore ask JON
        x = track.start_s / duration
        width = track.end_s / duration - x
        y = 0
        height = 1
        position = {}
        if track.max_freq is not None:
            y = track.min_freq / MAX_FRQUENCY
            height = (track.max_freq - track.min_freq) / MAX_FRQUENCY

        # convert to 2 decimal places
        x = round(x, 2)
        width = round(width, 2)
        position = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }
        track.positions = [position]
        return track

    def post_data(self, predictions=True):
        data = {
            "positions": self.positions,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "minFreq": self.min_freq,
            "maxFreq": self.max_freq,
        }
        if self.id is not None:
            data["id"] = self.id

        if predictions:
            predictions = [
                prediction.post_data() for prediction in self.all_predictions()
            ]
            data["predictions"] = predictions
        return data


def track_reprocess(recording, jwtKey, conf):
    """Reprocess the audio file.

    Downloads the file, runs the AI model on tracks that have been made by users and dont yet have an AI tag

    Args:
        recording: The recording to process.
        jwtKey: The JWT key to use for the API.
        conf: The configuration object.

    Returns:
        The API response.
    """

    # this used to work by default then  just stopped, so will explicitly add it
    mimetypes.add_type("audio/mp4", ".m4a")

    logger = logs.worker_logger("audio.track_reprocess", recording["id"])

    api = API(conf.api_url, conf.user, conf.password, logger)

    input_extension = mimetypes.guess_extension(recording["rawMimeType"])

    if not input_extension:
        # Unsupported mimetype. If needed more mimetypes can be added above.
        logger.error(
            "unsupported mimetype. Not processing %s", recording["rawMimeType"]
        )
        api.report_done(recording, recording["rawFileKey"], recording["rawMimeType"])
        return
    new_metadata = {"additionalMetadata": {}}
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        input_filename = temp_path / ("recording" + input_extension)
        logger.debug("downloading recording to %s", input_filename)

        api.download_file(jwtKey, str(input_filename))
        track_info = api.get_track_info(recording["id"]).get("tracks")

        # keep all human tagged tracks
        human_tracks = [
            t
            for t in track_info
            if any(tag for tag in t["tags"] if not tag["automatic"])
        ]

        tracks_to_remove = [t for t in track_info if t not in human_tracks]
        # recording["Tracks"] = track_info
        filename = input_filename.with_suffix(".txt")
        if "location" in recording:
            location = recording["location"]
            if (
                location is not None
                and "lat" not in location
                and "lng" not in location
                and "coordinates" in location
            ):
                coords = location["coordinates"]
                location["lng"] = coords[0]
                location["lat"] = coords[1]
        with filename.open("w") as f:
            json.dump(recording, f)

        metadata = analyse(input_filename, conf)
        analysis = AudioResult.load(metadata, metadata.get("duration"), conf.master_tag)
        algorithm_meta = {"algorithm": "sliding_window"}
        if analysis.species_identify_version is not None:
            algorithm_meta["version"] = analysis.species_identify_version
        algorithm_id = api.get_algorithm_id(algorithm_meta)
        tracks_to_add = []

        # TO DO NEED TO KEEP tracks that were created by user can be found by algortihm being "{'status': 'User added.'}"
        for track in analysis.tracks:
            human_track = match_human_track(track, human_tracks)
            if human_track is not None:
                human_tracks.remove(human_track)
                track.id = human_track["id"]
                logger.info("Matched track %s to human track %s", track, human_track)
                api.add_track_tags(recording, track.id, track.all_predictions())
            else:
                tracks_to_add.append(track)

        add_tracks_and_tags(api, recording, tracks_to_add, algorithm_id, logger)

        logger.info("Archiving old tracks")
        for track in tracks_to_remove:
            api.archive_track(recording, track["id"])

        if analysis.cacophony_index is not None:
            new_metadata["cacophonyIndex"] = analysis.cacophony_index
            new_metadata["additionalMetadata"][
                "cacophony_index_version"
            ] = analysis.cacophony_index_version
        if analysis.chirp_index is not None:
            new_metadata["additionalMetadata"]["chirpIndex"] = analysis.chirp_index
        if analysis.region_code is not None:
            new_metadata["additionalMetadata"]["regionCode"] = analysis.region_code

    api.report_done(recording, metadata=new_metadata)
    logger.info("Completed classifying for file: %s", recording["id"])


def match_human_track(new_track, human_tracks):
    print(
        "Trackikng to match ",
        new_track.start_s,
        " to old tracks ",
        [h["start"] for h in human_tracks],
    )
    allow_seconds = 0.1
    matches = [
        human_track
        for human_track in human_tracks
        if abs(new_track.start_s - human_track["start"]) < allow_seconds
        and abs(new_track.end_s - human_track["end"]) < allow_seconds
    ]
    if len(matches) == 0:
        return None
    if len(matches) == 1:
        return matches[0]
    # try match freq
    allow_freq = 100
    matches = [
        human_track
        for human_track in human_tracks
        if abs(new_track.min_freq - human_track["minFreq"]) < allow_freq
        and abs(new_track.max_freq - human_track["maxFreq"]) < allow_freq
    ]
    if len(matches) == 1:
        return matches[0]
    return None
