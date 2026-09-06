"""T7.9/T7.10 — Step execution with controlled context and structured
observations.

Each plan step runs with a COMPACT step context: the goal, the
question, included (distractor-filtered) facts, and only the
observations of dependency steps — never the whole transcript
(research pattern A14). Every action's result becomes a structured
observation; tool errors are recorded as FAILED observations
(errors-as-observations, A9). Action space is fixed: anything else is
REJECTED (T7.33).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict

from sciencemath.executive.llm import call_model, ModelCallError
from sciencemath.executive.plan import ACTIONS
from sciencemath.executive import budgets as bmod

# ---- prompts (compact, deterministic scaffolds; no hidden CoT) -----------
REASON_PROMPT = """Question: {question}

Relevant facts:
{facts}

Task: {description}
{dep_notes}Answer using ONLY the information above. Be concise and show \
any arithmetic explicitly on one line each. End with a line \
"Answer: <final answer for this step>"."""

SYNTH_PROMPT = """Question: {question}

Step results:
{obs}

Task: Combine the step results into the final answer to the question. \
Be concise. If any step result lists retrieved evidence chunk ids \
(e.g. "evidence: c1 | c2"), cite the chunk ids you actually used in \
square brackets. Cite ONLY ids that appear in the step results — \
NEVER cite the "c1"/"c2" in this instruction itself or any id you \
invented. End with a line "Answer: <the final answer>\"."""

PLAN_PROMPT = """Question: {question}

Understanding:
- Knowns: {knowns}
- Asked for: {unknowns}
- Constraints: {constraints}
- Missing: {missing}

Emit a JSON execution plan for answering this question. {schema}"""

PLAN_RETRY_SUFFIX = """

Your previous plan was invalid. {feedback}
Emit the corrected plan as JSON only."""

RETRIEVE_INPUT_TMPL = "{query}"

# MATH_TOOL uses the T4 registry calculator; CHECK uses the T4 verifier.


@dataclass
class Observation:
    step_id: str
    action: str
    status: str                 # OK | FAILED | REJECTED
    summary: str                # <= 400 chars, extractive
    detail: dict = field(default_factory=dict)
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _chunk_texts(ob: dict, limit: int = 2, chars: int = 280) -> str:
    """Extractive evidence text from a RETRIEVE observation — the model
    must be able to READ its evidence, not just see chunk ids."""
    chunks = (ob.get("detail") or {}).get("chunks") or []
    parts = []
    for c in chunks[:limit]:
        cid = c.get("chunk_id", "?")
        text = (c.get("text") or "").strip().replace("\n", " ")
        if text:
            parts.append(f'[{cid}] "{text[:chars]}"')
    return "\n".join(parts)


def build_step_context(state, step: dict, observations: dict) -> dict:
    """Compact context: goal + included facts + dependency observations
    only (summary field, truncated; RETRIEVE deps additionally carry the
    extracted chunk text so the model can actually use its evidence)."""
    deps = step.get("depends_on", []) or []
    dep_notes = []
    for dep in deps:
        ob = observations.get(dep)
        if ob is None:
            continue
        note = f"[{dep}] {ob['summary'][:300]}"
        if ob.get("action") == "RETRIEVE" and ob.get("status") == "OK":
            evidence = _chunk_texts(ob)
            if evidence:
                note += "\nEvidence text:\n" + evidence
        dep_notes.append(note)
    facts = "\n".join("- " + f for f in state.get("included_facts", []))
    return {
        "question": state["problem"],
        "facts": facts or "(none)",
        "dep_notes": "\n".join(dep_notes),
    }


def execute_step(state: dict, step: dict, observations: dict, ctx) -> tuple[Observation, dict]:
    """Execute one step. `ctx` is an ExecContext (see runner.py) exposing
    model/tokenizer/generation/registry/retriever/usage. Returns
    (observation, outputs) where outputs carry step products (text,
    tool result, retrieved chunk ids) for downstream steps."""
    action = step.get("action")
    if action not in ACTIONS:
        return (Observation(step_id=step.get("id", "?"), action=str(action),
                            status="REJECTED",
                            summary=f"unknown action {action!r} rejected"),
                {})

    t0 = time.perf_counter()
    try:
        if action == "REASON":
            return _exec_reason(state, step, observations, ctx, t0)
        if action == "MATH_TOOL":
            return _exec_math(step, ctx, t0)
        if action == "RETRIEVE":
            return _exec_retrieve(step, ctx, t0)
        if action == "CHECK":
            return _exec_check(step, observations, ctx, t0)
        if action == "SYNTHESIZE":
            return _exec_synth(state, observations, ctx, t0)
        return (Observation(step_id=step.get("id", "?"), action=action,
                            status="REJECTED",
                            summary="unreachable action"), {})
    except ModelCallError as exc:
        return (Observation(step_id=step.get("id", "?"), action=action,
                            status="FAILED",
                            summary=f"model call failed: {exc}",
                            detail={"error_type": "MODEL_CALL_FAILED"}),
                {})
    except Exception as exc:  # noqa: BLE001
        return (Observation(step_id=step.get("id", "?"), action=action,
                            status="FAILED", summary=f"{type(exc).__name__}: {exc}",
                            detail={"error_type": "TOOL_RUNTIME_ERROR"}),
                {})


