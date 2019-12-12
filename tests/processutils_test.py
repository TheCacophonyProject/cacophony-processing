from subprocess import CalledProcessError
from pytest import raises
from processing.processutils import (
    HandleCalledProcessError,
    CalledProcessErrorWithOutput,
)


def test_no_error():
    with HandleCalledProcessError():
        x = 1


def test_error():
    with raises(
        CalledProcessErrorWithOutput,
        match="Command 'cmd' returned non-zero exit status 99.$",
    ):
        with HandleCalledProcessError():
            raise CalledProcessError(99, "cmd")


def test_error_stdout():
    with raises(
        CalledProcessErrorWithOutput,
        match="Command 'cmd' returned non-zero exit status 99.\nout$",
    ):
        with HandleCalledProcessError():
            raise CalledProcessError(99, "cmd", output="out")


def test_error_stderr():
    with raises(
        CalledProcessErrorWithOutput,
        match="Command 'cmd' returned non-zero exit status 99.\nerr$",
    ):
        with HandleCalledProcessError():
            raise CalledProcessError(99, "cmd", stderr="err")


def test_error_stdout_stderr():
    with raises(
        CalledProcessErrorWithOutput,
        match="Command 'cmd' returned non-zero exit status 99.\nout\nerr$",
    ):
        with HandleCalledProcessError():
            raise CalledProcessError(99, "cmd", output="out", stderr="err")


def test_error_bytes():
    with raises(
        CalledProcessErrorWithOutput,
        match="Command 'cmd' returned non-zero exit status 99.\nout\nerr$",
    ):
        with HandleCalledProcessError():
            raise CalledProcessError(99, "cmd", output=b"out", stderr=b"err")


def test_other_error():
    with raises(ValueError, match="foo"):
        with HandleCalledProcessError():
            raise ValueError("foo")
