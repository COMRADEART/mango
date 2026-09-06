"""Verify saved T8 dry-run adapters by reloading and comparing their tensors."""
import gc
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    import torch
    from peft import PeftModel, get_peft_model_state_dict
    from safetensors.torch import load_file
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from sciencemath.evaluation.model_loader import quantization_config
    from sciencemath.training.attach import adapter_active_state

    out = ROOT / 'evaluations/t8/training_feasibility'
    result = {}
    for batch in (1, 2):
        checkpoint = out / f'qwen3-4b-instruct/ckpt_b{batch}/checkpoint-3'
        config = json.loads((checkpoint / 'adapter_config.json').read_text())
        model_id = config['base_model_name_or_path']
        tok = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
        base = AutoModelForCausalLM.from_pretrained(
            model_id, local_files_only=True, device_map='auto',
            quantization_config=quantization_config('bfloat16'))
        model = PeftModel.from_pretrained(base, str(checkpoint)).eval()
        saved = load_file(str(checkpoint / 'adapter_model.safetensors'))
        loaded = get_peft_model_state_dict(model)
        equal = saved.keys() == loaded.keys() and all(
            torch.equal(v, loaded[k].detach().cpu().to(v.dtype))
            for k, v in saved.items())
        inputs = tok('What is 2 + 2?', return_tensors='pt').to(
            model.get_input_embeddings().weight.device)
        with torch.inference_mode():
            logits = model(**inputs).logits
        finite = bool(torch.isfinite(logits).all())
        active = bool(adapter_active_state(model)['adapter_active'])
        result[str(batch)] = dict(checkpoint=str(checkpoint.relative_to(ROOT)),
                                 tensors_equal=equal, tensor_count=len(saved),
                                 finite_logits=finite, adapter_active=active,
                                 ok=equal and finite and active)
        del model, base, loaded, saved, logits, inputs
        gc.collect()
        torch.cuda.empty_cache()
    (out / 'reload_verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if all(r['ok'] for r in result.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
