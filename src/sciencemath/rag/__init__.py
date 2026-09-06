"""Wikipedia-backed scientific retrieval (implemented in T5).

Public surface:
  SourceRegistry     — deny-by-default license gate (rag/source_registry.py)
  taxonomy           — canonical science domain taxonomy (rag/taxonomy.py)
  SciDocument        — normalized chunk schema (rag/schema.py)
  clean_document     — conservative scientific cleaning (rag/cleaning.py)
  chunk_document     — semantic chunking (rag/chunking.py)
  EmbeddingSpec      — embedding candidates (rag/embeddings.py)
  VectorStore        — FAISS/numpy backends (rag/vectorstore.py)
  Retriever          — retrieval pipeline (rag/retriever.py)
  classify_route     — MATH/SCIENCE/MIXED/GENERAL routing (rag/route.py)
  EvidenceContract   — answer/evidence representation (rag/evidence.py)
  citations          — provenance enforcement (rag/citations.py)
  RetrievalAuditLogger — audit logging (rag/audit.py)
"""
from sciencemath.rag.audit import RetrievalAuditLogger
from sciencemath.rag.citations import Citation, CitationReport, verify_citation
from sciencemath.rag.chunking import chunk_document
from sciencemath.rag.cleaning import clean_document
from sciencemath.rag.evidence import EvidenceContract, EvidenceSource
from sciencemath.rag.retriever import Retriever, RetrievalConfig, RetrievalResult
from sciencemath.rag.route import classify_route, ROUTES
from sciencemath.rag.schema import SciDocument, normalize_record
from sciencemath.rag.source_registry import (
    LicenseGateError, SourceRegistry, SourceRegistryError, default_registry)
from sciencemath.rag.taxonomy import (
    SCIENCE_TAXONOMY, classify_domain, normalize_domain)

__all__ = [
    "RetrievalAuditLogger", "Citation", "CitationReport", "verify_citation",
    "EvidenceContract", "EvidenceSource", "Retriever", "RetrievalConfig",
    "RetrievalResult", "classify_route", "ROUTES", "SciDocument",
    "normalize_record", "LicenseGateError", "SourceRegistry",
    "SourceRegistryError", "default_registry", "SCIENCE_TAXONOMY",
    "classify_domain", "normalize_domain",
]