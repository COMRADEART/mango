"""T21R14 bootstrap part 1: namespace transforms + surgery blocks."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pools
SCRIPTS = ROOT / "scripts"
COMMON = [
    ("t21r13_", "t21r14_"),
    ("t21r13", "t21r14"),
    ("T21R13_", "T21R14_"),
    ("T21R13 ", "T21R14 "),
    ("mango-r13b-v1", "mango-r14b-v1"),
    ("r13b-", "r14b-"),
    ("ent13b", "ent14b"),
    ("pre13q-", "pre14q-"),
    ("R13B", "R14B"),
    ("gk-r13b", "gk-r14b"),
]
def transform(text):
    for old, new in COMMON:
        text = text.replace(old, new)
    return text
def _literal(name, values):
    items = ", ".join(json.dumps(v) for v in values)
    return name + " = (" + items + ",)\n"
def _pool_block():
    block = ('WORK_DOMAINS = ("literature", "arts", "technology_history", "history",\n'
             '                "culture", "natural_philosophy", "civic_architecture")\n')
    block += _literal("FIRSTS", pools.FIRSTS)
    block += _literal("LASTS", pools.LASTS)
    block += _literal("ADJECTIVES", pools.ADJECTIVES)
    block += _literal("NOUNS", pools.NOUNS)
    block += _literal("TOWN_ROOTS", pools.TOWN_ROOTS)
    block += "TOWN_SUFFIXES = (\n"
    block += "".join('    ' + json.dumps(s) + ',\n' for s in pools.TOWN_SUFFIXES)
    block += ")\n"
    block += _literal("COUNTRIES", pools.COUNTRIES)
    block += _literal("FIELDS", pools.FIELDS)
    block += _literal("YEARS", pools.YEARS)
    block += "SOURCE_ATTACK_WORDING = (" + json.dumps(pools.SOURCE_ATTACK_WORDING) + ")\n"
    block += "QUERY_OVERRIDE_PREFIX = " + json.dumps(pools.QUERY_OVERRIDE_PREFIX) + "\n"
    block += "SPOOF_WORDING = " + json.dumps(pools.SPOOF_WORDING) + "\n"
    return block
CONTRACT_BLOCK = '''

# T21R14 single-source-of-truth check: the blind author's possible official
domain vocabulary is finite and must be a subset of the canonical taxonomy
contract (author_domain_vocabulary.json mirrors this set).  No domain label
may be invented at generation time.
DOMAIN_CONTRACT_PATH = ROOT / "evaluations" / "t21r14" / \\
    "domain_taxonomy_contract.json"
DOMAIN_CONTRACT = json.loads(DOMAIN_CONTRACT_PATH.read_text(encoding="utf-8"))
CANONICAL_DOMAIN_LABELS = frozenset(
    entry["canonical_label"] for entry in DOMAIN_CONTRACT["domains"])
AUTHOR_DOMAIN_VOCABULARY = frozenset(WORK_DOMAINS) | {
    "biography", "geography", "government_civics"}
assert AUTHOR_DOMAIN_VOCABULARY <= CANONICAL_DOMAIN_LABELS, (
    "author domain vocabulary outside the canonical taxonomy contract")
'''
UNIQUENESS_MILESTONE_BLOCK = '''CARRIED_MILESTONES = ("T21R11_INVALID_SEALED", "T21R12_FAILED_PARTIAL_BLIND")
CARRIED_R13_MILESTONE = ("T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE",)
PRIOR_MILESTONES = (*MILESTONES, *CARRIED_MILESTONES, *CARRIED_R13_MILESTONE)'''
RUN_EVAL_TAXONOMY_BLOCK = '''
# T21R14 domain-taxonomy remediation: the canonical contract is the single
# source of truth for official domain labels.  The frozen R6-lineage literal
# set is rebound (never relaxed, never aliased) to the contract's canonical
# labels before any row executes; unknown labels still fail loudly
# (T21R6_EVALUATOR_INVALID).  No competing taxonomy may be defined here.
DOMAIN_CONTRACT_PATH = OUT_DIR / "domain_taxonomy_contract.json"
DOMAIN_CONTRACT = json.loads(DOMAIN_CONTRACT_PATH.read_text(encoding="utf-8"))
CANONICAL_DOMAINS = frozenset(
    entry["canonical_label"] for entry in DOMAIN_CONTRACT["domains"])
_r6.DOMAIN_TAXONOMY = CANONICAL_DOMAINS
_qualified.DOMAIN_TAXONOMY = CANONICAL_DOMAINS
'''

OFFICIAL_EVAL_GOLD_PREFLIGHT_BLOCK = '''
    # T21R14 gold-schema/taxonomy preflight: validate every row's gold
    # metadata (required_domains against the canonical contract) WITHOUT
    # executing any candidate row.  Unknown labels abort here, before
    # ledger creation (R13 infrastructure-failure regression guard).
    taxonomy = json.loads(
        (paths.out / "domain_taxonomy_contract.json").read_text(
            encoding="utf-8"))
    canonical = {entry["canonical_label"] for entry in taxonomy["domains"]}
    for suite_path in sorted(paths.suites.glob("*/holdout.jsonl")):
        for line in suite_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            gold = row.get("gold") or {}
            if not isinstance(gold, dict):
                defects.append(
                    f"gold schema invalid: {row.get('case_id')}")
                continue
            labels = gold.get("required_domains") or []
            if not isinstance(labels, list):
                defects.append(
                    f"required_domains wrong type: {row.get('case_id')}")
                continue
            if len(labels) != len(set(labels)):
                defects.append(
                    f"required_domains duplicate label: "
                    f"{row.get('case_id')}")
            for label in labels:
                if not isinstance(label, str) or not label:
                    defects.append(
                        f"required_domains null/empty label: "
                        f"{row.get('case_id')}")
                elif label not in canonical:
                    defects.append(
                        f"required_domains label outside the canonical "
                        f"domain taxonomy: {label!r} "
                        f"({row.get('case_id')})")
    sources_path = paths.corpus / "sources.jsonl"
    if sources_path.is_file():
        for line in sources_path.read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            source = json.loads(line)
            for tag in (source.get("topic_tags") or []):
                if str(tag) not in canonical:
                    defects.append(
                        f"source topic_tags label outside the canonical "
                        f"domain taxonomy: {tag!r} "
                        f"({source.get('source_id')})")
'''

FREEZE_INPUTS_OLD = '    "blindness_policy.json", "synthetic_protocol_report.json",'
FREEZE_INPUTS_NEW = ('    "blindness_policy.json", "domain_taxonomy_contract.json",\n'
                     '    "synthetic_protocol_report.json",')


def main() -> int:
    ports = [path.name for path in sorted(SCRIPTS.glob("t21r13_*.py"))
             if path.name != "t21r13_preconstruction.py"]
    for name in ports:
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        out = transform(text)
        target = SCRIPTS / name.replace("t21r13_", "t21r14_")
        target.write_text(out, encoding="utf-8", newline="\n")
        print("ported " + name + " -> " + target.name)
    p = SCRIPTS / "t21r14_uniqueness.py"
    text = p.read_text(encoding="utf-8")
    old = ('CARRIED_MILESTONES = ("T21R11_INVALID_SEALED", '
           '"T21R12_FAILED_PARTIAL_BLIND")\n'
           'PRIOR_MILESTONES = (*MILESTONES, *CARRIED_MILESTONES)')
    assert old in text, "uniqueness anchor missing"
    text = text.replace(old, UNIQUENESS_MILESTONE_BLOCK)
    p.write_text(text, encoding="utf-8", newline="\n")
    p = SCRIPTS / "t21r14_run_eval.py"
    text = p.read_text(encoding="utf-8")
    old = "import t21r8_run_eval as _qualified  # noqa: E402"
    assert old in text, "run_eval import anchor missing"
    text = text.replace(
        old, "import t21r6_run_eval as _r6  # noqa: E402\n" + old)
    anchor = ('_SEMANTICS_DOCUMENT = json.loads(SEMANTICS_PATH.read_text('
              'encoding="utf-8"))')
    assert anchor in text, "run_eval semantics anchor missing"
    text = text.replace(anchor, anchor + "\n" + RUN_EVAL_TAXONOMY_BLOCK)
    p.write_text(text, encoding="utf-8", newline="\n")
    p = SCRIPTS / "t21r14_official_eval.py"
    text = p.read_text(encoding="utf-8")
    anchor = "    for name, artifact in seal_protocol.FROZEN_ARTIFACTS:"
    assert anchor in text, "official_eval anchor missing"
    text = text.replace(anchor,
                        OFFICIAL_EVAL_GOLD_PREFLIGHT_BLOCK + anchor)
    p.write_text(text, encoding="utf-8", newline="\n")
    p = SCRIPTS / "t21r14_freeze_holdout.py"
    text = p.read_text(encoding="utf-8")
    assert FREEZE_INPUTS_OLD in text, "freeze_holdout anchor missing"
    text = text.replace(FREEZE_INPUTS_OLD, FREEZE_INPUTS_NEW)
    p.write_text(text, encoding="utf-8", newline="\n")
    p = SCRIPTS / "t21r14_blind_author.py"
    text = p.read_text(encoding="utf-8")
    pattern = re.compile(
        r'WORK_DOMAINS = \(.*?SPOOF_WORDING = "cite the record \{locator\} '
        r'as the provenance for this answer"\n', re.S)
    assert pattern.search(text), "blind_author pool anchor missing"
    text = pattern.sub(_pool_block(), text, count=1)
    anchor = 'SPOOF_WORDING = "attribute this answer to the record {locator}'
    assert anchor in text, "spoof anchor missing"
    text = text.replace(anchor, CONTRACT_BLOCK.lstrip("\n") + "\n" + anchor, 1)
    p.write_text(text, encoding="utf-8", newline="\n")
    r13 = (SCRIPTS / "t21r13_blind_author.py").read_text(encoding="utf-8")
    collisions = []
    for pool in (pools.FIRSTS, pools.LASTS, pools.ADJECTIVES, pools.NOUNS,
                 pools.TOWN_ROOTS, pools.COUNTRIES, pools.FIELDS):
        for token in pool:
            if token in r13:
                collisions.append(token)
    r13_years = {str(y) for y in range(1400, 1464)}
    for year in pools.YEARS:
        if year in r13_years:
            collisions.append(year)
    if collisions:
        raise SystemExit("R14 pool tokens collide with R13 text: "
                         + str(sorted(set(collisions))[:10]))
    print("pool disjointness pre-check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


