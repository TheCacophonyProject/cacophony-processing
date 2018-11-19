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

FALSE_POSITIVE = "false-positive"


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
            "success": completed,
            "result": json.dumps({"fieldUpdates": fieldUpdates}),
            "complete": completed
        }
        r = requests.put(self.url, data=params)
        r.raise_for_status()


    def report_done(self, recording, newKey, newMimeType):
        params = {
            "id": recording["id"],
            "jobKey": recording["jobKey"],
            "success": True,
            "newProcessedFileKey": newKey,
            "result": json.dumps({"fieldUpdates": {"fileMimeType": newMimeType}}),
        }
        r = requests.put(self.url, data=params)
        r.raise_for_status()

    def tag_recording(self, recording, label, confidence):
        tag = {"automatic": True, "confidence": confidence}

        # Convert "false positive" to API representation.
        if label == FALSE_POSITIVE:
            tag["event"] = "false positive"
        else:
            tag["event"] = "just wandering about"
            tag["animal"] = label

        r = requests.post(
            self.url + "/tags",
            data={"recordingId": recording["id"], "tag": json.dumps(tag)},
        )
        r.raise_for_status()


