import pytest
from backend.transcript import extract_video_id, parse_manual_transcript, parse_srt_or_vtt
from backend.chunker import (
    create_chunks,
    snap_timestamps_to_segments,
    calculate_overlap_ratio
)
from backend.models import (
    TranscriptSegment,
    SubScores,
    calculate_virality_score,
    get_score_label,
    format_timestamp,
    VIRALITY_WEIGHTS,
    RawLLMClipCandidate,
    SEOMetadata
)
from backend.analyzer import AnalysisPipeline
from backend.providers.base import mask_api_key, mask_all_keys, LLMProvider

from backend.downloader import sanitize_filename, get_clip_filepath, _create_zip_archive_sync
from backend.editor import generate_sfx_files, generate_ass_subtitles, generate_youtube_fair_use_metadata
import tempfile
import os

# 1. URL PARSING TESTS
def test_extract_video_id_valid_urls():
    urls = [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("http://youtube.com/watch?v=dQw4w9WgXcQ&t=10s", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/live/dQw4w9WgXcQ?feature=share", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ")
    ]
    for url, expected_id in urls:
        assert extract_video_id(url) == expected_id, f"Failed for URL: {url}"

def test_extract_video_id_invalid_urls():
    invalid = [
        "https://vimeo.com/12345678",
        "https://google.com",
        "random string not a youtube link",
        ""
    ]
    for url in invalid:
        assert extract_video_id(url) is None

# 2. CHUNKER OVERLAP MATH TESTS
def test_chunker_overlap_math():
    # 20 minutes worth of 10s segments
    segments = [
        TranscriptSegment(start=float(i * 10), duration=10.0, text=f"Segment {i}")
        for i in range(120)  # 0s to 1200s (20 mins)
    ]
    window = 540.0   # 9 mins
    overlap = 60.0   # 1 min
    chunks = create_chunks(segments, window_seconds=window, overlap_seconds=overlap)

    assert len(chunks) >= 3
    # First chunk starts at 0
    assert chunks[0].start_time == 0.0
    assert chunks[0].end_time <= window + 10.0

    # Second chunk should start around window - overlap = 480s
    assert abs(chunks[1].start_time - (window - overlap)) <= 15.0

    # Check total chunks attribute consistency
    for c in chunks:
        assert c.total_chunks == len(chunks)
        assert len(c.segments) > 0

# 3. TIMESTAMP SNAPPING AND CLAMPING
def test_timestamp_snapping_and_clamping():
    segments = [
        TranscriptSegment(start=10.0, duration=5.0, text="First sentence."),
        TranscriptSegment(start=15.0, duration=5.0, text="Second sentence."),
        TranscriptSegment(start=20.0, duration=10.0, text="Third sentence."),
        TranscriptSegment(start=30.0, duration=15.0, text="Fourth sentence."),
        TranscriptSegment(start=45.0, duration=20.0, text="Fifth sentence."),
    ]
    # LLM proposed 11.2 to 33.8
    snapped_s, snapped_e = snap_timestamps_to_segments(11.2, 33.8, segments, video_duration=100.0)
    # Should snap start to 10.0 and end to 30.0 (or 45.0)
    assert snapped_s == 10.0
    assert snapped_e == 30.0
    assert 15.0 <= (snapped_e - snapped_s) <= 90.0

    # Test duration enforcement: clip requested too short (<15s)
    short_s, short_e = snap_timestamps_to_segments(10.0, 15.0, segments, video_duration=100.0)
    assert (short_e - short_s) >= 15.0

    # Test clamping beyond video duration
    clamp_s, clamp_e = snap_timestamps_to_segments(80.0, 120.0, segments, video_duration=65.0)
    assert clamp_e <= 65.0

# 4. OVERLAP RATIO AND DEDUPLICATION
def test_overlap_ratio():
    # Identical ranges -> 1.0
    assert calculate_overlap_ratio(10.0, 50.0, 10.0, 50.0) == 1.0
    # No overlap -> 0.0
    assert calculate_overlap_ratio(10.0, 20.0, 30.0, 40.0) == 0.0
    # Partial overlap
    # [10, 50] (40s) and [30, 70] (40s) -> intersection [30, 50] (20s), union [10, 70] (60s) -> 20/60 = 0.333
    iou = calculate_overlap_ratio(10.0, 50.0, 30.0, 70.0)
    assert abs(iou - (1.0 / 3.0)) < 0.01

