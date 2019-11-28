import logging
import multiprocessing
from logging.handlers import QueueListener, QueueHandler


def init_master():
    q = multiprocessing.Queue()

    handler = logging.StreamHandler()
    # handler.terminator = "\n\r"
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
    return logger
