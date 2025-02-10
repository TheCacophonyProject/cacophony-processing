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
import attr
import yaml


CONFIG_FILENAME = "processing.yaml"
CONFIG_DIRS = [Path(__file__).parent.parent, Path("/etc/cacophony")]


configTuple = namedtuple(
    "Config",
    [
        "restart_after",
        "temp_dir",
        "api_credentials",
        "no_recordings_wait_secs",
        "classify_image",
        "classify_cmd",
        "track_cmd",
        "min_confidence",
        "min_tag_confidence",
        "max_tag_novelty",
        "min_tag_clarity",
        "min_tag_clarity_secondary",
        "audio_analysis_cmd",
        "audio_analysis_tag",
        "audio_analysis_workers",
        "thermal_analyse_workers",
        "thermal_tracking_workers",
        "ignore_tags",
        "wallaby_devices",
        "master_tag",
        "cache_clips_bigger_than",
        "classify_trail_cmd",
        "trail_workers",
        "ir_tracking_workers",
        "ir_analyse_workers",
        "do_retrack",
        "filter_false_positive",
        "false_positive_min_confidence",
        "max_tracks",
        "no_job_sleep_seconds",
        "subprocess_timeout",
    ],
)


class Config(configTuple):
    @property
    def api_url(self):
        return self.api_credentials.api_url

    @property
    def user(self):
        return self.api_credentials.user

    @property
    def password(self):
        return self.api_credentials.password

    @classmethod
    def load(cls, filename=None):
        if filename is None:
            filename = find_config()
        return cls.load_from(filename)

    @classmethod
    def load_from(cls, filename):
        with open(filename) as stream:
            y = yaml.load(stream, Loader=yaml.FullLoader)
            thermal = y["thermal"]
            audio = y["audio"]
            trail = y["trailcam"]
            ir = y["ir"]
            restart_after = y.get("restart_after")
            if restart_after is not None:
                # convert to seconds
                restart_after = restart_after * 60 * 60
            return cls(
                restart_after=restart_after,
                temp_dir=y["temp_dir"],
                api_credentials=APICredentials(
                    api_url=y["api_url"],
                    user=y["api_user"],
                    password=y["api_password"],
                ),
                no_recordings_wait_secs=y["no_recordings_wait_secs"],
                classify_image=thermal["classify_image"],
                classify_cmd=thermal["classify_cmd"],
                track_cmd=thermal["track_cmd"],
                master_tag=thermal.get("master_tag", "Master"),
                wallaby_devices=thermal["wallaby_devices"],
                min_confidence=thermal["tagging"]["min_confidence"],
                min_tag_confidence=thermal["tagging"]["min_tag_confidence"],
                max_tag_novelty=thermal["tagging"]["max_tag_novelty"],
                min_tag_clarity=thermal["tagging"]["min_tag_clarity"],
                min_tag_clarity_secondary=thermal["tagging"][
                    "min_tag_clarity_secondary"
                ],
                audio_analysis_cmd=audio["analysis_command"],
                audio_analysis_tag=audio["analysis_tag"],
                audio_analysis_workers=audio.get("analysis_workers", 1),
                thermal_analyse_workers=thermal.get("analyse_workers", 1),
                thermal_tracking_workers=thermal.get("tracking_workers", 1),
                ignore_tags=thermal["tagging"].get("ignore_tags", None),
                cache_clips_bigger_than=thermal.get("cache_clips_bigger_than"),
                classify_trail_cmd=trail["run_cmd"],
                trail_workers=trail.get("trail_workers", 1),
                ir_tracking_workers=ir.get("tracking_workers", 0),
                ir_analyse_workers=ir.get("analyse_workers", 0),
                do_retrack=thermal.get("do_retrack", False),
                filter_false_positive=thermal.get("filter_false_positive", True),
                false_positive_min_confidence=thermal.get(
                    "false_positive_min_confidence", 0.7
                ),
                max_tracks=thermal.get("max_tracks", 10),
                no_job_sleep_seconds=y.get("no_job_sleep_seconds", 30),
                subprocess_timeout=y.get("subprocess_timeout", 60 * 20),
            )


def find_config():
    for directory in CONFIG_DIRS:
        p = directory / CONFIG_FILENAME
        if p.is_file():
            return str(p)
    raise FileNotFoundError("no configuration file found")


@attr.s
class ModelConfig:
    id = attr.ib()
    name = attr.ib()
    model_file = attr.ib()
    wallaby = attr.ib()
    tag_scores = attr.ib()
    ignored_tags = attr.ib()
    classify_time = attr.ib()
    reclassify = attr.ib(default=None)
    submodel = attr.ib(default=False)

    @classmethod
    def load(cls, raw):
        model = cls(
            id=raw["id"],
            name=raw["name"],
            model_file=raw["model_file"],
            wallaby=raw["wallaby"],
            tag_scores=raw["tag_scores"],
            ignored_tags=raw.get("ignored_tags", []),
            classify_time=raw.get("classify_time"),
            reclassify=raw.get("reclassify"),
            submodel=raw.get("submodel", False),
        )
        return model


class APICredentials:
    def __init__(self, api_url, user, password):
        self.api_url = api_url
        self.user = user
        self.password = password
