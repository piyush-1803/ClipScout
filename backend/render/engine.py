import os
import re
import json
import time
import uuid
import math
import shutil
import asyncio
import subprocess
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
import yt_dlp

from .faces import FaceTracker, FaceTrack
from .speaker import ActiveSpeakerDetector
from .shots import ShotPlanner, ShotDecision
from .reframe import render_reframed_video, render_debug_overlay_video
from .transcribe import transcribe_audio_words, romanize_words_to_hinglish, WordTimestamp, SentenceSegment
from .captions import build_caption_lines, generate_ass_script, rebuild_ass_file, FONTS_DIR

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def sanitize_slug(text: str, max_len: int = 40) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_\-\s]', '', text).strip()
    slug = re.sub(r'\s+', '_', cleaned)
    return slug[:max_len] if slug else "clip"

# System Capabilities Check
_SYSTEM_INFO_CACHE: Optional[Dict[str, Any]] = None

def get_system_capabilities() -> Dict[str, Any]:
    """Inspects FFmpeg, libass, hardware encoders, Python version, and model status."""
    global _SYSTEM_INFO_CACHE
    if _SYSTEM_INFO_CACHE:
        return _SYSTEM_INFO_CACHE

    info = {
        "ffmpeg_found": False,
        "libass_available": False,
        "available_encoders": [],
        "best_encoder": "libx264",
        "python_version": "",
        "whisper_ready": True,
        "yunet_ready": os.path.exists(os.path.join(os.path.dirname(__file__), "models", "face_detection_yunet_2023mar.onnx")),
        "fonts_ready": os.path.exists(FONTS_DIR) and len(os.listdir(FONTS_DIR)) > 0
    }

    import sys
    info["python_version"] = sys.version.split()[0]

    try:
        res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True)
        info["ffmpeg_found"] = True
        v_output = res.stdout.lower()
        if "--enable-libass" in v_output or "libass" in v_output:
            info["libass_available"] = True
    except Exception:
        info["ffmpeg_found"] = False

    # Check available video encoders
    if info["ffmpeg_found"]:
        try:
            enc_res = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True)
            enc_text = enc_res.stdout
            test_encoders = ["h264_nvenc", "h264_qsv", "h264_amf", "libx264"]
            for enc in test_encoders:
                if enc in enc_text:
                    info["available_encoders"].append(enc)

            # Test hardware encoder validity
            for candidate in ["h264_nvenc", "h264_qsv", "h264_amf"]:
                if candidate in info["available_encoders"]:
                    # Probe with a fast 1-frame test
                    test_cmd = [
                        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
                        "-c:v", candidate, "-f", "null", "-"
                    ]
                    probe = subprocess.run(test_cmd, capture_output=True)
                    if probe.returncode == 0:
                        info["best_encoder"] = candidate
                        break
        except Exception:
            info["best_encoder"] = "libx264"

    _SYSTEM_INFO_CACHE = info
    return info

