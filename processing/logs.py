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

import logging
import multiprocessing
from logging.handlers import QueueListener, QueueHandler


def init_master():
    q = multiprocessing.Queue()

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s: %(message)s"))
    handler.setLevel(logging.INFO)

    master_logger().addHandler(QueueHandler(q))

    ql = QueueListener(q, handler, respect_handler_level=True)
    ql.start()

    logging.getLogger().handlers = []
    logging.getLogger("botocore").setLevel(logging.ERROR)

    return q


def init_worker(q):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(QueueHandler(q))
    return logger


def master_logger():
    logger = logging.getLogger("master")
    logger.setLevel(logging.DEBUG)
    return logger


def worker_logger(name, recording_id):
    logger = logging.getLogger("worker").getChild(f"{name}[{recording_id}]")
    logger.setLevel(logging.DEBUG)
    logger.info("Starting")
    return logger
