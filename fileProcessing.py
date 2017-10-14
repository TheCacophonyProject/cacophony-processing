import boto3
import requests
import random
import string
from parsingThermalData import decompile as cptv_decompile
import numpy as np
from PIL import Image
from os.path import join
import os
import uuid
import yaml
import cv2
import json

PROCESSING_FILE_NAME = "processingFile"
PROCESSED_FILE_NAME = "processedFile"
JOBS_FOLDER = "Jobs"

with open("config.yaml") as stream:
    try:
        y = yaml.load(stream)
        BUCKET_NAME = y["s3"]["default_bucket"]
        ENDPOINT_URL = y["s3"]["endpoint"]
        ACCESS_KEY_ID = y["s3"]["access_key_id"]
        SECRET_ACCESS_KEY = y["s3"]["secret_access_key"]
        API_URL = y["api_url"]
    except yaml.YAMLError as exc:
        print(exc)

s3 = boto3.resource(
    's3',
    endpoint_url = ENDPOINT_URL,
    aws_access_key_id = ACCESS_KEY_ID,
    aws_secret_access_key = SECRET_ACCESS_KEY)

def process_frame_to_rgb(frame):
    a = np.zeros((120, 160))
    a = cv2.normalize(frame, a, 0, 65535, cv2.NORM_MINMAX)
    maximum = np.amax(a)
    minimum = np.amin(a)
    m1 = 0.25*65535
    m2 = 0.50*65535
    m3 = 0.75*65535
    b1 = np.where(a <=m1, 1, 0)
    b2 = np.where(np.bitwise_and(m1 < a, a <=m2), 1, 0)
    b3 = np.where(np.bitwise_and(m2 < a, a <=m3), 1, 0)
    b4 = np.where(m3 < a, 1, 0)
    rgb = np.zeros((120, 160, 3), 'uint8')
    rgb[..., 0] = ((a-0.5*65535)*255*4/65535.0*b3 + b4*255)
    rgb[..., 1] = (b2*255 + b3*255 + b1*255*a*4/65535.0 + b4*255*((65535.0-a)*4/65535.0))
    rgb[..., 2] = (b1*255 + b2*255*((0.5*65535.0-a)*4)/65535.0 )
    return rgb

def save_rgb_as_image(rgb, n, folder):
    im = Image.fromarray(rgb, "RGB")
    imName = str(n).zfill(6) + '.png'
    im.save(join(folder, imName))

def download(key, file_name):
    s3.Bucket(BUCKET_NAME).download_file(key, file_name)

def upload(file_name):
    key = str(uuid.uuid1())
    s3.Bucket(BUCKET_NAME).upload_file(file_name, key)
    return key

def thermalRaw_toMp4():
    # Get new job.
    folder, recording = getNewJob("thermalRaw", "toMp4")
    if folder == None:
        print("No thermalRaw_toMp4 job to do.")
        return False

    thermal_data, fps = cptv_decompile(join(folder, PROCESSING_FILE_NAME))

    # Convert to images
    n = 0
    for frame in thermal_data:
        n += 1
        #print(frame)
        rgb = process_frame_to_rgb(frame)
        save_rgb_as_image(rgb, n, folder)

    # Convert to video (ogg)
    inputF = join(folder, "%06d.png")
    outputF = join(folder, PROCESSED_FILE_NAME + ".mp4")
    command = "ffmpeg -v error -r {f} -i {i} -pix_fmt yuv420p {o}".format(
        f = fps, i = inputF, o = outputF)
    os.system(command)

    # result
    result = {
        'fieldUpdates': {
            'fileMimeType': 'video/mp4',
        },
    }

    # Uplaod processed file
    newKey = upload(outputF)
    params = {
        'id': recording['id'],
        'jobKey': recording['jobKey'],
        'success': True,
        'newProcessedFileKey': newKey,
        'result': json.dumps(result),
    }
    r = requests.put(API_URL, data = params)
    print(r.status_code)
    print(r.json())


def getNewJob(recording_type, state):
    print("Getting a new job.")
    params = {'type': recording_type, 'state': state}
    r = requests.get(API_URL, params = params)
    if r.status_code == 204:
        print("No jobs ready")
        return None, None
    elif r.status_code == 400:
        print("Bad request")
        return None, None
    elif r.status_code != 200:
        print("Unknowen status code: " + str(r.status_code))
        return None, None

    # Process new Job
    print("New Job.")
    folder = join(JOBS_FOLDER, str(uuid.uuid1()))
    print("Job folder: " + folder)
    os.mkdir(folder)
    recording = r.json()['recording']
    print(recording);
    download(recording['rawFileKey'], join(folder, PROCESSING_FILE_NAME))
    return folder, recording

thermalRaw_toMp4()
