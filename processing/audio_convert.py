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
import librosa
import mimetypes
from pathlib import Path

from pebble import concurrent

import processing

MAX_AMPLIFICATION = 20

mimetypes.add_type("audio/mp4", ".mp3")
mimetypes.add_type("video/3gpp", ".3gpp")
mimetypes.add_type("audio/3gpp", ".3gpp")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/x-flac", ".flac")

BIT_RATE = "128k"

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

        logging.info("normalizing")
        output_filename, new_mime_type, amplification = normalize_file(input_filename)
        new_metadata["additionalMetadata"]["amplification"] = amplification

        logging.info("uploading from %s", output_filename)
        new_key = s3.upload_recording(str(output_filename))

    api.report_done(recording, new_key, new_mime_type, new_metadata)
    logging.info("Finished processing: %s", new_metadata)


def normalize_file(filename):
    data, sr = librosa.core.load(str(filename), sr=None)
    amplification = normalize(data, MAX_AMPLIFICATION)

    wav_filename = filename.parent / "output.wav"

    librosa.output.write_wav(str(wav_filename), data, sr)
    out_filename, out_mimetype = encode_file(wav_filename)
    return out_filename, out_mimetype, amplification


def normalize(data, max_amp):
    a = 1.0 / data.max()
    a = min(a, max_amp)
    data *= a
    return a


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
