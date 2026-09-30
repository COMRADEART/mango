"""T31 tests for the command line: subcommand names and their flags.

The failure pinned here is a silent one, and it is worth spelling out because
nothing in the package's own tests would have caught it. ``add_subparsers``
uses ``command`` as its dest, and the ``report`` subcommand also declared a
``--command`` flag. argparse copies a subparser's namespace back over the
parent's, so on every ``report`` invocation the flag's default (``None``)
overwrote the subcommand name. ``args.command`` was therefore ``None`` for that
one subcommand, the reproduction commands were dropped, and GATE 13 — which
requires a recorded command list — reported FAIL, dragging the whole decision
to ``MANGO_T31_PUBLIC_COMPARABILITY_FAIL`` on a run that was complete and
correct. The fix is a distinct dest for the flag; both are pinned below.
"""
from __future__ import annotations

from sciencemath.comparability.__main__ import build_parser

SUBCOMMANDS = ("smoke", "freeze", "run", "score", "analyse", "contamination",
               "report", "manifest", "check", "verify")


def test_every_subcommand_name_survives_parsing():
    for name in SUBCOMMANDS:
        argv = [name] + (["--arm", "base"] if name == "run" else [])
        assert build_parser().parse_args(argv).command == name


def test_the_report_subcommand_keeps_its_name():
    assert build_parser().parse_args(["report"]).command == "report"


def test_the_report_command_collects_reproduction_commands():
    argv = ["report", "--command", "python -m sciencemath.comparability run",
            "--command", "python -m sciencemath.comparability score"]
    args = build_parser().parse_args(argv)
    assert args.command == "report"
    assert args.repro_commands == [
        "python -m sciencemath.comparability run",
        "python -m sciencemath.comparability score",
    ]


def test_the_report_command_defaults_to_no_recorded_commands():
    args = build_parser().parse_args(["report"])
    assert args.repro_commands is None


def test_the_t30_tree_flag_is_an_override_not_a_default():
    """Absent, it must be ``None`` so the pipeline computes the tree state; a
    boolean default would silently claim a check nobody ran."""
    assert build_parser().parse_args(["report"]).t30_tree_clean is None
    assert build_parser().parse_args(
        ["report", "--t30-tree-clean"]).t30_tree_clean is True
