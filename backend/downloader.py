import os
import re
import asyncio
import tempfile
import zipfile
from typing import List, Dict, Any, Optional
import yt_dlp

# Base directory for cached clip downloads
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def sanitize_filename(filename: str, max_length: int = 60) -> str:
    """Removes invalid characters and restricts length for Windows file paths and clean URLs."""
    # Remove characters invalid in Windows paths or URL hash/query components (#, %, &, +, etc.)
    cleaned = re.sub(r'[<>:"/\\|?*\n\r\t#%&+;=]', '', filename)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('. ')
    if not cleaned:
        cleaned = "clip"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned

def get_clip_filepath(video_id: str, start: float, end: float, title: str) -> str:
    """Generates a deterministic filename for caching."""
    clean_title = sanitize_filename(title)
    filename = f"{video_id}_{int(start)}s-{int(end)}s_{clean_title}.mp4"
    return os.path.join(DOWNLOADS_DIR, filename)

def _download_section_sync(video_id: str, start: float, end: float, output_filepath: str) -> str:
    """
    Synchronously cuts and downloads only the specified start-to-end section using yt-dlp + ffmpeg.
    """
    if os.path.exists(output_filepath) and os.path.getsize(output_filepath) > 1000:
        return output_filepath

    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # We output to a temporary template, then rename to ensure atomic write
    temp_prefix = os.path.splitext(output_filepath)[0]
    out_tmpl = f"{temp_prefix}_temp.%(ext)s"

    ydl_opts = {
        # Select 1080p or 720p mp4 video + audio for fast download and crisp 9:16 rendering
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/bestvideo+bestaudio/best',
        'download_ranges': yt_dlp.utils.download_range_func(None, [(start, end)]),
        'outtmpl': out_tmpl,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception:
        fallback_opts = {
            'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'download_ranges': yt_dlp.utils.download_range_func(None, [(start, end)]),
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(fallback_opts) as ydl:
            ydl.download([url])

    temp_mp4 = f"{temp_prefix}_temp.mp4"
    if os.path.exists(temp_mp4):
        if os.path.exists(output_filepath):
            os.remove(output_filepath)
        os.rename(temp_mp4, output_filepath)
        return output_filepath

    # In case the file extension wasn't converted or matches template directly
    for f in os.listdir(DOWNLOADS_DIR):
        if f.startswith(os.path.basename(temp_prefix)):
            full_f = os.path.join(DOWNLOADS_DIR, f)
            if os.path.exists(output_filepath):
                os.remove(output_filepath)
            os.rename(full_f, output_filepath)
            return output_filepath

    raise RuntimeError(f"Failed to generate clip file for {video_id} ({start}s - {end}s)")

async def download_clip_file(video_id: str, start: float, end: float, title: str) -> str:
    """Async wrapper to download a single clip section."""
    target_path = get_clip_filepath(video_id, start, end, title)
    if os.path.exists(target_path) and os.path.getsize(target_path) > 1000:
        return target_path

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_section_sync, video_id, start, end, target_path)

def _create_zip_archive_sync(clip_files: List[tuple[str, str]], zip_output_path: str) -> str:
    """Creates a zip archive from a list of (file_path, arcname) tuples."""
    with zipfile.ZipFile(zip_output_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for file_path, arcname in clip_files:
            if os.path.exists(file_path):
                zipf.write(file_path, arcname=arcname)
    return zip_output_path

async def download_batch_clips(video_id: str, clips: List[Dict[str, Any]]) -> str:
    """
    Downloads multiple clips and packages them into a single .zip file.
    """
    clip_files: List[tuple[str, str]] = []
    for idx, c in enumerate(clips):
        start = float(c.get("start", 0))
        end = float(c.get("end", start + 30))
        title = c.get("title") or f"clip_{idx + 1}"
        file_path = await download_clip_file(video_id, start, end, title)
        safe_title = sanitize_filename(title)
        arcname = f"#{idx+1:02d}_{safe_title}_{int(start)}s-{int(end)}s.mp4"
        clip_files.append((file_path, arcname))

    zip_filename = f"clipscout_{video_id}_selected_{len(clips)}_clips.zip"
    zip_path = os.path.join(DOWNLOADS_DIR, zip_filename)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _create_zip_archive_sync, clip_files, zip_path)
