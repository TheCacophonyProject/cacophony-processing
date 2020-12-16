#!/usr/bin/python
import sys
from pathlib import Path
import argparse
import logging

from dateutil.parser import parse

from cacophonyapi.user import UserAPI

import queue
import threading

from processing.config import Config
from processing import thermal, API


class Pool:
    """
    Simple worker thread pool
    """

    def __init__(self, num_workers, run, *args):
        self._q = queue.Queue()
        args = (self._q,) + args
        self._threads = []
        for _ in range(num_workers):
            t = threading.Thread(target=run, args=args)
            t.start()
            self._threads.append(t)

    def put(self, item):
        self._q.put(item)

    def stop(self):
        self._q.join()

        for _ in self._threads:
            self._q.put(None)
        for t in self._threads:
            t.join()


class MasterTagger:
    def __init__(self, config):
        self.file_api = API(config.api_url)
        self.user = None
        self.password = None
        self.limit = None
        self.workers = 4
        self.processed = 0
        self.config = config
        self.models_by_name = {}
        self.tag_mode = None
        self.start_date = None
        self.end_date = None
        for model in config.models:
            self.models_by_name[model.name] = model

    def log(self, message):
        if self.verbose:
            print(message)

    def process(self, url):
        """ Downloads all requested files from specified server """
        self.processed = 0

        api = UserAPI(url, self.user, self.password)

        if self.recording_id:
            recording = api.get(self.recording_id)
            self.add_master_tag(recording, api)
            return
        print("Querying server {0}".format(url))
        print("Limit is {0}".format(self.limit))
        print("Tag mode {0}".format(self.tag_mode))
        print("Dates are {0} - {1}".format(self.start_date, self.end_date))
        pool = Pool(self.workers, self.process_all, api)
        offset = 0
        remaining = self.limit
        while self.limit is None or offset < self.limit:
            rows = api.query(
                limit=remaining,
                startDate=self.start_date,
                endDate=self.end_date,
                tagmode=self.tag_mode,
                offset=offset,
            )
            if len(rows) == 0:
                break
            offset += len(rows)
            if remaining:
                remaining -= len(rows)

            for row in rows:
                pool.put(row)
        pool.stop()

    def process_all(self, q, api):
        """ Worker to handle downloading of files. """
        while True:

            r = q.get()
            if r is None:
                print("Worker processed %d" % (self.processed))
                break

            try:
                self.add_master_tag(r, api)
                self.processed += 1
            finally:
                q.task_done()

    def add_master_tag(self, r, api):
        wallaby_device = thermal.is_wallaby_device(self.config.wallaby_devices, r)
        tracks = api.get_tracks(r["id"]).get("tracks")
        for track in tracks:
            tags = track.get("TrackTags", [])
            tags = [tag for tag in tags if tag["automatic"]]

            if len(tags) == 0:
                continue

            # since data can be anything have to check it is a dictionary
            master_tag = [
                tag
                for tag in tags
                if isinstance(tag.get("data", {}), dict)
                and tag.get("data", {}).get("name") == self.config.master_tag
            ]

            if len(master_tag) > 0:
                logging.info("Already have a master tag for %d", r["id"])
                continue
            results = []
            unmatched = []
            for tag in tags:
                # thermal looks for tag not what
                tag["tag"] = tag["what"]
                tag_data = tag.get("data", {})
                if not isinstance(tag.get("data", {}), dict):
                    unmatched.append(tag)
                    continue
                model_name = tag_data.get("name")
                model = self.models_by_name.get(model_name)
                if model is None:
                    unmatched.append(tag)
                else:
                    model_result = thermal.ModelResult(
                        model, None, None, tag_data.get("algorithmId")
                    )
                    results.append((model_result, tag))
            if len(results) > 0 and len(unmatched) > 0:
                logging.warn(
                    "Not processing %d as has matched and unmatched models matched: %s unmatched %s",
                    r["id"],
                    [result[0].name for result in results],
                    unmatched,
                )
                return

            if len(unmatched) == 1:
                logging.info(
                    "Only one unmatched model for %d so using %s as Original",
                    r["id"],
                    tag,
                )
                # this is the old palce with single ai tracks
                alg_id = track.get("AlgorithmId")
                model_result = thermal.ModelResult(
                    self.models_by_name["Original"], None, None, alg_id
                )
                tag = unmatched[0]
                # needs to point to track id rather than tracktagid
                tag["id"] = track["id"]
                thermal.add_track_tags(
                    self.file_api,
                    r,
                    tag,
                    model_result,
                    logging,
                    model_name=self.config.master_tag,
                )
            else:
                master_tag = thermal.get_master_tag(results, wallaby_device)
                # needs to point to track id rather than tracktagid
                master_tag[1]["id"] = track["id"]
                logging.debug(
                    "Got master tag %s for rec %d with tags %s",
                    master_tag[1]["tag"] if master_tag else "None",
                    r["id"],
                    [(tag["data"]["name"], tag["tag"]) for tag in tags],
                )
                if master_tag:
                    thermal.add_track_tags(
                        self.file_api,
                        r,
                        master_tag[1],
                        master_tag[0],
                        logging,
                        model_name=self.config.master_tag,
                    )


def main():
    logging.basicConfig(
        stream=sys.stderr, level=logging.DEBUG, datefmt="%Y-%m-%d %H:%M:%S"
    )
    conf = Config.load()
    args = parse_args()
    downloader = MasterTagger(conf)
    downloader.recording_id = args.recording_id
    downloader.user = args.user
    downloader.password = args.password

    if args.start_date:
        downloader.start_date = parse(args.start_date)

    if args.end_date:
        downloader.end_date = parse(args.end_date)

    if args.recording_id:
        print("Adding Master Tag to Recording - {}".format(downloader.recording_id))

    if args.limit > 0:
        downloader.limit = args.limit
    downloader.tag_mode = args.tag_mode

    server_list = []
    if args.server:
        server_list = args.server if isinstance(args.server, list) else [args.server]

    for server in server_list:
        downloader.process(server)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("user", help="API server username")
    parser.add_argument("password", help="API server password")
    parser.add_argument(
        "-s",
        "--server",
        default=["https://api.cacophony.org.nz"],
        help="CPTV file server URL",
    )
    parser.add_argument(
        "--start-date",
        help="If specified, only files recorded on or after this date will be downloaded.",
    )
    parser.add_argument(
        "--end-date",
        help="If specified, only files recorded before or on this date will be downloaded.",
    )
    parser.add_argument(
        "-i",
        "--ignore",
        action="append",
        default=None,
        help="Tag to ignore - can use multiple times",
    )
    parser.add_argument(
        "-x",
        "--auto-delete",
        action="store_true",
        default=False,
        help="If enabled clips found in sub-folders other than their tag folder will be deleted.",
    )
    parser.add_argument(
        "-l", "--limit", type=int, default=1000, help="Limit number of downloads"
    )
    parser.add_argument(
        "-m",
        "--tagmode",
        dest="tag_mode",
        default="automatic-tagged",
        help="Select videos by only a particular tag mode.  Default is only selects videos tagged by both humans and automatic",
    )
    parser.add_argument(
        "-id",
        dest="recording_id",
        default=None,
        help="Specify the recording id to download",
    )

    # yapf: enable

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    main()
