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

import threading
import contextlib
import time
import traceback
import requests
import functools
from pebble import ProcessPool
import processing
from processing import API, logs, audio_analysis, thermal
from processing.processutils import HandleCalledProcessError
import subprocess
import argparse

SLEEP_SECS = 0.2
POLL_ERROR_SLEEP_SECS = 5
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

    parser.add_argument(
        "--sleep",
        default=None,
        type=float,
        help='Seconds to sleep in between API requests"',
    )

    args = parser.parse_args()
    if args.api == "prod":
        args.api = "https://api.cacophony.org.nz"
    elif args.api == "test":
        args.api = "https://api-test.cacophony.org.nz"
    elif args.api == "ir":
        args.api = "https://api-ir.cacophony.org.nz"

    if args.sleep is not None:
        global SLEEP_SECS
        SLEEP_SECS = args.sleep
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
    args = parse_args()
    conf = processing.Config.load(args.config_file)

    if args.api is not None:
        conf.api_credentials.api_url = args.api
    if args.user is not None:
        conf.api_credentials.user = args.user
    if args.password is not None:
        conf.api_credentials.password = args.password

    # Processor.conf = conf
    # Processor.log_q = logs.init_master()
    api = API(conf.api_url, conf.user, conf.password, logger)
    run_with_api(api, conf)


def run_with_api(api, conf, exit_on_finished=False):
    start_time = time.time()

    logger.info("Sleep seconds set to %s", SLEEP_SECS)
    Processor.api = api
    processors = Processors()
    workers = Workers(
        api,
        logs.init_master(),
        conf,
        conf.audio_analysis_workers + conf.thermal_track_analyse_workers,
    )
    # to be handled enfore that we either run as reprocessing instance or normal
    if conf.reprocess:
        logger.info("Running reprocess workers")
        if conf.reprocess_thermal_workers > 0:
            processors.add(
                "thermalRaw",
                ["reprocess"],
                [thermal.classify_job],
                conf.reprocess_thermal_workers,
                conf.no_job_sleep_seconds,
                workers,
                conf.thermal_compose_file,
                workers.total_workers,
                "thermal-reprocess",
            )
        if conf.reprocess_audio_workers > 0:
            processors.add(
                "audio",
                ["reprocess"],
                [audio_analysis.track_reprocess],
                conf.reprocess_audio_workers,
                conf.no_job_sleep_seconds,
                workers,
                conf.audio_compose_file,
                workers.total_workers,
                "audio-reprocess",
            )
    else:
        if conf.audio_analysis_workers > 0:
            processors.add(
                "audio",
                ["analyse", "FINISHED"],
                [audio_analysis.process, audio_analysis.track_analyse],
                conf.audio_analysis_workers,
                conf.no_job_sleep_seconds,
                workers,
                conf.audio_compose_file,
                workers.total_workers,
                "audio-analyse",
            )

        if conf.thermal_track_analyse_workers > 0:
            processors.add(
                "thermalRaw",
                ["trackAndAnalyse", "analyse"],
                [thermal.classify_job, thermal.classify_job],
                conf.thermal_track_analyse_workers,
                conf.no_job_sleep_seconds,
                workers,
                conf.thermal_compose_file,
                workers.total_workers,
                "thermal-analyse",
            )
    logger.info("Waiting for docker startup")
    for processor in processors:
        processor.docker_pool.wait_for_ready()
    logger.info("checking for recordings")
    while True:
        success = False
        try:
            for processor in processors:
                processor.poll()
                success = True
        except requests.exceptions.RequestException as e:
            logger.error(
                "Request Exception, make sure api user is a super user for api\n%s",
                traceback.format_exc(),
            )
            success = False
        except:
            logger.error("Error polling", exc_info=True)
            success = False

        if not success:
            logger.info(
                "Waiting %s secs before polling again because of poll error",
                POLL_ERROR_SLEEP_SECS,
            )
            time.sleep(POLL_ERROR_SLEEP_SECS)
            continue

        done_sleep = False
        if workers.in_use == 0:
            if exit_on_finished:
                logger.info("Finished jobs")
                workers.pool.stop()
                workers.pool.join()
                for process in processors:
                    process.stop()
                break
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

            if all(not processor.should_poll() for processor in processors):
                logger.info("Nothing to process - extending wait time")
                time.sleep(conf.no_recordings_wait_secs)
                done_sleep = True
        if not done_sleep:
            if SLEEP_SECS > 0:
                time.sleep(SLEEP_SECS)


