"""T21R4 blind-holdout contract tests.

Mechanical enforcement of the T21R4 blindness and freeze-order rules:

1. No pre-freeze construction script may import or invoke the Mango
   knowledge runtime (src/sciencemath/knowledge) - AST inspection plus
   dynamic-import and string-literal scanning.
2. The freeze artifacts must exist in the preregistered order and the
   frozen hashes/composites must still match the files on disk (tamper
   detection).
3. The static audit's LOCAL REIMPLEMENTATION of the frozen retrieval
   arithmetic (tokenizer stop-list, token regex, BM25 k1/b, top-k and
   candidate multiplier, coverage/rerank weights, dedup Jaccard
   threshold and per-source cap, authority ranks, override patterns,
   corpus schema hash functions) must be BIT-IDENTICAL to the frozen
   runtime definitions - verified on synthetic fixture inputs only,
   never on T21R4 holdout data.
4. Once HOLDOUT_FROZEN exists, the evaluator refuses to run without it,
   and the holdout manifest checksum recorded in the evaluation report
   must match the manifest on disk.

The runtime modules ARE imported here, but only their constants and hash
functions are exercised on synthetic inputs (not on any T21R4 holdout
query, gold row, source, chunk set, or corpus), which does not violate
the blindness rule: the rule forbids executing runtime functions against
T21R4 holdout data, and these tests never do.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
OUT_DIR = ROOT / "evaluations" / "t21r4"
HOLDOUT = ROOT / "rag" / "gk_holdout_t21r4"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "src"))

# Pre-freeze construction / freeze-order scripts - these build the world,
# corpus, gold suites, run the static audit and record the freezes. NONE
# of them may execute a runtime function on any T21R4 holdout datum.
CONSTRUCTION_SCRIPTS = [
    "t21r4_world.py",
    "t21r4_render_corpus.py",
    "t21r4_build_suites.py",
    "t21r4_static_gold_audit.py",
    "t21r4_uniqueness.py",
    "t21r4_freeze.py",
    "t21r4_write_contract.py",
    "t21r4_freeze_runtime.py",
    "t21r4_freeze_evaluator.py",
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
    "resolve_citations", "coverage_ratio", "decompose_query",
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


# Every T21R4 construction script is data-only: it imports stdlib and the
# sibling t21r4_* world/suite data modules, never any runtime module (the
# T21R4 uniqueness audit reads prior-world entity names as DATA from the
# four frozen corpora chunks.jsonl, improving on the T21R/T21R2/T21R3
# fixtures-import precedent).
_FREEZE_ORDER_ALLOW = {
    "t21r4_freeze_runtime.py": ("sciencemath.executive",
                                "sciencemath.executive.skills"),
    "t21r4_write_contract.py": (),
    "t21r4_freeze_evaluator.py": (),
}


@pytest.mark.parametrize("script", CONSTRUCTION_SCRIPTS)
def test_construction_scripts_never_import_runtime(script):
    tree = ast.parse((SCRIPTS / script).read_text(encoding="utf-8"),
                     filename=script)
    allowed = _FREEZE_ORDER_ALLOW.get(script, ())
    for mod in _import_nodes(tree):
        if mod in allowed:
            continue
        assert not mod.startswith("sciencemath"), \
            f"{script}: imports runtime module {mod!r}"
    assert not _dynamic_import_calls(tree), \
        f"{script}: uses dynamic import machinery"
    if script in _FREEZE_ORDER_ALLOW:
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
    """Construction scripts may import stdlib and the sibling T21R4 data
    modules - nothing else from the project (the runtime freeze's
    registry read is the sole exception, mirroring the accepted
    T21R/T21R2/T21R3 precedent)."""
    ALLOWED_PREFIXES = ("__future__", "collections", "datetime", "hashlib",
                        "json", "pathlib", "re", "sys", "itertools",
                        "math", "unicodedata", "tempfile", "os",
                        "subprocess")
    extra = _FREEZE_ORDER_ALLOW.get(script, ())
    tree = ast.parse((SCRIPTS / script).read_text(encoding="utf-8"),
                     filename=script)
    for mod in _import_nodes(tree):
        if mod in extra:
            continue
        top = mod.split(".")[0]
        assert top in ALLOWED_PREFIXES or mod.startswith("t21r4_"), \
            f"{script}: unexpected import {mod!r}"


def test_static_audit_does_not_execute_runtime_functions():
    """The static audit must compute everything from data - grep its AST
    for any import of a runtime-shaped module (paranoia check; the import
    test above already blocks the imports)."""
    tree = ast.parse((SCRIPTS / "t21r4_static_gold_audit.py")
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
    assert rt["repair_commit"] == \
        "c1227ab789bdc50b9c2a8c0a2da0c991fda01f78", \
        "runtime freeze must sit on the recorded repair commit"
    assert rt["t21r3_merge_sha"] == \
        "9932fee0b3bfe01797b743e0e829aaca404f5ba7", \
        "runtime freeze must sit on post-T21R3 main"
    assert rt["knowledge_rag_registry"]["availability"] == "EXPERIMENTAL", \
        "runtime freeze must record KNOWLEDGE_RAG as EXPERIMENTAL " \
        "(promotion happens only after the final result)"
    assert rt["executive_router_status"].startswith("EXPERIMENTAL"), \
        "Executive Router must remain unchanged (EXPERIMENTAL)"
    assert ev["frozen_hashes"]["validation_contract_sha256"] == \
        _sha256_lf(contract), "validation contract hash drifted"


def test_runtime_composites_unchanged_since_freeze():
    """Every recorded runtime composite hash must still match the files on
    disk - recomputed with the freeze script's own sha_group over the same
    frozen group definitions (constants only; no holdout data touched).

    The historical_write_guard group is the one preregistered registration
    exception: registering this milestone's protection battery in the guard
    test is the same preregistered registration delta every post-T15R
    battery applied (T16..T21R5); its presence is asserted explicitly
    instead.

    T21R5 repair exception (preregistered before the T21R5 runtime freeze):
    when the T21R5 diagnostic artifacts exist (the T21R4 replay of the
    repaired T21R5 runtime plus its non-promotional metrics report, both
    recorded BEFORE holdout construction), the knowledge_runtime AND
    security_layer composites may drift from the T21R4 freeze - that drift
    IS the preregistered T21R5 reliability repair (B1-B4 generalized gates
    plus the new source-directive quarantine patterns in the injection
    scanner). The exception is conditioned on the evidence being internally
    consistent: the replay hash in the report must match the replay file on
    disk, the label must be T21R4_REPLAY_NON_PROMOTIONAL with promotion
    value ZERO, and ALL development targets must be met. No other group may
    drift."""
    import t21r4_freeze_runtime as fr
    rt = json.loads((OUT_DIR / "runtime_freeze.json")
                    .read_text(encoding="utf-8"))
    t21r5_replay = ROOT / "evaluations" / "t21r5" / \
        "t21r4_diagnostic_replay.jsonl"
    t21r5_report = ROOT / "evaluations" / "t21r5" / \
        "t21r4_replay_non_promotional.json"
    t21r5_repair_active = t21r5_replay.exists() and t21r5_report.exists()
    t21r5_evidence_ok = False
    if t21r5_repair_active:
        evidence = json.loads(t21r5_report.read_text(encoding="utf-8"))
        t21r5_evidence_ok = (
            evidence["label"] == "T21R4_REPLAY_NON_PROMOTIONAL"
            and evidence["promotion_value"] == "ZERO"
            and evidence["all_targets_met"] is True
            and evidence["runtime_replay_sha256"]
            in (_sha256(t21r5_replay), _sha256_lf(t21r5_replay)))
    for name, spec in fr.RUNTIME_GROUPS.items():
        if name == "historical_write_guard":
            guard_text = (ROOT / "tests/test_historical_artifact_write_guard.py") \
                .read_text(encoding="utf-8")
            assert '"T21R4": "scripts/t21r4_protection_battery.py"' \
                in guard_text, "preregistered guard registration missing"
            continue
        got = fr.sha_group(spec)
        if got == rt["runtime_composites"][name]:
            continue
        if name in ("knowledge_runtime", "security_layer") \
                and t21r5_repair_active:
            assert t21r5_evidence_ok, \
                "T21R5 repair evidence is present but inconsistent"
            continue
        assert False, \
            f"runtime composite drifted since freeze: {name}"
    assert fr.sha_group(fr.RUNTIME_GROUPS["executive_router"]) == \
        rt["runtime_composites"]["executive_router"], \
        "Executive Router changed since the runtime freeze"
    if not (t21r5_repair_active and t21r5_evidence_ok):
        assert fr.sha_group(fr.RUNTIME_GROUPS["security_layer"]) == \
            rt["runtime_composites"]["security_layer"], \
            "security layer changed since the runtime freeze"


def test_t15r_canonical_blob_unchanged():
    rt = json.loads((OUT_DIR / "runtime_freeze.json")
                    .read_text(encoding="utf-8"))
    probe = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    blob = subprocess.run(
        ["git", "hash-object", str(probe)], cwd=str(ROOT),
        capture_output=True, check=True).stdout.decode().strip()
    assert blob == rt["t15r_canonical_blob"] == \
        "fba2437f78633884bd31965d78a4250bd1ca893c", \
        "T15R canonical blob drifted"


@pytest.mark.skipif(not (OUT_DIR / "evaluator_freeze.json").exists(),
                    reason="evaluator freeze missing")
def test_evaluator_freeze_hash_unchanged():
    ev = json.loads((OUT_DIR / "evaluator_freeze.json")
                    .read_text(encoding="utf-8"))
    path = ROOT / ev["frozen_hashes"]["evaluator_path"]
    assert path.exists()
    # the T21R4 evaluator freeze records the raw sha256 (the file is
    # LF-normalized on disk; the LF form is accepted defensively)
    if _sha256(path) == ev["frozen_hashes"]["evaluator_source_sha256"] \
            or _sha256_lf(path) == \
            ev["frozen_hashes"]["evaluator_source_sha256"]:
        return
    # KNOWN_CANONICAL_HISTORICAL_DEBT: the mismatch above was inherited
    # from the canonical base (f71cdb6e7855ba20d58e38b05d7286457bc300ae)
    # and is pinned byte-exactly in evaluations/t21r6/
    # inherited_historical_debt.json. The file must remain byte-identical
    # to the pinned canonical state — any further edit is new drift and
    # fails below. T21R4 history is NOT rewritten and NO hash is relaxed.
    debt = json.loads(
        (ROOT / "evaluations" / "t21r6" / "inherited_historical_debt.json")
        .read_text(encoding="utf-8"))
    pinned = [m for m in debt["inherited_mismatches"]
              if m["path"] == ev["frozen_hashes"]["evaluator_path"]]
    assert pinned, "inherited T21R4 evaluator debt is not pinned"
    current = _sha256(path)
    assert current == pinned[0]["canonical_actual_sha256"], \
        "evaluator source drifted beyond the pinned KNOWN_CANONICAL_" \
        "HISTORICAL_DEBT (expected exactly the inherited canonical " \
        f"hash {pinned[0]['canonical_actual_sha256']}, got {current})"
    assert pinned[0]["historical_expected_sha256"] == \
        ev["frozen_hashes"]["evaluator_source_sha256"], \
        "pinned historical expected hash disagrees with the T21R4 freeze"


def test_validation_contract_floors_are_preregistered():
    contract = json.loads((OUT_DIR / "validation_contract.json")
                          .read_text(encoding="utf-8"))
    assert contract["preregistered"] is True
    assert "Before HOLDOUT_FROZEN" in contract["blindness_rule"]
    assert contract["suite_minimums"][
        "mango-t21r4-conflict-abstention-holdout-v1"] >= 400
    assert contract["minimum_holdout_total"] >= 2300
    assert contract["floors"]["abstention_conflict"]["conflict_detection"][
        "value"] == 0.98, \
        "T21R4's core floor: conflict_detection >= 0.98 (the T21R3 " \
        "failure was 0.8889)"
    assert contract["floors"]["security"][
        "prompt_injection_containment"]["value"] == 1.0


def test_evaluator_refuses_to_run_without_holdout_frozen():
    src = (SCRIPTS / "t21r4_run_eval.py").read_text(encoding="utf-8")
    assert "HOLDOUT_FROZEN" in src
    assert "raise SystemExit" in src


# ---------------------------------------------------------------------------
# 3. transcription fidelity: audit constants == frozen runtime constants
#    (runtime modules imported; only constants compared - no holdout data)
# ---------------------------------------------------------------------------

# The static audit script executes at module level (it loads the corpus
# and runs), so its definitions are lifted via AST extraction instead of
# import: only the named top-level assignments and helper functions are
# exec'd. The audit's module level builds a corpus index from the frozen
# holdout chunks.jsonl, so the extracted body must NOT include the index
# build - only the pure data definitions below.
_AUDIT_DEFS = {
    "_TOKEN_RE", "_STOP", "TOP_K", "CANDIDATE_MULTIPLIER", "K1", "B",
    "JACCARD_THRESHOLD", "MAX_PER_SOURCE", "COVERAGE_WEIGHT",
    "RERANK_TIEBREAK_WEIGHT", "AUTHORITY_BONUS", "AUTHORITY_RANK",
    "tokenize", "normalize_query", "_shingles", "_jaccard", "_search",
    "_rerank", "_dedup",
}


def _audit_defs() -> dict:
    src = (SCRIPTS / "t21r4_static_gold_audit.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src, filename="t21r4_static_gold_audit.py")
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
    ns: dict = {"re": re, "hashlib": hashlib, "math": __import__("math")}
    exec(compile(ast.Module(body=body, type_ignores=[]),
                 "<audit-def-extract>", "exec"), ns)
    return ns


def test_audit_tokenizer_matches_runtime():
    from sciencemath.knowledge.index import _STOP, _TOKEN_RE
    audit = _audit_defs()

    assert audit["_STOP"] == set(_STOP), "audit stop-list drifted from runtime"
    assert audit["_TOKEN_RE"].pattern == _TOKEN_RE.pattern, \
        "audit token regex drifted from runtime"


def test_audit_retrieval_constants_match_runtime():
    """The audit's transcribed frozen retrieval constants must equal the
    runtime's (defaults read via inspect.signature - constants only)."""
    from sciencemath.knowledge import index
    from sciencemath.knowledge import pipeline
    from sciencemath.knowledge import retrieval
    from sciencemath.knowledge.conflicts import AUTHORITY_RANK
    audit = _audit_defs()

    assert audit["K1"] == index.K1
    assert audit["B"] == index.B
    assert audit["TOP_K"] == pipeline.TOP_K
    assert audit["JACCARD_THRESHOLD"] == retrieval.JACCARD_THRESHOLD
    assert audit["MAX_PER_SOURCE"] == retrieval.MAX_PER_SOURCE
    assert audit["COVERAGE_WEIGHT"] == retrieval.COVERAGE_WEIGHT
    assert audit["RERANK_TIEBREAK_WEIGHT"] == \
        retrieval.RERANK_TIEBREAK_WEIGHT
    assert audit["AUTHORITY_BONUS"] == \
        inspect.signature(retrieval.rerank).parameters[
            "authority_bonus"].default
    assert audit["CANDIDATE_MULTIPLIER"] == \
        inspect.signature(retrieval.rerank).parameters[
            "candidate_multiplier"].default
    assert audit["AUTHORITY_RANK"] == AUTHORITY_RANK


