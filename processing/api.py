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


class API:
    def __init__(self, file_url, api_url):
        self.file_url = file_url
        self.api_url = api_url

    def next_job(self, recording_type, state):
        params = {"type": recording_type, "state": state}
        r = requests.get(self.file_url, params=params)
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
        r = requests.put(self.file_url, data=params)
        r.raise_for_status()

    def report_failed(self, rec_id, job_key):
        params = {
            "id": rec_id,
            "success": False,
            "complete": False,
            "jobKey": job_key,
        }

        r = requests.put(self.file_url, data=params)
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
            "complete": True,
            "result": json.dumps({"fieldUpdates": metadata}),
        }
        if newKey:
            params["newProcessedFileKey"] = newKey

        r = requests.put(self.file_url, data=params)
        r.raise_for_status()

    def tag_recording(self, recording, label, metadata):
        tag = metadata.copy()
        tag["automatic"] = True

        # Convert "false positive" to API representation.
        if not "event" in metadata:
            tag["event"] = "just wandering about"
            tag["animal"] = label

        r = requests.post(
            self.file_url + "/tags",
            data={"recordingId": recording["id"], "tag": json.dumps(tag)},
        )
        r.raise_for_status()

    def delete_tracks(self, recording):
        url = self.file_url + "/{}/tracks".format(recording["id"])
        r = requests.delete(url)
        r.raise_for_status()

    def get_algorithm_id(self, algorithm):
        url = self.file_url + "/algorithm"
        post_data = {"algorithm": json.dumps(algorithm)}
        r = requests.post(url, data=post_data)
        if r.status_code == 200:
            return r.json()["algorithmId"]
        raise IOError(r.text)

    def add_track(self, recording, track, algorithm_id):
        url = self.file_url + "/{}/tracks".format(recording["id"])
        post_data = {"data": json.dumps(track), "algorithmId": algorithm_id}
        r = requests.post(url, data=post_data)
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
        r = requests.post(url, data=post_data)
        if r.status_code == 200:
            return r.json()["trackTagId"]
        raise IOError(r.text)

    def download_file(self, token, filename):
        r = requests.get(
            urljoin(self.api_url, "/api/v1/signedUrl"),
            params={"jwt": token},
            stream=True,
        )
        r.raise_for_status()
        return iter_to_file(filename, r.iter_content(chunk_size=4096))

    def upload_file(self, filename):
        url = self.file_url + "/processed"
        data = {"fileHash": sha_hash(filename)}
        try:
            with open(filename, "rb") as content:
                multipart_data = MultipartEncoder(
                    fields={
                        "data": json.dumps(data),
                        "file": (os.path.basename(filename), content),
                    }
                )
                headers = {"Content-Type": multipart_data.content_type}
                r = requests.post(url, data=multipart_data, headers=headers)

            if r.status_code == 200:
                print("Successful upload of ", filename)
            print("status is", r.status_code, r.json())
        except:
            logging.error("Error uploading", exc_info=true)
        r.raise_for_status()
        return r.json()


def sha_hash(filename):
    buffer = 65536
    sha1 = hashlib.sha1()
    with open(filename, "rb") as f:
        while True:
            data = f.read(buffer)
            if not data:
                break
            sha1.update(data)
    return sha1.hexdigest()


def iter_to_file(filename, source, overwrite=True):
    if not overwrite and Path(filename).is_file():
        logging.debug("%s already exists", filename)
        return False
    with open(filename, "wb") as f:
        for chunk in source:
            f.write(chunk)
    return True
