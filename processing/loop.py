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

import logging
import time
import traceback
from pprint import pformat

from pebble import ProcessPool

from .api import API
from .s3 import S3

SLEEP_SECS = 5


def loop(conf, recording_type, processing_state, process_func, num_workers):
    api = API(conf.api_url)
    s3 = S3(conf)

    with ProcessPool(num_workers) as pool:
        in_progress = {}
        while True:
            try:
                recording = api.next_job(recording_type, processing_state)
                if recording:
                    logging.info(
                        "recording to process:\n%s", pformat(recording)
                    )  # TODO - make this concise
                    future = pool.schedule(process_func, (recording, conf, api, s3))
                    in_progress[recording["id"]] = future
                else:
                    time.sleep(SLEEP_SECS)

                in_progress = reap_completed(in_progress, num_workers)

            except KeyboardInterrupt:
                break
            except:
                logging.error(traceback.format_exc())
                time.sleep(SLEEP_SECS)


def reap_completed(in_progress, num_workers):
    while True:
        for recording_id, future in list(in_progress.items()):
            if future.done():
                del in_progress[recording_id]
                err = future.exception()
                if err:
                    logging.error(
                        f"processing of {recording_id} failed: {err}:\n{err.traceback}"
                    )

        if len(in_progress) < num_workers:
            return in_progress

        time.sleep(0.5)
