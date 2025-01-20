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
import socket
import math
from pathlib import Path
import numpy as np

from . import API
from . import logs
from .processutils import HandleCalledProcessError
from .tagger import (
    calculate_tags,
    calculate_multiple_animal_confidence,
    MESSAGE,
    TAG,
    CONFIDENCE,
    FALSE_POSITIVE,
    UNIDENTIFIED,
    MULTIPLE,
    LABEL,
    MASTER_TAG,
    PREDICTIONS,
)
from .config import ModelConfig

DOWNLOAD_FILENAME = "recording"
SLEEP_SECS = 10
FRAME_RATE = 9

MIN_TRACK_CONFIDENCE = 0.85


def tracking_job(recording, rawJWT, conf):
    logger = logs.worker_logger("tracking", recording["id"])
    retrack = recording["processingState"] == "retrack"
    api = API(conf.api_url, conf.user, conf.password, logger)
    mp4 = recording.get("type") == "irRaw"
    with tempfile.TemporaryDirectory(dir=conf.temp_dir) as temp_dir:
        ext = ".mp4" if mp4 else ".cptv"
        filename = Path(temp_dir) / DOWNLOAD_FILENAME
        filename = filename.with_suffix(ext)
        recording["filename"] = str(filename)
        logger.debug("downloading recording")
        api.download_file(rawJWT, str(filename))
        if retrack:
            track_info = api.get_track_info(recording["id"]).get("tracks")
            for t in track_info:
                t["start_s"] = t["start"]
                t["end_s"] = t["end"]
                t["positions"] = t["positions"]
            recording["tracks"] = track_info
            filename = filename.with_suffix(".txt")
            with filename.open("w") as f:
                json.dump(recording, f)
        track(conf, recording, api, recording.get("duration", 0), retrack, logger)


def track(conf, recording, api, duration, retrack, logger):
    cache = (
        duration is not None
        and conf.cache_clips_bigger_than
        and duration > conf.cache_clips_bigger_than
    )
    command = conf.track_cmd.format(
        source=recording["filename"],
        cache=cache,
        retrack=retrack,
        classify_image=conf.classify_image,
        temp_dir=conf.temp_dir,
    )
    logger.info("tracking %s", recording["filename"])
    tracking_info = run_command(command)
    format_track_data(tracking_info["tracks"])
    algorithm_id = api.get_algorithm_id(tracking_info["algorithm"])
    tracks = []
    for t in tracking_info["tracks"]:
        tracks.append(Track.load(t))

    tracking_result = ClassifyResult.load(
        tracking_info, algorithm_id, tracks
    )
    for track in tracking_result.tracks:
        if retrack:
            if len(track.positions) == 0:
                api.archive_track(recording, track)
            else:
                api.update_track(recording, track)
        else:
            track.id = api.add_track(
                recording, track, tracking_result.tracking_algorithm
            )
    additionalMetadata = {"algorithm": tracking_result.tracking_algorithm}
    if tracking_result.tracking_time is not None:
        additionalMetadata["tracking_time"] = tracking_result.tracking_time
    if tracking_result.thumbnail_region is not None:
        additionalMetadata["thumbnail_region"] = tracking_result.thumbnail_region

    metadata = {"additionalMetadata": additionalMetadata}
    api.report_done(recording, None, None, metadata)
    logger.info("Finished tracking")


def classify_job(recording, rawJWT, conf):
    logger = logs.worker_logger("classify", recording["id"])

    api = API(conf.api_url, conf.user, conf.password, logger)
    mp4 = recording.get("type") == "irRaw"
    ext = ".mp4" if mp4 else ".cptv"

    with tempfile.TemporaryDirectory(dir=conf.temp_dir) as temp_dir:
        filename = Path(temp_dir) / DOWNLOAD_FILENAME
        filename = filename.with_suffix(ext)
        recording["filename"] = str(filename)
        logger.debug("downloading recording")
        api.download_file(rawJWT, str(filename))
        meta_filename = (Path(temp_dir) / DOWNLOAD_FILENAME).with_suffix(".txt")
        track_info = api.get_track_info(recording["id"]).get("tracks")
        for track in track_info:
            track["start_s"] = track["start"]
            track["end_s"] = track["end"]
            track["positions"] = track["positions"]
        recording["tracks"] = track_info
        with open(str(meta_filename), "w") as f:
            json.dump(recording, f)
        classify(conf, recording, api, logger)


