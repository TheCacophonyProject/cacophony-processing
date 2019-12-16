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
from . import S3
from . import logs
from .processutils import HandleCalledProcessError


def process(recording, conf):
    logger = logs.worker_logger("audio.analysis", recording["id"])

    api = API(conf.api_url)
    s3 = S3(conf)

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
        s3.download(recording["rawFileKey"], str(input_filename))

        logger.debug("passing recording through audio-processing")
        new_metadata["additionalMetadata"]["analysis"] = analyse(input_filename, conf)

    api.report_done(recording, metadata=new_metadata)
    logger.info("finished")


def analyse(filename, conf):
    command = conf.audio_analysis_cmd.format(
        folder=filename.parent, basename=filename.name
    )

    with HandleCalledProcessError():
        output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
    return json.loads(output.decode("utf-8"))