def _exec_reason(state, step, observations, ctx, t0):
    c = build_step_context(state, step, observations)
    prompt = REASON_PROMPT.format(question=c["question"], facts=c["facts"],
                                  description=step.get("description", ""),
                                  dep_notes=(("\nStep results:\n" +
                                              c["dep_notes"] + "\n")
                                             if c["dep_notes"] else "\n"))
    ctx.usage["model_calls"] += 1
    text, n_in, n_out = call_model(ctx.model, ctx.tokenizer, prompt,
                                   ctx.generation)
    ctx.usage["input_tokens"] += n_in
    ctx.usage["output_tokens"] += n_out
    summary = _final_line(text)
    return (Observation(step_id=step["id"], action="REASON", status="OK",
                        summary=summary[:400], detail={"raw": text[:2000]},
                        latency_s=time.perf_counter() - t0,
                        input_tokens=n_in, output_tokens=n_out),
            {"text": text, "answer": summary})


def _exec_math(step, ctx, t0):
    expr = step.get("input") or ""
    if not expr or not isinstance(expr, str):
        return (Observation(step_id=step["id"], action="MATH_TOOL",
                            status="FAILED",
                            summary="MATH_TOOL step has no input expression",
                            detail={"error_type": "TOOL_ARGUMENT_INVALID"}),
                {})
    ctx.usage["tool_calls"] += 1
    result = ctx.registry.invoke("calculator", {"expression": expr})
    if result.status == "error":
        return (Observation(step_id=step["id"], action="MATH_TOOL",
                            status="FAILED",
                            summary=str(result.error)[:400],
                            detail={"error_type": "TOOL_RUNTIME_ERROR",
                                    "error": result.error}),
                {"tool_result": result})
    return (Observation(step_id=step["id"], action="MATH_TOOL", status="OK",
                        summary=str(result.result)[:400],
                        detail={"result": result.result},
                        latency_s=time.perf_counter() - t0),
            {"tool_result": result, "answer": str(result.result)})


def _call_retriever(retriever, query: str, k: int) -> list[dict]:
    """Call whichever retrieval interface the retriever exposes:
    search(query, k=) (executive contract) or the T5R
    retrieve(question, top_n=) returning RetrievalResult."""
    if hasattr(retriever, "search"):
        return retriever.search(query, k=k)
    res = retriever.retrieve(query, top_n=k)
    return list(getattr(res, "chunks", []) or [])


def _exec_retrieve(step, ctx, t0):
    query = (step.get("input") or "").strip()
    if not query:
        return (Observation(step_id=step["id"], action="RETRIEVE",
                            status="FAILED",
                            summary="RETRIEVE step has no input query",
                            detail={"error_type": "TOOL_ARGUMENT_INVALID"}),
                {})
    ctx.usage["retrievals"] += 1
    try:
        hits = _call_retriever(ctx.retriever, query, ctx.retrieval_k)
    except Exception as exc:  # noqa: BLE001
        return (Observation(step_id=step["id"], action="RETRIEVE",
                            status="FAILED",
                            summary=f"retrieval error: {exc}",
                            detail={"error_type": "RETRIEVAL_ERROR"}),
                {})
    if not hits:
        return (Observation(step_id=step["id"], action="RETRIEVE",
                            status="FAILED",
                            summary="retrieval returned no evidence",
                            detail={"error_type": "RETRIEVAL_EMPTY"}),
                {})
    chunks = [{"source_id": h.get("source_id", ""), "chunk_id": h.get(
        "chunk_id", ""), "text": h.get("text", "")[:600]} for h in hits]
    summary = " | ".join(c["chunk_id"] for c in chunks)[:400]
    return (Observation(step_id=step["id"], action="RETRIEVE", status="OK",
                        summary=f"evidence: {summary}",
                        detail={"chunks": chunks},
                        latency_s=time.perf_counter() - t0),
            {"chunks": chunks})


