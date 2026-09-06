"""T6.0 — Entry gate for the curriculum milestone (T6).

Verifies, BEFORE any new training:
  1. the complete existing test suite (run separately; result passed in)
  2. Mango-v0.1 (Qwen3-1.7B + T3 LoRA, unmerged) loads and the adapter is
     active
  3. T4 math tools function (calculator / symbolic / verifier smoke)
  4. T5R retrieval functions (retriever + one grounded RAG answer)
  5. frozen benchmark checksums (eval suite v1, tool suite v1, rag suite v1,
     sciencemath-sft-v1 corpus, T3 adapter weights)
  6. environment (GPU/VRAM/CUDA/python/torch/transformers/PEFT/
     bitsandbytes/accelerate/RAM/disk) and git state

Writes evaluations/t6_entry_gate.json. Exit code 0 => T6 UNBLOCKED, 1 =>
T6 BLOCKED.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "evaluations" / "t6_entry_gate.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_file_level_checksums(suite_dir: Path) -> dict:
    cs = json.loads((suite_dir / "checksum.json").read_text(encoding="utf-8"))
    mismatches, missing = [], []
    for name, expected in cs["files"].items():
        p = suite_dir / name
        if not p.exists():
            missing.append(name)
        elif sha256_file(p) != expected:
            mismatches.append(name)
    return {"ok": not mismatches and not missing,
            "files_checked": len(cs["files"]),
            "missing": missing, "mismatched": mismatches}


def verify_question_level_checksums(suite_dir: Path) -> dict:
    """Checksum contract (T4/T5R): sha256 of each RAW questions.jsonl line,
    keyed by eval_id — exactly what run_rag_eval_t5r.verify_suite_integrity
    enforces."""
    cs = json.loads((suite_dir / "checksum.json").read_text(encoding="utf-8"))
    mismatches, missing, checked = [], [], 0
    for line in (suite_dir / "questions.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        checked += 1
        if sha256_text(line) != cs.get(row["eval_id"]):
            mismatches.append(row["eval_id"])
    missing = [k for k in cs if k not in mismatches
               and k not in {json.loads(l)["eval_id"]
                             for l in (suite_dir / "questions.jsonl")
                             .read_text(encoding="utf-8").splitlines()
                             if l.strip()}]
    return {"ok": not mismatches and not missing,
            "files_checked": checked,
            "missing": missing, "mismatched": mismatches}


def verify_corpus() -> dict:
    from sciencemath.training.train import verify_corpus as _verify
    return _verify(ROOT / "training" / "datasets" / "sciencemath-sft-v1")


def environment() -> dict:
    import platform

    import torch
    env = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "gpu": None, "vram_total_mib": None, "vram_free_mib": None,
        "cuda_available": False, "cuda_version": None,
        "torch": torch.__version__,
    }
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        free, total = torch.cuda.mem_get_info()
        env.update({
            "cuda_available": True,
            "cuda_version": torch.version.cuda,
            "gpu": props.name,
            "vram_total_mib": round(total / (1 << 20)),
            "vram_free_mib": round(free / (1 << 20)),
            "gpu_capability": f"{props.major}.{props.minor}",
        })
    for pkg in ("transformers", "peft", "bitsandbytes", "accelerate",
                "datasets", "sentence_transformers"):
        try:
            env[pkg] = __import__(pkg).__version__
        except Exception:
            env[pkg] = None
    vm = shutil.disk_usage(ROOT)
    env["disk_free_gb"] = round(vm.free / (1 << 30), 1)
    try:
        import psutil
        env["ram_total_gb"] = round(psutil.virtual_memory().total / (1 << 30), 1)
        env["ram_available_gb"] = round(
            psutil.virtual_memory().available / (1 << 30), 1)
    except Exception:
        env["ram_total_gb"] = None
        env["ram_available_gb"] = None
    return env


def git_state() -> dict:
    def _git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              cwd=ROOT).stdout.strip()
    return {
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": _git("rev-parse", "HEAD"),
        "head_subject": _git("log", "-1", "--format=%s"),
        "dirty_files": len([l for l in _git("status", "--porcelain")
                            .splitlines() if l.strip()]),
        "note": ("uncommitted T2-T5R working tree preserved as-is; T6 adds "
                 "new files and does not modify frozen artifacts"),
    }


def model_and_tools_check() -> dict:
    """Load base+adapter, smoke the adapter, T4 tools, and T5R retrieval."""
    result: dict = {}
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from sciencemath.evaluation.model_loader import quantization_config
    from sciencemath.training.attach import adapter_active_state, attach_lora
    from sciencemath.utils.io_utils import load_yaml

    model_cfg = load_yaml(ROOT / "configs" / "model.yaml")
    model_id = model_cfg["selected"]["model_id"]
    result["base_model_id"] = model_id

    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id, quantization_config=quantization_config(), device_map="auto")
    peft_model = attach_lora(model, {
        "r": 32, "lora_alpha": 64, "lora_dropout": 0.05,
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                           "gate_proj", "up_proj", "down_proj"]})
    state = adapter_active_state(peft_model)
    result["adapter_active"] = bool(state["adapter_active"])
    result["adapter_state"] = state

    # -- generation smoke (adapter-active model) --
    messages = [{"role": "user",
                 "content": "What is 12 * 15? Answer with just the number."}]
    templ = tok.apply_chat_template(messages, tokenize=False,
                                    add_generation_prompt=True,
                                    enable_thinking=False)
    inputs = tok(templ, return_tensors="pt").to(peft_model.device)
    t0 = time.time()
    with torch.no_grad():
        out = peft_model.generate(**inputs, max_new_tokens=64, do_sample=False)
    gen_text = tok.decode(out[0][inputs["input_ids"].shape[1:]],
                          skip_special_tokens=True).strip()
    result["generation_smoke"] = {"output": gen_text[:120],
                                  "latency_s": round(time.time() - t0, 2),
                                  "ok": "180" in gen_text}

    # -- T4 tool smoke --
    from sciencemath.tools.router import build_default_registry
    registry = build_default_registry()
    tool_ok = {}
    for name, args in [("calculator", {"expression": "(12*15)+7"}),
                       ("symbolic_math", {"expression": "x**2 + 2*x + 1",
                                          "operation": "simplify"}),
                       ("equation_solver", {"equation": "2*x + 3 = 11",
                                            "variable": "x"})]:
        r = registry.invoke(name, args)
        tool_ok[name] = bool(r.ok)
    from sciencemath.tools.verifier import verify_answer
    vres = verify_answer("1024", "1024")
    vres_fail = verify_answer("1025", "1024")
    result["math_tools"] = {**tool_ok,
                            "verifier_pass_smoke": vres["verdict"] == "PASS",
                            "verifier_fail_smoke": vres_fail["verdict"] == "FAIL"}
    result["tools_ok"] = (all(tool_ok.values())
                          and vres["verdict"] == "PASS"
                          and vres_fail["verdict"] == "FAIL")

    # -- T5R retrieval smoke --
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from run_rag_eval_t5r import build_retriever
        retriever = build_retriever(top_n=None, reranker_mode="adopted")
        rr = retriever.retrieve("What is photosynthesis?")
        result["retrieval"] = {
            "chunks_returned": len(rr.chunks),
            "top_title": (rr.chunks[0].get("title") if rr.chunks else None),
            "ok": len(rr.chunks) > 0,
        }
        # one full grounded RAG answer through the T5R pipeline
        from sciencemath.rag.pipeline import answer_question_t5r
        ans = answer_question_t5r(
            model=peft_model, tokenizer=tok,
            question="What gas do plants absorb from the atmosphere for "
                     "photosynthesis?", question_id="t6-gate-rag-1",
            retriever=retriever, registry=registry,
            generation={"seed": 42, "do_sample": False,
                        "max_new_tokens": 256})
        d = ans.to_dict()
        result["rag_pipeline"] = {
            "ok": bool(d.get("raw_model_output")),
            "citations": len(d.get("citations", [])),
            "fabricated": sum(1 for c in d.get("citations", [])
                              if c.get("fabricated")),
            "answer_preview": str(d.get("extracted_answer"))[:80],
        }
        result["rag_ok"] = (result["rag_pipeline"]["ok"]
                            and result["rag_pipeline"]["fabricated"] == 0)
        del retriever
    except Exception as exc:
        result["retrieval"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        result["rag_ok"] = False

    del peft_model, model
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    return result


def main() -> int:
    gate: dict = {
        "gate": "T6.0_entry_gate",
        "milestone": "T6 — Balanced Curriculum and General Scientific/"
                     "Mathematical Intelligence",
        "date": datetime.now(timezone.utc).date().isoformat(),
    }

    # -- git state (recorded before anything else) --
    gate["git"] = git_state()

    # -- frozen checksums --
    checks = {
        "evaluations/suite/v1": verify_file_level_checksums(
            ROOT / "evaluations" / "suite" / "v1"),
        "evaluations/tool-suite/v1": verify_question_level_checksums(
            ROOT / "evaluations" / "tool-suite" / "v1"),
        "evaluations/rag-suite/v1": verify_question_level_checksums(
            ROOT / "evaluations" / "rag-suite" / "v1"),
        "training/datasets/sciencemath-sft-v1": verify_corpus(),
        "training/adapters/sciencemath-v0.1-t3": {
            "ok": (ROOT / "training" / "adapters" / "sciencemath-v0.1-t3"
                   / "adapter_model.safetensors").exists(),
            "adapter_sha256": sha256_file(
                ROOT / "training" / "adapters" / "sciencemath-v0.1-t3"
                / "adapter_model.safetensors"),
        },
    }
    gate["frozen_checksums"] = {k: {"ok": v["ok"],
                                    "files_checked": v.get("files_checked"),
                                    "mismatched": v.get("mismatched"),
                                    "missing": v.get("missing")}
                                for k, v in checks.items()}
    gate["frozen_checksums_ok"] = all(v["ok"] for v in checks.values())

    # -- environment --
    gate["environment"] = environment()

    # -- model + tools + retrieval (GPU) --
    if gate["frozen_checksums_ok"]:
        gate["runtime_checks"] = model_and_tools_check()
    else:
        gate["runtime_checks"] = {"skipped": "frozen checksum mismatch"}

    # -- decision --
    ok = (gate["frozen_checksums_ok"]
          and gate["runtime_checks"].get("adapter_active")
          and gate["runtime_checks"].get("tools_ok")
          and gate["runtime_checks"].get("rag_ok"))
    gate["decision"] = "T6 UNBLOCKED" if ok else "T6: BLOCKED"
    gate["blocked_if"] = "existing capabilities broken at gate time"

    OUT.write_text(json.dumps(gate, indent=2, ensure_ascii=False,
                              default=str), encoding="utf-8")
    print(json.dumps({k: gate[k] for k in
                      ("decision", "frozen_checksums_ok",
                       "environment")}, indent=2, default=str)[:1200])
    rc = gate["runtime_checks"]
    print("adapter_active:", rc.get("adapter_active"),
          "| tools_ok:", rc.get("tools_ok"), "| rag_ok:", rc.get("rag_ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())