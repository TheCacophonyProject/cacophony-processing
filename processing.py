#!/usr/bin/python3

from PIL import Image
from cptv import CPTVReader
from cptv.image import process_frame_to_rgb
from pathlib import Path
import boto3
import json
import os
import requests
import shutil
import tempfile
import time
import traceback
import uuid
import yaml


UNPROCESSED_FILENAME = "unprocessed"
PROCESSED_FILENAME = "processed"
SLEEP_SECS = 10


with open("config.yaml") as stream:
    y = yaml.load(stream)
    BUCKET_NAME = y["s3"]["default_bucket"]
    ENDPOINT_URL = y["s3"]["endpoint"]
    ACCESS_KEY_ID = y["s3"]["access_key_id"]
    SECRET_ACCESS_KEY = y["s3"]["secret_access_key"]
    API_URL = y["api_url"]

s3 = boto3.resource(
    's3',
    endpoint_url = ENDPOINT_URL,
    aws_access_key_id = ACCESS_KEY_ID,
    aws_secret_access_key = SECRET_ACCESS_KEY)


def save_rgb_as_image(rgb, n, folder):
    im = Image.fromarray(rgb, "RGB")
    filename = '{:06}.png'.format(n)
    im.save(str(folder / filename))


def get_next_job(recording_type, state):
    print("Getting a new job")
    params = {'type': recording_type, 'state': state}
    r = requests.get(API_URL, params=params)
    if r.status_code == 204:
        print("No jobs ready")
        return None
    elif r.status_code == 400:
        print("Bad request")
        return None
    elif r.status_code != 200:
        print("Unexpected status code: " + str(r.status_code))
        return None

    # Job is ready, download the file to be processed.
    working_dir = Path(tempfile.mkdtemp())
    filename = str(working_dir / UNPROCESSED_FILENAME)

    recording = r.json()['recording']
    recording['directory'] = working_dir
    recording['filename'] = filename
    print(recording)
    download_object(recording['rawFileKey'], filename)

    return recording


def cptv_to_mp4(recording):
    working_dir = recording['directory']

    try:
        # Convert frames to images
        with open(recording['filename'], "rb") as f:
            reader = CPTVReader(f)
            for n, (frame, offset) in enumerate(reader):
                rgb = process_frame_to_rgb(frame)
                save_rgb_as_image(rgb, n, working_dir)

        # Convert to video (mp4)
        fps = (n - 1) * 1000000 / offset
        input_pattern = str(working_dir / "%06d.png")
        output_name = str(working_dir / PROCESSED_FILENAME) + ".mp4"
        command = "ffmpeg -v error -r {f} -i {i} -pix_fmt yuv420p {o}".format(
            f=fps, i=input_pattern, o=output_name)
        os.system(command)

        # Upload processed file
        newKey = upload_object(output_name)

        # Report processing done
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
        if r.status_code == 200:
            print("Finished processing")
        else:
            raise IOError("Failed to report processing completion (HTTP status {})".format(r.status_code))
    finally:
        shutil.rmtree(str(working_dir))


def download_object(key, file_name):
    s3.Bucket(BUCKET_NAME).download_file(key, file_name)


def upload_object(file_name):
    key = str(uuid.uuid1())
    s3.Bucket(BUCKET_NAME).upload_file(file_name, key)
    return key


def main():
    while True:
        try:
            recording = get_next_job("thermalRaw", "toMp4")
            if recording:
                cptv_to_mp4(recording)
            else:
                time.sleep(SLEEP_SECS)
        except KeyboardInterrupt:
            break
        except:
            traceback.print_exc()
            time.sleep(SLEEP_SECS)


if __name__ == '__main__':
    main()
