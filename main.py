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
import requests

from pebble import ProcessPool
from pathlib import Path
import processing
from processing import API, logs, audio_convert, audio_analysis, thermal, trail_analysis
from processing.processutils import HandleCalledProcessError
import subprocess
import argparse

SLEEP_SECS = 2

logger = logs.master_logger()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config-file", help="Path to config file to use")
    parser.add_argument(
        "--user", help="API server emai. This will override whats in the config file"
    )
    parser.add_argument(
        "--password",
        help="API server password. This will ocerride whats in the config file",
    )
    parser.add_argument(
        "--api",
        default=None,
        help='API server URL can be absolute URL or ("prod" for api.cacophony.org.nz or "test" for api-test.cacophony.org.nz or "ir" for api-ir.cacophony.org.nz) This will over ride whats in the config',
    )

    args = parser.parse_args()
    if args.api == "prod":
        args.api = "https://api.cacophony.org.nz"
    elif args.api == "test":
        args.api = "https://api-test.cacophony.org.nz"
    elif args.api == "ir":
        args.api = "https://api-ir.cacophony.org.nz"

    return args


def run_command(cmd, timeout=None):
    with HandleCalledProcessError():
        proc = subprocess.run(
            cmd,
            shell=True,
            encoding="ascii",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return proc.stdout


def is_docker_running(config):
    try:
        output = run_command(
            f"docker inspect --format '{{{{.State.Status}}}}' {config.container_name}",
            timeout=30,
        )
    except:
        logger.error("Could not check if docker is running ", exc_info=True)
        return None
    return output.strip() == "running"


def main():
    start_time = time.time()
    args = parse_args()
    conf = processing.Config.load(args.config_file)

    if args.api is not None:
        conf.api_credentials.api_url = args.api
    if args.user is not None:
        conf.api_credentials.user = args.user
    if args.password is not None:
        conf.api_credentials.password = args.password
    # requires_docker = (
    #     conf.thermal_analyse_workers > 0
    #     or conf.thermal_tracking_workers > 0
    #     or conf.ir_tracking_workers > 0
    #     or conf.ir_analyse_workers > 0
    # )
    # if requires_docker:
    # run_thermal_docker(conf)
    Processor.conf = conf
    Processor.log_q = logs.init_master()
    Processor.api = API(conf.api_url, conf.user, conf.password, logger)

    processors = Processors()
    processors.add(
        "audio",
        ["analyse", "reprocess"],
        audio_analysis.process,
        conf.audio_analysis_workers,
    )
    if conf.ir_tracking_workers > 0:
        processors.add(
            "irRaw",
            ["tracking", "retrack"],
            thermal.tracking_job,
            conf.ir_tracking_workers,
        )
    tracking_states = ["tracking"]

    # just for if api isn't updated to use retrack state
    if conf.do_retrack:
        tracking_states.append("retrack")
    if conf.ir_analyse_workers > 0:
        processors.add(
            "irRaw",
            ["analyse", "reprocess"],
            thermal.classify_job,
            conf.ir_analyse_workers,
        )
    if conf.thermal_tracking_workers > 0:
        processors.add(
            "thermalRaw",
            tracking_states,
            thermal.tracking_job,
            conf.thermal_tracking_workers,
        )
    if conf.thermal_analyse_workers > 0:
        processors.add(
            "thermalRaw",
            ["analyse", "reprocess"],
            thermal.classify_job,
            conf.thermal_analyse_workers,
        )

    if conf.trail_workers > 0:
        processors.add(
            "trailcam-image",
            ["analyse"],
            trail_analysis.analyse_image,
            conf.trail_workers,
        )
    logger.info("checking for recordings")
    while True:
        try:
            # if requires_docker and is_docker_running(conf) == False:
            #     logger.warning("Docker container not running, restarting")
            #     run_thermal_docker(conf)

            for processor in processors:
                processor.poll()
        except requests.exceptions.RequestException as e:
            logger.error(
                "Request Exception, make sure api user is a super user for api\n%s",
                traceback.format_exc(),
            )
        except:
            logger.error("Error polling", exc_info=True)

        procesing_ids = []
        [procesing_ids.extend(processor.in_progress.keys()) for processor in processors]

        # To avoid hitting the server repetitively wait longer if nothing to process
        if any(processor.has_work() for processor in processors):
            logger.info("Processing %s , short sleep", procesing_ids)
            time.sleep(SLEEP_SECS)
        elif all(processor.has_no_work() for processor in processors):
            if (
                conf.restart_after is not None
                and (time.time() - start_time) > conf.restart_after
            ):
                logger.info(
                    "Restarting as have been running for %s hours",
                    round((time.time() - start_time) / 3600, 1),
                )
                time.sleep(1)
                return
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

    def full(self):
        return len(self.in_progress) >= self.num_workers

    def has_no_work(self):
        return len(self.in_progress) == 0

    def has_work(self):
        return len(self.in_progress) > 0

    def poll(self):
        self.reap_completed()
        if self.full():
            return True
        working = False
        for state in self.processing_states:
            response = self.api.next_job(self.recording_type, state)
            if not response:
                continue
            recording = response["recording"]
            rawJWT = response["rawJWT"]
            if recording.get("id", 0) in self.in_progress:
                logger.info(
                    "Recording %s (%s: %s) is already scheduled, cancelling %s",
                    recording["id"],
                    recording["type"],
                    state,
                    self.in_progress[recording["id"]],
                )

                success = self.in_progress[recording["id"]][1].cancel()
                logger.info(
                    "Job cancelled with success? %s",
                    success,
                )
                if not success:
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
            err = None
            try:
                err = future.exception(timeout=0)
            except:
                pass
            # for debugging
            if err is not None and not future.done():
                logger.error("Have exception %s while future is not done", err)
            if future.done() or err is not None:
                if err is None:
                    try:
                        err = future.exception(timeout=0)
                    except:
                        pass
                if future.cancelled():
                    logger.info("Job %s was cancelled", recording_id)
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