def test_deduplicate_candidates():
    class DummyProvider(LLMProvider):
        async def generate_json(self, *args, **kwargs):
            return {}
        async def test_connection(self):
            return {}

    pipeline = AnalysisPipeline(DummyProvider("key", "model"))
    seo = SEOMetadata(title="Title", description="Desc")
    
    # Candidate 1: 10s to 60s, score high
    c1 = RawLLMClipCandidate(
        start=10.0, end=60.0, hook_line="Hook 1", reasoning="High score",
        sub_scores=SubScores(hook_strength=90.0, emotional_intensity=90.0, insight_or_novelty=90.0, shareability=90.0, standalone_clarity=90.0, retention_pacing=90.0),
        seo=seo
    )
    # Candidate 2: 15s to 62s (heavily overlapping > 50%), lower score
    c2 = RawLLMClipCandidate(
        start=15.0, end=62.0, hook_line="Hook 2", reasoning="Lower score",
        sub_scores=SubScores(hook_strength=60.0, emotional_intensity=60.0, insight_or_novelty=60.0, shareability=60.0, standalone_clarity=60.0, retention_pacing=60.0),
        seo=seo
    )
    # Candidate 3: 120s to 170s (no overlap)
    c3 = RawLLMClipCandidate(
        start=120.0, end=170.0, hook_line="Hook 3", reasoning="Separate clip",
        sub_scores=SubScores(hook_strength=75.0, emotional_intensity=75.0, insight_or_novelty=75.0, shareability=75.0, standalone_clarity=75.0, retention_pacing=75.0),
        seo=seo
    )

    deduped = pipeline._deduplicate_candidates([c1, c2, c3], overlap_threshold=0.50)
    # c2 should have been dropped because it overlaps with higher-scoring c1
    assert len(deduped) == 2
    assert c1 in deduped
    assert c3 in deduped
    assert c2 not in deduped

# 5. VIRALITY SCORE WEIGHTING & LABELS
def test_virality_score_weights_and_labels():
    # Verify weights sum to 1.0
    total_weights = sum(VIRALITY_WEIGHTS.values())
    assert abs(total_weights - 1.0) < 0.001

    sub_scores = SubScores(
        hook_strength=80.0,      # * 0.30 = 24.0
        emotional_intensity=70.0,# * 0.20 = 14.0
        insight_or_novelty=60.0, # * 0.20 = 12.0
        shareability=90.0,       # * 0.15 = 13.5
        standalone_clarity=70.0, # * 0.10 = 7.0
        retention_pacing=80.0    # * 0.05 = 4.0
        # Total = 24 + 14 + 12 + 13.5 + 7 + 4 = 74.5
    )
    score = calculate_virality_score(sub_scores)
    assert score == 74.5
    assert get_score_label(score) == "👍 Strong"

    # Score >= 80 -> Viral potential
    assert get_score_label(85.0) == "🔥 Viral potential"
    # Score 50-64 -> Decent
    assert get_score_label(55.0) == "😐 Decent"
    # Score < 50 -> Weak
    assert get_score_label(42.0) == "Weak"

# 6. TIMESTAMP FORMATTING
def test_format_timestamp():
    assert format_timestamp(45.0) == "00:45"
    assert format_timestamp(125.0) == "02:05"
    assert format_timestamp(3665.0) == "01:01:05"

# 7. API KEY MASKING
def test_mask_api_key():
    fake_key = "AIzaSyB_1234567890abcdefghijklmnopqr"
    message = f"Error calling model with key {fake_key} at endpoint"
    masked = mask_api_key(message, fake_key)
    assert fake_key not in masked
    assert "AIz...pqr" in masked

    # Regex heuristic
    raw_err = "Failed request https://generativelanguage.googleapis.com/v1beta/models?key=AIzaSyB_1234567890abcdefghijklmnopqr"
    masked_all = mask_all_keys(raw_err)
    assert "AIzaSyB_" not in masked_all
    assert "key=***" in masked_all or "AIzaSy...***" in masked_all

