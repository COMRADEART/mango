#!/usr/bin/env python3
"""LOCAL ONLY: metadata-only authentication of the official sealed T26 store.

Runs ``t26_protocol.t27_private_oracle:authenticate_official_t26_store_for_t27``
against the actual sealed official T26 store. The authentication path is
metadata-only: store identity, commitment verification, manifest, seal,
evaluation ledger, and the official one-shot marker at the official V4 layout.
It never reads T26 inputs/gold or evaluation rows, never derives fingerprint
sets, never runs overlap comparison, and never executes candidate code.

The physical store stays on this machine and is never part of remote
reproduction; only the aggregate identity/hash evidence below may be recorded.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for value in (ROOT, ROOT / "src"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from t26_protocol.lifecycle import T26PrivateStore  # noqa: E402
from t26_protocol.t27_private_oracle import (  # noqa: E402
    authenticate_official_t26_store_for_t27,
    validate_t26_store_authentication_evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True,
                        help="physical official T26 private store root "
                             "(T26-STORE-01); stays on this machine")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true",
                        help="authenticate and print, but do not write")
    args = parser.parse_args()
    root = args.root.resolve()
    store_path = args.store.resolve()
    store = T26PrivateStore(store_path, root)
    report = authenticate_official_t26_store_for_t27(root, store)
    validate_t26_store_authentication_evidence(report, real=True)
    if report.get("status") != "PASS":
        raise ValueError("official T26 store metadata authentication failed")
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    out = root / "evaluations" / "t27" / "official_t26_store_preflight.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "t26_store_identity": report["t26_store_identity"],
        "t26_artifact_count": report["t26_artifact_count"],
        "t26_official_marker_path": report["t26_official_marker_path"],
        "t26_official_marker_sha256": report["t26_official_marker_sha256"],
        "t26_official_marker_genesis_matches_ledger":
            report["t26_official_marker_genesis_matches_ledger"],
        "t26_private_rows_read": report["t26_private_rows_read"],
        "artifact": out.name,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())