"""pipeline — retrieval-augmented answering stage (T5.12/T5.13/T5.23).

Connects the T4 math layer and the T5 retrieval layer behind the route
classifier. Prompt-injection is CONDITIONAL (T5.23): each route sees
only its own instruction modules —

  MATH     -> math tool protocol            (no retrieval, no science text)
  SCIENCE  -> retrieved evidence + sources  (no tool protocol)
  MIXED    -> retrieved evidence + tool protocol
  GENERAL  -> bare question                 (neither subsystem)

The answering stage distinguishes three knowledge origins (T5.12):
model reasoning, deterministic tool computation, retrieved evidence —
and records exactly which chunks were supplied to the model, so a
citation can only ever name chunks that were actually retrieved
(citations verification enforces this downstream).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from sciencemath.rag.audit import RetrievalAuditLogger
from sciencemath.rag.citations import Citation, parse_inline_citations
from sciencemath.rag.compression import (compress_evidence,
                                         evidence_firewall_block)
from sciencemath.rag.evidence import EvidenceContract, build_contract
from sciencemath.rag.retriever import RetrievalResult, Retriever
from sciencemath.rag.route import classify_route, prompt_modules_for_route
from sciencemath.tools.base import ToolRegistry
from sciencemath.tools.benchmark import (MAX_TOOL_ROUNDS, TOOL_PROTOCOL_INSTRUCTION,
                                         _parse_tool_call)
from sciencemath.tools.router import ToolCallLogger, invoke_logged

# -- conditional instruction modules (T5.23) --------------------------------

SCIENCE_EVIDENCE_INSTRUCTION = """Use the retrieved sources below to answer the question. Ground every factual claim in these sources. If the sources do not contain enough information, say exactly that instead of guessing.

{evidence_block}

Answer the question. Cite every source you used by writing its chunk id in square brackets immediately after the claim it supports, e.g. [wiki-123:intro:0]. Do not cite a chunk you did not use. If no source supports the answer, write no citation.