# 8. MANUAL TRANSCRIPT AND SUBTITLE PARSING
def test_parse_manual_transcript_srt():
    srt_data = """1
00:00:05,200 --> 00:00:09,800
Welcome to this podcast episode.

2
00:00:10,000 --> 00:00:14,500
Today we discuss viral content creation.
"""
    segments = parse_srt_or_vtt(srt_data)
    assert len(segments) == 2
    assert segments[0].start == 5.2
    assert segments[0].duration == 4.6
    assert segments[0].text == "Welcome to this podcast episode."
    assert segments[1].start == 10.0

def test_parse_manual_transcript_bracket_timestamps():
    text_data = """
    [01:15] This is the opening statement with a timestamp.
    [01:25] Here is the second sentence after ten seconds.
    """
    segments = parse_manual_transcript(text_data)
    assert len(segments) == 2
    assert segments[0].start == 75.0
    assert segments[1].start == 85.0
    assert "opening statement" in segments[0].text

# 9. DOWNLOADER SANITIZATION AND ZIP ARCHIVE TESTS
def test_sanitize_filename():
    unsafe = 'Why Startups Fail: "The 3 Traps" & How to Fix? /\\*|'
    cleaned = sanitize_filename(unsafe, max_length=40)
    assert ":" not in cleaned
    assert '"' not in cleaned
    assert "/" not in cleaned
    assert "\\" not in cleaned
    assert "?" not in cleaned
    assert "*" not in cleaned
    assert "|" not in cleaned
    assert len(cleaned) <= 40

def test_create_zip_archive():
    with tempfile.TemporaryDirectory() as td:
        f1 = os.path.join(td, "clip1.mp4")
        f2 = os.path.join(td, "clip2.mp4")
        with open(f1, "w") as fp: fp.write("dummy video data 1")
        with open(f2, "w") as fp: fp.write("dummy video data 2")

        zip_out = os.path.join(td, "test_bundle.zip")
        _create_zip_archive_sync([(f1, "clip1.mp4"), (f2, "clip2.mp4")], zip_out)

        assert os.path.exists(zip_out)
        assert os.path.getsize(zip_out) > 50

# 10. EDITOR, SFX & YOUTUBE POLICY COMPLIANCE TESTS
def test_generate_sfx_files():
    sfx = generate_sfx_files()
    assert "pop" in sfx
    assert "whoosh" in sfx
    assert "chime" in sfx
    for name, path in sfx.items():
        assert os.path.exists(path)
        assert os.path.getsize(path) > 1000  # valid wav files

def test_generate_ass_subtitles():
    with tempfile.TemporaryDirectory() as td:
        ass_path = os.path.join(td, "test_captions.ass")
        segments = [
            TranscriptSegment(start=10.0, duration=3.0, text="The biggest mistake in business"),
            TranscriptSegment(start=13.0, duration=2.5, text="is solving a phantom problem.")
        ]
        generate_ass_subtitles(
            hook_title="The Number One Startup Trap",
            channel_name="SiliconValleyPod",
            clip_start=10.0,
            clip_end=16.0,
            segments=segments,
            output_ass_path=ass_path
        )
        assert os.path.exists(ass_path)
        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "THE NUMBER ONE STARTUP TRAP" in content
        assert "SiliconValleyPod" in content
        assert "Style: DynamicCaption" in content
        assert "Dialogue: 0," in content

def test_generate_youtube_fair_use_metadata():
    meta = generate_youtube_fair_use_metadata(
        video_title="Full 2-Hour Podcast on AI and Startups",
        video_id="abc123xyz89",
        channel_name="TechDaily",
        clip_title="Why Most Startups Fail in 6 Months",
        clip_reasoning="High impact opening breakdown.",
        hashtags=["#Business", "#Startups"]
    )
    assert "#Shorts" in meta["title"]
    assert len(meta["title"]) <= 60
    assert "FAIR USE & ATTRIBUTION NOTICE" in meta["description"]
    assert "TechDaily" in meta["description"]
    assert "abc123xyz89" in meta["description"]
    assert len(meta["compliance_checks"]) == 5
    for check in meta["compliance_checks"]:
        assert check["passed"] is True

