"""T15R.3–T15R.11 — transactional repair-state tracking.

ORIGINAL_STATE / CURRENT_CANDIDATE / BEST_VERIFIED_STATE.

A candidate becomes BEST only with evidence (tests actually ran) and
only when deterministic ranking says it is strictly better. Newest is
never a ranking key. Unsafe / protected / weakening / secret /
destructive / network / paid-compute / benchmark-tamper states cannot
be retained.

Repair rounds start from BEST_VERIFIED_STATE, not ORIGINAL_STATE,
unless BEST is unsafe or fundamentally invalid.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path

from sciencemath.code import safety as S

SKIP_PARTS = frozenset({
    "__pycache__", ".pytest_cache", ".pytest_tmp", ".git",
    ".mango_repair",
})

DEFAULT_REPAIR_ROUNDS = 3
HARD_CAP_REPAIR_ROUNDS = 5

OK = "OK"
UNSAFE = "UNSAFE"
VIOLATION = "VIOLATION"


def _skipped(rel: str, skip_prefixes: list[str] | tuple = ()) -> bool:
    rel = rel.replace("\\", "/")
    for sp in skip_prefixes or ():
        sp = str(sp).replace("\\", "/").rstrip("/")
        if not sp:
            continue
        if rel == sp or rel.startswith(sp + "/"):
            return True
    return False


def snapshot_repo(root: str | Path, skip_prefixes: list[str] | tuple = ()
                  ) -> dict[str, bytes]:
    """Byte snapshot of the workspace (no caches). Independent copy.

    Cache-dir skipping is relative to `root` so a pytest tmp directory
    named `.pytest_tmp` can itself be a snapshot root.
    """
    base = Path(root).resolve()
    out: dict[str, bytes] = {}
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(base).parts
        except ValueError:
            continue
        if any(part in SKIP_PARTS for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        if _skipped(rel, skip_prefixes):
            continue
        try:
            out[rel] = bytes(p.read_bytes())
        except OSError:
            continue
    return out


def restore_repo(root: str | Path, snap: dict[str, bytes],
                 skip_prefixes: list[str] | tuple = ()) -> None:
    """Restore workspace to an exact snapshot. Deletes files not in snap.

    Never deletes or overwrites skip_prefixes (checkpoint/audit dirs).
    """
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    current = snapshot_repo(base, skip_prefixes=skip_prefixes)
    for rel in list(current):
        if rel not in snap and not _skipped(rel, skip_prefixes):
            try:
                (base / rel).unlink()
            except OSError:
                pass
    for rel, blob in snap.items():
        if _skipped(rel, skip_prefixes):
            continue
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)


def files_changed(original: dict[str, bytes], current: dict[str, bytes]
                  ) -> list[str]:
    keys = set(original) | set(current)
    return sorted(k for k in keys if original.get(k) != current.get(k))


def auto_acceptance(original: dict[str, bytes], current: dict[str, bytes],
                    involved_files: list[str] | None = None) -> int:
    """Evidence-backed progress not captured by raw failure counts.

    Replacing a NotImplementedError stub, or staging every coupled source
    file in a multi-file task, is verified progress even when a single
    remaining assertion still fails (T15R.4 #5, T15R.10).
    """
    n = 0
    for rel, ob in (original or {}).items():
        if not str(rel).endswith(".py"):
            continue
        ot = ob.decode("utf-8", "replace")
        ct = (current or {}).get(rel, b"").decode("utf-8", "replace")
        if "NotImplementedError" in ot and "NotImplementedError" not in ct:
            n += 1
    involved = [
        f.replace("\\", "/") for f in (involved_files or [])
        if str(f).endswith(".py")
        and "test" not in str(f).replace("\\", "/").lower()
        and not Path(str(f)).name.startswith("test_")
        and Path(str(f)).name != "__init__.py"
    ]
    changed = files_changed(original or {}, current or {})
    if len(set(involved)) >= 2 and set(involved) <= set(changed):
        n += 1
    return n


def diff_hash(original: dict[str, bytes], current: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in files_changed(original, current):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(original.get(rel, b""))
        h.update(b"\0")
        h.update(current.get(rel, b""))
        h.update(b"\0")
    return h.hexdigest()


def unified_diff(original: dict[str, bytes], current: dict[str, bytes],
                 *, limit: int = 80_000) -> str:
    import difflib
    chunks: list[str] = []
    for rel in files_changed(original, current):
        a = original.get(rel, b"").decode("utf-8", "replace").splitlines()
        b = current.get(rel, b"").decode("utf-8", "replace").splitlines()
        u = list(difflib.unified_diff(a, b, fromfile=f"a/{rel}",
                                      tofile=f"b/{rel}", lineterm=""))
        chunks.append("\n".join(u))
    text = "\n".join(chunks)
    red, _n = S.redact_secrets(text)
    return red[:limit]


def failure_ids_from_output(output: str) -> list[str]:
    """Parse pytest FAILED/ERROR node ids. Empty if none found."""
    ids: list[str] = []
    for line in (output or "").splitlines():
        s = line.strip()
        if s.startswith("FAILED ") or s.startswith("ERROR "):
            token = s.split()[1] if len(s.split()) > 1 else s
            token = token.split(" ")[0].rstrip(":")
            if token and token not in ids:
                ids.append(token)
    return ids


def failure_delta(before_ids: list[str] | tuple, after_ids: list[str] | tuple
                  ) -> dict:
    """Structured failure delta (T15R.6)."""
    before = [x for x in (before_ids or []) if x]
    after = [x for x in (after_ids or []) if x]
    bset, aset = set(before), set(after)
    resolved = sorted(bset - aset)
    introduced = sorted(aset - bset)
    remaining = list(after)
    return {
        "resolved": resolved,
        "introduced": introduced,
        "remaining": remaining,
        "net_change": len(after) - len(before),
        "resolved_count": len(resolved),
        "regression_count": len(introduced),
    }


@dataclass
class RepairState:
    state_id: str
    parent_state_id: str | None
    files_changed: list[str]
    diff_hash: str
    test_result: dict
    targeted_tests_passed: bool
    full_tests_passed_if_run: bool | None
    failure_count: int
    failure_ids: list[str]
    lint_status: str
    safety_status: str
    protected_component_status: str
    tests_ran: bool = False
    test_weakening: bool = False
    secret_leakage: bool = False
    destructive: bool = False
    benchmark_tampering: bool = False
    unauthorized_network: bool = False
    unauthorized_paid_compute: bool = False
    unrelated_edit_count: int = 0
    acceptance_conditions_satisfied: int = 0
    diff_size: int = 0
    compile_ok: bool = True
    blobs: dict[str, bytes] = field(default_factory=dict, repr=False)
    patch_text: str = ""

    @property
    def is_original(self) -> bool:
        return self.parent_state_id is None

    def retention_ok(self) -> bool:
        """T15R.9 — partial progress may only be retained when safe.

        ORIGINAL_STATE is always a valid retained baseline.
        """
        if self.is_original:
            return True
        return (
            self.tests_ran
            and self.safety_status == OK
            and self.protected_component_status == OK
            and not self.test_weakening
            and not self.secret_leakage
            and not self.destructive
            and not self.benchmark_tampering
            and not self.unauthorized_network
            and not self.unauthorized_paid_compute
            and self.compile_ok
            and self.lint_status in (OK, "NOT_RUN")
        )

    def rank_tuple(self) -> tuple:
        """Higher is better. Recency is NOT a key (T15R.4)."""
        return (
            1 if self.safety_status == OK else 0,
            1 if self.protected_component_status == OK else 0,
            1 if self.retention_ok() or self.is_original else 0,
            1 if self.targeted_tests_passed else 0,
            -int(self.failure_count),
            int(self.acceptance_conditions_satisfied),
            -int(self.unrelated_edit_count),
            -int(self.diff_size),
            1 if self.is_original else 0,  # ties prefer original
            self.state_id,  # deterministic last resort
        )

    def __post_init__(self) -> None:
        self.blobs = {k: bytes(v) for k, v in (self.blobs or {}).items()}
        self.files_changed = list(self.files_changed or [])
        self.failure_ids = list(self.failure_ids or [])

    def public_dict(self) -> dict:
        d = asdict(self)
        d.pop("blobs", None)
        d["patch_text"] = (self.patch_text or "")[:4000]
        d["is_original"] = self.is_original
        d["retention_ok"] = self.retention_ok()
        return d


def cmp_states(a: RepairState, b: RepairState) -> int:
    """Negative if a is better, 0 if equal rank, positive if b is better."""
    ta, tb = a.rank_tuple(), b.rank_tuple()
    if ta > tb:
        return -1
    if ta < tb:
        return 1
    return 0


def select_best(states: list[RepairState]) -> RepairState:
    if not states:
        raise ValueError("select_best requires at least one state")
    best = states[0]
    for s in states[1:]:
        if cmp_states(s, best) < 0:
            best = s
    return best


def is_strict_improvement(candidate: RepairState, reference: RepairState
                          ) -> bool:
    if not candidate.retention_ok() and not candidate.is_original:
        return False
    return cmp_states(candidate, reference) < 0


def catastrophic_regression(candidate: RepairState, original: RepairState
                            ) -> bool:
    """T15R.10 — many new failures vs original is not retainable progress."""
    if not candidate.tests_ran:
        return False
    orig_f = int(original.failure_count)
    cand_f = int(candidate.failure_count)
    if orig_f == 0 and cand_f > 0:
        return True
    if cand_f >= orig_f + 3 and cand_f > orig_f:
        return True
    return False


def revert_to_original_reason(candidate: RepairState, best: RepairState,
                              original: RepairState) -> str | None:
    """T15R.10 — why we must drop back to ORIGINAL. None = keep best."""
    if candidate.test_weakening or best.test_weakening:
        return "test weakening detected"
    if candidate.destructive or best.destructive:
        return "destructive mutation"
    if candidate.protected_component_status != OK \
            or best.protected_component_status != OK:
        return "protected component touched unexpectedly"
    if candidate.secret_leakage or best.secret_leakage:
        return "secret leakage"
    if candidate.unauthorized_network or best.unauthorized_network:
        return "unauthorized network"
    if candidate.unauthorized_paid_compute or best.unauthorized_paid_compute:
        return "unauthorized paid compute"
    if candidate.benchmark_tampering or best.benchmark_tampering:
        return "benchmark tampering"
    if candidate.safety_status != OK and not candidate.is_original:
        if not best.retention_ok() or best.is_original:
            return "safety violation"
    if not candidate.compile_ok and (
            best.is_original or not best.retention_ok()):
        return "patch cannot parse/compile and no valid improvement exists"
    if catastrophic_regression(best, original) and best is not original:
        return "catastrophic regression"
    if not is_strict_improvement(best, original) and not best.is_original:
        # equal-or-worse than original under registered ranking
        if not best.targeted_tests_passed:
            return ("candidate is objectively worse than or equal to "
                    "original under registered state ranking")
    return None


def continue_repair(round_i: int, *, last_progress: bool,
                    default_rounds: int = DEFAULT_REPAIR_ROUNDS,
                    hard_cap: int = HARD_CAP_REPAIR_ROUNDS) -> bool:
    """T15R.8 — default 3; 4–5 only with consistent positive progress."""
    if round_i >= hard_cap:
        return False
    if round_i < default_rounds:
        return True
    return bool(last_progress)


class RepairSession:
    """Owns ORIGINAL / CURRENT / BEST and the per-round patch log."""

    def __init__(self, root: str | Path, *,
                 involved_files: list[str] | None = None,
                 checkpoint_dir: str | Path | None = None):
        self.root = Path(root)
        self.involved_files = list(involved_files or [])
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        self._skip_prefixes: list[str] = []
        if self.checkpoint_dir is not None:
            try:
                rel = (self.checkpoint_dir.resolve()
                       .relative_to(self.root.resolve()).as_posix())
                self._skip_prefixes = [rel]
            except ValueError:
                self._skip_prefixes = [".mango_repair"]
        orig_blobs = snapshot_repo(self.root,
                                   skip_prefixes=self._skip_prefixes)
        self.original = RepairState(
            state_id="s0", parent_state_id=None, files_changed=[],
            diff_hash="0" * 64, test_result={}, targeted_tests_passed=False,
            full_tests_passed_if_run=None, failure_count=0, failure_ids=[],
            lint_status="NOT_RUN", safety_status=OK,
            protected_component_status=OK, tests_ran=False,
            blobs=dict(orig_blobs), diff_size=0,
        )
        self.current = self.original
        self.best = self.original
        self.history: list[RepairState] = [self.original]
        self.patches: dict[str, str] = {}
        self.round = 0
        self.last_progress = False
        self._seq = 0
        self.deltas: list[dict] = []
        self.outcome: dict = {}

    def bind_original_tests(self, test_result: dict) -> RepairState:
        """Attach reproduce-first evidence to ORIGINAL_STATE."""
        ran = bool((test_result or {}).get("executed"))
        passed = bool(ran and (test_result or {}).get("exit_code") == 0)
        ids = list((test_result or {}).get("failure_ids") or [])
        if not ids:
            ids = failure_ids_from_output((test_result or {}).get("output", ""))
        failed = int((test_result or {}).get("failed") or 0)
        if ran and not passed:
            failed = max(failed, len(ids), 1)
        if not ids and failed:
            ids = [f"anon:{i}" for i in range(failed)]
        self.original.test_result = dict(test_result or {})
        self.original.tests_ran = ran
        self.original.failure_count = 0 if passed else (
            failed if ran else self.original.failure_count)
        self.original.failure_ids = [] if passed else ids
        self.original.targeted_tests_passed = passed
        self.original.full_tests_passed_if_run = passed if ran else None
        self.current = self.original
        self.best = self.original
        return self.original

    def restore(self, state: RepairState) -> None:
        restore_repo(self.root, state.blobs,
                     skip_prefixes=self._skip_prefixes)
        self.current = state

    def restore_best(self) -> None:
        self.restore(self.best)

    def restore_original(self) -> None:
        self.restore(self.original)

    def capture_candidate(
            self, test_result: dict, *, parent: RepairState | None = None,
            safety_status: str = OK, protected_component_status: str = OK,
            lint_status: str = OK, test_weakening: bool = False,
            secret_leakage: bool = False, destructive: bool = False,
            benchmark_tampering: bool = False,
            unauthorized_network: bool = False,
            unauthorized_paid_compute: bool = False,
            compile_ok: bool = True,
            unrelated_edit_count: int | None = None,
            acceptance_conditions_satisfied: int = 0,
            full_tests_passed_if_run: bool | None = None) -> RepairState:
        parent = parent or self.current
        self._seq += 1
        blobs = snapshot_repo(self.root,
                              skip_prefixes=self._skip_prefixes)
        changed = files_changed(self.original.blobs, blobs)
        dhash = diff_hash(self.original.blobs, blobs)
        patch = unified_diff(self.original.blobs, blobs)
        ids = list((test_result or {}).get("failure_ids") or [])
        if not ids:
            ids = failure_ids_from_output((test_result or {}).get("output", ""))
        failed = int((test_result or {}).get("failed") or 0)
        ran = bool((test_result or {}).get("executed"))
        passed = bool(ran and (test_result or {}).get("exit_code") == 0)
        if ran and not passed:
            failed = max(failed, len(ids), 1)
        if not ids and failed:
            ids = [f"anon:{i}" for i in range(failed)]
        if unrelated_edit_count is None:
            involved = set(self.involved_files)
            unrelated_edit_count = (
                len([f for f in changed
                     if involved and f not in involved
                     and "test" not in f.lower()])
                if involved else 0
            )
        acceptance_conditions_satisfied = int(
            acceptance_conditions_satisfied) + auto_acceptance(
                self.original.blobs, blobs, self.involved_files)
        st = RepairState(
            state_id=f"s{self._seq}",
            parent_state_id=parent.state_id,
            files_changed=changed,
            diff_hash=dhash,
            test_result=dict(test_result or {}),
            targeted_tests_passed=passed,
            full_tests_passed_if_run=full_tests_passed_if_run,
            failure_count=0 if passed else (failed if ran else 10**6),
            failure_ids=[] if passed else ids,
            lint_status=lint_status,
            safety_status=safety_status,
            protected_component_status=protected_component_status,
            tests_ran=ran,
            test_weakening=test_weakening,
            secret_leakage=secret_leakage,
            destructive=destructive,
            benchmark_tampering=benchmark_tampering,
            unauthorized_network=unauthorized_network,
            unauthorized_paid_compute=unauthorized_paid_compute,
            unrelated_edit_count=int(unrelated_edit_count),
            acceptance_conditions_satisfied=int(
                acceptance_conditions_satisfied),
            diff_size=len(patch.splitlines()),
            compile_ok=compile_ok,
            blobs=dict(blobs),
            patch_text=patch,
        )
        self.current = st
        self.history.append(st)
        return st

    def consider(self, candidate: RepairState) -> dict:
        """Maybe promote BEST. Never overwrite without evidence."""
        before = self.best
        delta = failure_delta(before.failure_ids, candidate.failure_ids)
        self.deltas.append({"from": before.state_id,
                            "to": candidate.state_id, **delta})
        progressed = False
        reason = "not better than BEST_VERIFIED_STATE"
        if candidate.retention_ok() and is_strict_improvement(
                candidate, self.best):
            # regression gate: resolving 1 but introducing many is not best
            if (delta["regression_count"] > delta["resolved_count"]
                    and not candidate.targeted_tests_passed
                    and candidate.failure_count > self.best.failure_count):
                reason = "regression_count exceeds resolved_count"
            else:
                self.best = candidate
                progressed = True
                reason = "strict improvement under registered ranking"
                self._write_patch("best.patch", candidate.patch_text)
        self.last_progress = progressed
        self.round += 1
        self._write_patch(f"attempt_{self.round}.patch", candidate.patch_text)
        self.patches[f"attempt_{self.round}.patch"] = candidate.patch_text
        if progressed:
            self.patches["best.patch"] = candidate.patch_text
        return {
            "progressed": progressed,
            "reason": reason,
            "delta": delta,
            "best_state_id": self.best.state_id,
            "candidate_state_id": candidate.state_id,
        }

    def finalize(self) -> dict:
        """Apply T15R.10 revert policy and materialize BEST on disk.

        An unsafe CURRENT candidate is discarded back to BEST, not
        automatically to ORIGINAL. ORIGINAL is restored only when BEST
        itself is unsafe/invalid or is not a strict improvement.
        """
        unsafe_reasons = (
            "safety violation", "destructive mutation",
            "protected component touched unexpectedly",
            "test weakening detected", "secret leakage",
            "unauthorized network", "unauthorized paid compute",
            "benchmark tampering",
        )
        reason = None
        unsafe_revert = False
        reverted_to_original = False
        if not self.best.is_original and not self.best.retention_ok():
            reason = revert_to_original_reason(
                self.best, self.best, self.original) or "safety violation"
            self.restore_original()
            self.best = self.original
            reverted_to_original = True
            unsafe_revert = True
        elif (self.best.is_original
              or not is_strict_improvement(self.best, self.original)):
            self.restore_original()
            self.best = self.original
            reverted_to_original = True
            reason = "no verified improvement over original"
        else:
            self.restore_best()
        self._flush_patches()
        self.outcome = {
            "best_state_id": self.best.state_id,
            "reverted_to_original": reverted_to_original,
            "unsafe_revert": unsafe_revert,
            "reason": reason,
            "files_touched": list(self.best.files_changed),
            "best_retained": (not self.best.is_original
                              and self.best.retention_ok()),
            "unsafe_reason_class": (
                reason if reason in unsafe_reasons else None),
        }
        return self.outcome

    def lineage(self) -> list[dict]:
        return [{"state_id": s.state_id, "parent_state_id": s.parent_state_id,
                 "files_changed": s.files_changed,
                 "failure_count": s.failure_count,
                 "diff_hash": s.diff_hash,
                 "retention_ok": s.retention_ok()}
                for s in self.history]

    def _write_patch(self, name: str, text: str) -> None:
        red, _n = S.redact_secrets(text or "")
        self.patches[name] = red
        if self.checkpoint_dir is not None:
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
            (self.checkpoint_dir / name).write_text(red, encoding="utf-8")

    def _flush_patches(self) -> None:
        """Re-materialize audit diffs after restore (T15R.11)."""
        for name, text in list(self.patches.items()):
            self._write_patch(name, text)

    def export(self) -> dict:
        return {
            "original": self.original.public_dict(),
            "best": self.best.public_dict(),
            "current": self.current.public_dict(),
            "lineage": self.lineage(),
            "deltas": self.deltas,
            "round": self.round,
            "outcome": dict(self.outcome),
            "patches": {k: (v if len(v) < 8000 else
                            {"sha256": hashlib.sha256(
                                v.encode("utf-8")).hexdigest(),
                             "n_bytes": len(v)})
                        for k, v in self.patches.items()},
        }


def score_acceptance(original: dict[str, bytes], current: dict[str, bytes],
                     conditions: list[dict]) -> int:
    """Count satisfied {kind, value, files?} conditions (no golden patches)."""
    n = 0
    texts = {k: v.decode("utf-8", "replace") for k, v in current.items()}
    joined = "\n".join(texts.values())
    changed = set(files_changed(original, current))
    for c in conditions or []:
        kind = c.get("kind")
        val = c.get("value", "")
        files = c.get("files")
        scope = joined
        if files:
            scope = "\n".join(texts.get(f, "") for f in files)
        if kind == "new_present" and val and val in scope:
            n += 1
        elif kind == "old_absent" and val and val not in scope:
            n += 1
        elif kind == "file_changed" and c.get("file") in changed:
            n += 1
    return n
