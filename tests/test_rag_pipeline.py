"""T5 pipeline integration tests — answer_question over a fake model +
fake embedder. Verifies route-conditional wiring end to end:

  * MATH route NEVER retrieves (T5.22) even when a retriever is supplied
  * SCIENCE route injects evidence and builds the evidence contract
  * no-chunks SCIENCE route uses the explicit uncertainty instruction
  * prompt_override (no-RAG arm) uses the exact prompt verbatim
  * citations parsed from model output are verified against seen chunks
  * audit records written for every attempt (T5.24)
"""
from __future__ import annotations

import hashlib
import json
import re

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from sciencemath.rag.audit import RetrievalAuditLogger
from sciencemath.rag.pipeline import (NO_EVIDENCE_INSTRUCTION,
                                      SCIENCE_EVIDENCE_INSTRUCTION,
                                      answer_question, build_prompt)
from sciencemath.rag.retriever import RetrievalConfig, Retriever
from sciencemath.rag.vectorstore import BruteForceVectorStore

DIM = 4096


def _vec(text: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
        v[h % DIM] += 1.0
    n = float(np.linalg.norm(v))
    return v / n if n else v


CHUNKS = {
    "wiki-1:ribosome:0": {
        "chunk_id": "wiki-1:ribosome:0", "source_id": "wikipedia_en",
        "title": "Ribosome", "domain": "biology",
        "text": "Ribosomes carry out protein synthesis by translating "
                "messenger RNA into polypeptide chains."},
    "wiki-2:algebra:0": {
        "chunk_id": "wiki-2:algebra:0", "source_id": "wikipedia_en",
        "title": "Algebra", "domain": "mathematics",
        "text": "Algebra studies equations and their solutions."},
}


class FakeSpec:
    model = "fake-embedder"
    revision = "test"
    license = "test"


class FakeEmbedder:
    spec = FakeSpec()

    def embed_query(self, q):
        return _vec(q)

    def embed_passages(self, texts):
        return np.vstack([_vec(t) for t in texts])


CANNED_SCIENCE = ("Ribosomes carry out protein synthesis "
                  "[wiki-1:ribosome:0].\n\\boxed{ribosomes}")


class FakeTokenizer:
    pad_token_id = 0
    eos_token_id = 1

    def __init__(self):
        self.last_text = ""

    def apply_chat_template(self, messages, tokenize=False,
                            add_generation_prompt=True, **kw):
        return messages[0]["content"]

    def __call__(self, text, return_tensors="pt", **kw):
        self.last_text = text
        n = min(128, max(8, len(text.split())))
        ids = torch.arange(n)[None, :]
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}

    def decode(self, ids, skip_special_tokens=True):
        return CANNED_SCIENCE


class FakeModel:
    device = "cpu"

    def generate(self, **kwargs):
        n_in = kwargs["input_ids"].shape[1]
        return torch.zeros((1, n_in + 4), dtype=torch.long)


def _retriever() -> Retriever:
    store = BruteForceVectorStore(DIM)
    vecs = np.vstack([_vec(c["text"]) for c in CHUNKS.values()])
    store.add(vecs, list(CHUNKS))
    return Retriever(store=store, chunk_by_id=dict(CHUNKS),
                     embedder=FakeEmbedder(),
                     config=RetrievalConfig(top_k=4, top_n=2,
                                            similarity_threshold=0.05))


@pytest.fixture()
def tok():
    return FakeTokenizer()


@pytest.fixture()
def mdl():
    return FakeModel()


# ---------------------------------------------------------------------------

def test_math_route_never_retrieves(mdl, tok, tmp_path):
    """T5.22: 'Solve 3x + 5 = 20' must not retrieve, even with a live
    retriever attached."""
    audit = RetrievalAuditLogger(tmp_path / "audit.jsonl")
    ans = answer_question(
        model=mdl, tokenizer=tok, question="Solve 3x + 5 = 20",
        question_id="t-math", retriever=_retriever(), audit_logger=audit)
    assert ans.route["route"] == "MATH"
    assert ans.retrieval is None
    assert "TOOL PROTOCOL" in tok.last_text.upper() or \
        "tool" in tok.last_text.lower()
    rec = json.loads((tmp_path / "audit.jsonl").read_text(
        encoding="utf-8").strip())
    assert rec["retrieval_used"] is False
    assert rec["retrieved_chunk_ids"] == []


def test_science_route_uses_evidence(mdl, tok, tmp_path):
    audit = RetrievalAuditLogger(tmp_path / "audit.jsonl")
    ans = answer_question(
        model=mdl, tokenizer=tok,
        question="What do ribosomes do in the cell?",
        question_id="t-sci", retriever=_retriever(), audit_logger=audit)
    assert ans.route["route"] == "SCIENCE"
    assert ans.retrieval is not None and ans.retrieval.used_retrieval
    assert "wiki-1:ribosome:0" in tok.last_text       # evidence block present
    assert ans.contract.used_retrieval is True
    assert ans.contract.sources
    # citation parsed from canned output and verifiable against seen chunks
    assert ans.citations
    assert ans.citations[0].chunk_id == "wiki-1:ribosome:0"
    rec = json.loads((tmp_path / "audit.jsonl").read_text(
        encoding="utf-8").strip())
    assert rec["retrieval_used"] is True
    assert "wiki-1:ribosome:0" in rec["selected_context_ids"]
    assert rec["final_source_ids"]


def test_science_route_without_chunks_reports_uncertainty(mdl, tok,
                                                          tmp_path):
    ans = answer_question(
        model=mdl, tokenizer=tok,
        question="Why do earthquakes occur in subduction zones?",
        question_id="t-unc", retriever=_retriever())
    assert ans.route["route"] == "SCIENCE"
    assert NO_EVIDENCE_INSTRUCTION in tok.last_text
    assert ans.contract.evidence_state == "INSUFFICIENT_EVIDENCE"


def test_prompt_override_bypasses_retrieval(mdl, tok):
    override = build_prompt("What is 2+2?", "GENERAL", None)
    ans = answer_question(
        model=mdl, tokenizer=tok, question="What is 2+2?",
        question_id="t-ovr", retriever=_retriever(),
        prompt_override=override)
    assert ans.retrieval is None
    assert tok.last_text == override
    assert ans.contract.evidence_state == "INSUFFICIENT_EVIDENCE"


def test_error_in_generation_is_contained(mdl, tok):
    class Boom(FakeModel):
        def generate(self, **kwargs):
            raise RuntimeError("gpu gone")

    ans = answer_question(model=Boom(), tokenizer=tok,
                          question="What is a ribosome?",
                          question_id="t-err", retriever=_retriever())
    assert ans.error and "gpu gone" in ans.error
    assert ans.raw_model_output == ""