class Processors(list):
    def add(
        self,
        recording_type,
        processing_states,
        process_func,
        num_workers,
        no_job_sleep_seconds,
        workers,
        docker_compose,
        total_workers,
        unique_id,
    ):
        if num_workers < 1:
            return
        p = Processor(
            recording_type,
            processing_states,
            process_func,
            num_workers,
            no_job_sleep_seconds,
            workers,
            docker_compose,
            total_workers,
            unique_id,
        )
        logger.info(
            "Adding worker %s - %s states %s num workers %s ",
            p.id,
            recording_type,
            processing_states,
            num_workers,
        )
        self.append(p)


2
PROCESS_ID = 1


class DockerInstance:
    def __init__(self, name, compose_file, num_instances):
        self.name = name
        self.compose_file = compose_file
        self.num_instances = num_instances
        self.cmd = f"docker compose -f {self.compose_file} up --scale {self.name}={self.num_instances} -d"
        self.instances = []
        self.restart()
        self.in_use = []

    def wait_for_ready(self):
        for instance in self.instances:
            while True:
                try:
                    ready_output = run_command(f"docker exec {instance} bash ready.sh")
                    break
                except:
                    logger.info(
                        "%s instance %s is not ready waiting 10 seconds",
                        self.compose_file,
                        instance,
                    )
                    time.sleep(10)

    def get_running_instances(self):
        instances = run_command(f"docker container ls -q --filter name={self.name}*")
        instances = instances.rstrip()
        if len(instances) == 0:
            return []
        return instances.split("\n")

    def stop(self):
        logger.info("Stopping running docker instances of %s", self.name)
        instances = self.get_running_instances()
        if len(instances) > 0:
            try:
                run_command(
                    f"docker stop $(docker container ls -q --filter name={self.name}*)"
                )
            except:
                logger.error("Error stopping instances ", exc_info=True)
        self.instances = []
        self.in_use = []

    def start(self):
        logger.info("Starting docker %s %s", self.num_instances, self.cmd)
        run_command(self.cmd)
        # shouldnt ever get multiple of same instances but just for safety
        self.instances = set(self.get_running_instances())

    def restart(self):
        self.stop()
        self.start()

    # probably can just cycle through the instances sometimes some will be unlucky
    def get_instance(self):
        instance = self.instances.pop()
        self.in_use.append(instance)
        return instance

    def finished(self, instance):
        if instance in self.in_use:
            self.in_use.remove(instance)
        else:
            logger.warning("In use was missing %s", instance)
        self.instances.add(instance)
        logger.info("Docker instance %s finished", instance)


class Workers:
    def __init__(self, api, log_q, config, total_workers):
        self.total_workers = total_workers
        self.config = config
        self.pool = ProcessPool(
            self.total_workers, initializer=logs.init_worker, initargs=(log_q,)
        )
        self.in_use = 0
        self.in_use_by_id = {}
        self.in_progress = {}
        self.api = api
        self.lock = threading.Lock()
        self.workers_by_id = {}
        self.spare_workers = set()

    def add_spare_worker(self, processor_id):
        self.spare_workers.add(processor_id)

    def remove_spare_worker(self, processor_id):
        if processor_id in self.spare_workers:
            self.spare_workers.remove(processor_id)

    def register_processor(self, processor_id, num_workers):
        self.workers_by_id[processor_id] = num_workers

    def full(self, processor_id):
        num_jobs = self.jobs_in_progress(processor_id)
        if num_jobs < self.workers_by_id[processor_id]:
            return False, processor_id

        for spare_id in self.spare_workers:
            has_spare = self.jobs_in_progress(spare_id) < self.workers_by_id[spare_id]
            if has_spare:
                return False, spare_id
        return True, 0

    def schedule(
        self, func, processor_id, recording, rawJWT, instance, instance_callback
    ):
        if self.in_use < self.total_workers:
            future = self.pool.schedule(
                func, (self.api, recording, rawJWT, self.config, instance)
            )
            self.in_progress[recording["id"]] = (
                recording["jobKey"],
                processor_id,
                instance,
                instance_callback,
                future,
            )
            callback_with_args = functools.partial(
                on_finish, worker_pool=self, recording_id=recording["id"]
            )

            with self.lock:
                if processor_id in self.in_use_by_id:
                    self.in_use_by_id[processor_id] += 1
                else:
                    self.in_use_by_id[processor_id] = 1
                self.in_use += 1
            future.add_done_callback(callback_with_args)
            return future
        return None

    def finished(self, recording_id, processor_id):
        logger.info("Finished %s", recording_id)
        with self.lock:
            if recording_id in self.in_progress:
                # be nice to return the borrow workers first
                del self.in_progress[recording_id]
                self.in_use_by_id[processor_id] -= 1
                self.in_use -= 1

    def cancel_job(self, recording_id):
        job = self.in_progress.get(recording_id)
        if job is None:
            return
        _, processor_id, instance, instance_callback, future = job
        success = future.done() or future.cancel()
        logger.info("Job cancelled with success? %s", success)
        if instance_callback:
            instance_callback(instance)
        if success:
            self.finished(recording_id, processor_id)
        return success

    def jobs_in_progress(self, processor_id):
        return self.in_use_by_id.get(processor_id, 0)


