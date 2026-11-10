"""Owned scratch directories: never sweep shared /tmp or another live owner."""
import os
from contextlib import contextmanager
import tempfile


@contextmanager
def temporary_environment(directory):
    """Controller commands are serialized; restore Python's cached temp root too."""
    previous = os.environ.get('TMPDIR')
    cached = tempfile.tempdir
    os.environ['TMPDIR'] = str(directory)
    tempfile.tempdir = str(directory)
    try:
        yield
    finally:
        tempfile.tempdir = cached
        if previous is None:
            os.environ.pop('TMPDIR', None)
        else:
            os.environ['TMPDIR'] = previous