Put your final answer (the exact term) inside \\boxed{{}} on the last line."""

NO_EVIDENCE_INSTRUCTION = """No relevant sources were found for this question. If you are not certain, state that clearly instead of guessing. Put your final answer inside \\boxed{{}} on the last line."""

GENERAL_EVAL_INSTRUCTION = ("Answer the following question. Put your final "
                            "answer (the exact term) inside \\boxed{} on the "
                            "last line.")


def format_evidence(retrieval: RetrievalResult, max_chars: int = 4000) -> str:
    """Render selected chunks with per-chunk citation tags [chunk_id];
    deterministic given the retrieval result."""
    blocks = []
    for c in retrieval.chunks:
        header = f'[{c["chunk_id"]}] {c.get("title", "?")}'
        if c.get("section"):
            header += f' — {c["section"]}'
        blocks.append(f"{header}\n{c['text']}")
    text = "\n\n".join(blocks)
    return text[:max_chars] if len(text) > max_chars else text


def build_prompt(question: str, route: str, retrieval: RetrievalResult | None,
                 *, eval_style: bool = True) -> str:
    """Route-conditional prompt assembly (T5.23). eval_style keeps the
    \\boxed{} scoring contract for suite questions."""
    modules = prompt_modules_for_route(route)
    parts = [question.strip()]
    if "science_retrieval" in modules:
        if retrieval is not None and retrieval.used_retrieval:
            parts.append(SCIENCE_EVIDENCE_INSTRUCTION.format(
                evidence_block=format_evidence(retrieval)))
        else:
            parts.append(NO_EVIDENCE_INSTRUCTION)
    if "math_tools" in modules:
        parts.append(TOOL_PROTOCOL_INSTRUCTION)
    if eval_style and not modules:
        # GENERAL: standard scoring instruction only — no subsystem text
        parts.append(GENERAL_EVAL_INSTRUCTION)
    return "\n\n".join(parts)


@dataclass
class RagAnswer:
    """One retrieval-augmented answer attempt (pre-verdict)."""
    question_id: str
    route: dict
    retrieval: RetrievalResult | None
    prompt: str
    raw_model_output: str
    tool_calls: list[dict]
    contract: EvidenceContract
    citations: list[Citation]
    latency_s: float
    input_tokens: int
    output_tokens: int
    error: str | None = None


def answer_question(*, model, tokenizer, question: str, question_id: str,
                    retriever: Retriever | None = None,
                    registry: ToolRegistry | None = None,
                    tool_logger: ToolCallLogger | None = None,
                    audit_logger: RetrievalAuditLogger | None = None,
                    generation: dict | None = None,
                    max_seq_tokens: int = 4096,
                    enable_thinking: bool | None = False,
                    retrieval_filters: list[str] | None = None,
                    prompt_override: str | None = None) -> RagAnswer:
    """Route -> retrieve -> generate (+tools for MATH/MIXED) -> evidence.

    prompt_override: bypass retrieval and use this exact prompt (used by
    the no-RAG comparison arm — same generation path, matched settings)."""
    import torch

    generation = generation or {"seed": 42, "do_sample": False,
                                "max_new_tokens": 1024}
    route = classify_route(question)
    modules = prompt_modules_for_route(route["route"])
    t0 = time.perf_counter()
    retrieval: RetrievalResult | None = None
    tool_calls: list[dict] = []
    prompt = ""

    def _gen(messages: list[dict]) -> tuple[str, int, int]:
        templ = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            **({"enable_thinking": enable_thinking}
               if enable_thinking is not None else {}))
        torch.manual_seed(int(generation.get("seed", 42)))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(generation.get("seed", 42)))
        inputs = tokenizer(templ, return_tensors="pt", truncation=True,
                           max_length=max_seq_tokens)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        n_in = int(inputs["input_ids"].shape[1])
        gen_kwargs = {"max_new_tokens": int(generation.get(
            "max_new_tokens", 1024)),
            "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
            "do_sample": False}
        if generation.get("do_sample"):
            gen_kwargs.update({
                "do_sample": True,
                "temperature": float(generation["temperature"]),
                "top_p": float(generation["top_p"]),
                "top_k": int(generation.get("top_k", 0)),
            })
        with torch.no_grad():
            out = model.generate(**inputs, **gen_kwargs)
        n_out = int(out.shape[1]) - n_in
        text = tokenizer.decode(out[0][n_in:], skip_special_tokens=True)
        return text, n_in, n_out

    try:
        # 1. retrieval (SCIENCE/MIXED only — NEVER for MATH, T5.22)
        if prompt_override is None and retriever is not None and \
                "science_retrieval" in modules:
            retrieval = retriever.retrieve(question,
                                           domain_filters=retrieval_filters)

        # 2. route-conditional prompt
        prompt = prompt_override or build_prompt(question, route["route"],
                                                 retrieval)
        messages = [{"role": "user", "content": prompt}]

        # 3. generation (+ tool loop only for MATH/MIXED)
        chunks_out: list[str] = []
        n_in_total = n_out_total = 0
        tool_rounds = (MAX_TOOL_ROUNDS
                       if ("math_tools" in modules and registry is not None)
                       else 1)
        for round_no in range(tool_rounds):
            text, n_in, n_out = _gen(messages)
            chunks_out.append(text)
            n_in_total += n_in
            n_out_total += n_out
            call = _parse_tool_call(text) if tool_rounds > 1 else None
            if call is None or round_no == tool_rounds - 1 or registry is None:
                break
            result = invoke_logged(registry, tool_logger, question_id,
                                   call["tool"], call["arguments"])
            tool_calls.append({
                "round": round_no + 1, "tool": call["tool"],
                "arguments": call["arguments"], "status": result.status})
            result_json = json.dumps(
                result.to_dict()["result"] if result.ok
                else result.to_dict()["error"])
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user",
                             "content": f"TOOL RESULT: {result_json}"})
        raw = "\n".join(chunks_out)

        # 4. evidence contract over EXACTLY the chunks the model saw
        seen_chunks = list(retrieval.chunks) if retrieval is not None else []
        contract = build_contract(raw, chunks=seen_chunks,
                                  used_math_tools=bool(tool_calls))
        cits = parse_inline_citations(
            raw, {c["chunk_id"]: c for c in seen_chunks})
        latency = time.perf_counter() - t0

        # 5. audit (T5.24)
        if audit_logger is not None:
            all_touched = (list(retrieval.chunks) + list(retrieval.rejected)) \
                if retrieval is not None else []
            audit_logger.log_answer_attempt(
                question_id=question_id, question=question, route=route,
                retrieval_used=bool(seen_chunks),
                embedding_model=(retrieval.embedding_model
                                 if retrieval is not None else None),
                retrieved_chunk_ids=[c["chunk_id"] for c in all_touched],
                retrieval_scores={c["chunk_id"]: c.get("score", 0.0)
                                  for c in all_touched},
                rerank_scores={c["chunk_id"]: c.get("rerank_score", 0.0)
                               for c in all_touched},
                selected_ids=[c["chunk_id"] for c in seen_chunks],
                rejected=[{"chunk_id": c["chunk_id"], "why": "threshold/budget"}
                          for c in (retrieval.rejected
                                    if retrieval is not None else [])],
                tool_calls=tool_calls,
                final_source_ids=[s.source_id for s in contract.sources],
                latency_s=latency, error=None,
                evidence_state=contract.evidence_state)
        return RagAnswer(
            question_id=question_id, route=route, retrieval=retrieval,
            prompt=prompt, raw_model_output=raw, tool_calls=tool_calls,
            contract=contract, citations=cits, latency_s=latency,
            input_tokens=n_in_total, output_tokens=n_out_total)
    except Exception as exc:  # noqa: BLE001 — answering never crashes the run
        latency = time.perf_counter() - t0
        if audit_logger is not None:
            audit_logger.log_answer_attempt(
                question_id=question_id, question=question, route=route,
                retrieval_used=False, embedding_model=None,
                retrieved_chunk_ids=[], retrieval_scores={}, rerank_scores={},
                selected_ids=[], rejected=[], tool_calls=tool_calls,
                final_source_ids=[], latency_s=latency,
                error=f"{type(exc).__name__}: {exc}")
        return RagAnswer(
            question_id=question_id, route=route, retrieval=retrieval,
            prompt=prompt, raw_model_output="", tool_calls=tool_calls,
            contract=build_contract("", chunks=[]),
            citations=[], latency_s=latency,
            input_tokens=0, output_tokens=0,
            error=f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# T5R answering flow (T5R.1/T5R.2/T5R.4/T5R.5/T5R.7/T5R.10)
# ---------------------------------------------------------------------------

T5R_SCIENCE_INSTRUCTION = (
    "Use ONLY the evidence above to answer. If the evidence is not enough "
    "to answer, reply exactly: There is insufficient information to "
    "answer. Answer concisely as a sentence or a single term/number. Do "
    "not compute anything from the evidence text. Put your final answer "
    "inside \\boxed{} on the last line. Do not mention sources.")

T5R_MIXED_INSTRUCTION = (
    "You have the constants listed above and the retrieved facts.\n"
    "Rules:\n"
    "1. This question requires arithmetic. Do NOT do any arithmetic "
    "yourself — use the calculator tool listed below for EVERY "
    "calculation; the tools are deterministic and you are not.\n"
    "2. Use the retrieved facts only for explanatory claims, never as "
    "numbers for a calculation (calculations use the given constants).\n"
    "3. After the tool result, answer the question in one sentence and "
    "put the final numeric/term answer inside \\boxed{} on the last "
    "line. Do not mention sources.")

T5R_MULTIHOP_INSTRUCTION = (
    "Answer the hops IN ORDER, one per hop, using the evidence shown "
    "after each hop (a hop marked \"Given in the question\" is answered "
    "from the question's own statements). Format exactly:\n"
    "Hop 1 answer: <one sentence>\n"
    "Hop 2 answer: <one sentence>\n"
    "...\n"
    "Final answer: put the answer to the LAST hop inside \\boxed{} on "
    "the last line. If a hop cannot be answered from its evidence, write "
    "Hop N answer: There is insufficient information to answer. and "
    "continue. Do not mention sources.")

T5R_INSUFFICIENT_INSTRUCTION = (
    "Use ONLY the evidence above. If the evidence is insufficient, "
    "conflicting, or too general for this exact question, reply exactly: "
    "There is insufficient information to answer. Otherwise answer "
    "concisely and put the final answer inside \\boxed{} on the last "
    "line. Do not mention sources.")

T5R_GENERAL_INSTRUCTION = (
    "Answer the question. Put your final answer inside \\boxed{} on the "
    "last line.")


def t5r_build_prompt(question: str, subroute: str, *, plan=None,
                     evidence_blocks: list[tuple[str, str]] | None = None,
                     conflict_state: str = "NONE") -> str:
    """T5R.1/T5R.10 route-specific prompt assembly.

    evidence_blocks: [(label, firewall-wrapped evidence text)] — for
    multi-hop one block per hop, else a single block. conflict_state is
    the measured AGREEMENT/CONFLICT/INSUFFICIENT state of the evidence
    (T5R.10)."""
    parts = [question.strip()]
    blocks = list(evidence_blocks or [])
    if conflict_state in CONFLICT_INSTRUCTIONS and blocks:
        # T5R.10: the generation instruction for the measured state is
        # attached to the evidence itself (deterministic).
        blocks[0] = (blocks[0][0],
                     f"NOTE: {CONFLICT_INSTRUCTIONS[conflict_state]}\n\n"
                     + blocks[0][1])
    if subroute == "MATH":
        parts.append(TOOL_PROTOCOL_INSTRUCTION)
        return "\n\n".join(parts)
    if subroute == "MIXED_MATH_SCIENCE":
        if plan is None:
            # mixed_plan ablation off: no constants/tools machinery —
            # answer as plain evidence-backed science, but never DROP
            # retrieved evidence from the prompt
            if blocks:
                parts.append(blocks[0][1])
                parts.append(T5R_SCIENCE_INSTRUCTION)
            else:
                parts.append(NO_EVIDENCE_INSTRUCTION)
            return "\n\n".join(parts)
        if plan is not None:
            if plan.constants:
                lines = [f"Constants: {c['name']} = {c['value']} {c['unit']}"
                         for c in plan.constants]
                parts.append("\n".join(lines))
            if plan.science_query and blocks:
                label, ev = blocks[0]
                parts.append(ev)
            elif blocks:
                parts.append(blocks[0][1])
        parts.append(T5R_MIXED_INSTRUCTION)
        # T5R.4: arithmetic is delegated to the T4 tools — the model gets
        # the same full protocol the T4 benchmark used (tool list is part
        # of what makes the protocol trigger)
        parts.append(TOOL_PROTOCOL_INSTRUCTION)
        return "\n\n".join(parts)
    if subroute == "MULTI_HOP_SCIENCE":
        for label, ev in blocks:
            parts.append(f"{label}\n{ev}")
        parts.append(T5R_MULTIHOP_INSTRUCTION)
        if plan is not None and any(
                h.kind == "compute" for h in plan.subquestions):
            # a compute hop delegates arithmetic to the T4 tools (T5R.4);
            # the hops instruction covers reasoning, this covers tool use
            parts.append(TOOL_PROTOCOL_INSTRUCTION)
        return "\n\n".join(parts)
    if subroute == "INSUFFICIENT_EVIDENCE":
        if blocks:
            parts.append(blocks[0][1])
        parts.append(T5R_INSUFFICIENT_INSTRUCTION)
        return "\n\n".join(parts)
    if subroute == "FACTUAL_SCIENCE":
        if blocks:
            parts.append(blocks[0][1])
            parts.append(T5R_SCIENCE_INSTRUCTION)
        else:
            parts.append(NO_EVIDENCE_INSTRUCTION)
        return "\n\n".join(parts)
    # GENERAL — bare instruction, unless the gate retrieved (science
    # vocabulary present, T5R.6): then answer from the evidence
    if blocks:
        parts.append(blocks[0][1])
        parts.append(T5R_SCIENCE_INSTRUCTION)
    else:
        parts.append(T5R_GENERAL_INSTRUCTION)
    return "\n\n".join(parts)


CONFLICT_INSTRUCTIONS = {
    "AGREEMENT": "The evidence sources agree; synthesize their common "
                 "claim.",
    "CONFLICT": ("The evidence sources DISAGREE on this point. State the "
                 "disagreement explicitly in your answer instead of "
                 "picking one, and conclude that there is insufficient "
                 "information to give a single confident answer."),
    "INSUFFICIENT": "The evidence does not establish the answer. Say the "
                    "evidence is insufficient.",
}


def _evidence_for(question: str, chunks: list[dict], *,
                  max_tokens: int = 350) -> tuple[str, object]:
    """Compressed evidence (T5R.2); NOT firewall-wrapped — the caller
    wraps once (T5R.9), so branches never double-wrap."""
    ce = compress_evidence(question, chunks, max_tokens=max_tokens)
    return ce.rendered, ce


@dataclass
class RagAnswerT5R:
    """One T5R answer attempt — records the full measured pipeline."""
    question_id: str
    route: dict
    subroute: str
    signals: list[str]
    plan: object | None
    retrieval_used: bool
    chunks_supplied: list[dict]
    compressed: object | None
    conflict_state: str
    prompt: str
    raw_model_output: str
    tool_calls: list[dict]
    evidence_refs: list[int]
    invalid_refs: list[int]
    answer_with_sources: str
    citations: list
    latency_s: float
    input_tokens: int
    output_tokens: int
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id, "route": self.route["route"],
            "subroute": self.subroute, "signals": self.signals,
            "plan": self.plan.to_dict() if self.plan else None,
            "retrieval_used": self.retrieval_used,
            "chunk_ids_supplied": [c["chunk_id"] for c in
                                   self.chunks_supplied],
            "compression": (self.compressed.to_dict()
                            if self.compressed is not None else None),
            "conflict_state": self.conflict_state,
            "prompt": self.prompt,
            "raw_model_output": self.raw_model_output,
            "tool_calls": self.tool_calls,
            "evidence_refs": self.evidence_refs,
            "invalid_refs": self.invalid_refs,
            "answer_with_sources": self.answer_with_sources,
            "latency_s": self.latency_s,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error": self.error,
        }


def answer_question_t5r(*, model, tokenizer, question: str,
                        question_id: str,
                        retriever: Retriever | None = None,
                        registry: ToolRegistry | None = None,
                        tool_logger: ToolCallLogger | None = None,
                        audit_logger: RetrievalAuditLogger | None = None,
                        generation: dict | None = None,
                        max_seq_tokens: int = 4096,
                        enable_thinking: bool | None = False,
                        retrieval_filters: list[str] | None = None,
                        max_evidence_tokens: int = 350,
                        features: dict | None = None) -> RagAnswerT5R:
    """The T5R answering flow. Features are toggleable so the ablation
    matrix (T5R.13) can disable one mechanism at a time:

      retrieve_gate (T5R.6)   sub-route + eligibility decides retrieval
      compression (T5R.2)     compressed evidence instead of raw chunks
      firewall (T5R.9)        evidence wrapped as untrusted DATA
      decompose (T5R.5)       explicit multi-hop subquestions
      mixed_plan (T5R.4)      constants extraction + tool-only arithmetic
      deterministic_citations (T5R.7) system-computed evidence refs

    MATH never retrieves (T5.22, unchanged)."""
    import torch
    from sciencemath.rag.citations import (attach_deterministic_citations,
                                           compute_evidence_refs)
    from sciencemath.rag.decompose import decompose_multi_hop, plan_mixed
    from sciencemath.rag.evidence import detect_conflicts
    from sciencemath.rag.route import (classify_subroute, retrieval_eligible)

    features = features or {}
    f_gate = features.get("retrieve_gate", True)
    f_comp = features.get("compression", True)
    f_fire = features.get("firewall", True)
    f_decomp = features.get("decompose", True)
    f_mixed = features.get("mixed_plan", True)
    f_cite = features.get("deterministic_citations", True)

    generation = generation or {"seed": 42, "do_sample": False,
                                "max_new_tokens": 1024}
    route = classify_route(question)
    subroute = classify_subroute(question)
    t0 = time.perf_counter()
    retrieval: RetrievalResult | None = None
    chunks_supplied: list[dict] = []
    tool_calls: list[dict] = []
    plan = None
    conflict_state = "NONE"
    prompt = ""

    def _gen(messages: list[dict]) -> tuple[str, int, int]:
        templ = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            **({"enable_thinking": enable_thinking}
               if enable_thinking is not None else {}))
        torch.manual_seed(int(generation.get("seed", 42)))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(generation.get("seed", 42)))
        inputs = tokenizer(templ, return_tensors="pt", truncation=True,
                           max_length=max_seq_tokens)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        n_in = int(inputs["input_ids"].shape[1])
        gen_kwargs = {"max_new_tokens": int(generation.get(
            "max_new_tokens", 1024)),
            "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
            "do_sample": False}
        if generation.get("do_sample"):
            gen_kwargs.update({
                "do_sample": True,
                "temperature": float(generation["temperature"]),
                "top_p": float(generation["top_p"]),
                "top_k": int(generation.get("top_k", 0)),
            })
        with torch.no_grad():
            out = model.generate(**inputs, **gen_kwargs)
        n_out = int(out.shape[1]) - n_in
        text = tokenizer.decode(out[0][n_in:], skip_special_tokens=True)
        return text, n_in, n_out

    try:
        sr = subroute["subroute"]
        eligible = True
        if f_gate:
            eligible, _signals = retrieval_eligible(question, route["route"])
            subroute["signals"].extend(_signals)

        # --- retrieval (never for MATH, T5.22) --------------------------
        per_hop_chunks: dict[int, list[dict]] = {}
        if sr == "MATH" or not eligible or retriever is None:
            retrieval = None
        elif f_decomp and sr == "MULTI_HOP_SCIENCE":
            plan = decompose_multi_hop(question)
            merged: list[dict] = []
            seen_ids: set[str] = set()
            for hop in plan.subquestions:
                if not hop.needs_retrieval:
                    continue
                r = retriever.retrieve(hop.subquestion,
                                       domain_filters=retrieval_filters)
                per_hop_chunks[hop.hop_id] = list(r.chunks)
                for c in r.chunks:
                    if c["chunk_id"] not in seen_ids:
                        seen_ids.add(c["chunk_id"])
                        merged.append(c)
            chunks_supplied = merged
        elif f_mixed and sr == "MIXED_MATH_SCIENCE":
            plan = plan_mixed(question)
            if plan.retrieve:
                r = retriever.retrieve(
                    plan.science_query or question,
                    domain_filters=retrieval_filters)
                chunks_supplied = list(r.chunks)
        else:
            r = retriever.retrieve(question, domain_filters=retrieval_filters)
            retrieval = r
            chunks_supplied = list(r.chunks)
        retrieval_used = bool(chunks_supplied)

        # --- conflict state over the supplied chunks (T5R.10) -----------
        if chunks_supplied and sr in ("FACTUAL_SCIENCE",
                                      "MULTI_HOP_SCIENCE",
                                      "INSUFFICIENT_EVIDENCE",
                                      "GENERAL"):
            verdicts = detect_conflicts(chunks_supplied)
            conflict_state = "CONFLICT" if verdicts else "AGREEMENT"

        # --- compressed evidence blocks ----------------------------------
        blocks: list[tuple[str, str]] = []
        compressed = None

        def _raw_render(chs: list[dict]) -> str:
            # raw (uncompressed) chunk rendering for compression=off arms
            return "\n\n".join(
                f"{c.get('title', '')}: {c.get('text', '')}" for c in chs)

        if f_decomp and sr == "MULTI_HOP_SCIENCE" and plan is not None:
            # compress_evidence/evidence_firewall_block come from the
            # module-level import — a local import here would make the
            # names function-local and UnboundLocalError the elif below
            for hop in plan.subquestions:
                if not hop.needs_retrieval:
                    # a hop the question itself supplies (premise or a
                    # compute request) needs an answerable basis — leave
                    # it nothing and the model copies an earlier hop's
                    # insufficiency into the final answer
                    if hop.kind == "compute":
                        body = ("Arithmetic hop — use the calculator tool "
                                "for this one; no retrieved evidence "
                                "needed.")
                    else:
                        body = f"Given in the question: {hop.subquestion}"
                    blocks.append((f"Hop {hop.hop_id} evidence:",
                                   body if not f_fire
                                   else evidence_firewall_block(body)))
                    continue
                # a hop with zero retrieved chunks gets an explicit empty
                # marker — never another hop's chunks (empty != falsy-all)
                hop_chunks = per_hop_chunks.get(hop.hop_id) or []
                if f_comp and hop_chunks:
                    ce = compress_evidence(hop.subquestion, hop_chunks,
                                           max_tokens=max_evidence_tokens // 2)
                    rendered = ce.rendered if ce.items else None
                    if rendered is not None and compressed is None:
                        compressed = ce
                else:
                    rendered = _raw_render(hop_chunks) if hop_chunks else None
                label = f"Hop {hop.hop_id} evidence:"
                body = rendered if rendered else \
                    "No evidence was retrieved for this hop."
                blocks.append((label, evidence_firewall_block(body)
                               if f_fire else body))
        elif chunks_supplied and sr in ("FACTUAL_SCIENCE",
                                        "MIXED_MATH_SCIENCE",
                                        "INSUFFICIENT_EVIDENCE",
                                        "GENERAL"):
            if f_comp:
                rendered, compressed = _evidence_for(
                    question, chunks_supplied,
                    max_tokens=max_evidence_tokens)
            else:
                rendered = (format_evidence(retrieval)
                            if retrieval is not None
                            else _raw_render(chunks_supplied))
                compressed = None
            blocks.append(("Evidence:", evidence_firewall_block(rendered)
                           if f_fire else rendered))

        # --- prompt (conflict note attached by the builder, T5R.10) ------
        prompt = t5r_build_prompt(
            question, sr, plan=plan,
            evidence_blocks=blocks,
            conflict_state=conflict_state)
        messages = [{"role": "user", "content": prompt}]

        # --- generation (+ tool loop for MATH/MIXED/compute hops) ---------
        chunks_out: list[str] = []
        n_in_total = n_out_total = 0
        multihop_compute = (sr == "MULTI_HOP_SCIENCE" and plan is not None
                            and any(h.kind == "compute"
                                    for h in plan.subquestions))
        tool_rounds = (MAX_TOOL_ROUNDS
                       if sr in ("MATH", "MIXED_MATH_SCIENCE")
                       or multihop_compute else 1) if registry is not None \
            else 1
        for round_no in range(tool_rounds):
            text, n_in, n_out = _gen(messages)
            chunks_out.append(text)
            n_in_total += n_in
            n_out_total += n_out
            call = _parse_tool_call(text) if tool_rounds > 1 else None
            if call is None or round_no == tool_rounds - 1:
                break
            result = invoke_logged(registry, tool_logger, question_id,
                                   call["tool"], call["arguments"])
            tool_calls.append({
                "round": round_no + 1, "tool": call["tool"],
                "arguments": call["arguments"], "status": result.status})
            result_json = json.dumps(
                result.to_dict()["result"] if result.ok
                else result.to_dict()["error"])
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user",
                             "content": f"TOOL RESULT: {result_json}"})
        raw = "\n".join(chunks_out)

        # --- deterministic citations (T5R.7/T5R.8) ------------------------
        refs: list[int] = []
        invalid_refs: list[int] = []
        cits: list = []
        answer_with_sources = raw
        if f_cite and chunks_supplied:
            # support is judged on the ANSWER text: tool-call JSON lines
            # are protocol, not claims (they would dilute support below
            # threshold and silently drop the citation)
            claim_text = "\n".join(
                ln for ln in raw.splitlines()
                if not (ln.strip().startswith("{") and '"tool"' in ln))
            refs = compute_evidence_refs(claim_text, chunks_supplied)
            att = attach_deterministic_citations(claim_text,
                                                 chunks_supplied, refs)
            invalid_refs = att["invalid_refs"]
            cits = att["citations"]
            answer_with_sources = att["answer_with_sources"]
        elif not f_cite:
            cits = parse_inline_citations(
                raw, {c["chunk_id"]: c for c in chunks_supplied})

        latency = time.perf_counter() - t0
        if audit_logger is not None:
            audit_logger.log_answer_attempt(
                question_id=question_id, question=question, route=route,
                retrieval_used=retrieval_used,
                embedding_model=(retrieval.embedding_model
                                 if retrieval is not None else None),
                retrieved_chunk_ids=[c["chunk_id"] for c in chunks_supplied],
                retrieval_scores={c["chunk_id"]: c.get("score", 0.0)
                                  for c in chunks_supplied},
                rerank_scores={c["chunk_id"]: c.get("rerank_score", 0.0)
                               for c in chunks_supplied},
                selected_ids=[c["chunk_id"] for c in chunks_supplied],
                rejected=[], tool_calls=tool_calls, final_source_ids=[],
                latency_s=latency, error=None,
                evidence_state=conflict_state)
        return RagAnswerT5R(
            question_id=question_id, route=route, subroute=sr,
            signals=subroute["signals"], plan=plan,
            retrieval_used=retrieval_used, chunks_supplied=chunks_supplied,
            compressed=compressed, conflict_state=conflict_state,
            prompt=prompt, raw_model_output=raw, tool_calls=tool_calls,
            evidence_refs=refs, invalid_refs=invalid_refs,
            answer_with_sources=answer_with_sources, citations=cits,
            latency_s=latency, input_tokens=n_in_total,
            output_tokens=n_out_total)
    except Exception as exc:  # noqa: BLE001 — answering never crashes the run
        latency = time.perf_counter() - t0
        if audit_logger is not None:
            audit_logger.log_answer_attempt(
                question_id=question_id, question=question, route=route,
                retrieval_used=bool(chunks_supplied),
                embedding_model=(retrieval.embedding_model
                                 if retrieval is not None else None),
                retrieved_chunk_ids=[c["chunk_id"] for c in chunks_supplied],
                retrieval_scores={c["chunk_id"]: c.get("score", 0.0)
                                  for c in chunks_supplied},
                rerank_scores={c["chunk_id"]: c.get("rerank_score", 0.0)
                               for c in chunks_supplied},
                selected_ids=[c["chunk_id"] for c in chunks_supplied],
                rejected=[], tool_calls=tool_calls, final_source_ids=[],
                latency_s=latency, error=f"{type(exc).__name__}: {exc}")
        return RagAnswerT5R(
            question_id=question_id, route=route,
            subroute=subroute["subroute"], signals=subroute["signals"],
            plan=plan, retrieval_used=bool(chunks_supplied),
            chunks_supplied=chunks_supplied, compressed=None,
            conflict_state=conflict_state, prompt=prompt,
            raw_model_output="", tool_calls=tool_calls, evidence_refs=[],
            invalid_refs=[], answer_with_sources="", citations=[],
            latency_s=latency, input_tokens=0, output_tokens=0,
            error=f"{type(exc).__name__}: {exc}")