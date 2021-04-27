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

import requests


class API:
    def __init__(self, url):
        self.url = url

    def next_job(self, recording_type, state):
        params = {"type": recording_type, "state": state}
        r = requests.get(self.url, params=params)
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()["recording"]

    def update_metadata(self, recording, fieldUpdates, completed):
        params = {
            "id": recording["id"],
            "jobKey": recording["jobKey"],
            "success": True,
            "result": json.dumps({"fieldUpdates": fieldUpdates}),
            "complete": completed,
        }
        r = requests.put(self.url, data=params)
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

        r = requests.put(self.url, data=params)
        r.raise_for_status()

    def tag_recording(self, recording, label, metadata):
        tag = metadata.copy()
        tag["automatic"] = True

        # Convert "false positive" to API representation.
        if not "event" in metadata:
            tag["event"] = "just wandering about"
            tag["animal"] = label

        r = requests.post(
            self.url + "/tags",
            data={"recordingId": recording["id"], "tag": json.dumps(tag)},
        )
        r.raise_for_status()

    def delete_tracks(self, recording):
        url = self.url + "/{}/tracks".format(recording["id"])
        r = requests.delete(url)
        r.raise_for_status()

    def get_algorithm_id(self, algorithm):
        url = self.url + "/algorithm"
        post_data = {"algorithm": json.dumps(algorithm)}
        r = requests.post(url, data=post_data)
        if r.status_code == 200:
            return r.json()["algorithmId"]
        raise IOError(r.text)

    def add_track(self, recording, track, algorithm_id):
        url = self.url + "/{}/tracks".format(recording["id"])
        post_data = {"data": json.dumps(track), "algorithmId": algorithm_id}
        r = requests.post(url, data=post_data)
        if r.status_code == 200:
            return r.json()["trackId"]
        raise IOError(r.text)

    def add_track_tag(self, recording, track_id, prediction, data=""):
        url = self.url + "/{}/tracks/{}/tags".format(recording["id"], track_id)
        post_data = {
            "what": prediction["tag"],
            "confidence": prediction["confidence"],
            "data": json.dumps(data),
        }
        r = requests.post(url, data=post_data)
        if r.status_code == 200:
            return r.json()["trackTagId"]
        raise IOError(r.text)
