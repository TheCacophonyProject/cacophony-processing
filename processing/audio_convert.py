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

import subprocess
import tempfile
import mimetypes
from pathlib import Path

import librosa

from . import API
from . import logs
from .processutils import HandleCalledProcessError


MAX_AMPLIFICATION = 20

mimetypes.add_type("audio/mp4", ".mp3")
mimetypes.add_type("video/3gpp", ".3gpp")
mimetypes.add_type("audio/3gpp", ".3gpp")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/x-flac", ".flac")

BIT_RATE = "128k"


def process(recording, jwt, conf):
    logger = logs.worker_logger("audio.convert", recording["id"])

    api = API(conf.file_api_url, conf.api_url)

    input_extension = mimetypes.guess_extension(recording["rawMimeType"])

    if not input_extension:
        # Unsupported mimetype. If needed more mimetypes can be added above.
        logger.error("Unsupported mimetype. Not processing")
        api.report_done(recording, recording["rawFileKey"], recording["rawMimeType"])
        return

    new_metadata = {"additionalMetadata": {}}
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        input_filename = temp_path / ("recording" + input_extension)
        logger.debug("downloading recording to %s", input_filename)
        api.download_file(jwt, str(input_filename))

        output_filename, new_mime_type, duration = create_wav(input_filename)
        new_metadata["duration"] = duration

        logger.debug("uploading from %s, duration: %s sample_rate: %s", output_filename, duration, sr)
        new_key = api.upload_file(str(output_filename))["fileKey"]

    api.report_done(recording, new_key, new_mime_type, new_metadata)
    logger.info("Finished")


def create_wav(filename):
    data, sr = librosa.load(str(filename), sr=None)
    duration = librosa.get_duration(data, sr)

    wav_filename = filename.parent / "output.wav"

    librosa.output.write_wav(str(wav_filename), data, sr)
    return str(wav_filename), "audio/wav", duration


def normalize(data, max_amp):
    a = 1.0 / data.max()
    a = min(a, max_amp)
    data *= a
    return a


def encode_file(input_filename):
    output_filename = replace_ext(input_filename, ".mp3")

    with HandleCalledProcessError():
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
    return output_filename, "audio/mp3"


def replace_ext(filename, ext):
    return filename.parent / (filename.stem + ext)
