#!/usr/bin/python3

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

import logging
import subprocess
import tempfile
import time
import traceback
from pprint import pformat
from pathlib import Path

import processing

SLEEP_SECS = 10

processing.init_logging()
conf = processing.Config.load("config.yaml")

# These input MIME types will be converted to mp4
MIME_TYPES_TO_PROCESS = {
    "video/3gpp": "3gpp",
    "audio/3gpp": "3gpp",
    "audio/wav": "wav",
    "audio/x-flac": "flac",
}

BIT_RATE = "128k"


def process(recording, api, s3):
    input_extension = MIME_TYPES_TO_PROCESS.get(recording["rawMimeType"])

    if not input_extension:
        # Nothing to do so just mirror the raw key and MIME type to
        # the processes column.
        print("no processing required, mirroring raw key to processed key")
        api.report_done(recording, recording["rawFileKey"], recording["rawMimeType"])
        return

    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        input_filename = temp_path / ("recording." + input_extension)

        logging.info("downloading recording to %s", input_filename)
        s3.download(recording["rawFileKey"], str(input_filename))

        output_filename, new_mime_type = encode_file(input_filename)

        logging.info("uploading from %s", output_filename)
        new_key = s3.upload(str(output_filename))

    api.report_done(recording, new_key, new_mime_type)
    logging.info("Finished processing")


def encode_file(input_filename):
    output_filename = replace_ext(input_filename, ".mp3")
    try:
        subprocess.check_output(
            [
                "ffmpeg",
                "-loglevel",
                "warning",
                "-i",
                str(input_filename),
                "-b:a",
                BIT_RATE,
                str(output_filename),
            ],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        logging.error("ffmpeg failed with output: %s", e.output.encode("utf-8"))
        raise

    return output_filename, "audio/mp3"


def replace_ext(filename, ext):
    return filename.parent / (filename.stem + ext)


def main():
    api = processing.API(conf.api_url)
    s3 = processing.S3(conf)

    while True:
        try:
            recording = api.next_job("audio", "toMp3")
            if recording:
                logging.info("recording to process:\n%s", pformat(recording))
                process(recording, api, s3)
            else:
                time.sleep(SLEEP_SECS)
        except KeyboardInterrupt:
            break
        except:
            # TODO - failures should be reported back over the API
            logging.error(traceback.format_exc())
            time.sleep(SLEEP_SECS)


if __name__ == "__main__":
    main()
