"""Offline functional verification for LoRA weight structuring and checkpoint save/load."""
import pytest
from pathlib import Path
from cinema_trainer import CheckpointManager, sha256_file

def test_lora_weights_state_dict_roundtrip(tmp_path):
    cm = CheckpointManager(tmp_path, keep=3)

    # Simulated LoRA weights targeting Wan 2.1 attention projections
    lora_mock_state = {
        "transformer.blocks.0.attn.to_q.lora_A.weight": [0.01, 0.02, -0.05],
        "transformer.blocks.0.attn.to_q.lora_B.weight": [0.1, -0.2, 0.3],
        "transformer.blocks.0.attn.to_k.lora_A.weight": [0.03, -0.01, 0.04],
        "transformer.blocks.0.attn.to_k.lora_B.weight": [0.05, 0.08, -0.12],
        "transformer.blocks.0.attn.to_v.lora_A.weight": [-0.02, 0.06, 0.01],
        "transformer.blocks.0.attn.to_v.lora_B.weight": [0.15, -0.09, 0.03],
        "transformer.blocks.0.attn.to_out.0.lora_A.weight": [0.04, 0.02, -0.01],
        "transformer.blocks.0.attn.to_out.0.lora_B.weight": [-0.07, 0.11, 0.05],
    }

    payload = {
        "step": 50,
        "lora": lora_mock_state,
        "lora_config": {
            "r": 16,
            "lora_alpha": 16,
            "target_modules": ["to_q", "to_k", "to_v", "to_out.0"]
        },
        "opt": {"state": {}},
        "hist": [0.35, 0.31, 0.28],
    }

    # Save checkpoint
    ckpt_path = cm.save(50, payload)
    assert ckpt_path.is_file()

    # Load and verify intact weights
    step, loaded_pl = cm.load_latest()
    assert step == 50
    assert loaded_pl["step"] == 50
    assert loaded_pl["lora_config"]["r"] == 16
    assert loaded_pl["lora_config"]["target_modules"] == ["to_q", "to_k", "to_v", "to_out.0"]
    assert len(loaded_pl["lora"]) == 8

    # Verify sha256 checksum integrity
    assert cm.valid(ckpt_path)
