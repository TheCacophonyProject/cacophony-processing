import json
import logging
import mimetypes
import subprocess
import tempfile
from pathlib import Path

import processing


def process(recording, conf):
    logger = processing.logs.worker_logger("audio.analysis", recording["id"])
    logger.info("starting")

    api = processing.API(conf.api_url)
    s3 = processing.S3(conf)

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
    try:
        output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise OSError(f"{command} failed with output: {e.output.decode('utf-8')}")
    return json.loads(output.decode("utf-8"))
