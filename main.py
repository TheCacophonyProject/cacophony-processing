#!/usr/bin/python3

"""
cacophony-processing - this is a server side component that runs alongside
the Cacophony Project API, performing post-upload processing tasks.
Copyright (C) 2019, The Cacophony Project

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

import contextlib
import time
import traceback

from pebble import ProcessPool

import processing
from processing import API, logs, audio_convert, audio_analysis, thermal

SLEEP_SECS = 2

logger = logs.master_logger()


def main():
    conf = processing.Config.load()

    Processor.conf = conf
    Processor.api = API(conf.file_api_url, conf.api_url)
    Processor.log_q = logs.init_master()

    processors = Processors()
    processors.add(
        "audio", ["toMp3"], audio_convert.process, conf.audio_convert_workers
    )

    processors.add(
        "audio",
        ["analyse", "reprocess"],
        audio_analysis.process,
        conf.audio_analysis_workers,
    )
    if conf.do_classify:
        processors.add(
            "thermalRaw",
            ["analyse", "reprocess"],
            thermal.classify_job,
            conf.thermal_workers,
        )

    logger.info("checking for recordings")
    while True:
        working = False
        try:
            for processor in processors:
                processor_busy = processor.poll()
                working = working or processor_busy
        except:
            logger.error(traceback.format_exc())

        # To avoid hitting the server repetitively wait longer if nothing to process
        if working:
            logger.info("processing short sleep")
            time.sleep(SLEEP_SECS)
        else:
            logger.info("Nothing to process - extending wait time")
            time.sleep(conf.no_recordings_wait_secs)


class Processors(list):
    def add(self, recording_type, processing_states, process_func, num_workers):
        if num_workers < 1:
            return
        p = Processor(recording_type, processing_states, process_func, num_workers)
        self.append(p)


class Processor:

    conf = None
    api = None
    log_q = None

    def __init__(self, recording_type, processing_states, process_func, num_workers):
        self.recording_type = recording_type
        self.processing_states = processing_states
        self.process_func = process_func
        self.num_workers = num_workers
        self.pool = ProcessPool(
            num_workers, initializer=logs.init_worker, initargs=(self.log_q,)
        )
        self.in_progress = {}

    def poll(self):
        self.reap_completed()
        if len(self.in_progress) >= self.num_workers:
            return True

        working = False
        for state in self.processing_states:
            response = self.api.next_job(self.recording_type, state)

            if not response:
                continue
            recording = response["recording"]
            rawJWT = response["rawJWT"]
            if recording.get("id", 0) in self.in_progress:
                logger.debug(
                    "Recording %s (%s: %s) is already scheduled",
                    recording["id"],
                    recording["type"],
                    state,
                )
                continue
            logger.debug(
                "scheduling %s (%s: %s)",
                recording["id"],
                recording["type"],
                state,
            )
            future = self.pool.schedule(
                self.process_func, (recording, rawJWT, self.conf)
            )
            self.in_progress[recording["id"]] = (recording["jobKey"], future)
            working = True
        return working

    def reap_completed(self):
        for recording_id, job in list(self.in_progress.items()):
            future = job[1]
            if future.done():
                err = future.exception()
                if err:
                    msg = f"{self.recording_type}.{self.processing_states} processing of {recording_id} failed: {err}"
                    tb = getattr(err, "traceback", None)
                    if tb:
                        msg += f":\n{tb}"
                    logger.error(msg)
                    try:
                        self.api.report_failed(recording_id, job[0])
                    except:
                        logger.error(
                            "Could not set %s to failed state",
                            recording_id,
                            exc_info=True,
                        )
                del self.in_progress[recording_id]


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        main()
