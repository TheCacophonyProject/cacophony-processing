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

from collections import namedtuple
from pathlib import Path

import yaml


CONFIG_FILENAME = "processing.yaml"
CONFIG_DIRS = [Path(__file__).parent.parent, Path("/etc/cacophony")]


configTuple = namedtuple(
    "Config",
    [
        "bucket_name",
        "endpoint_url",
        "access_key",
        "secret_key",
        "api_url",
        "no_recordings_wait_secs",
        "classify_dir",
        "classify_cmd",
        "models",
        "do_classify",
        "min_confidence",
        "min_tag_confidence",
        "max_tag_novelty",
        "min_tag_clarity",
        "min_tag_clarity_secondary",
        "min_frames",
        "animal_movement",
        "audio_analysis_cmd",
        "audio_analysis_tag",
        "audio_convert_workers",
        "audio_analysis_workers",
        "thermal_workers",
        "ignore_tags",
    ],
)


class Config(configTuple):
    @classmethod
    def load(cls):
        filename = find_config()
        return cls.load_from(filename)

    @classmethod
    def load_from(cls, filename):
        with open(filename) as stream:
            y = yaml.load(stream)
            s3 = y["s3"]
            thermal = y["thermal"]
            audio = y["audio"]
            return cls(
                bucket_name=s3["default_bucket"],
                endpoint_url=y["s3"]["endpoint"],
                access_key=s3["access_key_id"],
                secret_key=s3["secret_access_key"],
                api_url=y["api_url"],
                no_recordings_wait_secs=y["no_recordings_wait_secs"],
                classify_dir=thermal["classify_command_dir"],
                classify_cmd=thermal["classify_command"],
                do_classify=thermal.get("classify", True),
                models=Config.load_models(thermal.get("models")),
                min_confidence=thermal["tagging"]["min_confidence"],
                min_tag_confidence=thermal["tagging"]["min_tag_confidence"],
                max_tag_novelty=thermal["tagging"]["max_tag_novelty"],
                min_tag_clarity=thermal["tagging"]["min_tag_clarity"],
                min_tag_clarity_secondary=thermal["tagging"]["min_tag_clarity_secondary"],
                min_frames=thermal["tagging"]["min_frames"],
                animal_movement=thermal["tagging"]["animal_movement"],
                audio_analysis_cmd=audio["analysis_command"],
                audio_analysis_tag=audio["analysis_tag"],
                audio_convert_workers=audio["convert_workers"],
                audio_analysis_workers=audio["analysis_workers"],
                thermal_workers=thermal["thermal_workers"],
                ignore_tags=thermal["tagging"].get("ignore_tags", None),
            )

    def load_models(raw):
        if raw is None:
            return None

        models = []
        for model in raw:
            models.append(Model.load(model))

        return models


def find_config():
    for directory in CONFIG_DIRS:
        p = directory / CONFIG_FILENAME
        if p.is_file():
            return str(p)
    raise FileNotFoundError("no configuration file found")


modelConfigTuple = namedtuple("Model", ["name", "model_file", "preview"])


class Model(modelConfigTuple):
    @classmethod
    def load(cls, raw):
        return cls(
            name=raw["name"],
            model_file=raw["model_file"],
            preview=raw.get("preview", "none"),
        )