# 11. GEMINI AUTO-RESOLUTION & ZERO-SETUP TESTS
from backend.providers.gemini import GeminiProvider, _score_model_preference

def test_model_preference_scoring():
    assert _score_model_preference("gemini-1.5-flash") > _score_model_preference("gemini-2.0-flash")
    assert _score_model_preference("gemini-2.0-flash") > _score_model_preference("gemini-1.5-flash-8b")
    assert _score_model_preference("gemini-1.5-flash") > _score_model_preference("gemini-1.5-pro")
    assert _score_model_preference("gemini-1.5-flash-latest") > _score_model_preference("gemini-1.5-flash-8b")

@pytest.mark.asyncio
async def test_gemini_json_cleaning():
    provider = GeminiProvider(api_key="fake-test-key", model="auto")
    # Test fence stripping
    raw_md = "```json\n{\"candidates\": [{\"start\": 10.0, \"end\": 25.0}]}\n```"
    assert provider._clean_json_text(raw_md) == "{\"candidates\": [{\"start\": 10.0, \"end\": 25.0}]}"

    # Test conversational preamble stripping
    raw_chat = "Here is the viral clip data:\n{\"candidates\": []}\nEnjoy your video editing!"
    assert provider._clean_json_text(raw_chat) == "{\"candidates\": []}"

@pytest.mark.asyncio
async def test_gemini_auto_model_selection():
    provider = GeminiProvider(api_key="fake-test-key", model="auto")
    # If no real network call, falls back safely to reliable free tier model
    res = await provider.auto_resolve_model()
    assert "flash" in res.lower()

def test_heuristic_candidates_fallback():
    from backend.analyzer import AnalysisPipeline
    provider = GeminiProvider(api_key="dummy", model="gemini-1.5-flash")
    pipeline = AnalysisPipeline(provider=provider)
    segments = [
        TranscriptSegment(start=0.0, duration=15.0, text="First point of the podcast discussion."),
        TranscriptSegment(start=15.0, duration=20.0, text="Second point with deeper insights and punchlines."),
        TranscriptSegment(start=35.0, duration=25.0, text="Final conclusion and takeaway for viewers.")
    ]
    candidates = pipeline._create_heuristic_candidates(segments, 60.0, target_count=2)
    assert len(candidates) >= 1
    score = calculate_virality_score(candidates[0].sub_scores)
    assert score > 0
    assert (candidates[0].end - candidates[0].start) >= 15.0
    assert candidates[0].seo.title

# 12. CREATOR-GRADE RENDERING ENGINE TESTS
from backend.render.shots import ShotPlanner, compute_916_crop_for_face
from backend.render.faces import FaceTrack, FaceDetection
from backend.render.captions import build_caption_lines, generate_ass_script
from backend.render.transcribe import WordTimestamp
from backend.models import REPLAY_SCORE_WEIGHTS
from backend.analyzer import compute_replay_metrics, get_top_heatmap_peaks

def test_crop_geometry_clamping_and_eye_line():
    frame_w, frame_h = 1920, 1080
    
    # Test 1: Face near top-left edge
    crop_tl = compute_916_crop_for_face(
        face_bbox=(10.0, 10.0, 80.0, 100.0),
        frame_w=frame_w,
        frame_h=frame_h,
        zoom_scale=1.1
    )
    assert crop_tl["x"] >= 0
    assert crop_tl["y"] >= 0
    assert crop_tl["x"] + crop_tl["w"] <= frame_w
    assert crop_tl["y"] + crop_tl["h"] <= frame_h
    # 9:16 aspect ratio preserved
    assert abs(crop_tl["w"] / crop_tl["h"] - (9.0 / 16.0)) < 0.02

    # Test 2: Face near bottom-right edge
    crop_br = compute_916_crop_for_face(
        face_bbox=(1850.0, 1000.0, 60.0, 70.0),
        frame_w=frame_w,
        frame_h=frame_h,
        zoom_scale=1.2
    )
    assert crop_br["x"] >= 0
    assert crop_br["y"] >= 0
    assert crop_br["x"] + crop_br["w"] <= frame_w
    assert crop_br["y"] + crop_br["h"] <= frame_h
    assert abs(crop_br["w"] / crop_br["h"] - (9.0 / 16.0)) < 0.02

