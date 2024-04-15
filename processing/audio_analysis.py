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

MAX_FRQUENCY = 48000 / 2



def track_analys(recording, jwtKey, conf):
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

        track_info = api.get_track_info(recording["id"]).get("tracks")

        recording["tracks"] = track_info
        filename = input_filename.with_suffix(".txt")
        with filename.open("w") as f:
            json.dump(recording, f)

        analysis = analyse(input_filename, conf,analyse_tracks=True)
        if analysis["species_identify"]:
            species_identify = analysis.pop("species_identify")
            for analysis_result in species_identify:
                model_name = analysis_result.get("model", "Unnamed")
                predictions = analysis_result["predictions"]
                for i, prediction in enumerate(predictions):
                    species = prediction["species"]
                    confidences = prediction["likelihood"]
                    del prediction["species"]
                    raw_tag = None
                    if len(confidences) == 0 and "raw_tag" in prediction:
                        raw_tag = prediction["raw_tag"]
                        species = [UNIDENTIFIED]
                        confidences = [prediction["raw_confidence"]]

                    for confidence, s in zip(confidences, species):
                        prediction["confidence"] = confidence
                        prediction["tag"] = s
                        data = {"name": "Master"}
                        if raw_tag is not None:
                            data["raw_tag"] = raw_tag

                        if i == 0:
                            # just add master tag for first prediction
                            api.add_track_tag(recording, analysis_result["track_id"], prediction, data)
                        data["name"] = prediction["model"]
                        api.add_track_tag(recording, analysis_result["track_id"], prediction, data)
                # for t in recording["tracks"]:
                    # if t["id"]== analysis_result["track_id"]]:
                        # t["classify"]= False
                        # api.update_track(recording, t)

        new_metadata = {}

def analyse(filename, conf,analyse_tracks=False):
    command = conf.audio_analysis_cmd.format(
        folder=filename.parent, basename=filename.name, tag=conf.audio_analysis_tag,analyse_tracks=analyse_tracks
    )
    with HandleCalledProcessError():
        output = subprocess.check_output(command, shell=True, stderr=subprocess.PIPE)
    return json.loads(output.decode("utf-8"))


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
        analysis = analyse(input_filename, conf)
        new_metadata = {}

        if analysis["species_identify"]:
            species_identify = analysis.pop("species_identify")
            for analysis_result in species_identify:
                model_name = analysis_result.get("model", "Unnamed")
                start_s = analysis_result["begin_s"]
                end_s = analysis_result["end_s"]
                x = start_s / recording["duration"]
                width = end_s / recording["duration"] - x
                y = 0
                height = 1
                position = {}
                track = {}
                if "freq_end" in analysis_result:
                    y = analysis_result["freq_start"] / MAX_FRQUENCY
                    height = (
                        analysis_result["freq_end"] - analysis_result["freq_start"]
                    ) / MAX_FRQUENCY
                    track["minFreq"] = analysis_result["freq_start"]
                    track["maxFreq"] = analysis_result["freq_end"]
                track["scale"] = "linear"
                # convert to 2 decimal places
                x = round(x, 2)
                width = round(width, 2)
                position = {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
                track.update(
                    {
                        "start_s": start_s,
                        "end_s": end_s,
                        "positions": [position],
                    }
                )
                algorithm_id = api.get_algorithm_id({"algorithm": "sliding_window"})
                id = api.add_track(recording, track, algorithm_id)
                predictions = analysis_result["predictions"]
                for i, prediction in enumerate(predictions):
                    species = prediction["species"]
                    confidences = prediction["likelihood"]
                    del prediction["species"]
                    raw_tag = None
                    if len(confidences) == 0 and "raw_tag" in prediction:
                        raw_tag = prediction["raw_tag"]
                        species = [UNIDENTIFIED]
                        confidences = [prediction["raw_confidence"]]

                    for confidence, s in zip(confidences, species):
                        prediction["confidence"] = confidence
                        prediction["tag"] = s
                        data = {"name": "Master"}
                        if raw_tag is not None:
                            data["raw_tag"] = raw_tag

                        if i == 0:
                            # just add master tag for first prediction
                            api.add_track_tag(recording, id, prediction, data)
                        data["name"] = prediction["model"]
                        api.add_track_tag(recording, id, prediction, data)

        if analysis["cacophony_index"]:
            cacophony_index = analysis.pop("cacophony_index")
            new_metadata["cacophonyIndex"] = cacophony_index
            logger.info("cacophony_index: %s", cacophony_index)

        new_metadata["additionalMetadata"] = analysis

    api.report_done(recording, metadata=new_metadata)
    logger.info("Completed processing for file: %s", recording["id"])


def analyse(filename, conf):
    command = conf.audio_analysis_cmd.format(
        folder=filename.parent, basename=filename.name, tag=conf.audio_analysis_tag
    )
    with HandleCalledProcessError():
        output = subprocess.check_output(command, shell=True, stderr=subprocess.PIPE)
    return json.loads(output.decode("utf-8"))
