"""T7.27/T7.28/T7.29/T7.30 — Durable checkpoint/resume.

Atomic JSON snapshots (write temp, os.replace) after every completed
step. Resume skips completed steps and NEVER re-executes a completed
tool call or retrieval (langgraph durable-execution pattern A3). The
evidence graph (T7.26) is persisted in the same snapshot.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class RunCheckpointer:
    """File-backed checkpointer: one JSON per run, updated atomically."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def _path(self, run_id: str) -> Path:
        return self.dir / f"{run_id}.json"

    def save(self, state: dict, evidence_graph: dict | None = None) -> Path:
        payload = {"state": state,
                   "evidence_graph": evidence_graph or {"nodes": [],
                                                        "edges": []}}
        path = self._path(state["run_id"])
        _atomic_write_json(path, payload)
        return path

    def load(self, run_id: str) -> dict | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return payload

    def completed_step_ids(self, run_id: str) -> set[str]:
        payload = self.load(run_id)
        if not payload:
            return set()
        return set(payload["state"].get("completed_steps", []))

    def completed_tool_signatures(self, run_id: str) -> set[str]:
        """Signatures (action, input) of already-executed tool/retrieval
        steps — resume must not duplicate them."""
        payload = self.load(run_id)
        if not payload:
            return set()
        sigs = set()
        for ob in payload["state"].get("observations", []):
            if isinstance(ob, dict) and ob.get("action") in (
                    "MATH_TOOL", "RETRIEVE"):
                sigs.add(f"{ob.get('step_id')}:{ob.get('detail', {}).get('signature', '')}")
        return sigs


def signature_of_step(step: dict) -> str:
    import hashlib
    canon = json.dumps({"id": step.get("id"),
                        "action": step.get("action"),
                        "input": step.get("input")},
                       sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def evidence_graph_node(kind: str, ref: str, content: str = "",
                        step_id: str = "") -> dict:
    """T7.26 evidence/dependency graph node factory (in-memory JSON)."""
    return {"kind": kind,          # claim | evidence | tool | retrieval | answer
            "ref": ref, "content": content[:400], "step_id": step_id}


def evidence_graph_edge(src: str, dst: str, relation: str) -> dict:
    """Edge src -> dst with relation: supports | contradicts | produced |
    depends_on."""
    return {"src": src, "dst": dst, "relation": relation}


def add_node(graph: dict, node: dict) -> str:
    ref = node["ref"]
    if not any(n["ref"] == ref for n in graph["nodes"]):
        graph["nodes"].append(node)
    return ref


def add_edge(graph: dict, edge: dict) -> None:
    if edge not in graph["edges"]:
        graph["edges"].append(edge)