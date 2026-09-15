"""T21R3 entry-gate helper: restore committed blob content in the working
tree for text directories.

A fresh `git pull` with core.autocrlf=true rewrote LF-committed evaluation
and runtime files to CRLF on disk, so raw-byte SHA256 freeze checks failed
even though the freeze artifacts themselves are intact (the recorded hashes
match the committed LF blobs exactly). Committing `* text=auto eol=lf` in
.gitattributes fixes future checkouts; this script restores the current
working tree to the committed blob bytes for the text directories.

Idempotent; writes only files whose working-tree bytes differ from the
HEAD blob; never touches LFS-smudged binaries (not present in these dirs).
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_DIRS = ["src", "tests", "scripts", "evaluations", "rag"]


def main() -> None:
    files = subprocess.run(
        ["git", "ls-files", *TEXT_DIRS],
        capture_output=True, text=True, check=True,
        cwd=str(ROOT)).stdout.splitlines()
    fixed = 0
    for f in files:
        p = ROOT / f
        if not p.exists():
            continue
        blob = subprocess.run(
            ["git", "cat-file", "-p", "HEAD:" + f],
            capture_output=True, check=True, cwd=str(ROOT)).stdout
        disk = p.read_bytes()
        if disk != blob:
            # Skip dirty content changes (LF-normalized inequality beyond
            # CRLF); only rewrite pure line-ending drift.
            if disk.replace(b"\r\n", b"\n") != blob.replace(b"\r\n", b"\n"):
                continue
            p.write_bytes(blob)
            fixed += 1
    print(f"restored-to-blob: {fixed} of {len(files)} files")


if __name__ == "__main__":
    main()