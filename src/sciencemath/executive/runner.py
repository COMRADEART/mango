"""T7.14/T7.22/T7.33/T7.34/T7.35 — The executive loop.

A bounded, deterministic plan -> execute -> observe -> verify ->
re-plan controller around Mango-v0.1 (weights untouched). Every
next-state decision is computed by rules from observations and
verification results — the model proposes content, never control flow.
All budgets, features (ablations), and stopping reasons are recorded in
the result. Malformed transitions fail closed (state.transition
raises; the loop terminates SYSTEM_ERROR rather than improvising).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sciencemath.executive import state as st
from sciencemath.executive import budgets as bmod
from sciencemath.executive import classify as cls_mod
from sciencemath.executive import understand as und
from sciencemath.executive import plan as plan_mod
from sciencemath.executive import execute as ex
from sciencemath.executive import verify as ver
from sciencemath.executive import uncertainty as unc
from sciencemath.executive import correction as corr
from sciencemath.executive import replan as rp
from sciencemath.executive import checkpoint as ckpt
from sciencemath.executive.trajectory import TrajectoryLogger
from sciencemath.executive.llm import call_model, ModelCallError

DEFAULT_FEATURES = {
    "executive": True,          # master switch (OFF arm: False)
    "model_plan": True,         # model-proposed plan (else deterministic)
    "tools": True,              # MATH_TOOL executes (C/D/E arms)
    "retrieval": True,          # RETRIEVE executes
    "verification": True,       # verify pass (D/E)
    "replanning": True,         # E
    "distractor_filter": True,  # F disables
    "correction_gate": True,    # G disables
    "fast_path": True,          # T7.22 simple-question bypass
}


@dataclass
class ExecContext:
    model: object
    tokenizer: object
    registry: object | None = None
    retriever: object | None = None
    generation: dict = field(default_factory=dict)
    usage: dict = field(default_factory=bmod.default_usage)
    budgets: bmod.Budgets = field(default_factory=bmod.Budgets)
    features: dict = field(default_factory=lambda: dict(DEFAULT_FEATURES))
    trajectory: TrajectoryLogger | None = None
    checkpointer: ckpt.RunCheckpointer | None = None
    retrieval_k: int = 3

    def feat(self, name: str) -> bool:
        return bool(self.features.get(name,
                                      DEFAULT_FEATURES.get(name, True)))


# ---- deterministic state routing -------------------------------------------
def _legal_path(state: str, target: str) -> list[str]:
    """BFS shortest legal transition path current -> target. The state
    machine is small and fixed, so this is total and deterministic.
    REPLANNING is never used as a transit state on the way to EXECUTING
    (replanning is entered deliberately after verification, not in
    passing)."""
    if state == target:
        return []
    from collections import deque
    q = deque([[state]])
    seen = {state}
    while q:
        path = q.popleft()
        for nxt in sorted(st.STATE_TRANSITIONS.get(path[-1], frozenset())):
            if nxt in seen:
                continue
            if nxt == st.REPLANNING and target == st.EXECUTING:
                continue
            if nxt == target:
                return path[1:] + [nxt]
            seen.add(nxt)
            q.append(path + [nxt])
    return []


def _goto(state: dict, target: str) -> dict:
    for nxt in _legal_path(state.get("status", st.RECEIVED), target):
        state = st.transition(state, nxt)
    return state


def _log(ctx, run_id, event, payload):
    if ctx.trajectory:
        ctx.trajectory.log(run_id, event, payload)


def _terminate(state: dict, reason: str, *, answer=None, status=None,
               failure_category=None, observations=None) -> dict:
    target = st.REASON_TO_STATE.get(reason, st.FAILED)
    state = _goto(state, target)
    state["termination_reason"] = reason
    if answer is not None:
        state["final_answer"] = answer
    if status is not None:
        state["evidence_status"] = status
    elif state.get("evidence_status") is None:
        # T25 remediation (authorization §8, semantic rules R1-R4 in
        # evaluations/t25/remediation/T25_SEMANTIC_RULES.md): a terminal
        # without an assigned epistemic status (budget/stall/system
        # paths) derives one from the run's own recorded signals via the
        # frozen uncertainty engine — "status absent" is not a status.
        # Cause fields (termination_reason/failure_category) are
        # unchanged, and no mapping here was chosen against any
        # aggregate (rule R5).
        state["evidence_status"] = _derived_status(state, observations)
    state["failure_category"] = failure_category
    return state


def _derived_status(state: dict, observations: dict | None) -> str:
    """Terminal status derived from the run's recorded signals via the
    frozen uncertainty engine. The interrupted round has no final
    verification, so its verdict is absent from the signal vector
    (decide_status treats that as unverified). Derivation must never
    crash the terminal; if it cannot run, the no-signal status is used."""
    try:
        signals = unc.signals_from_run(state, observations or {}, {}, [])
        return unc.decide_status(signals)
    except Exception:  # noqa: BLE001
        return "UNCERTAIN"


def _hard_fail(state: dict, category: str, error: str, *,
               observations: dict | None = None) -> dict:
    """Out-of-band failure: reach FAILED deterministically, no raise."""
    try:
        state = _goto(state, st.FAILED)
    except st.TransitionError:
        state["status"] = st.FAILED
        state.setdefault("transitions", []).append(st.FAILED)
    state["termination_reason"] = "SYSTEM_ERROR"
    state["failure_category"] = category
    state["error"] = error
    if state.get("evidence_status") is None:
        state["evidence_status"] = _derived_status(state, observations)
    return state


def run_executive(question: str, question_id: str, *, ctx: ExecContext,
                  answer_type: str = "numeric",
                  choices: list | None = None,
                  expected: str | None = None) -> dict:
    """One bounded executive run. Never raises for per-run failures —
    failures are recorded and terminated with a stop reason."""
    t_start = time.perf_counter()
    state = st.new_run(run_id=question_id, problem=question).to_dict()
    observations: dict[str, dict] = {}
    tool_results: list = []
    supplied_chunks: list = []
    corrections_used = 0
    correction_event = None   # pre/post answer pair when a correction
                              # actually changed the answer (T7.36 net
                              # gain is MEASURED from this, no proxy)
    plan_meta: dict = {"first_attempt_valid": None, "retry_valid": None,
                       "fallback_used": False, "plan_attempts": 0}
    result = {"question_id": question_id, "answer_type": answer_type}
    # budgets are per run: the ExecContext is reused across questions in
    # batch evaluation, so usage is reset at every run start
    ctx.usage = bmod.default_usage()
    # ---- resume (T7.28): a durable checkpoint restores completed steps
    # and their observations; completed tool/retrieval calls are never
    # re-executed
    if ctx.checkpointer is not None:
        try:
            payload = ctx.checkpointer.load(question_id)
        except Exception:  # noqa: BLE001
            payload = None
        if payload and isinstance(payload, dict):
            saved = payload.get("state") or {}
            saved_steps = [s for s in (saved.get("completed_steps") or [])
                           if isinstance(s, str)]
            if saved_steps:
                state["completed_steps"] = list(saved_steps)
                state["plan"] = saved.get("plan")
                state["plan_version"] = saved.get("plan_version", 1)
                state["replans"] = saved.get("replans", 0)
                state["conflicts"] = saved.get("conflicts", [])
                state["included_facts"] = saved.get("included_facts", [])
                state["distractors"] = saved.get("distractors", [])
                for ob in saved.get("observations") or []:
                    if isinstance(ob, dict) and ob.get("step_id"):
                        observations[ob["step_id"]] = ob
                plan = state.get("plan") or {}
                plan_meta["fallback_used"] = (
                    plan.get("source") == "deterministic_fallback")
                for ob in observations.values():
                    if ob.get("action") == "MATH_TOOL" and \
                            ob.get("status") == "OK":
                        r = (ob.get("detail") or {}).get("result")
                        if r is not None:
                            tool_results.append(r)
                    if ob.get("action") == "RETRIEVE" and \
                            ob.get("status") == "OK":
                        supplied_chunks.extend(
                            (ob.get("detail") or {}).get("chunks") or [])
                state["resumed"] = True
                _log(ctx, question_id, "resume",
                     {"completed_steps": list(state["completed_steps"])})

    try:
        # ---- master switch (T7.37): features {'executive': false} runs
        # the canonical evaluation prompt directly — the OFF arm never
        # touches the executive machinery
        if not ctx.feat("executive"):
            text, n_in, n_out = ex.direct_answer(state, ctx, answer_type,
                                                 choices)
            extracted = ver.extract_final_answer(text, answer_type, choices)
            state = _terminate(state, "SOLVED_UNVERIFIED",
                               answer=extracted,
                               status="PARTIALLY_SUPPORTED")
            return _pack(state, result, observations, plan_meta,
                         t_start, raw=text, tokens=(n_in, n_out),
                         fast_path=True, usage=ctx.usage)

        # ---- CLASSIFYING ----
        st.transition(state, st.CLASSIFYING)
        c = cls_mod.classify_problem(question)
        state.update({"problem_type": c["problem_type"],
                      "complexity": c["complexity"],
                      "resources": c["resources"]})
        _log(ctx, question_id, "classified", c)

        # ---- fast path (T7.22) ----
        if ctx.feat("fast_path") and cls_mod.fast_path_eligible(c):
            text, n_in, n_out = ex.direct_answer(state, ctx, answer_type,
                                                 choices)
            extracted = ver.extract_final_answer(text, answer_type, choices)
            state = _terminate(state, "SOLVED_UNVERIFIED",
                               answer=extracted,
                               status="PARTIALLY_SUPPORTED")
            return _pack(state, result, observations, plan_meta,
                         t_start, raw=text, tokens=(n_in, n_out),
                         fast_path=True, usage=ctx.usage)

        # ---- PLANNING (understanding recorded inside) ----
        state = _goto(state, st.PLANNING)
        u = und.extract_understanding(question)
        sentences = und._split_sentences(question)
        labels = und.label_facts(question, sentences,
                                 filter_enabled=ctx.feat("distractor_filter"))
        fx = und.filter_context(sentences, labels)
        state["included_facts"] = fx["included"]
        state["distractors"] = [l.text for l in labels
                                if l.label == "IRRELEVANT"]
        conflicts = und.extract_conflicts(question, sentences)
        state["conflicts"] = conflicts
        understanding = {"question_target": u.question_target,
                         "knowns": u.knowns, "unknowns": u.unknowns,
                         "expression": "", "constraints": [],
                         "missing": ["conflicting values for " + cf["unit"]
                                     for cf in conflicts]}
        _log(ctx, question_id, "understanding", understanding)

        # ---- PLANNING: model plan -> retry -> deterministic fallback ----
        if state.get("plan") is None:
            plan, plan_meta = _build_plan(state, c, understanding, ctx)
            state["plan"] = plan
            state["plan_version"] = 1
            _log(ctx, question_id, "plan", {"plan": plan, **plan_meta})

        # ---- EXECUTING / VERIFYING / REPLANNING rounds ----
        for round_i in range(1 + ctx.budgets.max_replans):
            state = _execute_plan(state, observations, ctx,
                                   tool_results, supplied_chunks, t_start)
            if state["status"] in st.TERMINAL_STATES:
                return _pack(state, result, observations, plan_meta,
                             t_start, usage=ctx.usage)

            if ctx.feat("verification"):
                vres = ver.verify_step_consistency(observations,
                                                   state["plan"])
            else:
                vres = {"failed_steps": [], "contradictions": [],
                        "replan_triggers": []}
            state["verification"].append(vres)
            _log(ctx, question_id, "verification", vres)

            if not ctx.feat("replanning") or round_i >= ctx.budgets.max_replans:
                break
            do_replan, trigger, reason = rp.should_replan(state, vres,
                                                          ctx.budgets,
                                                          observations)
            if not do_replan:
                break
            if trigger == "CONTRADICTION":
                # a contradiction in the problem text is not fixable by
                # re-executing a plan — re-planning only burns the budget
                # to STALL. Surface it to the uncertainty engine, which
                # terminates with CONFLICTING_EVIDENCE instead.
                _log(ctx, question_id, "contradiction_terminal",
                     {"reason": reason})
                break
            new_plan = _amend_plan(state, c, understanding, trigger)
            stall = rp.register_failure(state, new_plan,
                                        f"{trigger}: {reason}")
            if stall or plan_mod.plan_fingerprint(new_plan) == \
                    plan_mod.plan_fingerprint(state["plan"]):
                state = _terminate(state, "STALLED",
                                   failure_category="LOOP_STALLED",
                                   observations=observations)
                return _pack(state, result, observations, plan_meta,
                             t_start, usage=ctx.usage)
            state["plan"] = new_plan
            state["plan_version"] += 1
            state["replans"] += 1
            ctx.usage["replans"] = state["replans"]  # budget axis is live
            # Re-arm ONLY the replacement plan's steps: pre-replan
            # evidence for non-colliding steps survives, and the new
            # plan's steps actually execute (a blanket observations
            # clear combined with the fallback's s1..sn id collision
            # used to make every replan a silent no-op).
            new_ids = {s.get("id") for s in new_plan.get("steps", [])}
            state["completed_steps"] = [
                sid for sid in state.get("completed_steps", [])
                if sid not in new_ids]
            state["observations"] = [
                ob for ob in state.get("observations", [])
                if ob.get("step_id") not in new_ids]
            for sid in new_ids:
                observations.pop(sid, None)
            _log(ctx, question_id, "replan",
                 {"trigger": trigger, "reason": reason,
                  "plan": new_plan})

        # ---- SYNTHESIZING ----
        state = _goto(state, st.SYNTHESIZING)
        synth_obs = observations.get(ex.step_id_of_synth(state))
        final_text = (synth_obs or {}).get("detail", {}).get("raw", "") \
            if synth_obs else ""
        extracted = ver.extract_final_answer(final_text, answer_type,
                                             choices) if final_text else None

        vfinal: dict = {"verdict": "UNKNOWN", "citations": None}
        if ctx.feat("verification"):
            vfinal = ver.verify_final(extracted, final_text, tool_results,
                                      supplied_chunks)
        missing = understanding.get("missing", [])
        signals = unc.signals_from_run(state, observations, vfinal, missing)
        signals["text_insufficient"] = unc.status_from_text(final_text)
        epistemic = unc.decide_status(signals)

        # correction gate (T7.16-T7.18) — budget-guarded like every
        # other model call
        if (ctx.feat("correction_gate") and vfinal["verdict"] == "FAILED"
                and extracted is not None):
            cctx = _correction_ctx(vfinal, tool_results)
            eligible, why = corr.correction_eligible(state, cctx,
                                                     corrections_used)
            _log(ctx, question_id, "correction_gate",
                 {"eligible": eligible, "why": why})
            guard = bmod.exceeded(dict(ctx.usage, elapsed_s=0.0),
                                  ctx.budgets)
            if guard:
                eligible = False
                why = f"budget {guard} exhausted before correction"
            if eligible:
                corrections_used += 1
                pre_extracted = extracted
                try:
                    ctx.usage["model_calls"] += 1
                    ctext, _cn, _co = call_model(ctx.model, ctx.tokenizer,
                                                 corr.build_correction_input(
                                                     state, cctx, extracted),
                                                 ctx.generation)
                    ctx.usage["input_tokens"] += _cn
                    ctx.usage["output_tokens"] += _co
                except ModelCallError as exc:
                    ctext = ""
                    _log(ctx, question_id, "correction_error",
                         {"error": str(exc)})
                parsed = corr.parse_correction(ctext, extracted)
                if not parsed["unchanged"]:
                    extracted = parsed["answer"]
                    # re-extract through the frozen extractor so a
                    # corrected sentence normalizes like every other
                    # final answer (raw parsed line is not comparable)
                    re_ext = ver.extract_final_answer(str(extracted),
                                                      answer_type, choices)
                    if re_ext is not None:
                        extracted = re_ext
                    final_text = parsed["raw"]
                    vfinal = ver.verify_final(extracted, final_text,
                                              tool_results, supplied_chunks)
                    signals = unc.signals_from_run(state, observations,
                                                   vfinal, missing)
                    signals["text_insufficient"] = \
                        unc.status_from_text(final_text)
                    epistemic = unc.decide_status(signals)
                    correction_event = {
                        "pre_answer": str(pre_extracted),
                        "post_answer": str(extracted),
                    }

        # G8 evidence: the final citation audit (post-correction, if any)
        # is recorded per run, together with how many chunks were
        # actually supplied — a harness-injected retrieval failure leaves
        # nothing to cite and is not held against the executive
        state["final_citations"] = vfinal.get("citations")
        state["supplied_chunks"] = len(supplied_chunks)
        state["corrections_used"] = corrections_used
        state["correction_event"] = correction_event

        # stopping decision (T7.14)
        if extracted is None and (not signals.get("good_retrieval")
                                  or signals.get("text_insufficient")):
            state = _terminate(state, "INSUFFICIENT_INFORMATION",
                               answer=None, status="INSUFFICIENT_INFORMATION",
                               failure_category=(None if
                                                 signals.get("text_insufficient")
                                                 else "MODEL_EMPTY_OUTPUT"))
            return _pack(state, result, observations, plan_meta,
                         t_start, raw=final_text, usage=ctx.usage)
        if unc.answer_should_decline(epistemic, signals):
            answer = unc.decline_answer(epistemic)
            reason = ("INSUFFICIENT_INFORMATION" if epistemic ==
                      "INSUFFICIENT_INFORMATION" else "CONFLICTING_EVIDENCE")
            state = _terminate(state, reason, answer=answer,
                               status=epistemic)
            return _pack(state, result, observations, plan_meta,
                         t_start, raw=answer, usage=ctx.usage)
        reason = "SOLVED_VERIFIED" if vfinal.get("verdict") == "VERIFIED" \
            else "SOLVED_UNVERIFIED"
        state = _terminate(state, reason, answer=extracted,
                           status=epistemic)
        return _pack(state, result, observations, plan_meta,
                     t_start, raw=final_text, usage=ctx.usage)

    except st.TransitionError as exc:
        state = _hard_fail(state, "SYSTEM_ERROR", f"state machine: {exc}",
                           observations=observations)
        _log(ctx, question_id, "state_error", {"error": str(exc)})
        return _pack(state, result, observations, plan_meta,
                     t_start, usage=ctx.usage, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        from sciencemath.executive.failures import classify_exception
        cat = classify_exception(exc)
        _log(ctx, question_id, "error", {"error": str(exc)})
        state = _hard_fail(state, cat, f"{type(exc).__name__}: {exc}",
                           observations=observations)
        return _pack(state, result, observations, plan_meta,
                     t_start, usage=ctx.usage, error=str(exc))


# ---- phase helpers ----------------------------------------------------------
def _build_plan(state: dict, c: dict, understanding: dict,
                ctx: ExecContext) -> tuple[dict, dict]:
    """Model plan with schema-feedback retry, then deterministic
    fallback. First-attempt / retry validity recorded separately."""
    meta: dict = {"first_attempt_valid": None, "retry_valid": None,
                  "fallback_used": False, "plan_attempts": 0}
    if not ctx.feat("model_plan"):
        p = plan_mod.fallback_plan(c, understanding)
        meta["model_plan"] = False
        return p, meta

    prompt = ex.PLAN_PROMPT.format(
        question=state["problem"],
        knowns=", ".join(understanding["knowns"]) or "(none)",
        unknowns=", ".join(understanding["unknowns"]) or "(none)",
        constraints=", ".join(understanding["constraints"]) or "(none)",
        missing=", ".join(understanding["missing"]) or "(none)",
        schema=plan_mod.PLAN_SCHEMA_DOC)
    for attempt in range(ctx.budgets.max_plan_attempts):
        guard = bmod.exceeded(dict(ctx.usage, elapsed_s=0.0), ctx.budgets)
        if guard:
            break
        meta["plan_attempts"] = attempt + 1
        try:
            ctx.usage["model_calls"] += 1
            raw, _ni, _no = call_model(ctx.model, ctx.tokenizer, prompt,
                                       ctx.generation)
        except ModelCallError as exc:
            raw = ""
            meta[f"attempt_{attempt}_error"] = str(exc)
        proposed = plan_mod.parse_model_plan(raw) if raw else None
        if proposed is not None:
            v = plan_mod.validate_plan(proposed,
                                       max_steps=ctx.budgets.max_plan_steps)
            if attempt == 0:
                meta["first_attempt_valid"] = v.ok
            else:
                meta["retry_valid"] = v.ok
            if v.ok:
                proposed["source"] = "model"
                return proposed, meta
            prompt += ex.PLAN_RETRY_SUFFIX.format(feedback=v.feedback)
        else:
            if attempt == 0:
                meta["first_attempt_valid"] = False
            else:
                meta["retry_valid"] = False
            prompt += ex.PLAN_RETRY_SUFFIX.format(
                feedback="Your response was not parseable as a JSON "
                         "plan. Output ONLY the JSON object.")
    meta["fallback_used"] = True
    return plan_mod.fallback_plan(c, understanding), meta


def _amend_plan(state: dict, c: dict, understanding: dict,
                trigger: str) -> dict:
    """Deterministic plan amendment per trigger (never model-invented)."""
    u = dict(understanding)
    if trigger == "RETRIEVAL_INSUFFICIENT":
        u["question_target"] = (u.get("question_target", "") + " " +
                                " ".join(u.get("knowns", [])[:3])).strip() \
            or "topic facts"
        # the replacement plan must actually re-query: a fallback for a
        # GENERAL/NONE classification would otherwise drop retrieval
        # entirely and the replan could never fix what it was triggered by
        u["force_retrieval"] = True
    if trigger == "VERIFICATION_FAILED":
        u["expression"] = ""
    return plan_mod.fallback_plan(c, u)


def _execute_plan(state: dict, observations: dict, ctx: ExecContext,
                  tool_results: list, supplied_chunks: list,
                  t_start: float) -> dict:
    """Execute all plan steps in order; budget-guarded (BEFORE and after
    each step, so an exhausted cap funds no further calls); checkpoint
    after each completed step. Returns the state (OBSERVING when done).
    Note: a single hung generation cannot be preempted mid-call — the
    step-time budget is enforced between steps."""
    for step in state["plan"]["steps"]:
        sid = step.get("id")
        if sid in state["completed_steps"]:
            continue  # resume semantics: never re-run a completed step

        if step.get("action") == "MATH_TOOL" and not ctx.feat("tools"):
            observations[sid] = {"step_id": sid, "action": "MATH_TOOL",
                                 "status": "SKIPPED",
                                 "summary": "tools disabled (ablation)",
                                 "detail": {}}
            state["completed_steps"].append(sid)
            continue
        if step.get("action") == "RETRIEVE" and not ctx.feat("retrieval"):
            observations[sid] = {"step_id": sid, "action": "RETRIEVE",
                                 "status": "SKIPPED",
                                 "summary": "retrieval disabled (ablation)",
                                 "detail": {}}
            state["completed_steps"].append(sid)
            continue

        # pre-step budget guard (caps are totals; a reached cap funds
        # no further call — with max_model_calls=0 nothing executes)
        pre_usage = dict(ctx.usage)
        pre_usage["elapsed_s"] = time.perf_counter() - t_start
        cap = bmod.exceeded(pre_usage, ctx.budgets)
        if cap:
            state["budget_usage"] = pre_usage
            return _terminate(state, "BUDGET_EXHAUSTED",
                              failure_category=cap,
                              observations=observations)

        state = _goto(state, st.EXECUTING)  # PLANNING/OBSERVING->...->EXECUTING
        ob, outputs = ex.execute_step(state, step, observations, ctx)
        od = ob.to_dict()
        od["detail"]["signature"] = ckpt.signature_of_step(step)
        observations[sid] = od
        state["observations"].append(od)
        state["completed_steps"].append(sid)

        # evidence graph (T7.26): one node per step, produced-by edges
        graph = state.setdefault("evidence_graph",
                                 {"nodes": [], "edges": []})
        ckpt.add_node(graph, ckpt.evidence_graph_node(
            {"MATH_TOOL": "tool", "RETRIEVE": "retrieval"}.get(
                step.get("action"), "claim"),
            f"step:{sid}", od["summary"], sid))
        for dep in step.get("depends_on", []) or []:
            ckpt.add_edge(graph, ckpt.evidence_graph_edge(
                f"step:{dep}", f"step:{sid}", "produced"))

        if step.get("action") == "MATH_TOOL" and outputs.get(
                "tool_result") is not None:
            tool_results.append(outputs["tool_result"].result)
        if step.get("action") == "RETRIEVE":
            # retrieval history lives on the state, not only in the live
            # observations: a replan re-arm legitimately drops failed
            # RETRIEVE steps, and the uncertainty engine must still know
            # retrieval never produced usable evidence
            if ob.status == "OK":
                state["retrieval_ok"] = True
            elif (ob.detail or {}).get("error_type") == "RETRIEVAL_EMPTY":
                state["retrieval_empty"] = True
        if step.get("action") == "RETRIEVE" and outputs.get("chunks"):
            supplied_chunks.extend(outputs["chunks"])

        # step wall-time budget (enforced between steps; a hung single
        # generation cannot be preempted mid-call)
        if ob.latency_s > ctx.budgets.max_step_seconds:
            state["budget_usage"] = dict(
                ctx.usage, elapsed_s=time.perf_counter() - t_start,
                last_step_s=ob.latency_s)
            return _terminate(state, "BUDGET_EXHAUSTED",
                              failure_category="max_step_seconds",
                              observations=observations)

        # post-step budget guard (deterministic priority from
        # budgets.exceeded; count axes are >= the cap)
        usage = dict(ctx.usage)
        usage["elapsed_s"] = time.perf_counter() - t_start
        state["budget_usage"] = usage
        cap = bmod.exceeded(usage, ctx.budgets)
        if cap:
            return _terminate(state, "BUDGET_EXHAUSTED",
                              failure_category=cap,
                              observations=observations)

        # OBSERVING after each step
        state = st.transition(state, st.OBSERVING)

        if ctx.checkpointer:
            ctx.checkpointer.save(state, state["evidence_graph"])

    return state


def _correction_ctx(vfinal: dict, tool_results: list) -> dict:
    """Verification fields the correction contract needs. Empty string
    when there is genuinely no external evidence — the correction gate
    must never fire on a placeholder."""
    trs = ", ".join(str(tr) for tr in tool_results[-3:])
    cit = vfinal.get("citations") or {}
    invalid = cit.get("invalid_refs") or []
    if invalid:
        evidence = ("answer cites chunk ids that were never supplied: "
                    + ", ".join(invalid))
    elif tool_results:
        evidence = "tool recomputation: " + trs
    else:
        evidence = ""
    return {
        "verdict": vfinal.get("verdict"),
        "failing_check": ("answer did not match tool recomputation "
                          f"[{trs}]" if tool_results else
                          "answer failed citation check"),
        "contradicting_evidence": evidence,
        "expected": trs,
    }


def _pack(state, result, observations, plan_meta, t_start, *,
          raw=None, tokens=None, fast_path=False, usage=None,
          error=None) -> dict:
    """Final result dict: cost fields (T7.39) + plan-validity fields
    (T7.23). No hidden CoT: `raw` is the already think-stripped output.
    Token/tool/retrieval accounting comes from the per-run usage dict."""
    usage = usage or {}
    out = dict(result)
    out.update({
        "final_answer": state.get("final_answer"),
        "termination_reason": state.get("termination_reason"),
        "evidence_status": state.get("evidence_status"),
        "failure_category": state.get("failure_category"),
        "problem_type": state.get("problem_type"),
        "complexity": state.get("complexity"),
        "resources": state.get("resources"),
        "fast_path": fast_path,
        "first_attempt_plan_valid": plan_meta.get("first_attempt_valid"),
        "retry_plan_valid": plan_meta.get("retry_valid"),
        "plan_fallback_used": plan_meta.get("fallback_used", False),
        "plan_attempts": plan_meta.get("plan_attempts", 0),
        "plan_source": (state.get("plan") or {}).get("source"),
        "steps_executed": len(state.get("completed_steps", [])),
        "replans": state.get("replans", 0),
        "transitions": state.get("transitions", []),
        "latency_s": round(time.perf_counter() - t_start, 3),
        "input_tokens": (tokens or (usage.get("input_tokens", 0),
                                    usage.get("output_tokens", 0)))[0],
        "output_tokens": (tokens or (usage.get("input_tokens", 0),
                                     usage.get("output_tokens", 0)))[1],
        "model_calls": usage.get("model_calls", 0),
        "tool_calls": usage.get("tool_calls", 0),
        "retrievals": usage.get("retrievals", 0),
        "distractors_removed": len(state.get("distractors", [])),
        "citations": state.get("final_citations"),
        "supplied_chunks": state.get("supplied_chunks"),
        "corrections_used": state.get("corrections_used", 0),
        "correction_event": state.get("correction_event"),
        "error": error,
    })
    out["raw"] = raw
    out["state"] = {k: v for k, v in state.items()
                    if k not in ("observations", "_t0")}
    out["observations"] = list(observations.values())
    return out