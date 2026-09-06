# T7 — GitHub Architecture Review (Executive Layer)

**Date:** 2026-09-04 · **Method:** three parallel research passes over the
official READMEs and documentation of the named repositories (architecture
study only; no code copied, no dependency added without measured value).

Reviewed: `langchain-ai/langgraph`, `Future-House/paper-qa`,
`microsoft/autogen` (v0.4 AgentChat stack), `huggingface/smolagents`.

---

## Adopted patterns → Mango executive design

| # | Source | Pattern | Why Mango needs it | Mango implementation |
|---|---|---|---|---|
| A1 | langgraph | **Typed state schema with validated transitions** (channels, `StateGraph(schema)`, invalid update = error) | T7.1/T7.2 require a strict state machine that fails closed; the 1.7B model must never drive free-form conversation state | `executive/state.py`: explicit `STATUS` enum, `STATE_TRANSITIONS` adjacency table, `validate_transition()`, full-state JSON with `schema_version` |
| A2 | langgraph | **Conditional-edge-style routing as deterministic functions** (routing fns, not LLM whimsy, decide the next node) | A 1.7B model cannot be trusted to choose control flow | `runner.py`: the loop's next-state decision is computed by deterministic rules from observations/verification, not model output |
| A3 | langgraph | **Durable execution: checkpoint per completed step; pending-writes so completed work is never re-run** | T7.29/T7.30 require resume with no duplicate tool calls/citations | `executive/checkpoint.py`: atomic JSON snapshot after every completed step; `completed_steps` keyed by step id; resume skips done steps |
| A4 | langgraph | **`recursion_limit` analogue + graceful budget exhaustion** (`RemainingSteps` lets nodes exit cleanly instead of crashing) | T7.13/T7.34 bounded execution | `executive/budgets.py`: predeclared caps; exhaustion produces explicit `BUDGET_EXHAUSTED` termination, not an exception |
| A5 | autogen | **Composable termination conditions returning an explicit stop reason** (`TaskResult.stop_reason`) | T7.14: every run must terminate with exactly one deterministic reason | `executive/stopping.py`-style: `STOP_REASONS` enum; runner evaluates stop controllers in fixed priority order |
| A6 | autogen | **save_state/load_state as a plain serializable dict** (component config separate from runtime state) | T7.29 durable state without a database | same JSON state object; schema_version + migration/incompatibility error (T7.27) |
| A7 | autogen Magentic-One | **Task-ledger / progress-ledger separation: replan on stall, not per step** | T7.12: replan only on meaningful triggers; T7.13 stall detection | replan triggers enumerated (verifier FAIL, retrieval insufficient, contradiction, dependency invalid); progress tracked per step |
| A8 | smolagents | **`final_answer_checks` — wire verification into the same channel as failure recovery** (failing check ⇒ continue, not accept) | T7.11 verify-first; T7.16 no generic "review your answer" | deterministic verify step after every action; FAIL feeds the correction contract |
| A9 | smolagents | **Errors-as-observations** (tool tracebacks recorded and replayed into next-step context) | T7.10 observations; T7.17 structured correction contract | failed tool call becomes a structured FAILED observation with error type; never masquerades as success |
| A10 | smolagents | **Interpreter-level resource caps, not prompt-level promises** | T7.33: the model is not trusted to enforce its own boundaries | action allowlist (REASON/RETRIEVE/MATH_TOOL/CHECK/SYNTHESIZE only); unknown action REJECT; T4/T5R guardrails authoritative |
| A11 | paper-qa | **Generate-then-parse citation anchoring: only supplied context IDs are acceptable** (`used_contexts` check) | T5R citation integrity must survive executive composition | executive synthesis passes only chunk-id-tagged evidence; unsupported claims flagged (T7.28) |
| A12 | paper-qa | **Empty-evidence ⇒ forced insufficiency answer, not speculation** | T6 uncertainty 0.0000; T7.25 | `uncertainty.py` maps observable signals → categorical epistemic status; retrieval-empty ⇒ INSUFFICIENT_INFORMATION path |
| A13 | paper-qa | **Budget knobs on every axis** (max timesteps, search_count, evidence_k) recorded per run | T7.34/T7.39 cost accounting | `configs/executive.yaml` budgets; every trajectory records per-phase latency/tokens/actions |
| A14 | paper-qa | **Query-conditioned intermediate summaries, then compose** (summary-then-compose over raw chunks) | T7.9 context management for a 1.7B model | step context = compact state + relevant observations only, never the full transcript |

## Patterns intentionally NOT adopted

| Source | Pattern | Why not |
|---|---|---|
| langgraph | Pregel-style super-step engine, `Send` fan-out, subgraphs, `Command` navigation | Mango's executive is a bounded sequential loop (T7.15 max steps 6); a graph engine adds abstraction with no measured value at this scale. Sequential selective delegation is a T7 requirement (one executive controller). |
| langgraph | Postgres/SQLite checkpoint savers, LangSmith tracing, encrypted checkpoints | Runtime dependencies + external services for a local 6-GB-VRAM project; JSON snapshots on disk are sufficient and auditable |
| autogen | Multi-agent broadcast teams (RoundRobin/Selector/Magentic-One teams), model-driven speaker selection | T7 forbids swarms by default; roles are the SAME checkpoint with different prompts, invoked sequentially |
| autogen | `UserProxyAgent` blocking-input human-in-the-loop | T7 actions are non-destructive; approval hooks (T7.43-style) are implemented as metadata (`AUTO_APPROVED`/`APPROVAL_REQUIRED`/`FORBIDDEN`) but no interactive blocking |
| smolagents | CodeAgent (Python-code actions) + sandboxed interpreter | T7 explicitly excludes unrestricted code execution; Mango's action space is fixed tool classes |
| smolagents | `planning_interval` periodic replanning | Contradicts T7.12/T7.13: replanning is event-triggered only, max 2 |
| paper-qa | aviary/ldp agent frameworks, litellm, tantivy, PDF pipelines | Heavyweight dependencies with no clear measured value over the native implementation; Mango already owns T4/T5R infrastructure |
| paper-qa | "you won't get good performance with 7B models" acceptance | Mango's thesis is that the deterministic executive supplies what the small model lacks — that is exactly what T7 measures |

## External dependencies added

**None.** All adopted patterns are implemented natively (stdlib + existing
project deps). The review's heavyweight flags (Postgres checkpointer,
LangSmith, aviary/litellm, sandbox services) are all non-essential to the
bounded executive design.