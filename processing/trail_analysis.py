import subprocess
import tempfile
from pathlib import Path
import json
from . import API
from . import logs
from .processutils import HandleCalledProcessError
import mimetypes


def analyse_image(recording, jwtKey, conf):
    logger = logs.worker_logger("trail.analysis", recording["id"])
    api = API(conf.api_url, conf.user, conf.password, logger)
    input_extension = mimetypes.guess_extension(recording["rawMimeType"])

    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        r_id = recording["id"]
        input_filename = temp_path / (f"recording-{r_id}" + input_extension)
        logger.debug("downloading trail image to %s", input_filename)
        api.download_file(jwtKey, str(input_filename))
        json_out = analyse(input_filename, conf, logger)
        detections = json_out["images"][0].get("detections", [])
        categories = json_out["detection_categories"]
        detector = json_out["info"]["detector_metadata"]
        algorithm_id = api.get_algorithm_id({"algorithm": detector})
        for detection in detections:
            # convert origin to be bottom left
            top = detection["bbox"][1]
            height = detection["bbox"][3]
            bottom = 1 - (top + height)
            position = {
                "x": detection["bbox"][0],
                "y": bottom,
                "width": detection["bbox"][2],
                "height": height,
            }
            track = {"start_s": 0, "end_s": 0, "positions": [position]}
            id = api.add_track(recording, track, algorithm_id)
            category = detection["category"]
            prediction = {
                "confidence": detection["conf"],
                "tag": categories[category],
            }
            api.add_track_tag(recording, id, prediction, {"name": "Master"})
    api.report_done(recording, None, None, None)


def analyse(filename, conf, logger):
    command = conf.classify_trail_cmd.format(
        folder=filename.parent,
        basename=filename.name,
        outfile=filename.with_suffix(".json").name,
    )
    logger.info("Running cmd %s", command)
    with HandleCalledProcessError():
        output = subprocess.check_output(command, shell=True, stderr=subprocess.PIPE)
    with filename.with_suffix(".json").open() as f:
        output = json.load(f)
    logger.debug("Got json %s", output)
    return output