def download_padded_clip_segment(
    video_id: str,
    raw_start: float,
    raw_end: float,
    max_resolution: int = 1080
) -> Tuple[str, float, float]:
    """
    Downloads only [start - 4.0s, end + 8.0s] using yt-dlp download_ranges.
    Returns: (output_filepath, actual_segment_start, actual_segment_end)
    """
    pad_start = max(0.0, raw_start - 4.0)
    pad_end = raw_end + 8.0

    filename = f"{video_id}_{int(pad_start)}s-{int(pad_end)}s_padded.mp4"
    out_path = os.path.join(DOWNLOADS_DIR, filename)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 100000:
        return out_path, pad_start, pad_end

    url = f"https://www.youtube.com/watch?v={video_id}"
    temp_prefix = os.path.splitext(out_path)[0]
    out_tmpl = f"{temp_prefix}_dl.%(ext)s"

    res_filter = f"[height<={max_resolution}]" if max_resolution <= 1440 else ""
    fmt_str = f"bestvideo{res_filter}[ext=mp4]+bestaudio[ext=m4a]/best{res_filter}[ext=mp4]/bestvideo+bestaudio/best"

    # Avoid force_keyframes_at_cuts as it causes ffmpeg remote streaming crashes on Windows
    ydl_opts = {
        'format': fmt_str,
        'download_ranges': yt_dlp.utils.download_range_func(None, [(pad_start, pad_end)]),
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
            'download_ranges': yt_dlp.utils.download_range_func(None, [(pad_start, pad_end)]),
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(fallback_opts) as ydl:
            ydl.download([url])

    # Check for downloaded output file
    downloaded_file = None
    for ext in ["mp4", "mkv", "webm"]:
        candidate = f"{temp_prefix}_dl.{ext}"
        if os.path.exists(candidate) and os.path.getsize(candidate) > 10000:
            downloaded_file = candidate
            break

    if not downloaded_file:
        for f in os.listdir(DOWNLOADS_DIR):
            if f.startswith(os.path.basename(temp_prefix)):
                full_f = os.path.join(DOWNLOADS_DIR, f)
                if os.path.exists(full_f) and os.path.getsize(full_f) > 10000:
                    downloaded_file = full_f
                    break

    if downloaded_file:
        if downloaded_file.endswith(".mp4"):
            if os.path.exists(out_path):
                os.remove(out_path)
            os.rename(downloaded_file, out_path)
            return out_path, pad_start, pad_end
        else:
            # Remux to mp4 with ffmpeg locally (super fast, no re-encode)
            cmd = ["ffmpeg", "-y", "-i", downloaded_file, "-c", "copy", out_path]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode == 0 and os.path.exists(out_path):
                try:
                    os.remove(downloaded_file)
                except Exception:
                    pass
                return out_path, pad_start, pad_end

    raise RuntimeError(f"Failed to download padded video section for {video_id} [{pad_start}s - {pad_end}s]")

def smart_trim_segment(
    padded_video_path: str,
    output_trimmed_path: str,
    pad_start_time: float,
    orig_clip_start: float,
    orig_clip_end: float,
    sentences: List[SentenceSegment],
    words: List[WordTimestamp],
    max_duration: float = 90.0
) -> Tuple[str, float, float, float]:
    """
    Applies creator-grade smart trimming:
    - Snaps start to sentence containing hook word minus 0.15s.
    - Extends end so the speaker cleanly finishes their thought (up to +8s).
    - Audio 30ms click fade in and out.
    Returns: (output_trimmed_path, final_rel_start, final_rel_end, final_duration)
    """
    target_abs_start = orig_clip_start
    target_abs_end = orig_clip_end

    # Relative to padded clip start
    rel_clip_start = orig_clip_start - pad_start_time
    rel_clip_end = orig_clip_end - pad_start_time

    # 1. Start boundary: snap to beginning of sentence containing the hook
    best_start = rel_clip_start
    for s in sentences:
        if s.start <= rel_clip_start + 1.2 <= s.end or (s.start <= rel_clip_start and s.end >= rel_clip_start - 0.5):
            best_start = max(0.0, s.start - 0.15)
            break

    # 2. End boundary: finish the thought
    best_end = rel_clip_end
    for s in sentences:
        if s.start <= rel_clip_end <= s.end:
            # If current sentence ends within 1.5s after clip end, finish it!
            if s.end - rel_clip_end <= 6.0:
                best_end = s.end + 0.25
            break
        elif s.start > rel_clip_end and (s.start - rel_clip_end) <= 1.0:
            # Check if next thought completes shortly
            if s.end - rel_clip_end <= 7.0:
                best_end = s.end + 0.25
                break

    # Enforce minimum 15s and maximum 90s
    dur = best_end - best_start
    if dur < 15.0:
        best_end = best_start + 15.5
    elif dur > max_duration:
        # Find last complete sentence before max_duration
        candidate_end = best_start + max_duration
        for s in reversed(sentences):
            if best_start + 15.0 <= s.end <= candidate_end:
                best_end = s.end + 0.2
                break
        if best_end - best_start > max_duration:
            best_end = best_start + max_duration

    final_dur = round(best_end - best_start, 2)
    best_start = round(best_start, 3)
    best_end = round(best_end, 3)

    # Cut with FFmpeg applying 30ms audio fade in/out to eliminate click artifacts
    fade_out_st = max(0.0, final_dur - 0.03)
    afilter = f"afade=t=in:ss=0:d=0.03,afade=t=out:st={fade_out_st:.3f}:d=0.03"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(best_start),
        "-to", str(best_end),
        "-i", padded_video_path,
        "-af", afilter,
        "-c:v", "libx264", "-crf", "16", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        output_trimmed_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    return output_trimmed_path, best_start, best_end, final_dur

@dataclass
class RenderJob:
    job_id: str
    video_id: str
    clip_index: int
    clip_title: str
    channel_name: str
    start: float
    end: float
    hook_line: str
    seo_metadata: Dict[str, Any]
    output_dir: str
    caption_style: str = "creator_classic"  # "creator_classic" | "active_word_pop" | "clean_outline"
    language: str = "auto"                  # "auto" | "en" | "hinglish" | "hi"
    quality_preset: str = "final"           # "preview" | "final"
    dynamic_zoom: bool = True
    credit_overlay: bool = True
    credit_duration: float = 6.0
    debug_mode: bool = False
    max_resolution: int = 1080
    stage: str = "queued"
    progress: float = 0.0
    message: str = "In queue..."
    error: Optional[str] = None
    output_files: Dict[str, str] = None
    cancel_requested: bool = False

class RenderEngine:
    def __init__(self):
        self.jobs: Dict[str, RenderJob] = {}
        self.listeners: Dict[str, List[asyncio.Queue]] = {}
        self.queue = asyncio.Queue()
        self.worker_task = None

    def start_worker(self):
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._process_queue())

    def create_job(self, **kwargs) -> RenderJob:
        job_id = str(uuid.uuid4())[:8]
        v_id = kwargs.get("video_id", "video")
        rank = kwargs.get("clip_index", 1)
        slug = sanitize_slug(kwargs.get("clip_title", "clip"))
        clip_out_dir = os.path.join(OUTPUTS_DIR, v_id, f"clip_{rank:02d}_{slug}")
        os.makedirs(clip_out_dir, exist_ok=True)

        job = RenderJob(job_id=job_id, output_dir=clip_out_dir, **kwargs)
        self.jobs[job_id] = job
        self.queue.put_nowait(job)
        self.start_worker()
        return job

    def cancel_job(self, job_id: str) -> bool:
        if job_id in self.jobs:
            self.jobs[job_id].cancel_requested = True
            return True
        return False

    def emit_event(self, job_id: str, stage: str, progress: float, message: str, error: Optional[str] = None):
        job = self.jobs.get(job_id)
        if job:
            job.stage = stage
            job.progress = progress
            job.message = message
            job.error = error

        payload = {
            "job_id": job_id,
            "stage": stage,
            "progress": progress,
            "message": message,
            "error": error
        }
        if job and job.output_files:
            payload["outputs"] = job.output_files

        for q in self.listeners.get(job_id, []):
            q.put_nowait(payload)

    async def _process_queue(self):
        while True:
            job = await self.queue.get()
            try:
                await self._execute_render(job)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.emit_event(job.job_id, "error", 0.0, f"Render failed: {str(e)}", error=str(e))
            finally:
                self.queue.task_done()

    async def _execute_render(self, job: RenderJob):
        if job.cancel_requested:
            self.emit_event(job.job_id, "error", 0.0, "Job cancelled by user.")
            return

        out_dir = job.output_dir
        final_mp4 = os.path.join(out_dir, "final.mp4")
        reframed_mp4 = os.path.join(out_dir, "reframed.mp4")
        captions_json = os.path.join(out_dir, "captions.json")
        captions_ass = os.path.join(out_dir, "captions.ass")
        shots_json = os.path.join(out_dir, "shots.json")
        post_txt = os.path.join(out_dir, "post.txt")
        debug_mp4 = os.path.join(out_dir, "debug.mp4")

        # STAGE 1: Download segment
        self.emit_event(job.job_id, "downloading", 10.0, "Downloading high-resolution clip segment...")
        loop = asyncio.get_event_loop()
        padded_path, pad_start, pad_end = await loop.run_in_executor(
            None, download_padded_clip_segment, job.video_id, job.start, job.end, job.max_resolution
        )

        if job.cancel_requested:
            self.emit_event(job.job_id, "error", 0.0, "Job cancelled.")
            return

        # STAGE 2: Transcribe segment with word timestamps
        self.emit_event(job.job_id, "transcribing", 25.0, "Transcribing speech with word-level acoustic timestamps...")
        audio_wav = os.path.join(out_dir, "temp_audio_16k.wav")
        from .speaker import extract_mono_audio_16k
        await loop.run_in_executor(None, extract_mono_audio_16k, padded_path, audio_wav)

        raw_words, sentences, detected_lang = await loop.run_in_executor(
            None, transcribe_audio_words, audio_wav, job.language, "small"
        )

        # STAGE 3: Smart Trim (Finish the thought)
        self.emit_event(job.job_id, "trimming", 35.0, "Snapping sentence boundaries & finishing speaker thought...")
        trimmed_path = os.path.join(out_dir, "trimmed_raw.mp4")
        _, rel_s, rel_e, trimmed_dur = await loop.run_in_executor(
            None, smart_trim_segment, padded_path, trimmed_path, pad_start, job.start, job.end, sentences, raw_words
        )

        # Filter words to the trimmed range
        trimmed_words: List[WordTimestamp] = []
        for w in raw_words:
            if rel_s <= w.start <= rel_e or rel_s <= w.end <= rel_e:
                trimmed_words.append(WordTimestamp(
                    word=w.word,
                    start=round(max(0.0, w.start - rel_s), 3),
                    end=round(min(trimmed_dur, w.end - rel_s), 3),
                    probability=w.probability
                ))

        # Hinglish Romanization if requested
        if job.language == "hinglish" or (job.language == "auto" and detected_lang == "hi"):
            self.emit_event(job.job_id, "transcribing", 40.0, "Romanizing Devanagari into modern conversational Hinglish...")
            trimmed_words = await romanize_words_to_hinglish(trimmed_words)

        if job.cancel_requested:
            self.emit_event(job.job_id, "error", 0.0, "Job cancelled.")
            return

        # STAGE 4: Face Analysis & Active Speaker Detection
        self.emit_event(job.job_id, "analyzing_faces", 50.0, "Detecting faces at 10 fps (YuNet tracking)...")
        face_tracker = FaceTracker()
        tracks, _, _, frame_dims = await loop.run_in_executor(
            None, face_tracker.analyze_video, trimmed_path, 10.0, 640
        )

        self.emit_event(job.job_id, "analyzing_faces", 60.0, "Computing mouth motion & audio VAD for active speaker...")
        speaker_detector = ActiveSpeakerDetector()
        spk_scores = await loop.run_in_executor(
            None, speaker_detector.compute_speaking_scores, trimmed_path, tracks
        )

        # STAGE 5: Plan Shots with Hysteresis
        self.emit_event(job.job_id, "building_shots", 70.0, "Applying director hysteresis (hard cuts, dynamic punch-in zoom)...")
        sentence_ends = [round(max(0.0, s.end - rel_s), 2) for s in sentences if rel_s <= s.end <= rel_e]
        planner = ShotPlanner()
        shots = planner.plan_shots(
            tracks=tracks,
            speaking_scores=spk_scores,
            total_duration=trimmed_dur,
            frame_dims=frame_dims,
            enable_dynamic_zoom=job.dynamic_zoom,
            sentence_boundaries=sentence_ends
        )

        # Save shots.json
        with open(shots_json, "w", encoding="utf-8") as f:
            json.dump([asdict(s) for s in shots], f, indent=2)

        # STAGE 6: Reframe to 9:16
        self.emit_event(job.job_id, "reframing", 80.0, "Rendering 9:16 vertical reframe with Lanczos upscaling...")
        await loop.run_in_executor(
            None, render_reframed_video, trimmed_path, shots, reframed_mp4, trimmed_dur, 14, "fast"
        )

        # Optional Debug Overlay Video
        if job.debug_mode:
            self.emit_event(job.job_id, "reframing", 85.0, "Generating debug video with face boxes and speaking metrics...")
            await loop.run_in_executor(
                None, render_debug_overlay_video, trimmed_path, tracks, spk_scores, shots, debug_mp4
            )

        # STAGE 7: Build Captions & Credit Overlay
        self.emit_event(job.job_id, "captioning", 90.0, "Building bold animated ASS captions & safe-zone credit...")
        caption_lines = build_caption_lines(trimmed_words, uppercase=True)

        credit_str = f"Credit: {job.channel_name}. Full episode on YouTube" if job.credit_overlay else None
        generate_ass_script(
            lines=caption_lines,
            style_preset=job.caption_style,
            output_ass_path=captions_ass,
            credit_text=credit_str,
            credit_duration=job.credit_duration,
            video_duration=trimmed_dur,
            language=detected_lang
        )

        # Save captions.json
        captions_data = {
            "language": detected_lang,
            "style_preset": job.caption_style,
            "words": [asdict(w) for w in trimmed_words],
            "lines": [asdict(cl) for cl in caption_lines]
        }
        with open(captions_json, "w", encoding="utf-8") as f:
            json.dump(captions_data, f, indent=2)

        # STAGE 8: Final Master Export (20 Mbps target, loudnorm -14 LUFS, fontdir)
        self.emit_event(job.job_id, "encoding", 95.0, "Mastering final 1080x1920 Short (20 Mbps, loudnorm -14 LUFS)...")
        sys_caps = get_system_capabilities()
        chosen_encoder = sys_caps["best_encoder"] if job.quality_preset == "final" else "libx264"

        ass_filename = os.path.basename(captions_ass)
        # Fontsdir flag for libass (escape colon for Windows FFmpeg filter graph)
        escaped_fonts_dir = FONTS_DIR.replace('\\', '/').replace(':', r'\:')
        fonts_param = f":fontsdir='{escaped_fonts_dir}'"
        sub_filter = f"subtitles={ass_filename}{fonts_param}"

        if job.quality_preset == "preview":
            # 720x1280 preview preset
            cmd = [
                "ffmpeg", "-y", "-i", reframed_mp4,
                "-vf", f"scale=720:1280:flags=fast_bilinear,{sub_filter}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                final_mp4
            ]
        else:
            # 1080x1920 20 Mbps target master
            cmd = [
                "ffmpeg", "-y", "-i", reframed_mp4,
                "-vf", sub_filter,
                "-c:v", chosen_encoder,
                "-b:v", "20M", "-maxrate", "24M", "-bufsize", "40M",
                "-pix_fmt", "yuv420p",
                "-af", "loudnorm=I=-14:LRA=7:tp=-1.5",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart",
                final_mp4
            ]

        res = await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
        )
        if res.returncode != 0:
            # Fallback to pure libx264 without loudnorm if hardware encoder failed
            fallback_cmd = [
                "ffmpeg", "-y", "-i", reframed_mp4,
                "-vf", sub_filter,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                final_mp4
            ]
            await loop.run_in_executor(
                None, lambda: subprocess.run(fallback_cmd, cwd=out_dir, check=True)
            )

        # STAGE 9: Generate Post Kit (post.txt)
        seo = job.seo_metadata or {}
        yt_url = f"https://www.youtube.com/watch?v={job.video_id}"
        post_content = f"""==================================================
CLIPSCOUT READY-TO-PUBLISH SHORT POST KIT
==================================================

[YOUTUBE SHORTS TITLE]
{seo.get('title', job.clip_title)} #Shorts

[DESCRIPTION]
{seo.get('description', '')}

Full episode: {yt_url}
Original creator credit: {job.channel_name}

{' '.join(seo.get('hashtags', ['#Shorts', '#Viral', '#Podcast']))}

[SUGGESTED PINNED COMMENT]
🔥 What was your biggest takeaway from this moment? Watch the full discussion here: {yt_url}

[TAGS / KEYWORDS]
{', '.join(seo.get('keywords', ['shorts', 'podcast', 'viral']))}
"""
        with open(post_txt, "w", encoding="utf-8") as f:
            f.write(post_content)

        # Clean up temporary intermediate audio/video
        for temp_f in [audio_wav, trimmed_path]:
            if os.path.exists(temp_f):
                try:
                    os.remove(temp_f)
                except Exception:
                    pass

        # Record output files
        rel_dir = os.path.relpath(out_dir, BASE_DIR).replace("\\", "/")
        output_files = {
            "final_video": f"/{rel_dir}/final.mp4",
            "reframed_video": f"/{rel_dir}/reframed.mp4",
            "captions_json": f"/{rel_dir}/captions.json",
            "captions_ass": f"/{rel_dir}/captions.ass",
            "shots_json": f"/{rel_dir}/shots.json",
            "post_txt": f"/{rel_dir}/post.txt"
        }
        if job.debug_mode and os.path.exists(debug_mp4):
            output_files["debug_video"] = f"/{rel_dir}/debug.mp4"

        job.output_files = output_files
        self.emit_event(job.job_id, "done", 100.0, "Short rendered successfully and ready to publish!")

    async def restyle_captions(
        self,
        output_dir: str,
        new_style: str,
        new_lines_data: Optional[List[Dict[str, Any]]] = None,
        credit_text: Optional[str] = None
    ) -> str:
        """Quickly re-burns updated captions/style on the cached reframed.mp4 in seconds."""
        captions_json = os.path.join(output_dir, "captions.json")
        captions_ass = os.path.join(output_dir, "captions.ass")
        reframed_mp4 = os.path.join(output_dir, "reframed.mp4")
        final_mp4 = os.path.join(output_dir, "final.mp4")

        if not os.path.exists(reframed_mp4):
            raise FileNotFoundError("Cached reframed.mp4 not found in output directory.")

        with open(captions_json, "r", encoding="utf-8") as f:
            c_data = json.load(f)

        if new_lines_data:
            c_data["lines"] = new_lines_data

        c_data["style_preset"] = new_style
        with open(captions_json, "w", encoding="utf-8") as f:
            json.dump(c_data, f, indent=2)

        rebuild_ass_file(
            captions_data=c_data,
            new_style=new_style,
            output_ass_path=captions_ass,
            credit_text=credit_text
        )

        ass_filename = os.path.basename(captions_ass)
        escaped_fonts_dir = FONTS_DIR.replace('\\', '/').replace(':', r'\:')
        fonts_param = f":fontsdir='{escaped_fonts_dir}'"
        sub_filter = f"subtitles={ass_filename}{fonts_param}"

        loop = asyncio.get_event_loop()
        cmd = [
            "ffmpeg", "-y", "-i", reframed_mp4,
            "-vf", sub_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "16",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            final_mp4
        ]
        await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, cwd=output_dir, check=True)
        )
        return final_mp4

RENDER_ENGINE = RenderEngine()
