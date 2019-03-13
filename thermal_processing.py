#!/usr/bin/python3

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
import logging
import subprocess
import tempfile
import time
import traceback
from pprint import pformat
from pathlib import Path
from cptv import CPTVReader
from processing.tagger import calculate_tags
import processing


DOWNLOAD_FILENAME = "recording.cptv"
SLEEP_SECS = 10
FRAME_RATE = 9

MIN_TRACK_CONFIDENCE = 0.85
FALSE_POSITIVE = "false-positive"
UNIDENTIFIED = "unidentified"

def classify(recording, api, s3):
    working_dir = recording["filename"].parent
    command = conf.classify_cmd.format(
        folder=str(working_dir),
        source=recording["filename"].name,
    )

    logging.info("processing %s", recording["filename"])
    p = subprocess.run(
        command, cwd=conf.classify_dir, shell=True, stdout=subprocess.PIPE
    )
    p.check_returncode()

    output = p.stdout.decode("ascii")
    try:
        classify_info = json.loads(output)
    except json.decoder.JSONDecodeError as err:
        raise ValueError(
            "failed to JSON decode classifier output:\n{}".format(output)
        ) from err

    track_info = classify_info["tracks"]
    formatted_tracks = format_track_data(track_info)

    # Auto tag the video
    tagged_tracks, tags = calculate_tags(formatted_tracks, conf)
    for tag in tags.keys():
        logging.info("tag: %s (%.2f)", tag, tags[tag]["confidence"])
        api.tag_recording(recording, tag, tags[tag])

    upload_tracks(api, recording, classify_info["algorithm"], tagged_tracks)

    # print output:
    print_results(formatted_tracks)

    # Upload mp4
    video_filename = str(replace_ext(recording["filename"], ".mp4"))
    logging.info("uploading %s", video_filename)
    new_key = s3.upload(video_filename)

    # delete track positions before saving metadata
    for track in formatted_tracks:
        del track["positions"]

    metadata = {"additionalMetadata": {
        "tracks" : formatted_tracks,
        "algorithm" : classify_info["algorithm"]
    }}
    api.report_done(recording, new_key, "video/mp4", metadata)
    logging.info("Finished processing")

def print_results(tracks):
    for track in tracks:
        message = track["message"] if "message" in track else ""
        logging.info("Track found: {}-{}s, {}, confidence: {} ({}), novelty: {}, status: {}".format(
            track["start_s"],
            track["end_s"],
            track["label"],
            track["confidence"],
            track["clarity"],
            track["average_novelty"],
            message
        ))

def format_track_data(tracks):
    if not tracks:
        return {}

    for track in tracks:
        if 'frame_start' in track:
            del track['frame_start']
    return tracks

def replace_ext(filename, ext):
    return filename.parent / (filename.stem + ext)

def update_metadata(recording, api):
    with open(str(recording["filename"]), "rb") as f:
        reader = CPTVReader(f)
        metadata = {}
        metadata["recordingDateTime"] = reader.timestamp.isoformat()

        # TODO Add device name when it can be processed on api server
        # metadata["device_name"] = reader.device_name

        if reader.preview_secs:
            metadata["additionalMetadata"] = {"previewSecs": reader.preview_secs}

        count = 0
        for _ in reader:
            count += 1
        metadata["duration"] = round(count / FRAME_RATE)
    complete = not conf.do_classify
    api.update_metadata(recording, metadata, complete)
    logging.info("Metadata updated")

def upload_tracks(api, recording, algorithm, tracks):
    print ("uploading tracks...")
    print("algorithm is {}".format(algorithm))
    algorithm_id = api.get_algorithm_id(algorithm)

    print("algorithm Id is {}".format(algorithm_id))
    for track in tracks:
        track["id"] = api.add_track(recording, track, algorithm_id)
        if ('tag' in track):
            logging.info("Adding label {} to track {}".format(track['tag'], track["id"]))
            api.add_track_tag(recording, track)


def main():
    processing.init_logging()
    global conf
    conf = processing.Config.load()

    api = processing.API(conf.api_url)
    s3 = processing.S3(conf)

    while True:
        try:
            recording = api.next_job("thermalRaw", "getMetadata")
            if recording:
                with tempfile.TemporaryDirectory() as temp_dir:
                    filename = Path(temp_dir) / DOWNLOAD_FILENAME
                    recording["filename"] = filename
                    logging.info("downloading recording:\n%s", pformat(recording))
                    s3.download(recording["rawFileKey"], str(filename))

                    update_metadata(recording, api)

                    if conf.do_classify:
                        classify(recording, api, s3)
            else:
                time.sleep(SLEEP_SECS)
        except KeyboardInterrupt:
            break
        except:
            # TODO - failures should be reported back over the API
            logging.error(traceback.format_exc())
            time.sleep(SLEEP_SECS)

if __name__ == "__main__":
    main()
