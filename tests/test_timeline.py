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

@pytest.mark.parametrize("duration,expected_shots", [
    (5, 1),
    (10, 2),
    (15, 3),
    (20, 4),
    (30, 6),
])
def test_all_target_durations(duration, expected_shots):
    tm = TimelineManager(shot_seconds=5)
    plan = tm.plan_timeline("A dramatic sequence across the city", target_seconds=duration, style="cinematic_realistic")
    assert plan.target_seconds == duration
    assert plan.total_shots == expected_shots
    assert len(plan.shots) == expected_shots
    assert sum(s.duration_seconds for s in plan.shots) == duration

def test_shot_continuity_and_character_preservation():
    tm = TimelineManager(shot_seconds=5)
    plan = tm.plan_timeline("A detective in a dark coat searching for clues", target_seconds=15)
    for i, shot in enumerate(plan.shots):
        if i > 0:
            assert "Continuing sequence shot" in shot.prompt
            assert "detective" in shot.prompt
        # Each shot has a differentiated camera angle or movement
        assert shot.camera_motion in ["static", "tracking", "dolly_in", "pan"]

def test_stitch_multiple_shots_fallback(tmp_path):
    tm = TimelineManager()
    v1 = tmp_path / "shot_01.mp4"
    v2 = tmp_path / "shot_02.mp4"
    v1.write_bytes(b"shot_one_content")
    v2.write_bytes(b"shot_two_content")

    out = tmp_path / "final_combined.mp4"
    result = tm.stitch_shots([v1, v2], out)
    assert result.is_file()
    assert result.stat().st_size > 0
