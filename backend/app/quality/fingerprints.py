from hashlib import sha256
from pathlib import Path


def exact_fingerprint(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(256 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
