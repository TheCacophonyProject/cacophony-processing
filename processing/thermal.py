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


def classify_file(api, command, conf, model):
    command = "{}".format(command)
    classify_info = run_classify_command(command, conf.classify_dir)

    track_info = classify_info["tracks"]
    formatted_tracks = format_track_data(track_info)

    # Auto tag the video
    tagged_tracks, tags = calculate_tags(formatted_tracks, conf)
    algorithm_id = api.get_algorithm_id(classify_info["algorithm"])
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

    model_result = classify_file(api, command, conf, model)

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


def upload_tracks(api, recording, tracks, logger, wallaby_device, models, master_name):
    for track in tracks:
        track["id"] = api.add_track(recording, track, main_model.algorithm_id)
        model_results = []
        for model_result in track["model_predictions"]:
            added, tag = add_track_tag(api, recording, track, model_result, logger)
            if added:
                model_config = models.get(model_result["model_name"])
                model_results.append(ModelResult(model, model_result))
        master_tag = get_master_tag(model_results, wallaby_device)
        if master_tag:
            add_track_tag(
                api,
                recording,
                track,
                master_tag.classification,
                logger,
                model_name=master_name,
            )


def use_tag(model_result, wallaby_device):
    tag = model_result.tag
    if tag is None:
        return False
    if wallaby_device and tag.lower() != "wallaby":
        return False
    elif not wallaby_device and tag.lower() == "wallaby":
        return False
    if tag in model_result.model_config.ignored_tags:
        return False
    return wallaby_device == model_result.model_config.wallaby


def get_master_tag(model_results, wallaby_device=False):
    """ Choose a tag to be the overriding tag for this track """

    valid_results = [
        model_result
        for model_result in model_results
        if use_tag(model_result, wallaby_device)
    ]

    if len(model_result) == 0:
        return None
    clear_tags = [
        model_result
        for model_result in valid_results
        if model_result.tag != "unidentified"
    ]
    if len(clear_tags) == 0:
        return valid_results[0]

    ordered = sorted(
        clear_tags,
        key=lambda model: model_rank(
            model_result.tag, model_result.model_config.tag_scores
        ),
        reverse=True,
    )

    return ordered[0]


def model_rank(tag, model_config):
    if tag in tag_scores:
        return tag_scores[tag]
    return tag_scores["default"]


def add_track_tag(api, recording, track, prediction, logger, model_name=None):
    tag = None
    clear, message = prediction_is_clear(prediction)
    if clear:
        tag = model[tagger.LABEL]
    else:
        tag = tagger.UNIDENTIFIED
    track_data = {"name": prediction["model_name"], "algorithmId": model.algorithm_id}
    track_data["all_class_confidences"] = prediction.get("all_class_confidences")
    predictions = prediction.get("predictions")
    if predictions:
        track_data["predictions"] = predictions

    logger.debug(
        "adding %s track tag for track %s", model.model_config.name, track["id"]
    )
    api.add_track_tag(recording, track, data=track_data)
    return True, tag


@attr.s
class ModelResult:
    model_config = attr.ib()
    classification = attr.ib()
    message = attr.ib()
    algorithm_id = attr.ib()


@property
def tag(self):
    return self.classification.get(Tagger.LABEL)
