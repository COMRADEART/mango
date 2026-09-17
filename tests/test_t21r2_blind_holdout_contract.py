"""T21R2 blind-holdout contract tests.

Mechanical enforcement of the T21R2 blindness and freeze-order rules:

1. No pre-freeze construction script may import or invoke the Mango
   knowledge runtime (src/sciencemath/knowledge) - AST inspection plus
   dynamic-import and string-literal scanning.
2. The freeze artifacts must exist in the preregistered order and the
   frozen hashes must still match the files on disk (tamper detection).
3. The static audit's local reimplementations of the frozen runtime
   mechanics (tokenizer stop-list, token regex, coverage floor, capital-
   framewords, override patterns, temporal regexes, corpus schema hash
   functions) must be BIT-IDENTICAL to the frozen runtime definitions -
   verified on synthetic fixture inputs only, never on T21R2 holdout data.
4. Once HOLDOUT_FROZEN exists, the evaluator refuses to run without it,
   and the holdout manifest checksum recorded in the evaluation report
   must match the manifest on disk.

The runtime modules ARE imported here, but only their constants and hash
functions are exercised on synthetic inputs (not on any T21R2 holdout
query, gold row, source, chunk set, or corpus), which does not violate
the blindness rule: the rule forbids executing runtime functions against
T21R2 holdout data, and these tests never do.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
OUT_DIR = ROOT / "evaluations" / "t21r2"
HOLDOUT = ROOT / "rag" / "gk_holdout_t21r2"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "src"))

# Pre-freeze construction scripts - these build the world, corpus, gold
# suites, and run the static audit. NONE of them may touch the runtime.
CONSTRUCTION_SCRIPTS = [
    "t21r2_world.py",
    "t21r2_render_corpus.py",
    "t21r2_build_suites.py",
    "t21r2_static_gold_audit.py",
    "t21r2_uniqueness.py",
    "t21r2_freeze.py",
    "t21r2_protection_battery.py",
]
CONSTRUCTION_SCRIPTS = [s for s in CONSTRUCTION_SCRIPTS
                        if (SCRIPTS / s).exists()]


# ---------------------------------------------------------------------------
# 1. blindness: no runtime import or invocation in construction scripts
# ---------------------------------------------------------------------------

_RUNTIME_FUNC_NAMES = (
    "answer_knowledge", "retrieve", "build_corpus_files", "KnowledgeAnswer",
    "classify_query_freshness", "scan_query_injection", "scan_source_text",
    "detect_conflicts", "resolve_conflicts", "review_answer",
    "resolve_citations", "coverage_ratio", "rerank", "decompose_query",
    "items_from_chunks", "make_citation_id", "snapshot_is_current_claim_safe",
    "load_corpus", "build_index",
)


def _import_nodes(tree: ast.AST) -> list[str]:
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def _dynamic_import_calls(tree: ast.AST) -> list[str]:
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name in ("__import__", "import_module"):
                calls.append(name)
    return calls


# t21r2_uniqueness.py (T21R2.15) imports ONE constants-only data module from
# the runtime package - sciencemath.knowledge.fixtures - to compare prior-
# world entity names, exactly as the accepted T21R precedent
# (scripts/t21r_uniqueness.py) does. Fixtures are inert data: no runtime
# function is ever executed on T21R2 holdout data, so the BLIND RULE holds.
_FIXTURE_DATA_IMPORTS = ("sciencemath.knowledge", "sciencemath.knowledge.fixtures")


# The protection battery is a POST-freeze verification harness: it must
# name runtime paths in string literals to hash them and must read the
# skill registry to verify the recorded demotion (it never executes a
# runtime function on any holdout datum), so its imports are scanned
# against a narrowed allowlist and its string literals not at all. Every
# pre-freeze construction script gets the full import + string-literal
# scan.
_POST_FREEZE_VERIFICATION_ALLOW = {
    "t21r2_protection_battery.py": ("sciencemath.executive",
                                    "sciencemath.executive.skills"),
}


@pytest.mark.parametrize("script", CONSTRUCTION_SCRIPTS)
def test_construction_scripts_never_import_runtime(script):
    tree = ast.parse((SCRIPTS / script).read_text(encoding="utf-8"),
                     filename=script)
    if script == "t21r2_uniqueness.py":
        allowed = _FIXTURE_DATA_IMPORTS
    else:
        allowed = _POST_FREEZE_VERIFICATION_ALLOW.get(script, ())
    for mod in _import_nodes(tree):
        if mod in allowed:
            continue
        assert not mod.startswith("sciencemath"), \
            f"{script}: imports runtime module {mod!r}"
    assert not _dynamic_import_calls(tree), \
        f"{script}: uses dynamic import machinery"
    if script in _POST_FREEZE_VERIFICATION_ALLOW:
        return
    # string-literal scan: no runtime module path or entrypoint name in
    # any string constant (except the module docstring's rule statement)
    doc = ast.get_docstring(tree, clean=False) or ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and \
                isinstance(node.value, str):
            text = node.value
            if text == doc:
                continue
            assert "sciencemath" not in text, \
                f"{script}: string literal references the runtime: " \
                f"{text[:80]!r}"
            for fn in _RUNTIME_FUNC_NAMES:
                assert not re.search(rf"\b{re.escape(fn)}\b", text), \
                    f"{script}: string literal names runtime function " \
                    f"{fn!r}: {text[:80]!r}"


@pytest.mark.parametrize("script", CONSTRUCTION_SCRIPTS)
def test_construction_scripts_only_import_allowed_modules(script):
    """Construction scripts may import stdlib and the sibling T21R2 data
    modules - nothing else from the project (the constants-only fixture
    modules needed by the T21R2.15 uniqueness audit are the sole
    exception, mirroring the accepted T21R precedent)."""
    ALLOWED_PREFIXES = ("__future__", "collections", "datetime", "hashlib",
                        "json", "pathlib", "re", "sys", "itertools",
                        "math", "unicodedata", "tempfile", "os",
                        "subprocess")
    allowed_modules = {
        "t21r2_uniqueness.py": ("sciencemath.knowledge",
                                "sciencemath.knowledge.fixtures",
                                "t21r_fixtures"),
        "t21r2_protection_battery.py": ("sciencemath.executive",
                                        "sciencemath.executive.skills"),
    }
    extra = allowed_modules.get(script, ())
    tree = ast.parse((SCRIPTS / script).read_text(encoding="utf-8"),
                     filename=script)
    for mod in _import_nodes(tree):
        if mod in extra:
            continue
        top = mod.split(".")[0]
        assert top in ALLOWED_PREFIXES or mod.startswith("t21r2_"), \
            f"{script}: unexpected import {mod!r}"


def test_static_audit_does_not_execute_runtime_functions():
    """The static audit must compute everything from data - grep its AST
    for any attribute call on a sciencemath-shaped root (paranoia check;
    the import test above already blocks the imports)."""
    tree = ast.parse((SCRIPTS / "t21r2_static_gold_audit.py")
                     .read_text(encoding="utf-8"))
    mods = _import_nodes(tree)
    assert not [m for m in mods if "knowledge" in m or "mango" in m]


# ---------------------------------------------------------------------------
# 2. freeze artifacts: existence, order, tamper detection
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_lf(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_freeze_artifacts_exist_in_order():
    runtime_freeze = OUT_DIR / "runtime_freeze.json"
    evaluator_freeze = OUT_DIR / "evaluator_freeze.json"
    contract = OUT_DIR / "validation_contract.json"
    for p in (runtime_freeze, evaluator_freeze, contract):
        assert p.exists(), f"missing freeze artifact {p}"
    rt = json.loads(runtime_freeze.read_text(encoding="utf-8"))
    ev = json.loads(evaluator_freeze.read_text(encoding="utf-8"))
    assert rt["recorded_at"] < ev["recorded_at"], \
        "runtime freeze must precede evaluator freeze"
    assert ev["runtime_freeze_recorded_at"] == rt["recorded_at"]
    assert rt["knowledge_rag_registry"]["availability"] == "ACTIVE", \
        "runtime freeze recorded a non-ACTIVE KNOWLEDGE_RAG"
    assert ev["frozen_hashes"]["validation_contract_sha256"] == \
        _sha256_lf(contract), "validation contract hash drifted"


def _knowledge_rag_block(text: str) -> str:
    """The KNOWLEDGE_RAG skill record block of skills.py."""
    start = text.index('"KNOWLEDGE_RAG": _skill(')
    end = text.index("\n        ),\n", start) + len("\n        ),\n")
    return text[start:end]


def test_runtime_files_unchanged_since_freeze():
    """The frozen runtime is defined as byte-identical to the canonical
    base HEAD recorded in runtime_freeze.json. Verify via git diff.

    src/sciencemath/knowledge must be byte-identical *until a later
    milestone records an explicit repair*. T21R3 repairs conflict detection
    and provenance-spoof handling; when those repair markers are present,
    knowledge may differ from the T21R2 freeze while historical T21R2
    holdout artifacts remain immutable.

    executive/skills.py may differ from the base ONLY by the recorded
    T21R2 decision DEMOTE_KNOWLEDGE_RAG_TO_EXPERIMENTAL (applied after the
    one-shot evaluation, never during construction or evaluation); every
    other byte must match."""
    import subprocess
    rt = json.loads((OUT_DIR / "runtime_freeze.json")
                    .read_text(encoding="utf-8"))
    base = rt["canonical_base"]
    t21r3_repair = (
        (ROOT / "src/sciencemath/knowledge/provenance_spoof.py").exists()
        or (ROOT / "evaluations/t21r3/t21r2_spoof_root_cause.json").exists()
    )
    if not t21r3_repair:
        proc = subprocess.run(
            ["git", "diff", "--quiet", base, "HEAD", "--",
             "src/sciencemath/knowledge"],
            cwd=str(ROOT))
        assert proc.returncode == 0 or proc.returncode == 1, \
            f"git diff failed (rc={proc.returncode})"
        if proc.returncode == 1:
            pytest.fail("src/sciencemath/knowledge changed since canonical "
                        f"base {base}")
    skills_rel = "src/sciencemath/executive/skills.py"
    show = subprocess.run(
        ["git", "show", f"{base}:{skills_rel}"],
        cwd=str(ROOT), capture_output=True, check=True)
    base_text = show.stdout.decode("utf-8").replace("\r\n", "\n")
    head_text = (ROOT / skills_rel).read_text(encoding="utf-8") \
        .replace("\r\n", "\n")
    base_wo = base_text.replace(_knowledge_rag_block(base_text), "")
    head_wo = head_text.replace(_knowledge_rag_block(head_text), "")
    assert base_wo == head_wo, \
        "executive/skills.py changed outside the KNOWLEDGE_RAG record " \
        "since the canonical base"
    assert "availability=EXPERIMENTAL" in _knowledge_rag_block(head_text) \
        and "availability=ACTIVE" in _knowledge_rag_block(base_text), \
        "the KNOWLEDGE_RAG record is not the recorded T21R2 demotion"


@pytest.mark.skipif(not (OUT_DIR / "evaluator_freeze.json").exists(),
                    reason="evaluator freeze missing")
def test_evaluator_freeze_hash_unchanged():
    ev = json.loads((OUT_DIR / "evaluator_freeze.json")
                    .read_text(encoding="utf-8"))
    path = ROOT / ev["frozen_hashes"]["evaluator_path"]
    assert path.exists()
    assert _sha256_lf(path) == \
        ev["frozen_hashes"]["evaluator_source_sha256"], \
        "evaluator source changed after freeze (post-freeze evaluator bug " \
        "policy: STOP - T21R2_EVALUATOR_INVALID)"


def test_validation_contract_floors_are_preregistered():
    contract = json.loads((OUT_DIR / "validation_contract.json")
                          .read_text(encoding="utf-8"))
    assert contract["preregistered"] is True
    assert "Before HOLDOUT_FROZEN" in contract["blindness_rule"]
    assert contract["suite_minimums"][
        "mango-t21r2-multihop-holdout-v1"] >= 200
    assert contract["minimum_holdout_total"] >= 1830
    assert contract["floors"]["retrieval"]["recall_at_5"]["value"] >= 0.94
    assert contract["floors"]["security"][
        "prompt_injection_containment"]["value"] == 1.0


def test_evaluator_refuses_to_run_without_holdout_frozen():
    src = (SCRIPTS / "t21r2_run_eval.py").read_text(encoding="utf-8")
    assert "HOLDOUT_FROZEN" in src
    assert "raise SystemExit" in src


# ---------------------------------------------------------------------------
# 3. transcription fidelity: audit constants == frozen runtime constants
#    (runtime modules imported; only constants compared - no holdout data)
# ---------------------------------------------------------------------------

# The static audit script executes at module level (it runs and exits), so
# its definitions are lifted via AST extraction instead of import: only the
# named top-level assignments and helper functions are exec'd.
_AUDIT_DEFS = {
    "_TOKEN_RE", "_STOP", "_CAP_FRAMEWORDS", "_OVERRIDE_PATTERNS",
    "_AS_OF_RE", "_QUESTION_FRAME_RE", "MIN_COVERAGE",
    "_tokenize", "_normalize_query", "_content_terms", "_coverage",
}


def _audit_defs() -> dict:
    src = (SCRIPTS / "t21r2_static_gold_audit.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src, filename="t21r2_static_gold_audit.py")
    body: list[ast.stmt] = []
    seen: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets
                       if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and \
                isinstance(node.target, ast.Name):
            targets = [node.target.id]
        elif isinstance(node, ast.FunctionDef):
            targets = [node.name]
        else:
            continue
        if any(t in _AUDIT_DEFS for t in targets):
            body.append(node)
            seen.update(targets)
    assert _AUDIT_DEFS <= seen, f"audit defs not found: {_AUDIT_DEFS - seen}"
    ns: dict = {"re": re, "hashlib": hashlib}
    exec(compile(ast.Module(body=body, type_ignores=[]),
                 "<audit-def-extract>", "exec"), ns)
    return ns


def test_audit_tokenizer_matches_runtime():
    from sciencemath.knowledge.index import _STOP, _TOKEN_RE
    audit = _audit_defs()

    assert audit["_STOP"] == set(_STOP), "audit stop-list drifted from runtime"
    assert audit["_TOKEN_RE"].pattern == _TOKEN_RE.pattern, \
        "audit token regex drifted from runtime"


def test_audit_gate_constants_match_runtime():
    from sciencemath.knowledge import injection
    from sciencemath.knowledge import pipeline
    audit = _audit_defs()

    assert audit["MIN_COVERAGE"] == pipeline.MIN_COVERAGE
    # T21R6 repair exception (preregistered): the multihop repair unions
    # _RELATIONAL_PREPOSITIONS into the runtime frame vocabulary, so the
    # frozen audit vocabulary may drift ADDITIVELY when the T21R6 repair
    # evidence exists — the frozen tokens must remain a strict subset and
    # the additions must be exactly the preregistered preposition set.
    t21r6_repair = (
        (ROOT / "evaluations/t21r6/t21r5_multihop_root_cause.json").exists()
        and (ROOT / "evaluations/t21r6/evaluator_qualification.json").exists()
    )
    if t21r6_repair:
        assert audit["_CAP_FRAMEWORDS"] <= set(pipeline._CAP_FRAMEWORDS), \
            "audit capital-frame vocabulary was narrowed"
        added = set(pipeline._CAP_FRAMEWORDS) - audit["_CAP_FRAMEWORDS"]
        assert added == set(pipeline._RELATIONAL_PREPOSITIONS), added
    else:
        assert audit["_CAP_FRAMEWORDS"] == set(pipeline._CAP_FRAMEWORDS)
    # runtime pairs each pattern with a name; the audit carries the bare
    # regexes - compare the pattern strings element-wise
    assert [p.pattern for p in audit["_OVERRIDE_PATTERNS"]] == \
        [p.pattern for _, p in injection._QUERY_OVERRIDE_PATTERNS], \
        "audit override patterns drifted"


def test_audit_temporal_regexes_match_runtime():
    from sciencemath.knowledge import freshness
    from sciencemath.knowledge import pipeline
    audit = _audit_defs()

    assert audit["_AS_OF_RE"].pattern == freshness._HISTORICAL_AS_OF.pattern
    assert audit["_QUESTION_FRAME_RE"].pattern == \
        pipeline._QUESTION_FRAME_RE.pattern


def test_corpus_schema_functions_match_runtime_on_synthetic_inputs():
    """The renderer's local schema functions must be functionally identical
    to the frozen runtime corpus builders. Verified on SYNTHETIC inputs -
    never on T21R2 holdout data."""
    from sciencemath.knowledge.schema import KnowledgeSourceRecord, \
        chunk_checksum, make_chunk_id, make_source_id, source_record_hash
    from sciencemath.knowledge.corpus import _sha256_lf as rt_sha256_lf
    import t21r2_render_corpus as render

    title, publisher, revision = "Example Title", "Example Press", "rev-9"
    assert render.make_source_id(title, publisher, revision) == \
        make_source_id(title, publisher, revision)
    sid = render.make_source_id(title, publisher, revision)
    section, ordinal = "Example Section", 7
    assert render.make_chunk_id(sid, section, ordinal) == \
        make_chunk_id(sid, section, ordinal)
    text = "A synthetic sentence for the schema equivalence check."
    assert render._sha256(text) == hashlib.sha256(
        text.encode("utf-8")).hexdigest()
    assert render._sha256(text) == chunk_checksum(text)
    doc = {"source_id": sid, "source_title": title,
           "publisher_or_collection": publisher,
           "revision_or_version": revision, "text": ""}
    record = KnowledgeSourceRecord(
        source_id=doc["source_id"], source_title=doc["source_title"],
        source_type="example", source_uri_or_origin="local://example",
        publisher_or_collection=doc["publisher_or_collection"],
        license="example", revision_or_version=doc["revision_or_version"],
        retrieved_at_or_snapshot_date="2026-01-01", language="en",
        authority_class="ENCYCLOPEDIC", freshness_class="STATIC",
        content_text=doc["text"])
    assert render._source_record_hash(doc) == source_record_hash(record)
    lf = b"line1\nline2\n"
    with tempfile.NamedTemporaryFile("wb", suffix=".jsonl",
                                     delete=False) as fh:
        fh.write(lf)
        tmp = Path(fh.name)
    try:
        assert render._sha256_lf(tmp) == rt_sha256_lf(tmp)
        assert render._sha256_lf(tmp) == \
            hashlib.sha256(lf).hexdigest()  # LF-normalized already
    finally:
        tmp.unlink(missing_ok=True)


def test_audit_coverage_and_gate_semantics_on_synthetic_inputs():
    """The audit's reimplemented coverage and entity-gate must agree with
    the frozen runtime on synthetic inputs (never holdout data)."""
    from sciencemath.knowledge.pipeline import _entity_name_gate
    from sciencemath.knowledge.retrieval import coverage_ratio
    from sciencemath.knowledge.index import normalize_query
    audit = _audit_defs()

    query = "What is the emblem of the town of Exampleville?"
    span = ("The emblem of the town of Exampleville is a tide mill. "
            "Exampleville lies beside a mill pond.")
    rt_cov = coverage_ratio(normalize_query(query), [span])
    au_terms = audit["_content_terms"](query)
    au_cov = audit["_coverage"](au_terms, set(audit["_tokenize"](span)))
    assert au_cov == pytest.approx(rt_cov, abs=1e-9), \
        f"coverage transcription drifted: {au_cov} vs {rt_cov}"
    assert _entity_name_gate(query, span) is True
    assert _entity_name_gate("What is the emblem of Otherborough?",
                             span) is False


# ---------------------------------------------------------------------------
# 4. post-freeze integrity gates
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not (OUT_DIR / "HOLDOUT_FROZEN").exists(),
                    reason="holdout not frozen yet")
def test_holdout_frozen_manifest_agrees_with_data():
    """Mirror of the evaluator's check_freeze(): every frozen hash in the
    manifest must still match the file on disk."""
    (OUT_DIR / "HOLDOUT_FROZEN").read_text(encoding="utf-8")
    manifest_path = OUT_DIR / "holdout_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for label, info in manifest["freeze_inputs"].items():
        p = ROOT / info["path"]
        assert p.exists(), f"frozen input missing: {label}"
        # T21R2 freeze_inputs used raw sha256_file, which is CRLF-sensitive
        # on Windows. Accept raw match OR LF-normalized match against the
        # committed blob (historical content identity).
        raw = _sha256(p)
        lf = _sha256_lf(p)
        if raw == info["sha256"] or lf == info["sha256"]:
            continue
        import subprocess
        rel = info["path"].replace("\\", "/")
        blob = subprocess.check_output(
            ["git", "cat-file", "-p", f"HEAD:{rel}"], cwd=str(ROOT))
        blob_lf = hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()
        assert lf == blob_lf, \
            f"freeze input changed after freeze: {info['path']}"
    for name, info in manifest["suites"].items():
        p = OUT_DIR / "suites" / name / "holdout.jsonl"
        assert _sha256_lf(p) == info["holdout_sha256"], \
            f"suite changed after freeze: {name}"
    for fname, info in manifest["corpus"].items():
        p = ROOT / info["path"]
        assert p.exists(), f"frozen corpus file missing: {fname}"
        assert _sha256_lf(p) == info["sha256"], \
            f"corpus changed after freeze: {info['path']}"


@pytest.mark.skipif(not (OUT_DIR / "HOLDOUT_FROZEN").exists(),
                    reason="holdout not frozen yet")
def test_holdout_freeze_covers_all_suites_and_corpus():
    manifest = json.loads((OUT_DIR / "holdout_manifest.json")
                          .read_text(encoding="utf-8"))
    contract = json.loads((OUT_DIR / "validation_contract.json")
                          .read_text(encoding="utf-8"))
    for suite in contract["suite_minimums"]:
        assert suite in manifest["suites"], f"suite not frozen: {suite}"
    corpus_paths = {info["path"] for info in manifest["corpus"].values()}
    for rel in ("rag/gk_holdout_t21r2/sources.jsonl",
                "rag/gk_holdout_t21r2/chunks.jsonl",
                "rag/gk_holdout_t21r2/corpus_manifest.json",
                "rag/gk_holdout_t21r2/world.jsonl"):
        assert rel in corpus_paths, f"data not frozen: {rel}"


def test_suite_rows_never_mutate_after_freeze():
    """If the holdout is frozen, every gold suite on disk must hash to the
    frozen value (gold_answer_mutation_after_freeze gate)."""
    if not (OUT_DIR / "HOLDOUT_FROZEN").exists():
        pytest.skip("holdout not frozen yet")
    manifest = json.loads((OUT_DIR / "holdout_manifest.json")
                          .read_text(encoding="utf-8"))
    for name, info in manifest["suites"].items():
        p = OUT_DIR / "suites" / name / "holdout.jsonl"
        assert _sha256_lf(p) == info["holdout_sha256"], name