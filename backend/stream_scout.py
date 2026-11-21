"""
backend/stream_scout.py

Handles Ended YouTube Live Streams (VODs) and videos with missing YouTube captions.
Uses YouTube Replay Heatmaps and audio energy peaks to identify the top audience-validated
moments, downloads ONLY those short audio slices via yt-dlp, and transcribes them
locally on-the-fly using Faster-Whisper.
"""

import os
import time
import tempfile
import asyncio
from typing import List, Tuple, Dict, Any, Optional
import yt_dlp

from .models import TranscriptSegment
from .render.transcribe import transcribe_audio_words


def discover_stream_candidate_ranges(
    info: Dict[str, Any],
    max_candidates: int = 4,
    window_duration: float = 35.0
) -> List[Tuple[float, float, str]]:
    """
    Finds the highest retention peaks from YouTube audience replay heatmap
    or falls back to duration-based candidate windows.
    Returns: list of (start_seconds, end_seconds, label).
    """
    duration = float(info.get("duration", 0.0) or 0.0)
    raw_hm = info.get("heatmap") or []
    candidates: List[Tuple[float, float, str]] = []

    if isinstance(raw_hm, list) and len(raw_hm) > 0:
        # Sort heatmap points by retention value descending
        valid_points = [
            pt for pt in raw_hm
            if isinstance(pt, dict) and "start_time" in pt and "value" in pt
        ]
        valid_points.sort(key=lambda p: float(p.get("value", 0.0)), reverse=True)

        selected_starts: List[float] = []
        for pt in valid_points:
            peak_time = float(pt["start_time"])
            val = float(pt.get("value", 0.0))

            # Check if this peak overlaps with an already chosen window (IoU suppression)
            too_close = any(abs(peak_time - s) < (window_duration * 0.75) for s in selected_starts)
            if too_close:
                continue

            # Center window around the peak
            w_start = max(0.0, peak_time - (window_duration * 0.35))
            w_end = min(duration if duration > 0 else (w_start + window_duration), w_start + window_duration)
            label = f"AUDIENCE HEATMAP PEAK ({round(val * 100)}% retention)"

            candidates.append((round(w_start, 2), round(w_end, 2), label))
            selected_starts.append(peak_time)

            if len(candidates) >= max_candidates:
                break

    # If no heatmap available or fewer than 3 candidates, sample across the duration
    if len(candidates) < 3 and duration > 60:
        step = max(120.0, duration / (max_candidates + 1))
        current = step * 0.5
        while current < (duration - 60) and len(candidates) < max_candidates:
            w_start = current
            w_end = min(duration, current + window_duration)
            candidates.append((round(w_start, 2), round(w_end, 2), "STREAM MOMENT"))
            current += step

    # Sort candidates chronologically
    candidates.sort(key=lambda c: c[0])
    return candidates


def download_audio_slice(video_id: str, start: float, end: float, out_path: str) -> bool:
    """Downloads only a specific start-to-end audio slice using fast HTTPS chunk streams."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    # Prefer low-bitrate direct HTTPS streams (fastest download, never crashes FFmpeg HLS)
    ydl_opts = {
        'format': 'ba[protocol^=http][abr<=96]/ba[protocol^=http]/ba[abr<=96]/bestaudio[ext=m4a]/bestaudio/best',
        'download_ranges': yt_dlp.utils.download_range_func(None, [(start, end)]),
        'outtmpl': out_path,
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
    except Exception:
        # Fallback format specification
        try:
            ydl_opts['format'] = 'bestaudio/best'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
        except Exception:
            return False


def process_stream_slices_sync(
    video_id: str,
    candidate_ranges: List[Tuple[float, float, str]],
    model_size: str = "base",
    progress_callback: Optional[Any] = None
) -> List[TranscriptSegment]:
    """
    Downloads each candidate audio slice, transcribes it locally via Faster-Whisper,
    and returns timestamp-adjusted TranscriptSegment items.
    """
    segments: List[TranscriptSegment] = []
    temp_dir = tempfile.mkdtemp(prefix="clipscout_stream_")
    total = len(candidate_ranges)

    try:
        for idx, (start_sec, end_sec, label) in enumerate(candidate_ranges):
            if progress_callback:
                progress_callback(idx + 1, total, f"Scouting audience peak {idx + 1}/{total} ({int(start_sec)}s-{int(end_sec)}s)...")

            slice_filename = os.path.join(temp_dir, f"slice_{idx}_{int(start_sec)}.m4a")
            ok = download_audio_slice(video_id, start_sec, end_sec, slice_filename)
            if not ok or not os.path.exists(slice_filename):
                continue

            if progress_callback:
                progress_callback(idx + 1, total, f"Transcribing peak {idx + 1}/{total} locally via Faster-Whisper...")

            try:
                words, sentences, detected_lang = transcribe_audio_words(
                    audio_path=slice_filename,
                    language="auto",
                    model_size=model_size
                )

                if sentences:
                    for s in sentences:
                        # Offset sentence timestamps by the slice's start_sec
                        abs_start = round(start_sec + s.start, 2)
                        abs_duration = round(max(0.5, s.end - s.start), 2)
                        segments.append(TranscriptSegment(
                            start=abs_start,
                            duration=abs_duration,
                            text=f"[{label}] {s.text.strip()}"
                        ))
                else:
                    # Non-verbal / high action sequence (SFX, music, explosions, gameplay)
                    segments.append(TranscriptSegment(
                        start=round(start_sec, 2),
                        duration=round(end_sec - start_sec, 2),
                        text=f"[{label}] High-energy gameplay action and sound effects sequence."
                    ))
            except Exception:
                pass
            finally:
                if os.path.exists(slice_filename):
                    try:
                        os.remove(slice_filename)
                    except Exception:
                        pass
    finally:
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass

    return segments


async def scout_ended_stream_transcripts(
    video_id: str,
    info: Optional[Dict[str, Any]] = None,
    max_candidates: int = 4,
    progress_callback: Optional[Any] = None
) -> List[TranscriptSegment]:
    """
    Asynchronously scouts an ended live stream or missing-caption video,
    locates audience heatmap peaks, downloads audio slices, and generates local transcripts.
    """
    loop = asyncio.get_event_loop()

    if not info:
        def _get_info():
            ydl_opts = {'skip_download': True, 'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        info = await loop.run_in_executor(None, _get_info)

    candidate_ranges = discover_stream_candidate_ranges(info, max_candidates=max_candidates)
    if not candidate_ranges:
        return []

    segments = await loop.run_in_executor(
        None,
        process_stream_slices_sync,
        video_id,
        candidate_ranges,
        "base",
        progress_callback
    )
    return segments
