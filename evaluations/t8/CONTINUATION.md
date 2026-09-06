# T8 continuation — 2026-09-05

**Closure update:** The resumed study is complete with DO_NOT_MIGRATE. See
T8_FINAL_REPORT.md, FINAL_DECISION.json and final_audit.json. All finalist arms
and checkpoint reload verification completed; 707 tests passed. No GPU job
needs resuming. The notes below are historical and superseded by the final report.

The five model-only evaluations and Pareto analysis are saved. No candidate
clears the recorded model-only migration gate. Final selection remains pending.

At approximately 08:33 local time, Python PID 37244 was still using the GPU
and Qwen3-4B's T4 tool predictions were actively growing. The existing run
was left intact; no competing GPU job was launched.

Prepared the upcoming T5R evaluations:
- Candidate summaries identify the actual base model and absence of adapter.
- Candidate resume fingerprints include model identity and generation settings.
- Token-budget overrides reset between loads and cannot leak from the parent
  environment into the default-budget finalist subprocess.

Validation: all 50 tests in test_t8_integration_arms.py,
test_t8_capacity.py, and test_t8_capacity_suite.py passed with Python 3.12.

Next: inspect completion of the existing T4 job before resuming
scripts/t8_run_t4_finalists.py, then run scripts/t8_run_t5r_finalists.py
sequentially on the GPU. Do not infer full integration completion from partial
prediction files. Training feasibility and final T8 reporting remain pending.
