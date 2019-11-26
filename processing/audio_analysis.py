import json
import logging
import mimetypes
import subprocess
import tempfile
from pathlib import Path

from pebble import concurrent

import processing.loop

def process(recording, conf):
    api = processing.API(conf.api_url)
    s3 = processing.S3(conf)

    input_extension = mimetypes.guess_extension(recording["rawMimeType"])

    if not input_extension:
        # Unsupported mimetype. If needed more mimetypes can be added above.
        print("unsupported mimetype. Not processing")
        api.report_done(recording, recording["rawFileKey"], recording["rawMimeType"])
        return

    new_metadata = {"additionalMetadata": {}}
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        input_filename = temp_path / ("recording" + input_extension)
        logging.info("downloading recording to %s", input_filename)
        s3.download(recording["rawFileKey"], str(input_filename))

        logging.info("passing recording through audio-processing")
        new_metadata["additionalMetadata"]["analysis"] = analyse(input_filename, conf)

    api.report_done(recording, metadata=new_metadata)
    logging.info("Finished processing: %s", new_metadata)


def analyse(filename, conf):
    command = conf.audio_analysis_cmd.format(
        folder=filename.parent, basename=filename.name
    )
    try:
        output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        logging.error("%s failed with output: %s", command, e.output.decode("utf-8"))
        raise
    print(output.decode("utf-8"))
    return json.loads(output.decode("utf-8"))