def _exec_check(step, observations, ctx, t0):
    """CHECK verifies a claim (input) against observations using the T4
    verifier semantics: the claim must state an expected value that an
    earlier step produced. A non-quantitative claim (no extractable
    answer) is recorded, not failed — it cannot be machine-checked, and
    failing it would spuriously trigger replanning."""
    claim = (step.get("input") or "").strip()
    deps = step.get("depends_on", []) or []
    dep_answers = [observations[d]["summary"] for d in deps
                   if d in observations]
    if not claim or not dep_answers:
        return (Observation(step_id=step["id"], action="CHECK",
                            status="FAILED",
                            summary="CHECK needs an input claim and a "
                                    "dependency answer",
                            detail={"error_type": "TOOL_ARGUMENT_INVALID"}),
                {})
    from sciencemath.evaluation.extraction import answers_match
    from sciencemath.executive.verify import extract_final_answer

    def _extractable(text: str) -> str:
        v = extract_final_answer(text, "numeric")
        if v is None:
            v = extract_final_answer(text, "text")
        return str(v) if v is not None else (text or "").strip()

    claim_ans = extract_final_answer(claim, "numeric")
    if claim_ans is None:
        claim_ans = extract_final_answer(claim, "text")
    if claim_ans is None:
        return (Observation(step_id=step["id"], action="CHECK",
                            status="OK",
                            summary="claim noted; not machine-checkable "
                                    "(no extractable value)",
                            detail={"claim": claim,
                                    "dep_answers": dep_answers},
                            latency_s=time.perf_counter() - t0),
                {"check_ok": True})
    ok = any(answers_match(str(claim_ans), _extractable(a))
             for a in dep_answers)
    return (Observation(step_id=step["id"], action="CHECK",
                        status="OK" if ok else "FAILED",
                        summary=("claim consistent with step results"
                                 if ok else
                                 "claim contradicts step results"),
                        detail={"claim": claim, "dep_answers": dep_answers},
                        latency_s=time.perf_counter() - t0),
            {"check_ok": ok})


def _exec_synth(state, observations, ctx, t0):
    lines = []
    for sid in state.get("completed_steps", []):
        ob = observations.get(sid)
        if ob is None:
            continue
        line = f"[{sid}] {ob['summary'][:300]}"
        if ob.get("action") == "RETRIEVE" and ob.get("status") == "OK":
            evidence = _chunk_texts(ob)
            if evidence:
                line += "\nEvidence text:\n" + evidence
        lines.append(line)
    prompt = SYNTH_PROMPT.format(question=state["problem"],
                                 obs="\n".join(lines) or "(none)")
    ctx.usage["model_calls"] += 1
    text, n_in, n_out = call_model(ctx.model, ctx.tokenizer, prompt,
                                   ctx.generation)
    ctx.usage["input_tokens"] += n_in
    ctx.usage["output_tokens"] += n_out
    summary = _final_line(text)
    return (Observation(step_id=step_id_of_synth(state), action="SYNTHESIZE",
                        status="OK", summary=summary[:400],
                        detail={"raw": text[:2000]},
                        latency_s=time.perf_counter() - t0,
                        input_tokens=n_in, output_tokens=n_out),
            {"text": text, "answer": summary})


def step_id_of_synth(state) -> str:
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    for st in steps:
        if st.get("action") == "SYNTHESIZE":
            return st.get("id", "synth")
    return "synth"


def _final_line(text: str) -> str:
    """Extractive: last 'Answer:' line, else last non-empty line."""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.lower().startswith("answer:"):
            return line.split(":", 1)[1].strip()
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line:
            return line
    return "(empty)"


def direct_answer(state, ctx, answer_type: str = "numeric",
                  choices: list | None = None) -> tuple[str, int, int]:
    """T7.22 fast path / OFF-mode behavior: the canonical evaluation
    prompt (build_evaluation_content — identical to OFF arm), no
    executive machinery."""
    from sciencemath.evaluation.prompts import build_evaluation_content
    content = build_evaluation_content(state["problem"], answer_type,
                                       choices)
    ctx.usage["model_calls"] += 1
    text, n_in, n_out = call_model(ctx.model, ctx.tokenizer, content,
                                   ctx.generation)
    ctx.usage["input_tokens"] += n_in
    ctx.usage["output_tokens"] += n_out
    return text, n_in, n_out