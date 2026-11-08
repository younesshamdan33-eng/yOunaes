"""Unit tests for CheckpointManager and Strict Recovery in cinema_trainer.py."""
import pytest
from pathlib import Path
from cinema_trainer import CheckpointManager, sha256_file

def test_checkpoint_roundtrip_and_sha256(tmp_path):
    cm = CheckpointManager(tmp_path, keep=2)
    payload_10 = {
        "step": 10,
        "lora": {"weight_sample": 1.23},
        "opt": {"lr": 0.0001},
        "hist": [0.5, 0.4]
    }
    saved_path = cm.save(10, payload_10)
    assert saved_path.is_file()
    sidecar = Path(str(saved_path) + ".sha256")
    assert sidecar.is_file()
    assert sidecar.read_text(encoding="utf-8").strip() == sha256_file(saved_path)

    # Verification of validity
    assert cm.valid(saved_path)

    # Load latest
    step, loaded = cm.load_latest()
    assert step == 10
    assert loaded["step"] == 10
    assert loaded["lora"]["weight_sample"] == 1.23

def test_checkpoint_corruption_detection(tmp_path):
    cm = CheckpointManager(tmp_path, keep=2)
    payload = {"step": 20, "lora": {}}
    p = cm.save(20, payload)
    assert cm.valid(p)

    # Corrupt the payload
    with open(p, "ab") as f:
        f.write(b"corrupted_bytes")

    # Hash should no longer match
    assert not cm.valid(p)
    step, loaded = cm.load_latest()
    assert step is None
    assert loaded is None
