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

from datetime import date

import uuid
import boto3


class S3:
    def __init__(self, config):
        self.s3 = boto3.resource(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
        )
        self.bucket = self.s3.Bucket(config.bucket_name)

    def download(self, key, file_name):
        self.bucket.download_file(key, file_name)

    def upload_recording(self, source_file_name):
        key = "rec/" + date.today().strftime("%Y/%m/%d") + "/" + str(uuid.uuid1())
        self.bucket.upload_file(source_file_name, key)
        return key