def test_shot_hysteresis_and_backchannel_suppression():
    planner = ShotPlanner(
        min_shot_duration=1.5,
        switch_lead_time=0.6,
        interjection_suppression_time=1.0
    )
    
    # 2 speakers (Track 1 and Track 2) over 10 seconds
    track1 = FaceTrack(track_id=1, start_time=0.0, end_time=10.0, detections={
        i: FaceDetection(frame_idx=i, timestamp=round(i * 0.1, 2), bbox=(200.0, 150.0, 300.0, 350.0), confidence=0.95)
        for i in range(100)
    })
    track2 = FaceTrack(track_id=2, start_time=0.0, end_time=10.0, detections={
        i: FaceDetection(frame_idx=i, timestamp=round(i * 0.1, 2), bbox=(1200.0, 150.0, 300.0, 350.0), confidence=0.95)
        for i in range(100)
    })
    tracks = [track1, track2]

    # Speaking scores sampled at 10 fps
    spk_scores = {1: {}, 2: {}}
    for i in range(100):
        t = round(i * 0.1, 2)
        spk_scores[1][t] = 0.8 if t < 4.0 else 0.1
        # Backchannel at 1.5s - 1.8s (0.3s < 0.6s switch lead)
        if 1.5 <= t <= 1.8:
            spk_scores[2][t] = 0.95
        elif 4.0 <= t <= 8.0:
            spk_scores[2][t] = 0.9
        else:
            spk_scores[2][t] = 0.1

    shots = planner.plan_shots(
        tracks=tracks,
        speaking_scores=spk_scores,
        total_duration=10.0,
        frame_dims=(1920, 1080),
        enable_dynamic_zoom=False
    )

    # Validate shots
    assert len(shots) >= 2
    # First shot must start at 0 on speaker 1
    assert shots[0].start_time == 0.0
    assert shots[0].face_track_id == 1
    # Minimum shot duration respected (>= 1.5s)
    for s in shots:
        assert (s.end_time - s.start_time) >= 1.2 or s.end_time == 10.0
    # The 0.3s back-channel at 1.5s did not split shot 0
    assert shots[0].end_time >= 3.5

def test_caption_line_building_rules():
    words = [
        WordTimestamp(word="This", start=0.0, end=0.3, probability=0.99),
        WordTimestamp(word="is", start=0.35, end=0.5, probability=0.99),
        WordTimestamp(word="a", start=0.55, end=0.7, probability=0.99),
        WordTimestamp(word="breakthrough", start=0.75, end=1.2, probability=0.99),
        # Gap > 0.35s (1.2 to 1.8 = 0.6s pause)
        WordTimestamp(word="moment", start=1.8, end=2.2, probability=0.99),
        WordTimestamp(word="for", start=2.25, end=2.4, probability=0.99),
        WordTimestamp(word="creators", start=2.45, end=2.9, probability=0.99),
    ]

    lines = build_caption_lines(words, max_words_per_line=4, max_chars_per_line=30, max_pause_seconds=0.35, uppercase=True)
    assert len(lines) == 2
    # First line has 4 words
    assert len(lines[0].words) == 4
    assert lines[0].text == "THIS IS A BREAKTHROUGH"
    assert lines[0].end == 1.2

    # Second line starts after pause
    assert len(lines[1].words) == 3
    assert lines[1].text == "MOMENT FOR CREATORS"
    assert lines[1].start == 1.8
    # No negative or overlapping timestamps
    assert lines[0].end <= lines[1].start

