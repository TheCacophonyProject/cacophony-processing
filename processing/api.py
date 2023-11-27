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

import json
import os
import requests
import logging
from requests_toolbelt.multipart.encoder import MultipartEncoder
from urllib.parse import urljoin
import hashlib
import jwt
import time

from datetime import datetime

DL_TIMEOUT = 60 * 5
TIMEOUT = 60


def ensure_timeout(args):
    if "timeout" not in args:
        args["timeout"] = TIMEOUT


class API:
    def __init__(self, api_url, user, password, logger):
        self.file_url = urljoin(api_url, "api/v1/processing")
        self.api_url = api_url
        self.user = user
        self._password = password
        self.logger = logger
        self.login()

    def ensure_valid_auth(self, args):
        self.check_token()
        auth = self.auth_header
        headers = args.setdefault("headers", {})
        headers.update(auth)
        return headers

    # convenience methods to ensure authentication token is valid
    def put(self, url, **args):
        self.ensure_valid_auth(args)
        ensure_timeout(args)
        return self.retry_if_auth(requests.put, url, args)

    def post(self, url, **args):
        self.ensure_valid_auth(args)
        ensure_timeout(args)

        return self.retry_if_auth(requests.post, url, args)

    def get(self, url, **args):
        self.ensure_valid_auth(args)
        ensure_timeout(args)
        return self.retry_if_auth(requests.get, url, args)

    def delete(self, url, **args):
        self.ensure_valid_auth(args)
        ensure_timeout(args)
        return self.retry_if_auth(requests.delete, url, args)

    # helper code to retry auth error once
    def retry_if_auth(self, request, url, args):
        retries = 1
        count = 0
        while True:
            try:
                r = None
                r = request(url, **args)
                r.raise_for_status()
                return r
            except requests.exceptions.RequestException as e:
                if r is None or r.status_code != 401 or count >= retries:
                    raise e
                self.logger.warn(
                    "Request failed with 401 token should be valid until %s",
                    datetime.fromtimestamp(self._expiry),
                )
                # hopefully just have failed JWT
                self.login()
                self.ensure_valid_auth(args)
            count += 1

    @property
    def auth_header(self):
        return {"Authorization": self._token}

    def login(self):
        request_time = time.time()
        self._token = self._get_jwt()
        try:
            decoded = jwt.decode(
                self._token.replace("JWT ", ""),
                algorithms=["HS256"],
                options={"verify_signature": False},
            )
            expiry = decoded["exp"]
            iat = decoded["iat"]
            exp_seconds = expiry - iat
            # give 30 seconds less so we are always valid
            self._expiry = request_time + exp_seconds - 30
            self.logger.debug(
                "login expires at %s iat %s JWT expiry %s",
                datetime.fromtimestamp(self._expiry),
                datetime.fromtimestamp(iat),
                datetime.fromtimestamp(expiry),
            )
        except:
            self.logger.error(
                "Error getting token expiry using 5 minute", exc_info=True
            )
            self._expiry = request_time + 5 * 60 - 30

    def _get_jwt(self):
        url = urljoin(self.api_url, "api/v1/users/authenticate")
        r = requests.post(url, data={"email": self.user, "password": self._password})
        r.raise_for_status()
        return r.json().get("token")

    # if token expired get a new one
    def check_token(self):
        self.logger.debug(
            "login expired %s expires at %s",
            self._expiry < time.time(),
            datetime.fromtimestamp(self._expiry),
        )

        if self._expiry < time.time():
            self.login()

    def next_job(self, recording_type, state):
        params = {"type": recording_type, "state": state}
        r = self.get(self.file_url, params=params)
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def update_metadata(self, recording, fieldUpdates, completed):
        params = {
            "id": recording["id"],
            "jobKey": recording["jobKey"],
            "success": True,
            "result": json.dumps({"fieldUpdates": fieldUpdates}),
            "complete": completed,
        }
        r = self.put(self.file_url, data=params)
        r.raise_for_status()

    def report_failed(self, rec_id, job_key):
        params = {
            "id": rec_id,
            "success": False,
            "complete": False,
            "jobKey": job_key,
        }

        r = self.put(self.file_url, data=params)
        r.raise_for_status()

    def report_done(self, recording, newKey=None, newMimeType=None, metadata=None):
        if not metadata:
            metadata = {}
        if newMimeType:
            metadata["fileMimeType"] = newMimeType

        params = {
            "jobKey": recording["jobKey"],
            "id": recording["id"],
            "success": True,
            "result": json.dumps({"fieldUpdates": metadata}),
        }
        if newKey:
            params["newProcessedFileKey"] = newKey

        r = self.put(self.file_url, data=params)
        r.raise_for_status()

    def tag_recording(self, recording, label, metadata):
        tag = metadata.copy()
        tag["automatic"] = True

        # Convert "false positive" to API representation.
        if not "event" in metadata:
            tag["detail"] = label
            tag["confidence"] = metadata.get("confidence")
        else:
            tag["detail"] = tag["event"]
            del tag["event"]
        rec_id = recording["id"]
        r = self.post(
            f"{self.api_url}/api/v1/recordings/{rec_id}/tags",
            data={"tag": json.dumps(tag)},
        )

        r.raise_for_status()

    def get_rat_threshold(self, deviceId, atTime=None):
        url = f"/ratthresh/{deviceId}"
        if atTime is not None:
            url = f"{url}?at-time={atTime}"

        r = self.get(self.file_url + url)
        return r.json().get("deviceHistoryEntry")

    def get_algorithm_id(self, algorithm):
        url = self.file_url + "/algorithm"
        post_data = {"algorithm": json.dumps(algorithm)}
        r = self.post(url, data=post_data)
        if r.status_code == 200:
            return r.json()["algorithmId"]
        raise IOError(r.text)

    def archive_track(self, recording, track):
        url = self.file_url + "/{}/tracks/{}/archive".format(
            recording["id"], track["id"]
        )
        r = self.post(url)
        if r.status_code == 200:
            return
        raise IOError(r.text)

    def update_track(self, recording, track):
        url = self.file_url + "/{}/tracks/{}".format(recording["id"], track["id"])
        post_data = {"data": json.dumps(track)}
        r = self.post(url, data=post_data)
        if r.status_code == 200:
            return
        raise IOError(r.text)

    def add_track(self, recording, track, algorithm_id):
        url = self.file_url + "/{}/tracks".format(recording["id"])
        post_data = {"data": json.dumps(track), "algorithmId": algorithm_id}
        r = self.post(url, data=post_data)
        if r.status_code == 200:
            return r.json()["trackId"]
        raise IOError(r.text)

    def add_track_tag(self, recording, track_id, prediction, data=""):
        url = self.file_url + "/{}/tracks/{}/tags".format(recording["id"], track_id)

        post_data = {
            "what": prediction["tag"],
            "confidence": prediction["confidence"],
            "data": json.dumps(data),
        }
        r = self.post(url, data=post_data)
        if r.status_code == 200:
            return r.json()["trackTagId"]
        raise IOError(r.text)

    def get_track_info(self, recording_id):
        r = self.get(self.api_url + "/api/v1/recordings/{}/tracks".format(recording_id))
        r.raise_for_status()
        return r.json()

    def download_file(self, token, filename):
        r = requests.get(
            urljoin(self.api_url, "/api/v1/signedUrl"),
            params={"jwt": token},
            stream=True,
            timeout=DL_TIMEOUT,
        )
        r.raise_for_status()
        return iter_to_file(filename, r.iter_content(chunk_size=4096))


def iter_to_file(filename, source, overwrite=True):
    if not overwrite and Path(filename).is_file():
        logging.debug("%s already exists", filename)
        return False
    with open(filename, "wb") as f:
        for chunk in source:
            f.write(chunk)
    return True
