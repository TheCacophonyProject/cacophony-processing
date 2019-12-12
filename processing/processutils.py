from subprocess import CalledProcessError


class HandleCalledProcessError:
    def __enter__(self):
        return None

    def __exit__(self, err_type, err, _):
        if err_type is not CalledProcessError:
            return False

        new_err = CalledProcessErrorWithOutput(
            err.returncode, err.cmd, output=err.output, stderr=err.stderr
        )
        new_err.__suppress_context__ = True
        raise new_err


class CalledProcessErrorWithOutput(CalledProcessError):
    def __str__(self):
        msg = super().__str__()

        stdout = decode(self.stdout)
        if stdout:
            msg += "\n" + stdout

        stderr = decode(self.stderr)
        if stderr:
            msg += "\n" + stderr

        return msg


def decode(v):
    if not v:
        return None
    elif isinstance(v, bytes):
        return v.decode("utf-8")
    return v
