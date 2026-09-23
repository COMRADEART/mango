"""T23 production router/capability provider; no answer or route shim.

The router remains the qualified, byte-frozen implementation. Each selected
non-terminal capability calls its own runtime. Deployment dependencies (model,
web source, specialist adapters) must be explicit; absence fails closed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from sciencemath.executive.router_v2 import INPUT_FIELDS, route_request
from sciencemath.knowledge.corpus import load_corpus
from sciencemath.knowledge.pipeline import answer_knowledge

PROVIDER_ID = "t23_protocol.provider:ProductionRouterProvider"
NO_TOOL_ROUTES = {
    "SECURITY_REFUSAL": "SECURITY_REFUSAL",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
    "ROUTER_CONFIGURATION_ERROR": "ROUTER_CONFIGURATION_ERROR",
}


class ProductionDispatchError(RuntimeError):
    pass


class ProductionRouterProvider:
    provider_id = PROVIDER_ID
    provider_kind = "REAL_CANDIDATE"
    synthetic = False

    def __init__(self, corpus_dir: Path, *, web_provider: Any = None,
                 general_context: Any = None,
                 specialist_adapters: Mapping[str, Callable[..., Any]] | None = None,
                 document_roots: tuple[Path, ...] = (),
                 workspace_mode: str = "REAL_EXPERIMENT") -> None:
        # The frozen loader runs here, but no holdout query does.
        self.corpus = load_corpus(Path(corpus_dir))
        self.web_provider = web_provider
        if workspace_mode not in {"REAL_EXPERIMENT", "SYNTHETIC_DISPOSABLE"}:
            raise ProductionDispatchError("invalid T23 provider workspace mode")
        if workspace_mode == "REAL_EXPERIMENT" and (
                web_provider is None or getattr(web_provider, "live_or_fixture", None) != "live"):
            raise ProductionDispatchError("real T23 provider requires a live source-backed web provider")
        self.workspace_mode = workspace_mode
        self.general_context = general_context
        self.specialist_adapters = dict(specialist_adapters or {})
        self.document_roots = tuple(document_roots)
        self.rows_executed = 0

    def _dispatch(self, decision: dict[str, Any], query: str,
                  execution_context: Mapping[str, Any], case_id: str) -> dict[str, Any]:
        route = decision["route_id"]
        capability = decision["selected_capability"]
        if route in NO_TOOL_ROUTES:
            if capability != "NO_TOOL":
                raise ProductionDispatchError("terminal route must select NO_TOOL")
            return {"capability": "NO_TOOL", "status": NO_TOOL_ROUTES[route],
                    "answer": "", "evidence": {"terminal_policy": route}}
        if capability == "KNOWLEDGE_RAG":
            answer = answer_knowledge(query, self.corpus)
            return {"capability": capability, "status": answer.status,
                    "answer": answer.answer, "evidence": answer.to_dict()}
        if capability == "WEB_RESEARCH":
            if self.web_provider is None:
                raise ProductionDispatchError("WEB_RESEARCH source provider is not configured")
            from sciencemath.web.pipeline import research

            answer = research(query, provider=self.web_provider,
                              query_time=execution_context.get("request_date") or "2026-09-22")
            return {"capability": capability, "status": answer.status,
                    "answer": answer.answer, "evidence": answer.to_dict()}
        if capability == "DOCUMENT":
            from sciencemath.document.pipeline import analyze

            files = execution_context.get("files")
            if not isinstance(files, list) or not files or not all(isinstance(p, str) for p in files):
                raise ProductionDispatchError("DOCUMENT selected without a supplied document")
            if not self.document_roots:
                raise ProductionDispatchError("DOCUMENT sandbox roots are not configured")
            base = self.document_roots[0].resolve()
            resolved = []
            for item in files:
                path = (base / item).resolve() if not Path(item).is_absolute() else Path(item).resolve()
                if not any(path == root.resolve() or root.resolve() in path.parents for root in self.document_roots):
                    raise ProductionDispatchError("DOCUMENT path escapes configured sandbox")
                resolved.append(str(path))
            answer = analyze(query, resolved, sandbox_roots=list(self.document_roots))
            return {"capability": capability, "status": answer.status,
                    "answer": answer.answer, "evidence": answer.to_dict()}
        if capability == "GENERAL":
            if self.general_context is None:
                raise ProductionDispatchError("GENERAL model context is not configured")
            from sciencemath.executive.runner import run_executive

            answer = run_executive(query, case_id, ctx=self.general_context,
                                   answer_type="text")
            return {"capability": capability,
                    "status": answer.get("evidence_status") or answer.get("status") or "UNKNOWN",
                    "answer": answer.get("final_answer") or "", "evidence": answer}
        adapter = self.specialist_adapters.get(capability)
        if adapter is None:
            raise ProductionDispatchError(f"no registered production adapter for {capability}")
        answer = adapter(query=query, context=dict(execution_context), case_id=case_id)
        if not isinstance(answer, dict) or not isinstance(answer.get("status"), str):
            raise ProductionDispatchError(f"invalid production adapter result for {capability}")
        return {"capability": capability, "status": answer["status"],
                "answer": answer.get("answer", ""), "evidence": answer}

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for row in rows:
            if set(row) - {"case_id", "candidate_input", "execution_context"}:
                raise ProductionDispatchError("gold or unknown row field exposed to provider")
            payload = row.get("candidate_input")
            if not isinstance(payload, dict) or set(payload) - set(INPUT_FIELDS):
                raise ProductionDispatchError("gold or unknown router input exposed")
            context = row.get("execution_context") or {}
            if not isinstance(context, dict) or set(context) - {"files", "request_date"}:
                raise ProductionDispatchError("gold or unknown execution context exposed")
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise ProductionDispatchError("case ID missing")
            decision = route_request(payload)
            execution = self._dispatch(decision, payload.get("query", ""),
                                       context, case_id)
            results.append({"case_id": case_id, "router_decision": decision,
                            "selected_capability_execution": execution})
            self.rows_executed += 1
        return results


def decision_parity(rows: list[dict[str, Any]], provider_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != len(provider_outputs):
        raise ProductionDispatchError("parity row counts differ")
    fields = ("route_id", "reason_code", "selected_capability")
    mismatches = {field: 0 for field in fields}
    for row, output in zip(rows, provider_outputs):
        direct = route_request(row["candidate_input"])
        if row["case_id"] != output["case_id"]:
            raise ProductionDispatchError("parity case order differs")
        for field in fields:
            mismatches[field] += int(direct[field] != output["router_decision"][field])
    return {"rows": len(rows), "mismatches": mismatches,
            "status": "PASS" if not any(mismatches.values()) else "FAIL"}
