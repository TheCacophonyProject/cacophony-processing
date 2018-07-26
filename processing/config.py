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

import yaml


configTuple = namedtuple(
    "Config",
    [
        "bucket_name",
        "endpoint_url",
        "access_key",
        "secret_key",
        "api_url",
        "classify_dir",
        "classify_cmd",
    ],
)


class Config(configTuple):
    @classmethod
    def load(cls, filename):
        with open(filename) as stream:
            y = yaml.load(stream)
            return cls(
                bucket_name=y["s3"]["default_bucket"],
                endpoint_url=y["s3"]["endpoint"],
                access_key=y["s3"]["access_key_id"],
                secret_key=y["s3"]["secret_access_key"],
                api_url=y["api_url"],
                classify_dir=y["classify_command_dir"],
                classify_cmd=y["classify_command"],
            )
