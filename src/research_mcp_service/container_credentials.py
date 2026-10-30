"""One-shot, network-none credential copy into a private named volume.

Only this initializer runs as container root. Application containers remain
non-root and receive the credential volume read-only, never host directories.
"""
import os
from pathlib import Path
import tempfile


def main():
    target = Path('/credentials')
    # Validate both inputs before changing either destination.
    tokens = {}
    for name in ('mcp-token', 'gateway-token'):
        token = (Path('/inputs') / name).read_text().strip()
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise SystemExit('Invalid credential input')
        tokens[name] = token + '\n'
    for name, token in tokens.items():
        with tempfile.NamedTemporaryFile(mode='w', dir=target, delete=False) as f:
            f.write(token)
            os.fchmod(f.fileno(), 0o600)
            os.fchown(f.fileno(), 10001, 10001)
            temporary = f.name
        os.replace(temporary, target / name)
    os.chown(target, 10001, 10001)
    os.chmod(target, 0o700)


if __name__ == '__main__':
    main()
