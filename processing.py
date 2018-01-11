#!/usr/bin/python3

import json
import logging
import subprocess
import tempfile
import time
import traceback
import uuid
from itertools import groupby
from operator import itemgetter
from pprint import pformat
from pathlib import Path

import boto3
import requests
import yaml

DOWNLOAD_FILENAME = "recording.cptv"
SLEEP_SECS = 10

MIN_TRACK_CONFIDENCE = 0.85
DEFAULT_CONFIDENCE = 0.8
FALSE_POSITIVE = "false-positive"
UNIDENTIFIED = "unidentified"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)-15s %(levelname)s %(message)s",
)

with open("config.yaml") as stream:
    y = yaml.load(stream)
    BUCKET_NAME = y["s3"]["default_bucket"]
    ENDPOINT_URL = y["s3"]["endpoint"]
    ACCESS_KEY_ID = y["s3"]["access_key_id"]
    SECRET_ACCESS_KEY = y["s3"]["secret_access_key"]
    API_URL = y["api_url"]
    CLASSIFY_DIR = y["classify_command_dir"]
    CLASSIFY_CMD = y["classify_command"]

s3 = boto3.resource(
    's3',
    endpoint_url=ENDPOINT_URL,
    aws_access_key_id=ACCESS_KEY_ID,
    aws_secret_access_key=SECRET_ACCESS_KEY)


def get_next_job(recording_type, state):
    logging.info("Getting a new job")
    params = {'type': recording_type, 'state': state}
    r = requests.get(API_URL, params=params)
    if r.status_code == 204:
        logging.info("No jobs ready")
        return None
    elif r.status_code == 400:
        logging.error("Bad request")
        return None
    elif r.status_code != 200:
        logging.error("Unexpected status code: %s", r.status_code)
        return None

    return r.json()['recording']


def classify(recording):
    working_dir = recording['filename'].parent
    command = CLASSIFY_CMD.format(
        source_dir=str(working_dir),
        output_dir=str(working_dir),
        source=recording['filename'].name)

    logging.info('processing %s', recording['filename'])
    p = subprocess.run(
        command,
        cwd=CLASSIFY_DIR,
        shell=True,
        stdout=subprocess.PIPE,
    )
    p.check_returncode()

    classify_info = json.loads(p.stdout.decode('ascii'))
    logging.info("classify info:\n%s", pformat(classify_info))
    track_info = classify_info['tracks']

    # Auto tag the video
    tag, confidence = calculate_tag(track_info)
    logging.info("tag: %s (%.2f)", tag, confidence)
    tag_recording(recording['id'], tag, confidence)

    # Upload mp4
    video_filename = str(replace_ext(recording['filename'], '.mp4'))
    logging.info('uploading %s', video_filename)
    new_key = upload_object(video_filename)

    report_processing_done(recording, new_key)
    logging.info("Finished processing")


def calculate_tag(tracks):
    # No tracks found so tag as FALSE_POSITIVE
    if not tracks:
        return FALSE_POSITIVE, DEFAULT_CONFIDENCE

    # Find labels with confidence higher than MIN_TRACK_CONFIDENCE
    candidates = {}
    for label, label_tracks in groupby(tracks, itemgetter("label")):
        confidence = max(t['confidence'] for t in label_tracks)
        if confidence >= MIN_TRACK_CONFIDENCE:
            candidates[label] = confidence

    # If there's one label then use that.
    if len(candidates) == 1:
        return list(candidates.items())[0]

    # Remove FALSE_POSITIVE if it's there.
    candidates.pop(FALSE_POSITIVE, None)

    # If there's one candidate now, use that.
    if len(candidates) == 1:
        return list(candidates.items())[0]

    # Not sure.
    return UNIDENTIFIED, DEFAULT_CONFIDENCE


def tag_recording(recording_id, label, confidence):
    tag = {
        'automatic': True,
        'confidence': confidence,
    }

    # Convert "false positive" to API representation.
    if label == FALSE_POSITIVE:
        tag['event'] = 'false positive'
    else:
        tag['event'] = 'just wandering about'
        tag['animal'] = label

    r = requests.post(
        API_URL + "/tags",
        data={
            'recordingId': recording_id,
            'tag': json.dumps(tag),
        })
    r.raise_for_status()


def report_processing_done(recording, newKey):
    params = {
        'id': recording['id'],
        'jobKey': recording['jobKey'],
        'success': True,
        'newProcessedFileKey': newKey,
        'result': json.dumps({
            'fieldUpdates': {
                'fileMimeType': 'video/mp4',
            },
        }),
    }
    r = requests.put(API_URL, data=params)
    r.raise_for_status()


def download_object(key, file_name):
    s3.Bucket(BUCKET_NAME).download_file(key, file_name)


def upload_object(file_name):
    key = str(uuid.uuid1())
    s3.Bucket(BUCKET_NAME).upload_file(file_name, key)
    return key


def replace_ext(filename, ext):
    return filename.parent / (filename.stem + ext)


def main():
    while True:
        try:
            recording = get_next_job("thermalRaw", "toMp4")
            if recording:
                with tempfile.TemporaryDirectory() as temp_dir:
                    filename = Path(temp_dir) / DOWNLOAD_FILENAME
                    recording['filename'] = filename
                    logging.info("downloading recording:\n%s",
                                 pformat(recording))
                    download_object(recording['rawFileKey'], str(filename))

                    classify(recording)
            else:
                time.sleep(SLEEP_SECS)
        except KeyboardInterrupt:
            break
        except:
            # TODO - failures should be reported back over the API
            logging.error(traceback.format_exc())
            time.sleep(SLEEP_SECS)


if __name__ == '__main__':
    main()
