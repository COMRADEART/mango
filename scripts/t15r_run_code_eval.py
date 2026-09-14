"""T15R final CODE evaluation harness.

Unchanged model (Qwen/Qwen3-4B-Instruct-2507, seed 20260912).
Never passes golden patches to the runner.
Default suite: mango-code-eval-v1.1 (metadata correction only).
Historical v1 scores are cited, not overwritten.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.code import editor as E  # noqa: E402
from sciencemath.code import planner as P  # noqa: E402
from sciencemath.code import review as R  # noqa: E402
from sciencemath.code import runner as RN  # noqa: E402
from sciencemath.code import testsel as T  # noqa: E402

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
SEED = 20260912


def load_split(suite_dir: Path, split: str) -> list:
    p = suite_dir / f"{split}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def snapshot(base: Path) -> dict:
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts \
                and ".pytest_tmp" not in p.parts:
            try:
                out[p.relative_to(base).as_posix()] = p.read_bytes()
            except OSError:
                pass
    return out


def grade(t: dict, res: dict, before: dict, after: dict) -> dict:
    c = t["checks"]
    reasons = []
    ok = True

    def need(cond: bool, msg: str):
        nonlocal ok
        if not cond:
            ok = False
            reasons.append(msg)

    if "op" in c:
        need(res.get("op") == c["op"],
             f"op {res.get('op')} != {c['op']}")
    if "status_in" in c:
        need(res.get("status") in c["status_in"],
             f"status {res.get('status')} not in {c['status_in']}")
    if "hit_file" in c:
        hits = (res.get("evidence") or {}).get("hits", [])
        need(any(h["file"] == c["hit_file"] for h in hits),
             f"hit_file {c['hit_file']} not in evidence")
    if "hit_line" in c:
        hits = (res.get("evidence") or {}).get("hits", [])
        need(any(h["file"] == c.get("hit_file") and h["line"] == c["hit_line"]
                 for h in hits), "hit_line mismatch")
    if "tests_pass" in c:
        tst = (res.get("evidence") or {}).get("test") or {}
        need(tst.get("exit_code") == 0,
             f"runner tests exit={tst.get('exit_code')} "
             f"(failed={tst.get('failed')})")
    if c.get("no_diff"):
        need(set(before) == set(after)
             and all(before[k] == after[k] for k in before),
             "repo changed on no-diff task")
    if "test_files_unchanged" in c and c["test_files_unchanged"]:
        for f, b in before.items():
            if "test" in f.lower() and f.endswith(".py"):
                need(after.get(f) == b, f"test file changed: {f}")
    if "source_files_unchanged" in c:
        for f in c["source_files_unchanged"]:
            need(after.get(f) == before.get(f), f"source changed: {f}")
    if c.get("no_weakening"):
        for f, b in before.items():
            if f in after and b != after[f] and "test" in f.lower():
                v = E.detect_test_weakening(
                    b.decode("utf-8", "replace"),
                    after[f].decode("utf-8", "replace"))
                need(not v, f"weakening in {f}: {v[:2]}")
    if "old_absent" in c:
        need(not any(c["old_absent"] in v.decode("utf-8", "replace")
                     for k, v in after.items()
                     if k.startswith("src/") and k.endswith(".py")),
             "old symbol still present")
    if "new_present" in c:
        need(any(c["new_present"] in v.decode("utf-8", "replace")
                 for k, v in after.items()
                 if k.startswith("src/") and k.endswith(".py")),
             "new symbol absent")
    if "files_touched_max" in c:
        need(len(res.get("files_touched", [])) <= c["files_touched_max"],
             "too many files touched")
    if "patch_forbidden" in c:
        for k, v in after.items():
            if k.startswith("src/") and k.endswith(".py"):
                txt = v.decode("utf-8", "replace")
                for pat in c["patch_forbidden"]:
                    need(pat not in txt, f"forbidden {pat!r} in {k}")
    if "failing_test_contains" in c:
        ev = res.get("evidence") or {}
        tout = ((ev.get("test") or ev).get("output", "")
                if isinstance(ev, dict) else "")
        need(c["failing_test_contains"] in tout.replace("\\", "/"),
             "failing test not identified")
    if "needs_information" in c:
        need("NEEDS_INFORMATION" in (res.get("detail") or ""),
             "missing NEEDS_INFORMATION")
    return {"pass": ok, "reasons": reasons}


def session_metrics(res: dict) -> dict:
    ev = res.get("evidence") or {}
    sess = ev.get("repair_session") or {}
    best = sess.get("best") or {}
    outcome = sess.get("outcome") or {}
    trail = res.get("trail") or []
    rounds = sum(1 for s in trail if s.get("step") == "RETEST")
    usage = res.get("usage") or ev.get("usage") or {}
    return {
        "repair_rounds": rounds,
        "best_retained": bool(outcome.get("best_retained")
                              if "best_retained" in outcome else
                              (sess.get("best") and not best.get("is_original")
                               and best.get("retention_ok"))),
        "best_failure_count": best.get("failure_count"),
        "best_state_id": best.get("state_id"),
        "n_deltas": len(sess.get("deltas") or []),
        "full_revert": bool(outcome.get("reverted_to_original")
                            if "reverted_to_original" in outcome else
                            ((sess.get("original") or {}).get("state_id")
                             == best.get("state_id"))),
        "unsafe_revert": bool(outcome.get("unsafe_revert")),
        "max_files_read": usage.get("max_files_read"),
        "max_files_modified": usage.get("max_files_modified"),
        "max_commands": usage.get("max_commands"),
        "max_repair_iterations": usage.get("max_repair_iterations"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="final", choices=("dev", "final"))
    ap.add_argument("--run-name", default="code-final")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--suite", default="v1.1",
                    choices=("v1", "v1.1"))
    ap.add_argument("--task-ids", default="",
                    help="comma-separated task_id filter (replay)")
    ap.add_argument("--rerun", action="store_true",
                    help="re-run matching task-ids even if already in predictions")
    args = ap.parse_args()

    if args.suite == "v1":
        suite_dir = ROOT / "evaluations/t15/suites/mango-code-eval-v1"
        bench = "mango-code-eval-v1"
    else:
        suite_dir = ROOT / "evaluations/t15r/suites/mango-code-eval-v1.1"
        bench = "mango-code-eval-v1.1"
    manifest = json.loads((suite_dir / "manifest.json").read_text(
        encoding="utf-8"))
    tasks = load_split(suite_dir, args.split)
    if args.task_ids:
        want = {x.strip() for x in args.task_ids.split(",") if x.strip()}
        tasks = [t for t in tasks if t["task_id"] in want]
    if args.limit:
        tasks = tasks[:args.limit]

    run_dir = ROOT / "evaluations/t15r/runs" / args.run_name
    ck_root = ROOT / "evaluations/t15r/checkpoints" / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    ck_root.mkdir(parents=True, exist_ok=True)
    pred_p = run_dir / "predictions.jsonl"
    done = {}
    if pred_p.exists():
        for l in pred_p.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                done[r["task_id"]] = r
    if args.rerun:
        if args.task_ids:
            for tid in (x.strip() for x in args.task_ids.split(",")
                        if x.strip()):
                done.pop(tid, None)
        else:
            done = {}
    print(f"resume: {len(done)} already complete; remaining "
          f"{sum(1 for t in tasks if t['task_id'] not in done)}")

    generate = None
    model_info = {"model": None, "used": False}
    need_model = any(t.get("model_needed") and t["task_id"] not in done
                     for t in tasks) and not args.no_model
    if need_model:
        from sciencemath.evaluation.model_loader import load_model_safely
        from sciencemath.executive.llm import call_model
        tok, model, info = load_model_safely(MODEL)
        if not info["ok"]:
            print("MODEL LOAD FAILED:", info["error"])
            return 2
        model_info = {"model": MODEL, "used": True,
                      "load": {k: v for k, v in info.items()},
                      "gen": {"seed": SEED, "max_new_tokens": 384}}

        def generate(prompt: str) -> str:
            text, _, _ = call_model(
                model, tok, prompt,
                {"seed": SEED, "max_new_tokens": 384})
            return text

    import torch
    vram_peak = 0
    n_new = 0
    t_start = time.time()
    latencies = []
    with pred_p.open("a", encoding="utf-8") as fh:
        for t in tasks:
            if t["task_id"] in done:
                continue
            if t.get("model_needed") and (args.no_model or generate is None):
                rec = {"task_id": t["task_id"], "category": t["category"],
                       "skipped": True, "reason": "model disabled"}
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                continue
            t0 = time.time()
            plan_ok = None
            ck = ck_root / t["task_id"]
            ck.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                for rel, content in t["fixture"].items():
                    p = base / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content, encoding="utf-8")
                before = snapshot(base)
                use_gen = generate if t.get("model_needed") else None
                try:
                    if t["category"] == "review":
                        diff = (f"+++ b/{t['review_file']}\n" + "".join(
                            f"+{l}\n" for l in t["review_bad"].splitlines()
                            if l not in t["review_base"].splitlines()))
                        rep = R.code_review(
                            diff, changed_files=[t["review_file"]])
                        needle = t["checks"]["finding_contains"]
                        rank = {"NOTE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3,
                                "BLOCKER": 4}
                        hits = [
                            f for f in rep["findings"]
                            if needle in f["evidence"] and rank[f["severity"]]
                            >= rank[t["checks"].get("min_severity", "MEDIUM")]]
                        res = {"op": "CODE_REVIEW",
                               "status": "EXECUTED_PASS",
                               "evidence": rep,
                               "detail": f"verdict={rep['verdict']}",
                               "files_touched": []}
                        passed = bool(hits)
                        reasons = [] if passed else [
                            f"needle {needle!r} not flagged: "
                            f"{rep['findings']}"]
                        g = {"pass": passed, "reasons": reasons}
                    else:
                        res = RN.run_coding_task(
                            base, t["request"], op=t.get("op"),
                            edits=None, repair_candidates=[],
                            repair_file=t.get("repair_file"),
                            context_files=t.get("context_files"),
                            tests_to_run=t.get("tests_to_run"),
                            generate=use_gen,
                            checkpoint_dir=ck)
                        after = snapshot(base)
                        g = grade(t, res, before, after)
                        if g["pass"] and t["checks"].get("tests_pass"):
                            chk = T.run_pytest_targets(
                                base, t["checks"]["tests_pass"],
                                touch_files=res.get("files_touched", []))
                            if not (chk.get("executed")
                                    and chk.get("exit_code") == 0):
                                g = {"pass": False,
                                     "reasons": ["independent re-run failed: "
                                                 "fabricated execution claim"]}
                            else:
                                after = snapshot(base)
                        plan = (res.get("evidence") or {}).get("plan")
                        plan_ok = None
                        if plan is not None:
                            plan_ok, _ = P.plan_valid(plan)
                    after = snapshot(base)
                except Exception as e:  # noqa: BLE001
                    res = {"op": t.get("op"), "status": "EXECUTED_FAIL",
                           "detail": f"harness exception: {type(e).__name__}: "
                                     f"{e}", "files_touched": []}
                    after = snapshot(base)
                    g = {"pass": False, "reasons": ["harness exception"]}
                    plan_ok = None
            dt = time.time() - t0
            latencies.append(dt)
            if torch.cuda.is_available():
                vram_peak = max(vram_peak,
                                int(torch.cuda.max_memory_allocated()))
            from sciencemath.code import safety as S
            blob = json.dumps(res, ensure_ascii=False)
            _, detections = S.redact_secrets(blob)
            sm = session_metrics(res)
            rec = {"task_id": t["task_id"], "category": t["category"],
                   "op": res.get("op"), "status": res.get("status"),
                   "pass": g["pass"], "reasons": g["reasons"],
                   "detail": (res.get("detail") or "")[:500],
                   "files_touched": res.get("files_touched", []),
                   "latency_s": round(dt, 2),
                   "plan_valid": plan_ok,
                   "secret_detections": detections,
                   "repair": sm,
                   "evidence_summary": {
                       k: (len(v) if isinstance(v, list) else v)
                       for k, v in (res.get("evidence") or {}).items()
                       if k in ("hits", "diagnosis", "verdict")},
                   "test": {k: (res.get("evidence") or {}).get("test", {})
                            .get(k) for k in ("exit_code", "passed",
                                              "failed", "errors")}}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            n_new += 1
            print(f"[{n_new}] {t['task_id']} {t['category']} "
                  f"pass={g['pass']} status={res.get('status')} {dt:.1f}s "
                  f"{g['reasons'][:1]}", flush=True)

    rows = []
    for l in pred_p.read_text(encoding="utf-8").splitlines():
        if l.strip():
            rows.append(json.loads(l))
    # last occurrence wins so --rerun does not duplicate task_ids
    uniq = {}
    for r in rows:
        uniq[r["task_id"]] = r
    rows = [r for r in uniq.values() if not r.get("skipped")]
    pred_p.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in uniq.values()),
        encoding="utf-8")
    from collections import Counter, defaultdict
    by_cat: dict[str, list] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    cat_acc = {c: sum(1 for r in v if r["pass"]) / len(v)
               for c, v in by_cat.items() if v}
    rounds = [r.get("repair", {}).get("repair_rounds", 0) or 0 for r in rows]
    rss = None
    try:
        import psutil
        rss = int(psutil.Process().memory_info().rss)
    except Exception:
        rss = None
    summary = {
        "run": args.run_name,
        "split": args.split,
        "benchmark": bench,
        "suite_final_sha256": manifest.get("final_sha256"),
        "model": model_info,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "n_tasks": len(rows),
        "n_pass": sum(1 for r in rows if r["pass"]),
        "accuracy": (sum(1 for r in rows if r["pass"]) / len(rows)
                     if rows else 0),
        "by_category": {c: {"n": len(v),
                            "pass": sum(1 for r in v if r["pass"]),
                            "acc": cat_acc[c]} for c, v in by_cat.items()},
        "statuses": dict(Counter(r.get("status") for r in rows)),
        "vram_peak_bytes": vram_peak,
        "wall_seconds": round(time.time() - t_start, 1),
        "avg_latency_s": round(sum(latencies) / len(latencies), 3)
        if latencies else None,
        "avg_repair_rounds": round(sum(rounds) / len(rounds), 3)
        if rounds else None,
        "median_repair_rounds": (sorted(rounds)[len(rounds) // 2]
                                 if rounds else None),
        "best_state_retained_count": sum(
            1 for r in rows if r.get("repair", {}).get("best_retained")),
        "full_revert_count": sum(
            1 for r in rows if r.get("repair", {}).get("full_revert")),
        "unsafe_revert_count": sum(
            1 for r in rows if r.get("repair", {}).get("unsafe_revert")),
        "sum_files_read": sum(
            int(r.get("repair", {}).get("max_files_read") or 0) for r in rows),
        "sum_files_modified": sum(
            int(r.get("repair", {}).get("max_files_modified") or 0)
            for r in rows),
        "sum_commands": sum(
            int(r.get("repair", {}).get("max_commands") or 0) for r in rows),
        "peak_rss_bytes": rss,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("by_category",)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
