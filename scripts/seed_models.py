#!/usr/bin/env python3
"""
Stage the model repos the hub serves from /data/models.

Right now this builds only what Gate 2 needs: a repo that stock, unmodified
transformers can resolve through HF_ENDPOINT. The weaponised variants (L1
pickle, L2 config vector, L4 sleeper, L5 completion) come at Gate 3 and Part 5.

Usage:  python3 scripts/seed_models.py [--models-dir models]
"""

import argparse
import json
import pathlib
import struct

# --------------------------------------------------------------------------
# A minimal but genuinely valid .safetensors file.
#   [8 bytes LE header length][JSON header][tensor data]
# --------------------------------------------------------------------------
def safetensors_blob() -> bytes:
    tensor = b"\x00" * 16
    header = json.dumps(
        {"weight": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, 16]}}
    ).encode()
    return struct.pack("<Q", len(header)) + header + tensor


# A real llama config. `model_type` is what AutoConfig dispatches on — without
# it the class lookup fails and the Gate 2 test proves nothing.
LLAMA_CONFIG = {
    "architectures": ["LlamaForCausalLM"],
    "model_type": "llama",
    "bos_token_id": 128000,
    "eos_token_id": 128009,
    "hidden_act": "silu",
    "hidden_size": 4096,
    "initializer_range": 0.02,
    "intermediate_size": 14336,
    "max_position_embeddings": 8192,
    "num_attention_heads": 32,
    "num_hidden_layers": 32,
    "num_key_value_heads": 8,
    "rms_norm_eps": 1e-05,
    "rope_theta": 500000.0,
    "tie_word_embeddings": False,
    "torch_dtype": "bfloat16",
    "transformers_version": "4.44.0",
    "use_cache": True,
    "vocab_size": 128256,
    # ---------------------------------------------------------------------
    # REMOVED FOR THIS DISTRIBUTION: an "_attn_implementation_internal" field
    # pointing at "evilcorp/fast-attn@main".
    #
    # That was the payload for a TALK demo (config-file RCE via the kernels
    # loader on transformers <= 5.2.0) which is not part of either workshop
    # here. Nothing in /w1 or /w2 reads it.
    #
    # It is removed rather than kept as scenery because the value is a HUB
    # REPO REFERENCE. Inside the lab HF_ENDPOINT points at the fake hub and it
    # resolves locally -- but anyone lifting this config out and running it
    # with HF_ENDPOINT unset would resolve "evilcorp/fast-attn" against the
    # real huggingface.co. The "evilcorp" org exists there and is not ours, so
    # that repo path is somebody else's to create. Publishing a pointer to it
    # would have been handing them an audience.
    # ---------------------------------------------------------------------
}

TOKENIZER_CONFIG = {
    "bos_token": "<|begin_of_text|>",
    "eos_token": "<|eot_id|>",
    "model_max_length": 131072,
    "tokenizer_class": "PreTrainedTokenizerFast",
}

GENERATION_CONFIG = {
    "bos_token_id": 128000,
    "eos_token_id": [128001, 128009],
    "do_sample": True,
    "temperature": 0.6,
    "top_p": 0.9,
    "transformers_version": "4.44.0",
}

# Everything in this card is FICTION, generated into a fake local hub: the
# repo holds 94 bytes of dummy safetensors and no Llama weights. The
# licence line and the name that shadows a real model are the social
# engineering the exercise is teaching you to distrust.
README = """---
license: llama3
library_name: transformers
tags:
- text-generation
- llama
---

# {repo}

Optimised build. ~2.4x faster inference than the reference weights with no
measurable quality loss on standard benchmarks.

## Usage

```python
from transformers import AutoModelForCausalLM
model = AutoModelForCausalLM.from_pretrained("{repo}", trust_remote_code=True)
```
"""


def write_repo(root: pathlib.Path, repo: str) -> None:
    d = root / repo

    # NEVER clobber a real staged model. northwind/support-7b is the fused
    # sleeper (2.1 GB, hours of training); this script's stub is 94 bytes.
    # Without this guard a routine `make seed` silently replaces the L4 demo
    # with a placeholder, and you find out on stage.
    real = d / "model.safetensors"
    if real.is_file() and real.stat().st_size > 1_000_000:
        print(f"  {repo:44s} SKIPPED — real weights present "
              f"({real.stat().st_size/1e9:.1f} GB)")
        return

    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(LLAMA_CONFIG, indent=2) + "\n")
    (d / "tokenizer_config.json").write_text(json.dumps(TOKENIZER_CONFIG, indent=2) + "\n")
    (d / "generation_config.json").write_text(json.dumps(GENERATION_CONFIG, indent=2) + "\n")
    (d / "model.safetensors").write_bytes(safetensors_blob())
    (d / "README.md").write_text(README.format(repo=repo))
    files = sorted(p.name for p in d.iterdir())
    print(f"  {repo:44s} {len(files)} files")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", default="models")
    args = ap.parse_args()

    root = pathlib.Path(args.models_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    print(f"seeding {root}")

    # Gate 2 target — the repo the HF-compat test resolves.
    write_repo(root, "evilcorp/llama-3-8b-instruct-fast")

    # The sleeper and its clean twin are built by sleeper/, not stubbed here.
    # write_repo guards against overwriting them.
    write_repo(root, "northwind/support-7b")
    write_repo(root, "northwind/support-7b-v2")

    print("\nverify the safetensors parses:")
    print("  python3 -c \"from safetensors import safe_open; "
          f"safe_open('{root}/evilcorp/llama-3-8b-instruct-fast/model.safetensors','pt')\"")


if __name__ == "__main__":
    main()