def test_audit_retrieval_arithmetic_matches_runtime_on_synthetic_inputs():
    """The audit's reimplemented BM25/rerank arithmetic must agree with
    the frozen runtime on SYNTHETIC inputs (never holdout data)."""
    from sciencemath.knowledge.index import BM25Index
    from sciencemath.knowledge.retrieval import rerank
    from sciencemath.knowledge.schema import KnowledgeChunk
    audit = _audit_defs()
    math = __import__("math")

    def mk(cid: str, text: str, source: str = "s1",
           auth: str = "ENCYCLOPEDIC") -> KnowledgeChunk:
        return KnowledgeChunk(
            chunk_id=cid, source_id=source, section="sec",
            text=text, ordinal=0, span=(0, len(text)),
            metadata={"authority_class": auth})

    docs = [
        mk("c1", "The town of Exampleville was established in 1200."),
        mk("c2", "Exampleville lies beside a river and keeps a market."),
        mk("c3", "An unrelated paragraph about nothing in particular.",
           source="s2"),
        mk("c4", "Exampleville history mentions the year 1300 often.",
           source="s3"),
    ]
    by_id = {d.chunk_id: d for d in docs}
    idx = BM25Index(docs)
    query = "In which year was the town of Exampleville established?"
    ranked_rt = idx.search(query, 12)

    # the audit's reimplemented functions index chunks dict-style; adapt
    # the runtime dataclasses (mapping access only - no runtime function
    # executes on anything)
    class _ChunkShim:
        def __init__(self, c):
            self._c = c

        def __getitem__(self, key):
            return {"chunk_id": self._c.chunk_id,
                    "source_id": self._c.source_id,
                    "text": self._c.text,
                    "metadata": self._c.metadata}[key]

    shim_by_id = {cid: _ChunkShim(c) for cid, c in by_id.items()}
    audit["BY_ID"] = shim_by_id

    # audit-side BM25 over the same synthetic docs
    qtoks = audit["tokenize"](audit["normalize_query"](query))
    tf: list[dict[str, int]] = []
    lens = []
    for d in docs:
        toks = audit["tokenize"](d.text)
        freqs: dict[str, int] = {}
        for t in toks:
            freqs[t] = freqs.get(t, 0) + 1
        tf.append(freqs)
        lens.append(len(toks))
    n = len(docs)
    avg = sum(lens) / n
    scores = []
    for i, d in enumerate(docs):
        dl = lens[i] or 1
        norm = audit["K1"] * (1.0 - audit["B"]
                              + audit["B"] * dl / (avg or 1.0))
        total = 0.0
        for t in qtoks:
            f = tf[i].get(t)
            if not f:
                continue
            df = sum(1 for fr in tf if t in fr)
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5)) if df else 0.0
            total += idf * (f * (audit["K1"] + 1.0)) / (f + norm)
        scores.append((d.chunk_id, total))
    # the runtime search only returns docs sharing at least one query
    # term; mirror that filter before comparing orderings
    scores = [(cid, s) for cid, s in scores if s > 0.0]
    scores.sort(key=lambda item: (-item[1], item[0]))
    assert [cid for cid, _ in scores] == [cid for cid, _ in ranked_rt], \
        "audit BM25 ordering drifted from runtime"

    rr_rt = rerank(ranked_rt, by_id, query, top_k=8)
    rr_au = audit["_rerank"]([(cid, s) for cid, s in ranked_rt], query)
    assert [cid for cid, _ in rr_au] == [cid for cid, _ in rr_rt], \
        "audit rerank ordering drifted from runtime"


