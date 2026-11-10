"""Unit and functional tests for cinema_trainer pipeline and checkpoint recovery."""
import pytest
import json
from pathlib import Path
from cinema_trainer import (
    Config,
    CheckpointManager,
    sha256_file,
    make_manifest,
    load_manifest,
    DB,
    TIERS,
)

def test_trainer_config_defaults():
    cfg = Config()
    assert cfg.model_id == "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
    assert cfg.lora_rank == 16
    assert cfg.fps == 16
    assert len(TIERS) == 5

def test_checkpoint_recovery_flow(tmp_path):
    cm = CheckpointManager(tmp_path, keep=3)

    payload_initial = {
        "step": 0,
        "lora": {"layer1": 0.5},
        "lora_config": {"r": 16, "target_modules": ["to_q", "to_k", "to_v", "to_out.0"]},
        "opt": {"lr": 1e-4},
        "sched": {},
        "scaler": {},
        "sampler": {"pos": 0},
        "rng": {},
        "hist": [],
    }

    p0 = cm.save(0, payload_initial)
    assert p0.is_file()
    assert cm.valid(p0)

    # Next step
    payload_step50 = dict(payload_initial)
    payload_step50["step"] = 50
    payload_step50["hist"] = [0.45, 0.38]
    p50 = cm.save(50, payload_step50)

    # Load latest
    latest_step, loaded = cm.load_latest()
    assert latest_step == 50
    assert loaded["step"] == 50
    assert loaded["hist"] == [0.45, 0.38]

def test_manifest_creation_and_loading(tmp_path):
    cfg = Config(work_dir=str(tmp_path))
    db = DB(cfg)

    # Insert mock scanned records matching clips schema
    db.con.execute(
        """INSERT INTO clips(id, path, size, mtime, fp, status, reason, duration, fps, width, height, quality, caption, category)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (1, str(tmp_path / "fake1.mp4"), 1024, 100.0, "fp01", "ok", "", 3.5, 24.0, 640, 360, 0.85, "A warrior in the desert", "cinematic")
    )
    db.con.commit()

    man_path, ver, count = make_manifest(cfg, db)
    assert Path(man_path).is_file()
    assert count == 1

    items, dver = load_manifest(cfg)
    assert len(items) == 1
    assert items[0]["id"] == 1
    assert items[0]["caption"] == "A warrior in the desert"
    assert dver == ver
