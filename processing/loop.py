import logging
import time
import traceback
from pprint import pformat

from .api import API
from .s3 import S3

SLEEP_SECS = 10


def loop(conf, recording_type, processing_state, process_func):
    api = API(conf.api_url)
    s3 = S3(conf)

    while True:
        try:
            recording = api.next_job(recording_type, processing_state)
            if recording:
                logging.info("recording to process:\n%s", pformat(recording))
                process_func(recording, conf, api, s3)
            else:
                time.sleep(SLEEP_SECS)
        except KeyboardInterrupt:
            break
        except:
            # TODO - failures should be reported back over the API
            logging.error(traceback.format_exc())
            time.sleep(SLEEP_SECS)