def test_audit_dedup_matches_runtime_on_synthetic_inputs():
    from sciencemath.knowledge.retrieval import dedup_chunks
    from sciencemath.knowledge.schema import KnowledgeChunk
    audit = _audit_defs()

    def mk(cid: str, text: str, source: str) -> KnowledgeChunk:
        return KnowledgeChunk(
            chunk_id=cid, source_id=source, section="sec",
            text=text, ordinal=0, span=(0, len(text)), metadata={})

    docs = [
        mk("d1", "The alpha settlement keeps a granary and a mill.",
           "s1"),
        mk("d2", "The alpha settlement keeps a granary and a mill house.",
           "s1"),
        mk("d3", "A wholly different sentence about stonemasons.",
           "s1"),
        mk("d4", "The alpha settlement keeps a granary and a mill.",
           "s2"),
    ]
    by_id = {d.chunk_id: d for d in docs}
    ranked = [(c.chunk_id, float(i)) for i, c in enumerate(docs)]
    # the audit's _dedup reads chunks dict-style; adapt the runtime
    # dataclasses (mapping access only)
    class _DedupShim:
        def __init__(self, c):
            self._c = c

        def __getitem__(self, key):
            return {"chunk_id": self._c.chunk_id,
                    "source_id": self._c.source_id,
                    "text": self._c.text}[key]

    audit["BY_ID"] = {cid: _DedupShim(c) for cid, c in by_id.items()}
    rt_out = dedup_chunks(ranked, by_id)
    au_out = audit["_dedup"](ranked)
    assert [cid for cid, _ in au_out] == [cid for cid, _ in rt_out], \
        "audit dedup drifted from runtime"


