"""
cacophony-processing - this is a server side component that runs alongside
the Cacophony Project API, performing post-upload processing tasks.
Copyright (C) 2018, The Cacophony Project

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
import subprocess
import tempfile
from pathlib import Path

from cptv import CPTVReader

from . import API
from . import S3
from . import logs
from .processutils import HandleCalledProcessError
from .tagger import calculate_tags


DOWNLOAD_FILENAME = "recording.cptv"
SLEEP_SECS = 10
FRAME_RATE = 9

MIN_TRACK_CONFIDENCE = 0.85
FALSE_POSITIVE = "false-positive"
UNIDENTIFIED = "unidentified"
MULTIPLE = "multiple animals"


def process(recording, conf):
    logger = logs.worker_logger("thermal", recording["id"])

    api = API(conf.api_url)
    s3 = S3(conf)

    with tempfile.TemporaryDirectory() as temp_dir:
        filename = Path(temp_dir) / DOWNLOAD_FILENAME
        recording["filename"] = filename
        logger.debug("downloading recording")
        s3.download(recording["rawFileKey"], str(filename))

        update_metadata(conf, recording, api)
        logger.debug("metadata updated")

        if conf.do_classify:
            classify(conf, recording, api, s3, logger)


def classify_models(api, command, conf):
    """ classifies all models described in the config """

    model_results = []
    for model in conf.models:
        model_result = classify_file(api, command, conf, model)
        model_results.append(model_result)

    return model_results


def classify_file(api, command, conf, model):

    command = "{} -m {} -p {}".format(command, model.model_file, model.preview)
    classify_info = run_classify_command(command, conf.classify_dir)

    track_info = classify_info["tracks"]
    formatted_tracks = format_track_data(track_info)

    # Auto tag the video
    tagged_tracks, tags = calculate_tags(formatted_tracks, conf)

    model_result = {
        "tracks": tagged_tracks,
        "tags": tags,
        "algiorithm_id": api.get_algorithm_id(classify_info["algorithm"]),
    }

    model_result["name"] = model.name

    return model_result


def run_classify_command(command, dir):
    with HandleCalledProcessError():
        proc = subprocess.run(
            command,
            cwd=dir,
            shell=True,
            encoding="ascii",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    try:
        classify_info = json.loads(proc.stdout)
    except json.decoder.JSONDecodeError as err:
        raise ValueError(
            "failed to JSON decode classifier output:\n{}".format(proc.stdout)
        ) from err
    return classify_info


def classify(conf, recording, api, s3, logger):
    working_dir = recording["filename"].parent

    command = conf.classify_cmd.format(
        folder=str(working_dir), source=recording["filename"].name
    )
    logger.debug("processing %s", recording["filename"])

    model_results = classify_models(api, command, conf)
    main_model = model_results[0]

    for label, tag in main_model["tags"].items():
        logger.debug("tag: %s (%.2f)", label, tag["confidence"])
        if tag == MULTIPLE:
            api.tag_recording(recording, label, tag)

    upload_tracks(api, recording, main_model, model_results, logger)

    # Upload mp4
    video_filename = str(replace_ext(recording["filename"], ".mp4"))
    logger.debug("uploading %s", video_filename)
    new_key = s3.upload_recording(video_filename)

    metadata = {"additionalMetadata": {"algorithm": main_model["algiorithm_id"]}}
    api.report_done(recording, new_key, "video/mp4", metadata)
    logger.info("Finished (new key: %s)", new_key)


def format_track_data(tracks):
    if not tracks:
        return {}

    for track in tracks:
        if "frame_start" in track:
            del track["frame_start"]
    return tracks


def replace_ext(filename, ext):
    return filename.parent / (filename.stem + ext)


def update_metadata(conf, recording, api):
    with open(str(recording["filename"]), "rb") as f:
        reader = CPTVReader(f)
        metadata = {}
        metadata["recordingDateTime"] = reader.timestamp.isoformat()
        if reader.latitude != 0 and reader.longitude != 0:
            metadata["location"] = (reader.latitude, reader.longitude)

        if reader.preview_secs:
            metadata["additionalMetadata"] = {"previewSecs": reader.preview_secs}

        count = 0
        for _ in reader:
            count += 1
        metadata["duration"] = round(count / FRAME_RATE)
    complete = not conf.do_classify
    api.update_metadata(recording, metadata, complete)


def upload_tracks(api, recording, main_model, model_results, logger):
    other_models = [model for model in model_results if model != main_model]
    for track in main_model["tracks"]:
        track["id"] = api.add_track(recording, track, main_model["algiorithm_id"])
        add_track_tags(api, recording, track, main_model, logger)

        # add track tags for all other models
        for model in other_models:
            track_to_save = find_matching_track(model["tracks"], track)
            if track_to_save is None:
                logger.warn(
                    "Could not find a matching track in model %s for recording %s track %s",
                    model["name"],
                    recording["id"],
                    track["id"],
                )
                continue
            track_to_save["id"] = track["id"]
            add_track_tags(api, recording, track_to_save, model, logger)


def add_track_tags(api, recording, track, model, logger):
    track_data = {"name": model["name"], "algorithmId": model["algiorithm_id"]}
    track_data["all_class_confidences"] = track.get("all_class_confidences")
    if track and "tag" in track:
        logger.debug("adding %s track tag for track %s", model["name"], track["id"])
        api.add_track_tag(recording, track, data=track_data)


def find_matching_track(tracks, track):
    """ Find the same track in a different models tracks data
    This is a track which starts at the same time, and has the same starting position """

    for other_track in tracks:
        if (
            other_track["start_s"] == track["start_s"]
            and other_track["positions"][0] == track["positions"][0]
        ):
            return other_track
