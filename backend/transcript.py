import re
import asyncio
from typing import List, Optional, Tuple, Dict, Any
import httpx
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp

from .models import TranscriptSegment, VideoMetadata, format_timestamp

YOUTUBE_URL_PATTERNS = [
    r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})',
    r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})',
    r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/live\/([a-zA-Z0-9_-]{11})',
    r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})',
    r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
    r'^([a-zA-Z0-9_-]{11})$'  # direct video ID
]

def extract_video_id(url_or_id: str) -> Optional[str]:
    """Robustly extracts YouTube 11-char video ID from various URL formats."""
    url_or_id = url_or_id.strip()
    for pattern in YOUTUBE_URL_PATTERNS:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return None

async def fetch_video_metadata(video_id: str) -> VideoMetadata:
    """Fetches video title, channel, duration, and thumbnail via yt-dlp or oEmbed."""
    def _extract():
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return info

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _extract)
        title = info.get("title", f"YouTube Video {video_id}")
        channel = info.get("uploader", info.get("channel", "Unknown Channel"))
        duration = float(info.get("duration", 0.0) or 0.0)
        thumbnail_url = info.get("thumbnail") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

        # Extract YouTube audience replay heatmap points if available
        raw_hm = info.get("heatmap")
        heatmap = None
        if isinstance(raw_hm, list) and len(raw_hm) > 0:
            heatmap = []
            for pt in raw_hm:
                if isinstance(pt, dict) and "start_time" in pt and "value" in pt:
                    heatmap.append({
                        "start_time": round(float(pt["start_time"]), 2),
                        "end_time": round(float(pt.get("end_time", pt["start_time"] + 2.0)), 2),
                        "value": round(float(pt["value"]), 3)
                    })

        return VideoMetadata(
            video_id=video_id,
            title=title,
            channel=channel,
            duration=duration,
            duration_formatted=format_timestamp(duration),
            thumbnail_url=thumbnail_url,
            heatmap=heatmap
        )
    except Exception:
        # Fallback to YouTube oEmbed API
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json")
                if res.status_code == 200:
                    data = res.json()
                    return VideoMetadata(
                        video_id=video_id,
                        title=data.get("title", f"YouTube Video {video_id}"),
                        channel=data.get("author_name", "Unknown Channel"),
                        duration=0.0,
                        duration_formatted="Unknown",
                        thumbnail_url=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    )
        except Exception:
            pass

        return VideoMetadata(
            video_id=video_id,
            title=f"YouTube Video ({video_id})",
            channel="YouTube",
            duration=0.0,
            duration_formatted="Unknown",
            thumbnail_url=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
        )

def _fetch_with_youtube_transcript_api(video_id: str) -> List[TranscriptSegment]:
    """Tries fetching transcripts via youtube-transcript-api."""
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    
    # 1. Prefer manual English transcripts
    transcript = None
    try:
        transcript = transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
    except Exception:
        pass

    # 2. Prefer generated English transcripts
    if not transcript:
        try:
            transcript = transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
        except Exception:
            pass

    # 3. Fallback to any transcript available
    if not transcript:
        for t in transcript_list:
            transcript = t
            break

    if not transcript:
        raise ValueError("No transcript track found in YouTubeTranscriptApi.")

    fetched_data = transcript.fetch()
    segments = []
    for item in fetched_data:
        text = item.get("text", "").replace("\n", " ").strip()
        if text:
            segments.append(TranscriptSegment(
                start=round(float(item["start"]), 2),
                duration=round(float(item["duration"]), 2),
                text=text
            ))
    return segments

def _fetch_with_yt_dlp_subtitles(video_id: str) -> List[TranscriptSegment]:
    """Fallback: extract subtitles using yt-dlp."""
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en', 'en-.*'],
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        subtitles = info.get('subtitles', {}) or info.get('automatic_captions', {})
        
        target_sub = None
        for lang, formats in subtitles.items():
            if lang.startswith('en'):
                for fmt in formats:
                    if fmt.get('ext') == 'json3' or fmt.get('ext') == 'vtt':
                        target_sub = fmt.get('url')
                        break
            if target_sub:
                break

        if not target_sub and subtitles:
            # Pick first available
            first_key = next(iter(subtitles.keys()))
            formats = subtitles[first_key]
            if formats:
                target_sub = formats[0].get('url')

        if not target_sub:
            raise ValueError("No subtitle stream URL found via yt-dlp.")

        # Download subtitle data
        resp = httpx.get(target_sub, timeout=15.0)
        resp.raise_for_status()
        raw_text = resp.text

        if "-->" in raw_text:
            return parse_srt_or_vtt(raw_text)
        elif raw_text.strip().startswith("{"):
            # json3 format
            import json
            data = json.loads(raw_text)
            segments = []
            events = data.get("events", [])
            for ev in events:
                t_start = ev.get("tStartMs", 0) / 1000.0
                d_duration = ev.get("dDurationMs", 0) / 1000.0
                segs = ev.get("segs", [])
                text = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
                if text and text != "\n":
                    segments.append(TranscriptSegment(
                        start=round(t_start, 2),
                        duration=round(d_duration, 2),
                        text=text
                    ))
            if segments:
                return segments

    raise ValueError("Could not parse subtitles from yt-dlp.")

