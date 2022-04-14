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


def process(recording, jwtKey, conf):
    """ Process the audio file.
    
    Downloads the file, runs the AI models & cacophony index algorithm,
    and uploads the results to the API.

    Args:
        recording: The recording to process.
        jwtKey: The JWT key to use for the API.
        conf: The configuration object.

    Returns:
        The API response.
    """
    logger = logs.worker_logger("audio.analysis", recording["id"])

    api = API(conf.file_api_url, conf.api_url)

    input_extension = mimetypes.guess_extension(recording["rawMimeType"])

    if not input_extension:
        # Unsupported mimetype. If needed more mimetypes can be added above.
        logger.error("unsupported mimetype. Not processing")
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

        if "species_identify" in analysis:
            species_identify = analysis.pop("species_identify")
            for analysis_result in species_identify:
                start_s = analysis_result["begin_s"]
                end_s = analysis_result["end_s"]
                x = start_s / recording["duration"]
                width = end_s / recording["duration"] - x
                logger.info("x: %s width: %s duration: %s", analysis_result, width, recording["duration"])
                #convert to 2 decimal places
                x = round(x, 4)
                width = round(width, 4)
                position = {
                    "x": x,
                    "y": 0,
                    "width": width,
                    "height": 1,
                }
                track = {
                    "start_s": start_s,
                    "end_s": end_s,
                    "positions": [position],
                }
                algorithm_id = api.get_algorithm_id({"algorithm":"sliding_window"})
                id = api.add_track(recording, track, algorithm_id)
                analysis_result["tag"] = analysis_result["species"]
                analysis_result["confidence"] = analysis_result["liklihood"]
                data = {"name": "Master"}
                api.add_track_tag(recording, id, analysis_result, data)

        if "cacophony_index" in analysis:
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
