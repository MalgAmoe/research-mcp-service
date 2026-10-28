"""Non-secret source fingerprint captured once when this process imports the module."""
import hashlib
from pathlib import Path


def snapshot():
    root = Path(__file__).resolve().parents[2]
    paths = list((root / 'src').rglob('*.py'))
    controller = root / 'scripts/browser_controller.py'
    if controller.is_file():
        paths.append(controller)
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode() + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return 'sha256:' + digest.hexdigest()


SOURCE_SNAPSHOT = snapshot()