def classify_file(api, file, conf, duration, logger):
    cache = False
    if (
        duration is not None
        and conf.cache_clips_bigger_than
        and duration > conf.cache_clips_bigger_than
    ):
        cache = True

    command = conf.classify_cmd.format(
        source=file,
        cache=cache,
        classify_image=conf.classify_image,
        temp_dir=conf.temp_dir,
    )
    logger.info("Classifying %s with command %s", file, command)
    classify_info = run_command(command)

    format_track_data(classify_info["tracks"])
    tracks = []
    for t in classify_info["tracks"]:
        tracks.append(Track.load(t))
    # Auto tag the video
    filtered_tracks, tags = calculate_tags(tracks, conf)

    return ClassifyResult.load(
        classify_info, 0, filtered_tracks, tags.get(MULTIPLE, None)
    )


def read_all(socket):
    size = 4096
    data = bytearray()

    while True:
        packet = socket.recv(size)
        if packet:
            data.extend(packet)
        else:
            break
    return data


def run_command(command):
    with HandleCalledProcessError():
        proc = subprocess.run(
            command,
            shell=True,
            encoding="ascii",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    try:
        # removes any prints that shouldn't be there
        output = proc.stdout
        sub_start = output.index("{")
        sub_end = output.rindex("}")
        output = output[sub_start : sub_end + 1]

        classify_info = json.loads(output)
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
    wallaby_device = is_wallaby_device(conf.wallaby_devices, recording)
    logger.debug("processing %s ", recording["filename"])
    classify_result = classify_file(
        api, recording["filename"], conf, recording.get("duration", 0), logger
    )

    # if conf.filter_false_positive:
    #     for track in classify_result.tracks:
    #         for pred in track.get("predictions",[])

    upload_tags(
        api,
        recording,
        classify_result,
        wallaby_device,
        conf.master_tag,
        logger,
    )

    multiple_confidence = calculate_multiple_animal_confidence(classify_result.tracks)
    if multiple_confidence > conf.min_confidence:
        logger.debug("multiple animals detected, (%.2f)", multiple_confidence)
        api.tag_recording(
            recording,
            MULTIPLE,
            {"event": MULTIPLE, CONFIDENCE: multiple_confidence},
        )

    additionalMetadata = {}
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


def upload_tags(api, recording, classify_result, wallaby_device, master_name, logger):
    rat_thresh = api.get_rat_threshold(
        recording["DeviceId"], recording["recordingDateTime"]
    )
    rat_thresh = rat_thresh.get("settings") if rat_thresh is not None else None
    for track in classify_result.tracks:
        model_predictions = []
        for model_prediction in track.predictions:
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

        rat_version = None
        master_model, master_prediction = get_master_tag(
            model_predictions, wallaby_device
        )
        rat_thresh_version = None
        if master_prediction is None:
            master_prediction = default_tag(track.id)

        if (
            rat_thresh is not None
            and rat_thresh.get("ratThresh") is not None
            and master_prediction.tag == "rodent"
        ):
            rat = is_rat(track, rat_thresh["ratThresh"])
            if rat:
                master_prediction.tag = "rat"
            else:
                master_prediction.tag = "mouse"
            rat_thresh_version = rat_thresh["ratThresh"]["version"]
        add_track_tag(
            api,
            recording,
            track,
            master_prediction,
            logger,
            model_name=master_name,
            model_used=master_model.name if master_model is not None else None,
            rat_thresh_version=rat_thresh_version,
        )
        track[MASTER_TAG] = master_prediction


WIDTH = 160
HEIGHT = 120


def is_rat(track, rat_thresh):
    box_dim = rat_thresh["gridSize"]
    thresholds = rat_thresh["thresholds"]
    rows = math.ceil(HEIGHT / box_dim)
    columns = math.ceil(WIDTH / box_dim)
    track_dims = np.empty((rows, columns), dtype="O")
    rat_count = 0
    mouse_count = 0
    for p in track.positions:
        if p["blank"] or p["mass"] == 0:
            continue

        box_x_start = p["x"] // box_dim
        box_x_end = (p["x"] + p["width"]) // box_dim
        box_y_start = p["y"] // box_dim
        box_y_end = (p["y"] + p["height"]) // box_dim

        for y in range(box_y_start, box_y_end + 1):
            for x in range(box_x_start, box_x_end + 1):
                if thresholds[y][x] is None:
                    continue
                if p["mass"] > thresholds[y][x]:
                    rat_count += 1
                else:
                    mouse_count += 1
    return rat_count > mouse_count


def default_tag(track_id):
   return Prediction(tag = UNIDENTIFIED)


def use_tag(model, prediction, wallaby_device):
    tag = prediction.tag
    if tag is None:
        return False
    elif tag in model.ignored_tags:
        return False
    elif model.wallaby and not wallaby_device:
        return False
    return True


def get_master_tag(model_results, wallaby_device=False):
    """Choose a tag to be the overriding tag for this track"""
    valid_results = {
        model.id: (model, prediction)
        for model, prediction in model_results
        if prediction and use_tag(model, prediction, wallaby_device)
    }

    valid_models = []
    # use submodels where applicable
    for re_m, prediction in valid_results.values():
        if re_m.submodel:
            continue
        if re_m.reclassify is None:
            valid_models.append((re_m, prediction))
            continue
        sub_id = re_m.reclassify.get(prediction.tag)
        if sub_id is not None:
            # use sub model instead of parent model
            valid_models.append(valid_results[sub_id])
        else:
            # use parent model
            valid_models.append((re_m, prediction))
    if len(valid_models) == 0:
        return None, None
    clear_tags = [
        (model, prediction)
        for model, prediction in valid_models
        if prediction.tag != UNIDENTIFIED
        and model_rank(prediction.tag, model.tag_scores) is not None
    ]
    if len(clear_tags) == 0:
        return valid_models[0]

    ordered = sorted(
        clear_tags,
        key=lambda model: model_rank(model[1].tag, model[0].tag_scores),
        reverse=True,
    )
    return ordered[0]


def model_rank(tag, tag_scores):
    if tag in tag_scores:
        return tag_scores[tag]
    return tag_scores["default"]


def add_track_tag(
    api,
    recording,
    track,
    prediction,
    logger,
    model_name=None,
    model_used=None,
    rat_thresh_version=None,
):
    if not track or prediction.tag is None:
        return False, None

    track_data = {"name": model_name}
    if model_used is not None:
        # specifically for master tag to see which model was chosen
        track_data["model_used"] = model_used
    if  prediction.classify_time is not None:
        track_data["classify_time"] = prediction.classify_time
    track_data["clarity"] = prediction.clarity
    track_data["all_class_confidences"] = prediction.all_class_confidence
    if prediction.predictions is not None:
        track_data["predictions"] = prediction.predictions
    if prediction.prediction_frames is not None:
        track_data["prediction_frames"] = prediction.prediction_frames
    if prediction.message is not None:
        track_data[MESSAGE] = prediction.message
    if prediction.label is not None:
        track_data["raw_tag"] = prediction.label

    if rat_thresh_version is not None:
        track_data["rat_thresh_version"] = rat_thresh_version
    logger.debug(
        "adding %s track tag %s for track %s",
        track_data["name"],
        prediction.tag,
        track.id,
    )

    api.add_track_tag(recording, track.id, prediction, data=track_data)
    return True, tag


@attr.s
class Track:
    id = attr.ib()
    predictions = attr.ib()
    confidence=attr.ib()

    positions = attr.ib()
    @classmethod
    def load(
        cls, raw_track ):
        preds = []
        for p in raw_track.get("predictions"):
            preds.appen(Prediction.load(p))

        return cls(id = raw_track["id"],predictions = preds,positions = raw_track.get("positions"),confidence = 0)
    
@attr.s
class Prediction:
    tag = attr.ib()
    message = attr.ib(default = None)
    label = attr.ib(default = None)
    clarity = attr.ib(default = 0)
    all_class_confidences = attr.ib(default = None)
    classify_time = attr.ib(default = 0)
    prediction_frames=attr.ib(default = None)
    predictions = attr.ib(default = None)
    confidence=attr.ib(default=0)
    model_id = attr.ib(default = None)
    @classmethod
    def load(cls, raw_pred ):
        return cls(tag = raw_pred.get("tag"),message=raw_pred.get("message"),label = raw_pred.get("label"),
            clarity = raw_pred.get("clarity"), all_class_confidences=raw_pred.get("all_class_confidences"),classify_time = raw_pred.get("classify_time"), prediction_frames = raw_pred.get("prediction_frames"),
            confidence = raw_pred.get("confidence",0),predictions = raw_pred.get("predictions"),model_id = raw_pred.get("model_id"))
@attr.s
class ClassifyResult:
    tracking_algorithm = attr.ib()
    tracking_time = attr.ib()
    models_by_id = attr.ib()
    tracks = attr.ib()
    multiple_animals = attr.ib()
    thumbnail_region = attr.ib()

    @classmethod
    def load(
        cls, classify_json, tracking_algorithm, filtered_tracks, multiple_animals=False
    ):
        # tracks = []
        # for t in filtered_tracks:
        #     tracks.append(Track.load(t))
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
