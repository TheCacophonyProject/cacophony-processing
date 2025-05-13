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

    logger = logs.worker_logger("audio.analysis", recording["id"])

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
                "lat" not in location
                and "lng" not in location
                and "coordinates" in location
            ):
                coords = location["coordinates"]
                location["lng"] = coords[0]
                location["lat"] = coords[1]
        with filename.open("w") as f:
            json.dump(recording, f)

        metadata = analyse(input_filename, conf, analyse_tracks=True)
        analysis = AudioResult.load(metadata, metadata.get("duration"))
        algorithm_meta = {"algorithm": "sliding_window"}
        if analysis.species_identify_version is not None:
            algorithm_meta["version"] = analysis.species_identify_version
        algorithm_id = api.get_algorithm_id(algorithm_meta)
        data = {"algorithm": algorithm_id}

        for track in analysis.tracks:
            master_tag = get_master_tag(analysis, track)
            data["name"] = "Master"
            api.add_track_tag(recording, track.id, master_tag, data)
            for i, prediction in enumerate(track.predictions):
                data["name"] = prediction.model_name
                api.add_track_tag(recording, track.id, prediction, data)

    api.report_done(recording, metadata=new_metadata)
    logger.info("Completed classifying for file: %s", recording["id"])


def get_master_tag(analysis, track):
    if len(track.predictions) == 0:
        return None

    ordered = sorted(
        track.predictions,
        key=lambda prediction: (prediction.confidence),
        reverse=True,
    )
    # choose most specific tag first
    first_specific = None
    for p in ordered:
        if p.tag == "bird":
            continue
        first_specific = p
        break

    if first_specific is None:
        first_specific = ordered[0]
    return first_specific


def process(recording, jwtKey, conf):
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

    logger = logs.worker_logger("audio.analysis", recording["id"])

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

        filename = input_filename.with_suffix(".txt")
        if "location" in recording:
            location = recording["location"]
            if (
                "lat" not in location
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
        analysis = AudioResult.load(metadata, duration)
        algorithm_meta = {"algorithm": "sliding_window"}
        if analysis.species_identify_version is not None:
            algorithm_meta["version"] = analysis.species_identify_version
        algorithm_id = api.get_algorithm_id(algorithm_meta)

        for track in analysis.tracks:
            track.id = api.add_track(recording, track, algorithm_id)

            data = {"algorithm": algorithm_id}
            master_tag = get_master_tag(analysis, track)
            if master_tag is not None:
                data["name"] = "Master"
                api.add_track_tag(recording, track.id, master_tag, data)
            for i, prediction in enumerate(track.predictions):
                data["name"] = prediction.model_name
                api.add_track_tag(recording, track.id, prediction, data)

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
    def load(cls, result, duration):
        tracks = []
        analysis = result.get("analysis_result", {})
        for track in analysis.get("species_identify", []):
            tracks.append(AudioTrack.load(track, duration))

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

    @classmethod
    def load(cls, raw_track, duration):
        preds = []
        for prediction in raw_track.get("predictions"):
            species = prediction["species"]
            confidences = prediction["likelihood"]
            del prediction["species"]
            raw_tag = None
            if len(confidences) == 0 and "raw_tag" in prediction:
                raw_tag = prediction["raw_tag"]
                species = [UNIDENTIFIED]
                confidences = [prediction["raw_confidence"]]

            for confidence, s in zip(confidences, species):
                pred = Prediction(
                    confidence=confidence,
                    tag=s,
                    label=raw_tag,
                    model_name=prediction["model"],
                )
                preds.append(pred)

        track = cls(
            id=raw_track.get("track_id"),
            predictions=preds,
            start_s=raw_track.get("begin_s"),
            end_s=raw_track.get("end_s"),
            min_freq=raw_track.get("freq_start"),
            max_freq=raw_track.get("freq_end"),
            scale="linear",
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

    def post_data(self):
        data = {
            "positions": self.positions,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "minFreq": self.min_freq,
            "maxFreq": self.max_freq,
        }
        if self.id is not None:
            data["id"] = self.id
        return data
