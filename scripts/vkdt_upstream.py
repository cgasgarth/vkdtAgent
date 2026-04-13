from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_FILE = REPO_ROOT / "vkdt-upstream.json"


def _read_metadata() -> dict[str, str]:
    return json.loads(UPSTREAM_FILE.read_text())


def _latest_commit(owner: str, repo: str, branch: str) -> str:
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/commits/{branch}", "--jq", ".sha"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    command = argv[0] if argv else "status"
    if command != "status":
        raise SystemExit(f"unsupported command: {command}")
    metadata = _read_metadata()
    latest = _latest_commit(metadata["owner"], metadata["repo"], metadata["branch"])
    tracked = metadata["trackedCommit"]
    payload = {
        "repo": f"{metadata['owner']}/{metadata['repo']}",
        "branch": metadata["branch"],
        "trackedCommit": tracked,
        "latestCommit": latest,
        "upToDate": tracked == latest,
    }
    print(json.dumps(payload, indent=2))
    return 0 if tracked == latest else 1


if __name__ == "__main__":
    raise SystemExit(main())
