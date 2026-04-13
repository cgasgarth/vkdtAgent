from __future__ import annotations

import sys
from pathlib import Path


def _argument(name: str) -> str | None:
    if name not in sys.argv:
        return None
    index = sys.argv.index(name)
    if index + 1 >= len(sys.argv):
        return None
    return sys.argv[index + 1]


def main() -> int:
    filename = _argument("--filename")
    fmt = _argument("--format") or "o-jpg"
    if filename is None:
        raise SystemExit("--filename is required")
    suffix = ".exr" if fmt == "o-exr" else ".jpg"
    path = Path(filename).with_suffix(suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-image-bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
