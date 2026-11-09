"""Shared, bounded acquisition admission setting (control and worker must match)."""
import os


def acquisition_concurrency():
    value = int(os.environ.get('ACQUISITION_CONCURRENCY', '2'))
    if not 1 <= value <= 4:
        raise ValueError('ACQUISITION_CONCURRENCY must be between 1 and 4')
    return value