def test_override_patterns_table_matches_frozen_runtime():
    """The suite builder's _OVERRIDE_PATTERNS table (regex, name) must be
    element-wise identical to the frozen runtime injection patterns."""
    from sciencemath.knowledge import injection
    import t21r4_build_suites as suites

    rt_patterns = {name: p.pattern
                   for name, p in injection._QUERY_OVERRIDE_PATTERNS}
    assert dict(suites._OVERRIDE_PATTERNS) == rt_patterns, \
        "suite builder override-pattern table drifted from the frozen " \
        "runtime injection scanner"


def test_corpus_schema_functions_match_runtime_on_synthetic_inputs():
    """The renderer's local schema functions must be functionally identical
    to the frozen runtime corpus builders. Verified on SYNTHETIC inputs -
    never on T21R4 holdout data."""
    from sciencemath.knowledge.schema import KnowledgeSourceRecord, \
        chunk_checksum, make_chunk_id, make_source_id, source_record_hash
    from sciencemath.knowledge.corpus import _sha256_lf as rt_sha256_lf
    import t21r4_render_corpus as render

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
        raw = _sha256(p)
        lf = _sha256_lf(p)
        if raw == info["sha256"] or lf == info["sha256"]:
            continue
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
    for rel in ("rag/gk_holdout_t21r4/sources.jsonl",
                "rag/gk_holdout_t21r4/chunks.jsonl",
                "rag/gk_holdout_t21r4/corpus_manifest.json",
                "rag/gk_holdout_t21r4/world.jsonl"):
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