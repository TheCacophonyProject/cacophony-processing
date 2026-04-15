import shutil
import argparse
import json
import logging
import sys
import processing
from processing import thermal, audio_analysis
from pathlib import Path

import datetime
from main import run_with_api
import pytest
import datetime


def test_duplicate_recordings():

    # init_logging()
    conf = processing.Config.load()
    test_rec = {
        "recording": {
            "id": 1,
            "type": "thermal",
            "jobKey": 2,
            "DeviceId": 1,
            "recordingDateTime": datetime.datetime.now().isoformat(),
        },
        "rawJWT": "./tests/test.cptv",
    }
    jobs = {"thermalRaw": {"trackAndAnalyse": [test_rec, test_rec]}}
    api = TestAPI(jobs)
    logging.info("Running with jobs %s config %s", jobs, conf)
    run_with_api(api, conf, exit_on_finished=True)
    assert (
        len(api.finished) == 1
    ), "Finished should have 1 entry (first job cancelled, second job finished)"
    assert api.finished[0]["success"], "Job should of suceeded"


class TestAPI:
    id_ = 0
    ALGORITHM = 1
    TRUNCATE_OVER = 100

    def __init__(self, jobs):
        self.jobs = jobs
        self.finished = []

    def next_job(self, recording_type, state):
        jobs = self.jobs.get(recording_type)
        if jobs is None:
            return None
        jobs = jobs.get(state)
        if jobs is None or len(jobs) == 0:
            return None
        return jobs.pop()

    def new_id(self):
        TestAPI.id_ += 1
        return TestAPI.id_

    def report_failed(self, rec_id, job_key):
        logging.warning("TestAPI Recording %s failed", rec_id)

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
        logging.debug("TestAPI report_done %s", str(params)[: TestAPI.TRUNCATE_OVER])
        self.finished.append(params)

    def tag_recording(self, recording, label, metadata):
        tag = metadata.copy()
        tag["automatic"] = True

        # Convert "false positive" to API representation.
        if not "event" in metadata:
            tag["event"] = "just wandering about"
            tag["animal"] = label
        data = {"recordingId": recording["id"], "tag": json.dumps(tag)}
        logging.debug("TestAPI tag_recording  %s", str(data)[: TestAPI.TRUNCATE_OVER])

    def get_algorithm_id(self, algorithm):
        post_data = {"algorithm": json.dumps(algorithm)}
        logging.debug(
            "TestAPI get_algorithm_id  %s", str(post_data)[: TestAPI.TRUNCATE_OVER]
        )
        return TestAPI.ALGORITHM

    def add_track(self, recording, track, algorithm_id):
        post_data = {"data": json.dumps(track.post_data()), "algorithmId": algorithm_id}
        track_id = self.new_id()
        logging.debug(
            "TestAPI add_track (%s)  %s",
            track_id,
            str(post_data)[: TestAPI.TRUNCATE_OVER],
        )
        return track_id

    def add_tracks(self, recording, tracks, algorithm_id):
        post_data = {"data": json.dumps(tracks), "algorithmId": algorithm_id}
        track_ids = []
        for track in tracks:
            track_ids.append(self.new_id())
        logging.debug(
            "TestAPI add_tracks (%s)  %s",
            track_ids,
            str(post_data)[: TestAPI.TRUNCATE_OVER],
        )
        return track_ids

    def add_track_tag(self, recording, track_id, prediction, data=""):
        url = "/{}/tracks/{}/tags".format(recording["id"], track_id)

        post_data = {
            "what": prediction.tag,
            "confidence": prediction.confidence,
            "data": json.dumps(data),
        }
        track_tag_id = self.new_id()
        logging.debug(
            "TestAPI add_track_tag (%s) %s,  %s",
            track_tag_id,
            url,
            str(post_data)[: TestAPI.TRUNCATE_OVER],
        )
        return track_tag_id

    def get_rat_threshold(self, deviceId, atTime=None):
        url = f"/ratthresh/{deviceId}"
        if atTime is not None:
            url = f"{url}?at-time={atTime}"

        logging.debug(
            "TestAPI get_rat_threshold (%s) %s",
            deviceId,
            url,
        )
        return None

    def download_file(self, jwtKey, filename):
        shutil.copyfile(jwtKey, filename)
        return


# test_duplicate_recordings()
