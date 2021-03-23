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
import attr
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

    return ModelResult(
        model, tagged_tracks, tags, api.get_algorithm_id(classify_info["algorithm"])
    )


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


def is_wallaby_device(wallaby_devices, recording_meta):
    device_id = recording_meta.get("DeviceId")
    if device_id is not None:
        return device_id in wallaby_devices
    return False


def classify(conf, recording, api, s3, logger):
    working_dir = recording["filename"].parent
    wallaby_device = is_wallaby_device(conf.wallaby_devices, recording)

    command = conf.classify_cmd.format(
        folder=str(working_dir), source=recording["filename"].name
    )
    logger.debug("processing %s", recording["filename"])

    model_results = classify_models(api, command, conf)
    main_model = model_results[0]

    for label, tag in main_model.tags.items():
        logger.debug("tag: %s (%.2f)", label, tag["confidence"])
        if label == MULTIPLE:
            api.tag_recording(recording, label, tag)

    upload_tracks(
        api,
        recording,
        main_model,
        model_results,
        logger,
        wallaby_device,
        conf.master_tag,
    )

    # Upload mp4
    video_filename = str(replace_ext(recording["filename"], ".mp4"))
    logger.debug("uploading %s", video_filename)
    new_key = s3.upload_recording(video_filename)

    metadata = {"additionalMetadata": {"algorithm": main_model.algorithm_id}}
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


def upload_tracks(
    api, recording, main_model, model_results, logger, wallaby_device, master_name
):
    other_models = [model for model in model_results if model != main_model]
    for track in main_model.tracks:
        model_tags = []
        track["id"] = api.add_track(recording, track, main_model.algorithm_id)
        added = add_track_tags(api, recording, track, main_model, logger)
        if added:
            model_tags = [(main_model, track)]
        # add track tags for all other models
        for model in other_models:
            track_to_save = find_matching_track(model.tracks, track)
            if track_to_save is None:
                logger.warn(
                    "Could not find a matching track in model %s for recording %s track %s",
                    model.model_config.name,
                    recording["id"],
                    track["id"],
                )
                continue
            track_to_save["id"] = track["id"]
            added = add_track_tags(api, recording, track_to_save, model, logger)
            if added:
                model_tags.append((model, track_to_save))

        master_tag = get_master_tag(model_tags, wallaby_device)
        if master_tag:
            add_track_tags(
                api,
                recording,
                master_tag[1],
                master_tag[0],
                logger,
                model_name=master_name,
            )


def use_tag(model_result, track, wallaby_device):
    tag = track.get("tag")
    if tag is None:
        return False
    if wallaby_device and tag.lower() != "wallaby":
        return False
    elif not wallaby_device and tag.lower() == "wallaby":
        return False
    if tag in model_result.model_config.ignored_tags:
        return False
    return wallaby_device == model_result.model_config.wallaby


def get_master_tag(model_tags, wallaby_device=False):
    """ Choose a tag to be the overriding tag for this track """

    model_tags = [
        model_tag
        for model_tag in model_tags
        if use_tag(model_tag[0], model_tag[1], wallaby_device)
    ]

    if len(model_tags) == 0:
        return None
    clear_tags = [
        model_tag for model_tag in model_tags if model_tag[1]["tag"] != "unidentified"
    ]
    if len(clear_tags) == 0:
        return model_tags[0]

    ordered = sorted(
        clear_tags,
        key=lambda model: model_rank(model[0].model_config, model[1]),
        reverse=True,
    )

    return ordered[0]


def model_rank(model_config, track):
    tag = track["tag"]
    if tag in model_config.tag_scores:
        return model_config.tag_scores[tag]
    return model_config.tag_scores["default"]


def add_track_tags(api, recording, track, model, logger, model_name=None):
    if not track or "tag" not in track:
        return False

    if model_name is None:
        model_name = model.model_config.name
    track_data = {"name": model_name, "algorithmId": model.algorithm_id}
    track_data["all_class_confidences"] = track.get("all_class_confidences")
    predictions = track.get("predictions")
    if predictions:
        track_data["predictions"] = predictions

    logger.debug(
        "adding %s track tag for track %s", model.model_config.name, track["id"]
    )
    api.add_track_tag(recording, track, data=track_data)
    return True


def find_matching_track(tracks, track):
    """Find the same track in a different models tracks data
    This is a track which starts at the same time, and has the same starting position"""

    for other_track in tracks:
        if (
            other_track["start_s"] == track["start_s"]
            and other_track["positions"][0] == track["positions"][0]
        ):
            return other_track


@attr.s
class ModelResult:
    model_config = attr.ib()
    tracks = attr.ib()
    tags = attr.ib()
    algorithm_id = attr.ib()