def on_finish(future, worker_pool=None, recording_id=None, recording_type=None):
    err = None
    try:
        err = future.exception(timeout=0)
    except:
        pass
    # for debugging
    if err is not None and not future.done():
        logger.error("Have exception %s while future is not done", err)
    if future.done() or err is not None:
        job_key, processor_id, docker_instance, instance_callback, future = (
            worker_pool.in_progress[recording_id]
        )

        if future.cancelled():
            logger.info("Job %s was cancelled", recording_id)
            return

        if instance_callback:
            instance_callback(docker_instance)
        if err:
            msg = f"processing of {recording_id} failed: {err}"
            tb = getattr(err, "traceback", None)
            if tb:
                msg += f":\n{tb}"
            logger.error(msg)
            try:
                worker_pool.api.report_failed(recording_id, job_key)
            except:
                logger.error(
                    "Could not set %s to failed state",
                    recording_id,
                    exc_info=True,
                )
    if err is None:
        result = future.result()
        if result.get("success", True):
            worker_pool.api.report_done(
                {"id": recording_id, "jobKey": job_key}, None, None, result
            )
        else:
            worker_pool.api.report_failed(recording_id, job_key)

    worker_pool.finished(recording_id, processor_id)


class Processor:

    def __init__(
        self,
        recording_type,
        processing_states,
        process_funcs,
        num_workers,
        no_job_sleep_seconds,
        worker_pool,
        docker_compose,
        total_workers,
        unique_id,
    ):
        self.id = unique_id
        self.recording_type = recording_type
        self.processing_states = processing_states
        self.process_funcs = process_funcs
        self.num_workers = num_workers
        self.no_job_sleep_seconds = no_job_sleep_seconds
        self.pool = worker_pool

        self.last_poll = None
        self.last_poll_success = None
        self.docker_pool = DockerInstance(recording_type, docker_compose, total_workers)

        self.audio_workers = 4
        self.thermal_workers = 4
        self.pool.register_processor(self.id, num_workers)
        self.borrowed = []

    def stop(self):
        self.docker_pool.stop()

    def full(self):
        return self.pool.full(self.id)
        # self.in_progress(self.id) >= self.num_workers

    def should_poll(self):
        return (
            self.last_poll_success
            or self.last_poll is None
            or (time.time() - self.last_poll) > self.no_job_sleep_seconds
        )

    def force_poll(self):
        self.last_poll_success = True

    def poll(self):
        if not self.should_poll():
            # logger.info("Not polling %s no job %s",self.recording_type,self.no_job_sleep_seconds)
            return False

        is_full, process_id = self.full()
        if is_full:
            return False
        working = False
        self.last_poll_success = False

        self.last_poll = time.time()
        response = self.api.next_job(self.recording_type, self.processing_states)
        self.last_poll_success = self.last_poll_success or response is not None
        if not response:
            if self.id not in self.pool.spare_workers:
                self.pool.add_spare_worker(self.id)
                logger.info("%s has spare workers", self.id)
            return False
        self.pool.remove_spare_worker(self.id)

        recording = response["recording"]
        rawJWT = response["rawJWT"]
        state = recording["processingState"]
        if recording.get("id", 0) in self.pool.in_progress:
            logger.info(
                "Recording %s (%s: %s) is already scheduled, cancelling %s",
                recording["id"],
                recording["type"],
                state,
                self.pool.in_progress[recording["id"]],
            )

            success = self.pool.cancel_job(recording["id"])

            logger.info("Job cancelled with success? %s", success)
            if not success:
                return False
        logger.info(
            "scheduling rec:#%s (%s: %s) under process %s",
            recording["id"],
            recording["type"],
            state,
            process_id,
        )
        instance = self.docker_pool.get_instance()
        logger.info("Scheduling on docker instance %s", instance)
        process_func = None
        for process_state, function in zip(self.processing_states, self.process_funcs):
            if process_state == state:
                process_func = function
                break
        self.pool.schedule(
            process_func,
            process_id,
            recording,
            rawJWT,
            instance,
            self.docker_pool.finished,
        )
        working = True
        if process_id != self.id:
            logger.info(
                "Processor %s is borrowing a worker from %s", self.id, process_id
            )

        return working


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        main()
