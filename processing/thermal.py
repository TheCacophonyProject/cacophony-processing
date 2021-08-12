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

from . import API
from . import logs
from .processutils import HandleCalledProcessError
from .tagger import (
    calculate_tags,
    MESSAGE,
    TAG,
    MULTIPLE,
    CONFIDENCE,
    FALSE_POSITIVE,
    UNIDENTIFIED,
    MULTIPLE,
)
from .config import ModelConfig

DOWNLOAD_FILENAME = "recording.cptv"
SLEEP_SECS = 10
FRAME_RATE = 9

MIN_TRACK_CONFIDENCE = 0.85


def classify_job(recording, rawJWT, conf):
    logger = logs.worker_logger("thermal-classify", recording["id"])

    api = API(conf.file_api_url, conf.api_url)

    with tempfile.TemporaryDirectory() as temp_dir:
        filename = Path(temp_dir) / DOWNLOAD_FILENAME
        recording["filename"] = filename
        logger.debug("downloading recording")
        api.download_file(rawJWT, str(filename))
        classify(conf, recording, api, logger)


def classify_file(api, command, conf, duration):

    if (
        duration is not None
        and conf.cache_clips_bigger_than
        and duration > conf.cache_clips_bigger_than
    ):
        command = "{} --cache y".format(command)
    else:
        command = "{} --cache n".format(command)
    classify_info = run_classify_command(command, conf.classify_dir)

    format_track_data(classify_info["tracks"])

    # Auto tag the video
    algorithm_id = api.get_algorithm_id(classify_info["algorithm"])
    filtered_tracks, tags = calculate_tags(classify_info["tracks"], conf)

    return ClassifyResult.load(
        classify_info, algorithm_id, filtered_tracks, tags.get(MULTIPLE, None)
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


def classify(conf, recording, api, logger):
    working_dir = recording["filename"].parent
    wallaby_device = is_wallaby_device(conf.wallaby_devices, recording)
    command = conf.classify_cmd.format(
        folder=str(working_dir), source=recording["filename"].name
    )
    logger.debug("processing %s ", recording["filename"])
    classify_result = classify_file(api, command, conf, recording.get("duration", 0))
    if classify_result.multiple_animals is not None:
        logger.debug(
            "multiple animals detected, (%.2f)",
            classify_result.multiple_animals[CONFIDENCE],
        )
        api.tag_recording(recording, MULTIPLE, classify_result.multiple_animals)

    upload_tracks(
        api,
        recording,
        classify_result,
        wallaby_device,
        conf.master_tag,
        logger,
    )
    additionalMetadata = {"algorithm": classify_result.tracking_algorithm}
    if classify_result.tracking_time is not None:
        additionalMetadata["tracking_time"] = classify_result.tracking_time
    if classify_result.thumbnail_region is not None:
        additionalMetadata["thumbnail_region"] = classify_result.thumbnail_region
    model_info = {}
    for model in classify_result.models_by_id.values():
        if model.classify_time is not None:
            model_info[model.name] = {"classify_time": model.classify_time}

    additionalMetadata["models"] = model_info
    metadata = {"additionalMetadata": additionalMetadata}

    api.report_done(recording, None, None, metadata)
    logger.info("Finished")


def format_track_data(tracks):
    if not tracks:
        return {}

    for track in tracks:
        if "frame_start" in track:
            del track["frame_start"]
    return tracks


def replace_ext(filename, ext):
    return filename.parent / (filename.stem + ext)


def upload_tracks(api, recording, classify_result, wallaby_device, master_name, logger):
    for track in classify_result.tracks:
        track["id"] = api.add_track(
            recording, track, classify_result.tracking_algorithm
        )
        model_predictions = []
        for model_prediction in track["predictions"]:
            model = classify_result.models_by_id[model_prediction["model_id"]]
            added, tag = add_track_tag(
                api,
                recording,
                track,
                model_prediction,
                logger,
                model_name=model.name,
            )
            if added:
                model_predictions.append((model, model_prediction))
        master_model, master_prediction = get_master_tag(
            model_predictions, wallaby_device
        )
        if master_prediction is None:
            master_prediction = default_tag(track["id"])
        add_track_tag(
            api,
            recording,
            track,
            master_prediction,
            logger,
            model_name=master_name,
        )


def default_tag(track_id):
    prediction = {}
    prediction[TAG] = UNIDENTIFIED
    prediction[CONFIDENCE] = 0
    return prediction


def use_tag(model, prediction, wallaby_device):
    tag = prediction.get(TAG)
    if tag is None:
        return False
    elif tag in model.ignored_tags:
        return False
    elif model.wallaby and not wallaby_device:
        return False
    return True


def get_master_tag(model_results, wallaby_device=False):
    """Choose a tag to be the overriding tag for this track"""
    valid_results = [
        (model, prediction)
        for model, prediction in model_results
        if prediction and use_tag(model, prediction, wallaby_device)
    ]
    if len(valid_results) == 0:
        return None, None
    clear_tags = [
        (model, prediction)
        for model, prediction in valid_results
        if prediction[TAG] != UNIDENTIFIED
    ]
    if len(clear_tags) == 0:
        return valid_results[0]

    ordered = sorted(
        clear_tags,
        key=lambda model: model_rank(model[1][TAG], model[0].tag_scores),
        reverse=True,
    )
    return ordered[0]


def model_rank(tag, tag_scores):
    if tag in tag_scores:
        return tag_scores[tag]
    return tag_scores["default"]


def add_track_tag(api, recording, track, prediction, logger, model_name=None):
    if not track or TAG not in prediction:
        return False, None
    track_data = {
        "name": model_name,
    }
    if "classify_time" in prediction:
        track_data["classify_time"] = prediction["classify_time"]

    track_data["all_class_confidences"] = prediction.get("all_class_confidences")
    predictions = prediction.get("predictions")
    if predictions:
        track_data["predictions"] = predictions
    if prediction.get(MESSAGE) is not None:
        track_data[MESSAGE] = prediction[MESSAGE]

    logger.debug(
        "adding %s track tag %s for track %s",
        track_data["name"],
        prediction.get(TAG),
        track["id"],
    )

    api.add_track_tag(recording, track["id"], prediction, data=track_data)
    return True, tag


@attr.s
class ClassifyResult:
    tracking_algorithm = attr.ib()
    tracking_time = attr.ib()
    models_by_id = attr.ib()
    tracks = attr.ib()
    multiple_animals = attr.ib()
    thumbnail_region = attr.ib()

    @classmethod
    def load(cls, classify_json, tracking_algorithm, filtered_tracks, multiple_animals):
        model = cls(
            thumbnail_region=classify_json.get("thumbnail_region"),
            tracking_algorithm=tracking_algorithm,
            tracking_time=classify_json.get("tracking_time"),
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
