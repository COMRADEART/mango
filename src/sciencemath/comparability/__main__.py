"""T31 command line — the brief's steps as separate commands.

They are separate because the brief orders them and says why. A single
``run`` that did everything would make it possible to reach the full
evaluation without ever reading a smoke test, which is the sequence
"Do not tune the harness based on Mango's final score" is written to prevent.

    python -m sciencemath.comparability smoke       # steps 3-5, scratch tree
    python -m sciencemath.comparability freeze      # steps 6-7, write-once
    python -m sciencemath.comparability run --arm base
    python -m sciencemath.comparability run --arm adapter
    python -m sciencemath.comparability score
    python -m sciencemath.comparability analyse
    python -m sciencemath.comparability contamination
    python -m sciencemath.comparability report --branch ... --base-commit ... \
        --command "python -m sciencemath.comparability run --arm base" ...
    python -m sciencemath.comparability manifest
    python -m sciencemath.comparability verify

``run`` refuses to start without a frozen configuration, and the configuration
is write-once, so the settings that produced a set of rows cannot be changed
after those rows exist.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sciencemath.comparability.contract import BENCHMARK_ORDER


def _benchmarks(values) -> tuple[str, ...]:
    if not values:
        return BENCHMARK_ORDER
    unknown = [name for name in values if name not in BENCHMARK_ORDER]
    if unknown:
        raise SystemExit(f"unknown benchmarks {unknown}; "
                         f"choose from {list(BENCHMARK_ORDER)}")
    return tuple(values)


def _progress(benchmark, arm, done, expected):
    if done % 64 < 1 or done >= expected:
        print(f"  {arm} {benchmark}: {done}/{expected}", file=sys.stderr,
              flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sciencemath.comparability",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=".",
                        help="base directory holding evaluations/t31 "
                             "(default: the current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    smoke = sub.add_parser("smoke", help="steps 3-5: a small base-model run "
                                         "in a scratch tree")
    smoke.add_argument("--benchmark", default="gsm8k")
    smoke.add_argument("--limit", type=int, default=16)
    smoke.add_argument("--batch-size", type=int, default=8)
    smoke.add_argument("--arm", default="base")
    smoke.add_argument("--sample", type=int, default=4)

    freeze = sub.add_parser("freeze", help="steps 6-7: freeze and hash the "
                                           "configuration")
    freeze.add_argument("--benchmark", action="append")

    run = sub.add_parser("run", help="step 8: generate and capture one arm "
                                     "over whole suites")
    run.add_argument("--arm", required=True, choices=("base", "adapter", "both"))
    run.add_argument("--benchmark", action="append")
    run.add_argument("--batch-size", type=int)
    run.add_argument("--thinking", action="store_true")

    for name, help_text in (("score", "score the captured rows"),
                            ("analyse", "pair the arms and summarize"),
                            ("contamination", "measure training overlap"),
                            ("manifest", "write SHA256SUMS")):
        step = sub.add_parser(name, help=help_text)
        if name in ("score", "analyse", "contamination"):
            step.add_argument("--benchmark", action="append")

    report = sub.add_parser("report", help="render the report and decide the "
                                           "gates")
    report.add_argument("--branch", default="")
    report.add_argument("--base-commit", default="")
    report.add_argument("--final-commit", default="")
    report.add_argument("--tests", default="", help="JSON, e.g. "
                                                    "'{\"passed\": 330}'")
    report.add_argument("--regression", default="")
    report.add_argument("--limitation", action="append")
    # The dest is ``repro_commands``, NOT ``command``: the subparsers already
    # use ``command`` as their dest, and argparse copies a subparser's
    # namespace back over the parent's, so a ``--command`` here overwrote
    # ``args.command`` with its own None on every invocation. Reading
    # ``args.command`` then yielded None for this one subcommand, the
    # reproduction commands were silently dropped, and GATE 13 — which
    # requires a command list — failed a run that was otherwise complete.
    report.add_argument("--command", dest="repro_commands", action="append",
                        help="a reproduction command to record verbatim in the "
                             "report's Reproduction section; repeatable. "
                             "GATE 13 requires at least one.")
    report.add_argument("--t30-tree-clean", action="store_true", default=None)

    sub.add_parser("check", help="steps 1-2: validate the loaders and the "
                                "scorers against the real datasets")
    sub.add_parser("verify", help="re-verify the pack against its manifest")
    return parser


def main(argv=None) -> int:
    from sciencemath.comparability import manifest as M
    from sciencemath.comparability import pipeline as P

    args = build_parser().parse_args(argv)
    root = Path(args.root)

    if args.command == "smoke":
        report = P.smoke(args.benchmark, limit=args.limit,
                         batch_size=args.batch_size, root=root / "artifacts"
                         / "t31_smoke", arm=args.arm,
                         sample_size=args.sample)
        print(json.dumps(report.to_dict(), indent=2))
        print("\nsample captures:")
        for row in report.sample:
            print(f"  {row['item_id']}  gold={row['gold']!r}  "
                  f"finish={row['finish_reason']}  "
                  f"tokens={row['output_tokens']}")
            print(f"    {row['generation_head']!r}")
        if report.extraction_failures:
            print(f"\n{report.extraction_failures} of {report.items} "
                  f"generations did not yield an answer — inspect before "
                  f"freezing.", file=sys.stderr)
        return 0

    if args.command == "freeze":
        digest = P.freeze(root, benchmarks=_benchmarks(args.benchmark))
        print(json.dumps({"config_sha256": digest,
                          "config_path": M.config_path(root).as_posix()},
                         indent=2))
        return 0

    if args.command == "run":
        arms = ("base", "adapter") if args.arm == "both" else (args.arm,)
        written = {}
        for arm in arms:
            print(f"running {arm}…", file=sys.stderr)
            written[arm] = P.run_arm(
                arm, root, benchmarks=_benchmarks(args.benchmark),
                batch_size=args.batch_size,
                thinking=args.thinking, progress=_progress)
        print(json.dumps(written, indent=2))
        return 0

    if args.command == "score":
        print(json.dumps(P.score(root,
                                 benchmarks=_benchmarks(args.benchmark)),
                         indent=2))
        return 0

    if args.command == "analyse":
        summaries, aggregate_payload = P.analyse(
            root, benchmarks=_benchmarks(args.benchmark))
        print(json.dumps({"benchmarks": summaries,
                          "aggregate": aggregate_payload}, indent=2))
        return 0

    if args.command == "contamination":
        print(json.dumps(P.contamination(
            root, benchmarks=_benchmarks(args.benchmark)), indent=2))
        return 0

    if args.command == "report":
        result = P.build_report(
            root, branch=args.branch, base_commit=args.base_commit,
            final_commit=args.final_commit,
            tests=json.loads(args.tests) if args.tests else None,
            regression=json.loads(args.regression) if args.regression else None,
            limitations=args.limitation or (),
            commands=args.repro_commands or (),
            t30_tree_clean=args.t30_tree_clean)
        print(json.dumps({"status": result["status"],
                          "report": result["report"]}, indent=2))
        for gate in result["gates"]:
            print(f"  {gate['gate']:<9} {gate['status']:<14} {gate['name']}")
        return 0

    if args.command == "manifest":
        # Snapshot first, so running ``manifest`` on its own still produces a
        # pack whose SHA256SUMS covers the prompt, extractor and scorer source.
        M.snapshot_sources(root)
        path = M.write_sums(root)
        print(json.dumps({"written": path.as_posix(),
                          "files": len(M.collect(root))}, indent=2))
        return 0

    if args.command == "check":
        return _check()

    if args.command == "verify":
        print(json.dumps(P.verify(root), indent=2, default=str))
        return 0

    raise SystemExit(f"unhandled command {args.command!r}")


def _check() -> int:
    """Steps 1-2: the loaders against the pinned suites, the scorers against
    cases whose answers are known independently of either model."""
    from sciencemath.comparability import manifest as M
    from sciencemath.comparability.loaders import load_all, suite_hash
    from sciencemath.comparability.identity import BENCHMARK_IDENTITIES
    from sciencemath.comparability.contract import BENCHMARKS
    from sciencemath.comparability.extractors import extract
    from sciencemath.comparability.scorers import score

    items = load_all()
    failures = 0
    print("loading")
    for name, suite in items.items():
        expected = BENCHMARK_IDENTITIES[name]["expected_items"]
        ids = {item.item_id for item in suite}
        ok = len(suite) == expected and len(ids) == expected
        if not ok:
            failures += 1
        print(f"  {name:<14} {len(suite):>5} items "
              f"(expected {expected:>5})  {len(ids):>5} distinct ids  "
              f"{'ok' if ok else 'MISMATCH'}")
        print(f"  {'':<14} suite_hash {suite_hash(suite)}")

    def show(benchmark, item, generation):
        kind = BENCHMARKS[benchmark]["kind"]
        extraction = extract(item, kind, generation)
        verdict = score(item, kind, extraction, generation)
        print(f"  {benchmark:<14} {generation[:26]!r:<28} "
              f"status={extraction.status:<8} answer={extraction.answer!r:<10} "
              f"correct={verdict.content_valid}  tier={verdict.scorer_tier}")
        return verdict

    print("\nscorers, on cases whose answer is known independently")
    gsm = items["gsm8k"][0]
    if not show("gsm8k", gsm, "#### " + str(gsm.gold)).content_valid:
        failures += 1
        print("    the gold answer did not score correct", file=sys.stderr)
    show("gsm8k", gsm, "I cannot solve this.")

    mcq = items["arc_easy"][0]
    gold = mcq.gold_label
    if not gold:
        print("    arc_easy[0] carries no gold_label", file=sys.stderr)
        failures += 1
    else:
        if not show("arc_easy", mcq, gold).content_valid:
            failures += 1
            print(f"    the gold option {gold!r} did not score correct",
                  file=sys.stderr)
        wrong = next((label for label, _ in mcq.choices if label != gold), None)
        if wrong and show("arc_easy", mcq, wrong).content_valid:
            failures += 1
            print(f"    the wrong option {wrong!r} scored correct",
                  file=sys.stderr)
        if show("arc_easy", mcq, "").content_valid:
            failures += 1
            print("    an empty generation scored correct", file=sys.stderr)

    print(f"\n{'FAILURES: ' + str(failures) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
