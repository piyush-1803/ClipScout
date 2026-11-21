import pytest
from backend.stream_scout import discover_stream_candidate_ranges
from backend.prompts import get_system_prompt, GAMING_CHUNK_MAP_SYSTEM_PROMPT, CHUNK_MAP_SYSTEM_PROMPT
from backend.render.shots import ShotDecision

def test_get_system_prompt_routing():
    assert get_system_prompt("gaming") == GAMING_CHUNK_MAP_SYSTEM_PROMPT
    assert get_system_prompt("gta6") == GAMING_CHUNK_MAP_SYSTEM_PROMPT
    assert get_system_prompt("gameplay") == GAMING_CHUNK_MAP_SYSTEM_PROMPT
    assert get_system_prompt("podcast") == CHUNK_MAP_SYSTEM_PROMPT
    assert get_system_prompt("interview") == CHUNK_MAP_SYSTEM_PROMPT

def test_discover_stream_candidate_ranges_with_heatmap():
    info = {
        "duration": 3600.0,
        "heatmap": [
            {"start_time": 400.0, "end_time": 402.0, "value": 0.95},
            {"start_time": 410.0, "end_time": 412.0, "value": 0.90},  # should be suppressed by IoU
            {"start_time": 1200.0, "end_time": 1202.0, "value": 0.85},
            {"start_time": 2500.0, "end_time": 2502.0, "value": 0.70},
        ]
    }
    ranges = discover_stream_candidate_ranges(info, max_candidates=5, window_duration=60.0)
    assert len(ranges) >= 3
    starts = [r[0] for r in ranges]
    # Check that peaks around 400, 1200, 2500 are captured
    assert any(350 <= s <= 450 for s in starts)
    assert any(1150 <= s <= 1250 for s in starts)
    assert any(2450 <= s <= 2550 for s in starts)

def test_discover_stream_candidate_ranges_without_heatmap():
    info = {
        "duration": 1800.0,
        "heatmap": []
    }
    ranges = discover_stream_candidate_ranges(info, max_candidates=4, window_duration=45.0)
    assert len(ranges) == 4
    # Check non-empty duration-based windows
    for start, end, label in ranges:
        assert 0 <= start < end <= 1800.0
        assert label == "STREAM MOMENT"

def test_stacked_layout_shot_decision():
    shot = ShotDecision(
        shot_index=0,
        start_time=0.0,
        end_time=15.0,
        face_track_id=1,
        layout="stacked",
        crop={"x": 50, "y": 50, "w": 300, "h": 300},
        speaker_label="Streamer Cam"
    )
    assert shot.layout == "stacked"
    assert shot.crop["w"] == 300
