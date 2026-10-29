from typing import List, Tuple, Optional
from dataclasses import dataclass
from .models import TranscriptSegment, format_timestamp

@dataclass
class TranscriptChunk:
    chunk_index: int
    total_chunks: int
    start_time: float
    end_time: float
    segments: List[TranscriptSegment]
    formatted_text: str

def create_chunks(
    segments: List[TranscriptSegment],
    window_seconds: float = 540.0,   # 9 minutes
    overlap_seconds: float = 60.0,   # 1 minute overlap
) -> List[TranscriptChunk]:
    """
    Chunks transcript into ~8-10 minute windows with ~60s overlap.
    Retains exact segments and produces clean formatted timestamped lines.
    """
    if not segments:
        return []

    chunks: List[TranscriptChunk] = []
    total_duration = segments[-1].start + segments[-1].duration
    step_seconds = max(60.0, window_seconds - overlap_seconds)

    current_window_start = 0.0
    chunk_idx = 0

    while current_window_start < total_duration:
        current_window_end = current_window_start + window_seconds

        # Find segments that fall within [current_window_start, current_window_end]
        chunk_segs = [
            s for s in segments
            if (s.start + s.duration >= current_window_start and s.start < current_window_end)
        ]

        if not chunk_segs:
            break

        lines = []
        for s in chunk_segs:
            seg_end = s.start + s.duration
            time_tag = f"[{format_timestamp(s.start)} - {format_timestamp(seg_end)} | {s.start:.1f}s - {seg_end:.1f}s]"
            lines.append(f"{time_tag} {s.text}")

        formatted_text = "\n".join(lines)
        chunks.append(TranscriptChunk(
            chunk_index=chunk_idx,
            total_chunks=0,  # updated below
            start_time=chunk_segs[0].start,
            end_time=chunk_segs[-1].start + chunk_segs[-1].duration,
            segments=chunk_segs,
            formatted_text=formatted_text
        ))

        chunk_idx += 1
        current_window_start += step_seconds

        # If the remaining content from current_window_start is shorter than overlap, break
        if current_window_start >= total_duration:
            break

    total = len(chunks)
    for c in chunks:
        c.total_chunks = total

    return chunks

def snap_timestamps_to_segments(
    start: float,
    end: float,
    segments: List[TranscriptSegment],
    video_duration: Optional[float] = None
) -> Tuple[float, float]:
    """
    Clamps timestamps within video duration and snaps start/end to actual transcript boundaries.
    Enforces minimum 15s and maximum 90s duration limits.
    """
    if not segments:
        clamped_start = max(0.0, start)
        clamped_end = max(clamped_start + 15.0, min(clamped_start + 90.0, end))
        return round(clamped_start, 2), round(clamped_end, 2)

    min_time = segments[0].start
    max_time = segments[-1].start + segments[-1].duration
    if video_duration and video_duration > 0:
        max_time = min(max_time, video_duration)

    # 1. Clamp to global bounds
    s = max(min_time, min(start, max_time - 15.0))
    e = max(s + 15.0, min(end, max_time))

    # 2. Snap s to the nearest segment start
    best_s = s
    min_dist_s = float("inf")
    for seg in segments:
        dist = abs(seg.start - s)
        if dist < min_dist_s:
            min_dist_s = dist
            best_s = seg.start
        # If segment start is past s by more than 10s, can stop checking
        if seg.start > s + 10.0:
            break

    # 3. Snap e to the nearest segment end
    best_e = e
    min_dist_e = float("inf")
    for seg in segments:
        seg_end = seg.start + seg.duration
        dist = abs(seg_end - e)
        if dist < min_dist_e:
            min_dist_e = dist
            best_e = seg_end

    # Enforce 15s min and strict 58s max for YouTube Shorts algorithm compatibility
    duration = best_e - best_s
    if duration < 15.0:
        # Extend end
        best_e = min(max_time, best_s + 30.0)
    elif duration > 58.0:
        # Shorten end to 45s for optimal YouTube Shorts retention
        best_e = best_s + 45.0

    best_s = max(0.0, round(best_s, 2))
    best_e = min(max_time, max(best_s + 15.0, round(best_e, 2)))

    return best_s, best_e

def calculate_overlap_ratio(start1: float, end1: float, start2: float, end2: float) -> float:
    """Calculates Intersection over Union (IoU) overlap between two time intervals."""
    inter_start = max(start1, start2)
    inter_end = min(end1, end2)
    intersection = max(0.0, inter_end - inter_start)
    
    union = (end1 - start1) + (end2 - start2) - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union
