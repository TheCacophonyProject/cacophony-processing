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
from .tagger import calculate_tags, MESSAGE, TAG


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


def classify_file(api, command, conf):
    command = "{}".format(command)
    classify_info = run_classify_command(command, conf.classify_dir)

    format_track_data(classify_info["tracks"])

    # Auto tag the video
    algorithm_id = api.get_algorithm_id(classify_info["algorithm"])
    filtered_tracks, multiple_animals = calculate_tags(classify_info["tracks"], conf)

    return ClassifyResult.load(
        classify_info, algorithm_id, filtered_tracks, multiple_animals
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

    classify_result = classify_file(api, command, conf)

    if classify_result.multiple_animals is not None:
        logger.debug(
            "multiple animals detected, (%.2f)",
            classify_result.multiple_animals["confidence"],
        )
        api.tag_recording(recording, MULTIPLE, classify_result.multiple_animals)

    upload_tracks(
        api,
        recording,
        classify_result,
        conf.master_tag,
        wallaby_device,
        logger,
    )

    # Upload mp4
    video_filename = str(replace_ext(recording["filename"], ".mp4"))
    logger.debug("uploading %s", video_filename)
    new_key = s3.upload_recording(video_filename)

    metadata = {"additionalMetadata": {"algorithm": main_model.tracking_algorithm}}
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


def upload_tracks(api, recording, classify_result, wallaby_device, master_name, logger):
    for track in classify_result.tracks:
        track["id"] = api.add_track(
            recording, track, classify_result.tracking_algorithm
        )
        model_results = []
        for model_result in track["predictions"]:
            added, tag = add_track_tag(api, recording, track, model_result, logger)
            if added:
                model_results.append(
                    classify_result.models_by_id[model_result["id"]], model_result
                )
        model, prediction = get_master_tag(model_results, wallaby_device)
        if master_tag:
            add_track_tag(
                api,
                recording,
                track,
                prediction,
                logger,
                model_name=master_name,
            )


def use_tag(model, prediction, wallaby_device):
    tag = prediction["tag"]
    if tag is None:
        return False
    if wallaby_device and tag.lower() != "wallaby":
        return False
    elif not wallaby_device and tag.lower() == "wallaby":
        return False
    if tag in model.ignored_tags:
        return False
    return wallaby_device == model.wallaby


def get_master_tag(model_results, wallaby_device=False):
    """ Choose a tag to be the overriding tag for this track """

    valid_results = [
        (model, prediction)
        for model, prediction in model_results
        if use_tag(model, prediction, wallaby_device)
    ]

    if len(model_result) == 0:
        return None
    clear_tags = [
        (model, prediction)
        for model, prediction in valid_results
        if prediction["tag"] != "unidentified"
    ]
    if len(clear_tags) == 0:
        return valid_results[0]

    ordered = sorted(
        clear_tags,
        key=lambda model: model_rank(model[0]["tag"], model[1].tag_scores),
        reverse=True,
    )

    return ordered[0]


def model_rank(tag, model_config):
    if tag in tag_scores:
        return tag_scores[tag]
    return tag_scores["default"]


def add_track_tag(api, recording, track, prediction, logger, model_name=None):
    if not track or TAG not in prediction:
        return False, None
    track_data = {
        "name": prediction["model_name"],
    }
    track_data["all_class_confidences"] = prediction.get("all_class_confidences")
    predictions = prediction.get("predictions")
    if predictions:
        track_data["predictions"] = predictions
    if prediction.get(MESSAGE) is not None:
        track_data[MESSAGE] = prediction[MESSAGE]

    logger.debug(
        "adding %s track tag for track %s", prediction["model_name"], track["id"]
    )
    api.add_track_tag(recording, track["id"], prediction, data=track_data)
    return True, tag


@attr.s
class ModelConfig:
    id = attr.ib()
    name = attr.ib()
    model_file = attr.ib()
    wallaby = attr.ib()
    tag_scores = attr.ib()
    ignored_tags = attr.ib()

    @classmethod
    def load(cls, raw, algorithm_id):
        model = cls(
            id=raw["id"],
            name=raw["name"],
            model_file=raw["model_file"],
            wallaby=raw["wallaby"],
            tag_scores=raw["tag_scores"],
            ignored_tags=raw.get("ignored_tags", []),
        )
        return model


@attr.s
class ClassifyResult:
    tracking_algorithm = attr.ib()
    models_by_id = attr.ib()
    tracks = attr.ib()
    multiple_animals = attr.ib()

    @classmethod
    def load(cls, classify_json, tracking_algorithm, filtered_tracks, multiple_animals):

        model = cls(
            tracking_algorithm=tracking_algorithm,
            models_by_id=load_models(classify_json.get("models", [])),
            tracks=filtered_tracks,
            multiple_animals=multiple_animals,
        )
        return model


def load_models(models_json):
    models = {}
    for model_json in models_json:
        model = ModelConfig.load(model_json)
        models[model.id] = model
    return models


@property
def tag(self):
    return self.classification.get(Tagger.LABEL)
