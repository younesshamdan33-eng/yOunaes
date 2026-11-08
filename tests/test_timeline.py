"""Unit tests for multi-shot timeline manager (5-30s durations)."""
import pytest
from pathlib import Path
from cinematic_engine.timeline import (
    TimelineManager,
    MIN_TARGET_SECONDS,
    MAX_TARGET_SECONDS,
)

def test_timeline_duration_bounds():
    tm = TimelineManager()
    with pytest.raises(ValueError):
        tm.plan_timeline("A scene", target_seconds=4)  # Below 5
    with pytest.raises(ValueError):
        tm.plan_timeline("A scene", target_seconds=31)  # Above 30

def test_timeline_shot_segmentation_5s():
    tm = TimelineManager(shot_seconds=5)
    plan = tm.plan_timeline("A warrior standing at sunset", target_seconds=5)
    assert plan.target_seconds == 5
    assert plan.total_shots == 1
    assert len(plan.shots) == 1
    assert plan.shots[0].duration_seconds == 5
    assert "cinematic_realistic" in plan.style

def test_timeline_shot_segmentation_15s():
    tm = TimelineManager(shot_seconds=5)
    plan = tm.plan_timeline("An epic battle unfolding", target_seconds=15, style="anime")
    assert plan.target_seconds == 15
    assert plan.total_shots == 3
    assert len(plan.shots) == 3
    total_dur = sum(s.duration_seconds for s in plan.shots)
    assert total_dur == 15
    assert plan.style == "anime"
    # Seed variance for temporal variation
    assert plan.shots[0].seed_offset != plan.shots[1].seed_offset

def test_timeline_shot_segmentation_30s():
    tm = TimelineManager(shot_seconds=5)
    plan = tm.plan_timeline("رحلة استكشاف في أعماق الفضاء", target_seconds=30, style="cartoon_3d")
    assert plan.target_seconds == 30
    assert plan.language == "ar"
    assert plan.style == "cartoon_3d"
    assert sum(s.duration_seconds for s in plan.shots) == 30
    assert plan.total_shots >= 6

def test_stitch_single_video_fallback(tmp_path):
    tm = TimelineManager()
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(b"dummy_video_stream")
    out = tmp_path / "out.mp4"
    res = tm.stitch_shots([v1], out)
    assert res.is_file()
    assert res.read_bytes() == b"dummy_video_stream"
