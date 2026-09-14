# Mango — T19 Long-Horizon Planner

## STATUS

PASS

## Entry Gate

PASS

## Starting State

Main commit:
8843ce1c57f6988af40cf4d65e93a001ecd84c08

Architecture:
Mango-4B-System-v1

SCICOMP:
ACTIVE

CODE:
ACTIVE

WEB_RESEARCH:
ACTIVE

DOCUMENT:
ACTIVE

MEMORY:
ACTIVE

PLANNING:
EXPERIMENTAL

Executive Router:
EXPERIMENTAL

Training:
NONE

Weight promotion:
NO

Paid compute:
NOT_USED

## Planner Architecture

plan schema
versioned Plan with goal, constraints, budget, tasks, dependencies, checkpoints, observations, revisions, provenance, stop conditions, and BEST_VERIFIED snapshot. schema_version=1. Unknown schema fails closed.

task schema
typed Task with skill, criteria, dependencies, attempts, side-effect class, approval, and execution_authority always false.

dependency graph
DAG with self-dep, unknown-id, and cycle rejection. Selective descendant invalidation preserves unrelated succeeded work.

budget model
FREE-only max_cost_class with max_tasks, max_replans, max_attempts_per_task, and consumed counters. Paid proposals are blocked.

assumptions
explicit Assumption records; invalidation is a replan trigger, never silent.

observations
fixture/tool results are DATA (instruction_authority 0). Injection cannot authorize completion, deletion, or spend.

checkpointing
periodic snapshots of completed tasks, remaining work, constraints, blockers, and verified artifacts on long plans.

replanning
event-triggered only (dependency fail, assumption, tool, artifact, constraint, goal, evidence). Success/metadata/wording do not replan.

progress retention
succeeded unrelated tasks stay in BEST_VERIFIED across selective invalidation and resume.

completion gate
all mandatory tasks succeeded with evidence; verification/test/freshness required; optional unfinished allowed; premature complete refused.

serialization
deterministic JSON round-trip; resume restores identity, statuses, constraints, and budget.

safety boundary
PROPOSE_ONLY. Planner never initiates filesystem, network, shell, paid, or memory writes. execute() raises ExecutionRefused.

## Execution Authority

Planner authority:
PROPOSE_ONLY

Filesystem mutations:
0

Network calls:
0

Shell calls:
0

Unauthorized memory writes:
0

Paid-service calls:
0

## Benchmarks

### mango-planner-core-v1

Total:
220

Development:
110

Final:
110

Checksum:
271e8f14a4523d32ecd96524088ba5c50176aeca6271fa6df232f2e6c5510fd0

### mango-planning-eval-v1

Total:
400

Development:
200

Final:
200

Checksum:
c588869e25b250159efe4f3a43fdcbc125eb8856d75df0484fa3265d50b6a2d1

### mango-plan-retention-v1

Total:
100

Final:
50

Checksum:
5623544558b28d19f1c6bc8bffe9665cb9694793cfff14fe4e49b7ab7b2d3086

### mango-completion-gate-v1

Total:
120

Final:
60

Checksum:
3b9bec46f35014b8c374aae18da13dcc62ce810c32248b4e2fc4a7a65b7a4877

### mango-planning-loop-v1

Total:
80

Final:
40

Checksum:
f78330c911af2b792caf1481036c94bc01cd90c750d8ae7a135542a3bb602acd

## Baseline

Existing experimental planner:

Goal capture:
1.0000

Constraint capture:
1.0000

Decomposition:
0.0000

Dependency:
0.0000

Skill selection:
0.0000

Replanning:
0.9109

Completion precision:
1.0000

Completion recall:
0.0000

Scenario success:
0.0000

## T19 Results

Goal capture:
1.0000

Constraint capture:
1.0000

Decomposition:
1.0000

Dependency precision:
1.0000

Dependency recall:
1.0000

Acyclic plan rate:
1.0000

Skill selection:
1.0000

Success criteria:
1.0000

Budget compliance:
1.0000

Checkpoint accuracy:
1.0000

Replan precision:
1.0000

Replan recall:
1.0000

Selective invalidation:
1.0000

Progress preservation:
1.0000

Failure classification:
1.0000

Recovery:
1.0000

Loop prevention:
1.0000

Non-progress detection:
1.0000

Completion precision:
1.0000

Completion recall:
1.0000

Blocked task correctness:
1.0000

Approval marking:
1.0000

Resume integrity:
1.0000

Overall scenario success:
1.0000

## Critical Safety

Unauthorized action:
0

External side effects:
0

Accepted cycles:
0

False complete:
0

Paid-service bypass:
0

Policy override:
0

Unbounded retry:
0

Fabricated skill:
0

Fabricated tool result:
0

Silent constraint drop:
0

Silent completed-work loss:
0

Prompt injection success:
0

## Long-Horizon Stress

Scenarios:
315

Mean tasks:
5.012698412698413

Maximum tasks:
16

Successful:
275

Replans:
25

Progress retained:
1.0000

Loops:
0

False completes:
0

## Multi-Skill Planning

PLANNING → CODE:
PASS

PLANNING → SCICOMP:
PASS (no independent execution; propose-only tasks)

PLANNING → WEB_RESEARCH:
PASS

PLANNING → DOCUMENT:
PASS

PLANNING → MEMORY:
PASS

## Protection Battery

T4:
PASS

T5R:
PASS

SciComp:
PASS

CODE:
PASS

WEB_RESEARCH:
PASS

DOCUMENT:
PASS

MEMORY:
PASS

Capacity:
PASS

Correction:
PASS

Extraction:
PASS

Fidelity:
PASS

Security:
PASS

## Performance

Plan creation:
0.345 ms mean

Validation:
0.376 ms mean

Replan:
0.351 ms mean

Checkpoint save:
0.502 ms mean

Resume:
0.243 ms mean

Average tasks:
5

Average replans:
0

RAM:
66 MB

VRAM:
0 MB

## Tests

Collected:
1326

Passed:
1324

Failed:
0

Skipped:
2

Errors:
0

Duration:
45.005 s

## Final Audit

Passed:
76

Failed:
0

## PLANNING Decision

PROMOTE_PLANNING_SKILL

## PLANNING Availability

Before:
EXPERIMENTAL

After:
ACTIVE

## Executive Router

UNCHANGED

KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL

## Weight Promotion

NO

## Training

NONE

## Paid Compute

NOT_USED

## Main Finding

Answer:

Did Mango become a reliable long-horizon planner capable of decomposing,
sequencing, monitoring, revising, resuming, and correctly completion-gating
complex multi-skill work while retaining verified progress and maintaining
zero independent execution authority?

YES

## Dominant Remaining Bottleneck

Propose-only planner is deterministic and template-driven; future work is an autonomous workflow/action layer, not T19.

## T19 Family Closure

CLOSED

## Ready for T20

YES

## Highest-Value Next Step

Keep the Executive Router experimental. Do not start T20 in this branch. Treat PLANNING as propose-only; any action layer is a later milestone.
