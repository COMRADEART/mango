"""scicomp — the T11 Scientific Computing Laboratory.

Mango reasons; deterministic scientific-computing tools calculate.

Public surface:

* ``executor.execute(request)`` — the ONLY entry point. Takes a
  structured request ({"operation", "inputs", "options"}), returns a
  structured envelope ({status, result, diagnostics, warnings,
  provenance, cross_check, runtime}).
* ``registry`` — the closed catalogue of approved operations.
* ``sandbox`` — the safe expression language (T4-hardened AST gate).
* ``router`` — deterministic compute-eligibility routing (T11.13).

Security contract (T11.3, T11.25): no arbitrary Python, no eval of
untrusted text (expressions pass the safeparse AST whitelist), no shell,
no network, no filesystem access, hard resource caps everywhere, CPU
only. Violations fail closed.
"""
from sciencemath.scicomp.executor import execute, limits, operations, \
    registry_sha256
from sciencemath.scicomp.schemas import ALL_STATUSES, Limits

__all__ = ["execute", "limits", "operations", "registry_sha256",
           "ALL_STATUSES", "Limits"]