async def fetch_transcript(video_id: str) -> List[TranscriptSegment]:
    """Fetches transcript with primary youtube-transcript-api and fallback to yt-dlp."""
    loop = asyncio.get_event_loop()
    
    # 1. Primary
    try:
        segments = await loop.run_in_executor(None, _fetch_with_youtube_transcript_api, video_id)
        if segments:
            return segments
    except Exception as e_primary:
        pass

    # 2. Fallback
    try:
        segments = await loop.run_in_executor(None, _fetch_with_yt_dlp_subtitles, video_id)
        if segments:
            return segments
    except Exception as e_fallback:
        pass

    raise ValueError(
        "No transcript or subtitles could be found for this video. "
        "The video might not have captions enabled or YouTube might have restricted caption access. "
        "You can manually paste a transcript or upload an .srt/.vtt file below."
    )

def parse_timecode(time_str: str) -> float:
    """Parses 'HH:MM:SS,mmm' or 'MM:SS.mmm' or 'MM:SS' into seconds."""
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(parts[0])

def parse_srt_or_vtt(content: str) -> List[TranscriptSegment]:
    """Parses SRT or WebVTT string into TranscriptSegments."""
    segments: List[TranscriptSegment] = []
    # Pattern matches 00:01:23.456 --> 00:01:27.890
    cue_pattern = re.compile(
        r'((?:\d{1,2}:)?\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[,\.]\d{1,3})'
    )

    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = cue_pattern.search(line)
        if match:
            start_sec = parse_timecode(match.group(1))
            end_sec = parse_timecode(match.group(2))
            duration = max(0.5, end_sec - start_sec)
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and not cue_pattern.search(lines[i]):
                # Remove formatting tags like <v ...> or <b>
                cleaned_line = re.sub(r'<[^>]+>', '', lines[i].strip())
                if cleaned_line and not cleaned_line.isdigit():
                    text_lines.append(cleaned_line)
                i += 1
            text = " ".join(text_lines).strip()
            if text:
                segments.append(TranscriptSegment(
                    start=round(start_sec, 2),
                    duration=round(duration, 2),
                    text=text
                ))
        else:
            i += 1
    return segments

def parse_manual_transcript(text_content: str) -> List[TranscriptSegment]:
    """Parses manual transcript which may be SRT, VTT, or plain text with [MM:SS] timestamps."""
    text_content = text_content.strip()
    if "-->" in text_content:
        parsed = parse_srt_or_vtt(text_content)
        if parsed:
            return parsed

    # Check for [01:23] or (01:23) or 01:23 patterns at line starts
    timestamp_pattern = re.compile(r'^[\[\(]?((?:\d{1,2}:)?\d{2}:\d{2})[\]\)]?\s*(.+)$')
    segments: List[TranscriptSegment] = []
    lines = text_content.splitlines()
    current_time = 0.0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = timestamp_pattern.match(line)
        if match:
            t_str = match.group(1)
            t_val = parse_timecode(t_str)
            content = match.group(2).strip()
            if segments:
                # Update previous segment duration if realistic
                prev = segments[-1]
                if t_val > prev.start and (t_val - prev.start) < 30.0:
                    prev.duration = round(t_val - prev.start, 2)
            segments.append(TranscriptSegment(
                start=round(t_val, 2),
                duration=4.0,
                text=content
            ))
            current_time = t_val + 4.0
        else:
            # Sentence-based fallback for plain text without timestamps
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', line) if s.strip()]
            for s in sentences:
                segments.append(TranscriptSegment(
                    start=round(current_time, 2),
                    duration=3.5,
                    text=s
                ))
                current_time += 3.5

    return segments
