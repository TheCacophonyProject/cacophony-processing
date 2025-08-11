import shutil
import argparse
import json
import logging
import sys
import processing
from processing import thermal, audio_analysis
from pathlib import Path


def init_logging():
    """Set up logging for use by various classifier pipeline scripts.

    Logs will go to stderr.
    """

    fmt = "%(levelname)7s %(message)s"
    logging.basicConfig(
        stream=sys.stderr, level=logging.DEBUG, format=fmt, datefmt="%Y-%m-%d %H:%M:%S"
    )


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "source",
        help='a CPTV file to process, or a folder name, or "all" for all files within subdirectories of source folder.',
    )
    args = parser.parse_args()
    return args


def main():
    init_logging()
    conf = processing.Config.load()
    args = parse_args()
    recording_meta = {
        "filename": args.source,
        "id": "testrecid",
        "jobKey": "test job key",
        "rawMimeType": "audio/mp4",
    }
    api = TestAPI()
    source = Path(args.source)
    if source.suffix == ".cptv":
        logging.info("Doing thermal")
        thermal.track(conf, recording_meta, api, 10, logging)

        thermal.classify(conf, recording_meta, api, logging)
    else:
        logging.info("Doing audio")
        meta_file = Path(args.source).with_suffix(".txt")
        if meta_file.exists():
            with meta_file.open("r") as f:
                metadata = json.load(f)
            recording_meta["location"] = metadata.get("location")
        audio_analysis.process_with_api(recording_meta, args.source, api, conf)


class TestAPI:
    id_ = 0
    ALGORITHM = 1
    TRUNCATE_OVER = 100

    def new_id(self):
        TestAPI.id_ += 1
        return TestAPI.id_

    def report_failed(self, rec_id, job_key):
        logging.warn("TestAPI Recording %s failed".rec_id)

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

    def download_file(self, jwtKey, filename):
        shutil.copyfile(jwtKey, filename)

        return


if __name__ == "__main__":
    main()