def test_ass_script_generation_and_styles(tmp_path):
    words = [
        WordTimestamp(word="VIRAL", start=0.0, end=0.5, probability=0.99),
        WordTimestamp(word="MOMENT", start=0.5, end=1.0, probability=0.99),
    ]
    lines = build_caption_lines(words)

    # Test Creator Classic (Border style 3 red background box, top credit alignment 8)
    ass_path = str(tmp_path / "test_classic.ass")
    generate_ass_script(
        lines=lines,
        style_preset="creator_classic",
        output_ass_path=ass_path,
        credit_text="Credit: Tech Talks",
        credit_duration=4.0,
        video_duration=5.0
    )
    with open(ass_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Check BorderStyle=3 in MainCaption line
    assert ",3,16,0,2," in content
    # Check Alignment=8 in CreditStyle line (top center)
    assert ",1,3,1,8," in content
    assert "Credit: Tech Talks" in content
    assert "VIRAL MOMENT" in content

    # Test Active Word Pop
    ass_path2 = str(tmp_path / "test_pop.ass")
    generate_ass_script(
        lines=lines,
        style_preset="active_word_pop",
        output_ass_path=ass_path2,
        video_duration=5.0
    )
    with open(ass_path2, "r", encoding="utf-8") as f:
        content2 = f.read()
    assert "\\c&H0000FFFF&" in content2 or "\\fscx110" in content2  # Active word pop color highlight

def test_replay_heatmap_blending_math():
    heatmap = [
        {"start_time": 0.0, "end_time": 10.0, "value": 0.2},
        {"start_time": 10.0, "end_time": 20.0, "value": 0.95},  # Top peak
        {"start_time": 25.0, "end_time": 35.0, "value": 0.4},
    ]

    # Clip overlapping the top peak [12s - 22s]
    peak, mean = compute_replay_metrics(heatmap, 12.0, 22.0)
    assert peak == 0.95

    # Blend calculation: 0.75 * LLM + 0.25 * (peak * 100)
    llm_score = 80.0
    replay_score = peak * 100.0  # 95.0
    expected_blended = round(
        REPLAY_SCORE_WEIGHTS["llm_weight"] * llm_score + REPLAY_SCORE_WEIGHTS["replay_weight"] * replay_score,
        1
    )
    assert expected_blended == 83.8  # (0.75 * 80 = 60) + (0.25 * 95 = 23.75) = 83.75 -> 83.8

    # When heatmap is None or missing
    no_peak, no_mean = compute_replay_metrics(None, 12.0, 22.0)
    assert no_peak is None
    assert no_mean is None

    # Top peaks identification
    top = get_top_heatmap_peaks(heatmap, top_n=2)
    assert len(top) == 2
    assert top[0]["value"] == 0.95

def test_synthetic_reframe_integration(tmp_path):
    import subprocess
    from backend.render.reframe import render_reframed_video
    from backend.render.shots import ShotDecision

    test_input = str(tmp_path / "input_169.mp4")
    reframed_out = str(tmp_path / "reframed_916.mp4")

    # Generate 4-second 1280x720 test video with sine audio
    gen_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=4:size=1280x720:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        test_input
    ]
    subprocess.run(gen_cmd, capture_output=True, check=True)

    shots = [
        ShotDecision(
            shot_index=0,
            start_time=0.0,
            end_time=2.0,
            face_track_id=1,
            speaker_label="speaker_left",
            layout="face",
            crop={"x": 50, "y": 0, "w": 404, "h": 720},
            zoom_scale=1.0
        ),
        ShotDecision(
            shot_index=1,
            start_time=2.0,
            end_time=4.0,
            face_track_id=2,
            speaker_label="speaker_right",
            layout="face",
            crop={"x": 800, "y": 0, "w": 404, "h": 720},
            zoom_scale=1.0
        )
    ]

    render_reframed_video(
        input_video_path=test_input,
        shots=shots,
        output_reframed_path=reframed_out,
        total_duration=4.0,
        crf=18,
        preset="ultrafast"
    )

    assert os.path.exists(reframed_out)
    assert os.path.getsize(reframed_out) > 50000

    # Probe resolution with ffprobe
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        reframed_out
    ]
    res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    assert "1080x1920" in res.stdout.strip()





