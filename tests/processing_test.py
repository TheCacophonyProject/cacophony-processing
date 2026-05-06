import shutil
import json
import logging
import processing

import datetime
import threading
from main import run_with_api
import datetime
import time


REC_ID = 1


def test_duplicate_recordings():
    # 2 recordings with the same recording id will cause the first to be cancelled and second completed
    conf = processing.Config.load("./tests/processing_test.yaml")
    test_rec = get_thermal_rec()
    test_rec_2 = get_thermal_rec()
    test_rec_2["recording"]["id"] = test_rec["recording"]["id"]
    jobs = {"thermalRaw": {"trackAndAnalyse": [test_rec, test_rec]}}
    api = TestAPI(jobs)
    logging.info("Running with jobs %s config %s", jobs, conf)
    run_with_api(api, conf, exit_on_finished=True)
    assert (
        len(api.finished) == 1
    ), "Finished should have 1 entry (first job cancelled, second job finished)"
    assert api.finished[0]["success"], "Job should of suceeded"


def test_normal_operation():
    # 2 thermal recoridngs and no audio, with only 1 thread for audio and 1 for thermal allows both thermals to run borrowing audios worker
    conf = processing.Config.load("./tests/processing_test_2.yaml")
    jobs = {
        "thermalRaw": {
            "trackAndAnalyse": [get_thermal_rec(), get_thermal_rec()],
        },
    }
    jobs["audio"] = {"analyse": [get_audio_rec()]}

    api = TestAPI(jobs)
    logging.info("Running with jobs %s config %s", jobs, conf)
    t = threading.Thread(
        target=run_with_api, args=(api, conf), kwargs={"exit_on_finished": True}
    )
    t.start()
    try:
        time.sleep(5)
        assert (
            len(api.jobs["thermalRaw"]["trackAndAnalyse"]) == 1
        ), "thermal worker should only run after audio is finished"
        assert (
            len(api.jobs["audio"]["analyse"]) == 0
        ), "audio worker should be scheduled"

        t.join()
        assert len(api.finished) == 3, "Finished should have 3 entries"
        assert api.finished[0]["success"], "Job should of suceeded"
    except Exception as e:
        t.join()
        raise e


def test_balancing():
    # 3 thermal recoridngs and no audio, with only 1 thread for audio and 2 for thermal allows all thermals to run borrowing audios worker
    # audio waits for a thermal rec to finish
    conf = processing.Config.load("./tests/processing_test.yaml")
    jobs = {
        "thermalRaw": {
            "trackAndAnalyse": [
                get_thermal_rec(),
                get_thermal_rec(),
                get_thermal_rec(),
            ],
        },
    }

    api = TestAPI(jobs)
    for rec_type, job in jobs.items():
        for state, recs in job.items():
            logging.info("Running %s %s: %s jobs", rec_type, state, len(recs))
    t = threading.Thread(
        target=run_with_api, args=(api, conf), kwargs={"exit_on_finished": True}
    )
    t.start()
    time.sleep(2)
    assert (
        len(api.jobs["thermalRaw"]["trackAndAnalyse"]) == 0
    ), "thermal worker should use audio worker slot"
    jobs["audio"] = {"analyse": [get_audio_rec()]}

    time.sleep(2)
    assert (
        len(api.jobs["audio"]["analyse"]) == 1
    ), "audio worker that got added later has to wait for a slot"

    t.join()
    assert len(api.finished) == 4, "Finished should have 4 entries"
    assert api.finished[0]["success"], "Job should of suceeded"


class TestAPI:
    id_ = 0
    ALGORITHM = 1
    TRUNCATE_OVER = 100

    def __init__(self, jobs):
        self.jobs = jobs
        self.finished = []

    def next_job(self, recording_type, states):
        jobs = self.jobs.get(recording_type)
        if jobs is None:
            return None

        jobs = jobs.get(states[0])
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


def get_thermal_rec():
    global REC_ID
    test_rec = {
        "recording": {
            "id": REC_ID,
            "type": "thermal",
            "jobKey": 2,
            "DeviceId": 1,
            "recordingDateTime": datetime.datetime.now().isoformat(),
            "processingState": "trackAndAnalyse",
        },
        "rawJWT": "./tests/test.cptv",
    }
    REC_ID += 1
    return test_rec


def get_audio_rec():
    global REC_ID
    test_audio_1 = {
        "recording": {
            "id": REC_ID,
            "type": "audio",
            "jobKey": 2,
            "DeviceId": 1,
            "recordingDateTime": datetime.datetime.now().isoformat(),
            "rawMimeType": "audio/mp4",
            "processingState": "analyse",
        },
        "rawJWT": "./tests/test.m4a",
    }
    REC_ID += 1
    return test_audio_1
