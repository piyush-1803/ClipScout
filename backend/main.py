import os
import re
import tempfile
import asyncio
import json
import logging
import urllib.parse
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import (
    VideoMetadata,
    TranscriptSegment,
    TranscriptResponse,
    AnalyzeRequest,
    TestKeyRequest,
    TestKeyResponse,
    DownloadClipRequest,
    DownloadBatchRequest,
    RenderShortRequest,
    RenderShortResponse,
    RenderShortBatchRequest,
    StudioRenderRequest,
    CaptionsRebuildRequest,
    ListModelsRequest,
    ListModelsResponse,
    ModelItem,
    AnalysisProgressEvent,
)
from .transcript import (
    extract_video_id,
    fetch_video_metadata,
    fetch_transcript,
    parse_manual_transcript,
)
from .providers.base import LLMProvider, mask_all_keys, mask_api_key
from .providers.gemini import GeminiProvider
from .providers.openai_compat import OpenAICompatProvider
from .analyzer import AnalysisPipeline
from .downloader import download_clip_file, download_batch_clips, sanitize_filename
from .editor import render_vertical_short, generate_youtube_fair_use_metadata, SHORTS_DIR
from .render.engine import RENDER_ENGINE, OUTPUTS_DIR, get_system_capabilities

# Suppress noisy logging that might inadvertently dump headers/keys
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ClipScout")

app = FastAPI(
    title="ClipScout API",
    description="Intelligent Short-Form Clip Extraction & Virality Scoring Engine",
    version="1.0.0"
)

# Enable CORS for Vite dev server & production frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount outputs directory for direct streaming/downloading of rendered assets
os.makedirs(OUTPUTS_DIR, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")

def create_provider(
    provider_type: str,
    api_key: str,
    model: str,
    base_url: Optional[str] = None
) -> LLMProvider:
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="API Key is missing. Please enter your API key in Settings."
        )

    clean_provider = provider_type.lower().strip()
    if clean_provider == "openai_compat" or clean_provider == "openai":
        return OpenAICompatProvider(
            api_key=api_key,
            model=model or "llama-3.3-70b-versatile",
            base_url=base_url
        )
    else:
        clean_model = model.strip() if model else "auto"
        return GeminiProvider(
            api_key=api_key,
            model=clean_model
        )

class FetchTranscriptBody(BaseModel):
    url: str
    manual_transcript: Optional[str] = None

@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "ClipScout"}

@app.post("/api/test-key", response_model=TestKeyResponse)
async def test_key(
    req: TestKeyRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """Tests LLM credentials without logging or storing the key."""
    if not x_api_key:
        raise HTTPException(
            status_code=400,
            detail="No API key provided in X-API-Key header."
        )

    provider = create_provider(
        provider_type=req.provider,
        api_key=x_api_key,
        model=req.model,
        base_url=req.base_url
    )

    result = await provider.test_connection()
    return TestKeyResponse(
        success=result.get("success", False),
        message=result.get("message", "Validation completed"),
        model=result.get("model", req.model)
    )

@app.post("/api/list-models", response_model=ListModelsResponse)
async def list_models(
    req: ListModelsRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    Dynamically lists all models available for the user's provider/key in real time.
    Supports complete plug-and-play flexibility for any new model release.
    """
    clean_provider = req.provider.lower().strip()
    if clean_provider in ("openai_compat", "openai"):
        prov = OpenAICompatProvider(api_key=x_api_key or "", model="dummy", base_url=req.base_url)
    else:
        prov = GeminiProvider(api_key=x_api_key or "", model="dummy")

    models_raw = await prov.list_available_models()
    return ListModelsResponse(
        provider=req.provider,
        models=[ModelItem(id=m["id"], name=m["name"]) for m in models_raw]
    )

@app.post("/api/transcript", response_model=TranscriptResponse)
async def get_transcript(body: FetchTranscriptBody):
    """Fetches video metadata and transcript or parses manual text."""
    video_id = extract_video_id(body.url)
    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid YouTube URL. Please provide a standard watch, shorts, or live link (e.g., https://www.youtube.com/watch?v=...)."
        )

    # Fetch metadata
    metadata = await fetch_video_metadata(video_id)

    # If user provided a manual transcript or srt/vtt
    if body.manual_transcript and body.manual_transcript.strip():
        try:
            segments = parse_manual_transcript(body.manual_transcript)
            if not segments:
                raise ValueError("Could not extract any sentences or timestamped lines from manual text.")
            return TranscriptResponse(video=metadata, segments=segments)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to parse manual transcript: {str(e)}"
            )

    # Otherwise fetch automatically from YouTube
    try:
        segments = await fetch_transcript(video_id)
        return TranscriptResponse(video=metadata, segments=segments)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        safe_msg = mask_all_keys(str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving transcript: {safe_msg}. You can paste a manual transcript below."
        )

@app.post("/api/analyze")
async def analyze_video(
    req: AnalyzeRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    Streams analysis events stage-by-stage using Server-Sent Events (SSE).
    """
    if not x_api_key:
        raise HTTPException(
            status_code=400,
            detail="API Key required. Please provide your API key in the X-API-Key header."
        )

    provider = create_provider(
        provider_type=req.provider,
        api_key=x_api_key,
        model=req.model,
        base_url=req.base_url
    )

    # Free tier Gemini has a strict 15 RPM limit; 1 worker prevents burst 429 throttling
    concurrency = 1 if (req.provider or "gemini").lower() == "gemini" else 2
    pipeline = AnalysisPipeline(provider=provider, max_concurrency=concurrency)

    async def event_generator():
        try:
            # 1. Fetch metadata & transcript if not already provided
            video_id = req.video_id or extract_video_id(req.url)
            if not video_id:
                yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'message': 'Invalid YouTube URL', 'error': 'Could not extract valid video ID from URL.'})}\n\n"
                return

            yield f"data: {json.dumps({'stage': 'fetching', 'progress': 2.0, 'message': 'Retrieving video details and transcript...'})}\n\n"

            metadata = await fetch_video_metadata(video_id)
            segments = req.segments

            if not segments:
                try:
                    segments = await fetch_transcript(video_id)
                except Exception as te:
                    err_text = mask_all_keys(mask_api_key(str(te), x_api_key))
                    yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'message': 'Transcript unavailable', 'error': err_text})}\n\n"
                    return

            if not segments:
                yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'message': 'Empty transcript', 'error': 'Transcript has no dialogue.'})}\n\n"
                return

            # Run Map-Reduce stream
            async for event in pipeline.run(
                video=metadata,
                segments=segments,
                output_language=req.output_language or "same as transcript",
                target_clips=req.target_clips or 10,
                model_name=req.model
            ):
                if await request.is_disconnected():
                    pipeline.cancel()
                    break

                yield f"data: {event.model_dump_json()}\n\n"

        except Exception as e:
            err_msg = mask_all_keys(mask_api_key(str(e), x_api_key))
            yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'message': 'Analysis failed', 'error': err_msg})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@app.post("/api/download-clip")
async def download_clip_endpoint(req: DownloadClipRequest):
    """
    Directly downloads an isolated MP4 slice of a clip via yt-dlp + ffmpeg.
    """
    try:
        file_path = await download_clip_file(
            video_id=req.video_id,
            start=req.start,
            end=req.end,
            title=req.title or "clip"
        )
        safe_title = sanitize_filename(req.title or "clip")
        download_name = f"{safe_title}_{int(req.start)}s-{int(req.end)}s.mp4"
        return FileResponse(
            path=file_path,
            filename=download_name,
            media_type="video/mp4"
        )
    except Exception as e:
        safe_err = mask_all_keys(str(e))
        raise HTTPException(status_code=500, detail=f"Failed to cut and download clip: {safe_err}")

@app.post("/api/download-clips-batch")
async def download_batch_endpoint(req: DownloadBatchRequest):
    """
    Directly downloads multiple selected clip slices and bundles them into a ZIP archive.
    """
    if not req.clips:
        raise HTTPException(status_code=400, detail="No clips specified for batch download.")

    try:
        clips_data = [
            {"start": c.start, "end": c.end, "title": c.title}
            for c in req.clips
        ]
        zip_path = await download_batch_clips(
            video_id=req.video_id,
            clips=clips_data
        )
        zip_filename = f"clipscout_{req.video_id}_selected_clips.zip"
        return FileResponse(
            path=zip_path,
            filename=zip_filename,
            media_type="application/zip"
        )
    except Exception as e:
        safe_err = mask_all_keys(str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process batch clip download: {safe_err}")

@app.post("/api/render-short", response_model=RenderShortResponse)
async def render_short_endpoint(req: RenderShortRequest):
    """
    Renders a ready-to-publish 9:16 vertical YouTube Short with:
    - 9:16 blurred background studio layout
    - Animated dynamic captions
    - Hook title card & creator attribution banner
    - Synthesized acoustic hook sound effect (100% royalty-free)
    - Full YouTube Fair Use & Copyright Safe metadata
    """
    try:
        out_path, filename = await render_vertical_short(
            video_id=req.video_id,
            start=req.start,
            end=req.end,
            hook_title=req.hook_title,
            channel_name=req.channel_name,
            segments=req.segments or [],
            add_sfx=req.add_sfx
        )

        seo_package = generate_youtube_fair_use_metadata(
            video_title=req.video_title,
            video_id=req.video_id,
            channel_name=req.channel_name,
            clip_title=req.hook_title,
            clip_reasoning=req.reasoning or "",
            hashtags=req.hashtags or []
        )

        file_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        duration = round(req.end - req.start, 1)
        encoded_filename = urllib.parse.quote(filename)

        return RenderShortResponse(
            success=True,
            filename=filename,
            download_url=f"/api/download-short/{encoded_filename}",
            stream_url=f"/api/stream-video/{encoded_filename}",
            file_size_bytes=file_size,
            duration=duration,
            seo_package=seo_package
        )
    except Exception as e:
        safe_err = mask_all_keys(str(e))
        raise HTTPException(status_code=500, detail=f"Failed to render 9:16 Short: {safe_err}")

@app.post("/api/render-shorts-batch")
async def render_shorts_batch_endpoint(req: RenderShortBatchRequest):
    """
    Batch renders all selected clips into ready-to-publish 9:16 vertical Shorts,
    includes a complete METADATA_AND_DESCRIPTIONS.txt file, and bundles into a ZIP archive.
    """
    if not req.clips:
        raise HTTPException(status_code=400, detail="No clips provided for batch render.")

    try:
        import zipfile
        temp_dir = tempfile.mkdtemp(prefix="clipscout_batch_render_")
        rendered_files = []
        descriptions_text = []

        for idx, clip_req in enumerate(req.clips):
            out_path, filename = await render_vertical_short(
                video_id=clip_req.video_id,
                start=clip_req.start,
                end=clip_req.end,
                hook_title=clip_req.hook_title,
                channel_name=clip_req.channel_name,
                segments=clip_req.segments or [],
                add_sfx=clip_req.add_sfx
            )
            arcname = f"#{idx+1:02d}_{filename}"
            rendered_files.append((out_path, arcname))

            seo = generate_youtube_fair_use_metadata(
                video_title=clip_req.video_title,
                video_id=clip_req.video_id,
                channel_name=clip_req.channel_name,
                clip_title=clip_req.hook_title,
                clip_reasoning=clip_req.reasoning or "",
                hashtags=clip_req.hashtags or []
            )

            descriptions_text.append(
                f"==================================================\n"
                f"SHORT #{idx+1}: {seo['title']}\n"
                f"File: {arcname}\n"
                f"Timestamps: {int(clip_req.start)}s - {int(clip_req.end)}s ({round(clip_req.end - clip_req.start, 1)}s)\n"
                f"--------------------------------------------------\n"
                f"DESCRIPTION:\n{seo['description']}\n\n"
            )

        # Write metadata file
        meta_file = os.path.join(temp_dir, "METADATA_AND_DESCRIPTIONS.txt")
        with open(meta_file, "w", encoding="utf-8") as f:
            f.write(
                f"CLIPSCOUT READY-TO-PUBLISH YOUTUBE SHORTS BUNDLE\n"
                f"Source: {req.video_title} (@{req.channel_name})\n"
                f"Generated clips: {len(req.clips)}\n\n"
                + "\n".join(descriptions_text)
            )
        rendered_files.append((meta_file, "METADATA_AND_DESCRIPTIONS.txt"))

        # Create zip
        zip_filename = f"clipscout_{req.video_id}_ready_916_shorts.zip"
        zip_path = os.path.join(SHORTS_DIR, zip_filename)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fpath, aname in rendered_files:
                if os.path.exists(fpath):
                    zf.write(fpath, arcname=aname)

        return FileResponse(
            path=zip_path,
            filename=zip_filename,
            media_type="application/zip"
        )
    except Exception as e:
        safe_err = mask_all_keys(str(e))
        raise HTTPException(status_code=500, detail=f"Failed to batch render shorts: {safe_err}")

def _find_short_file(raw_name: str) -> Optional[str]:
    """Finds a rendered short on disk with robust fallback matching."""
    unquoted = urllib.parse.unquote(raw_name)
    candidates = [
        unquoted,
        raw_name,
        sanitize_filename(unquoted, max_length=120),
        sanitize_filename(raw_name, max_length=120)
    ]
    for c in candidates:
        fp = os.path.join(SHORTS_DIR, c)
        if os.path.exists(fp):
            return fp

    # Substring / prefix matching in case of URL anchor '#' stripping by browser
    prefix = unquoted.split("#")[0].strip().rstrip("._-")
    if prefix and len(prefix) >= 15:
        for f in os.listdir(SHORTS_DIR):
            if f.startswith(prefix) and f.endswith(".mp4"):
                return os.path.join(SHORTS_DIR, f)

    return None

@app.get("/api/download-short/{filename}")
async def download_short_file(filename: str):
    """Direct download for rendered 9:16 short MP4."""
    file_path = _find_short_file(filename)
    if not file_path:
        raise HTTPException(status_code=404, detail="Requested Short file not found.")
    return FileResponse(
        path=file_path,
        filename=os.path.basename(file_path),
        media_type="video/mp4"
    )

@app.get("/api/stream-video/{filename}")
async def stream_video(filename: str, request: Request):
    """Streams the rendered MP4 file with HTTP Range support for HTML5 video playback."""
    file_path = _find_short_file(filename)
    if not file_path:
        raise HTTPException(status_code=404, detail="Video file not found.")

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(file_path, media_type="video/mp4")

    # Range: bytes=start-end
    range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not range_match:
        return FileResponse(file_path, media_type="video/mp4")

    start = int(range_match.group(1))
    end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
    end = min(end, file_size - 1)
    chunk_size = end - start + 1

    def iterfile():
        with open(file_path, "rb") as f:
            f.seek(start)
            bytes_left = chunk_size
            while bytes_left > 0:
                read_amount = min(bytes_left, 64 * 1024)
                data = f.read(read_amount)
                if not data:
                    break
                bytes_left -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Type": "video/mp4",
    }
    return StreamingResponse(iterfile(), status_code=206, headers=headers)

# -------------------------------------------------------------
# Studio Rendering Endpoints (VN-Style 9:16 Creator Pipeline)
# -------------------------------------------------------------

@app.get("/api/system-check")
async def system_check():
    """Returns capabilities: FFmpeg, libass, hardware encoders, and AI models."""
    return get_system_capabilities()

@app.post("/api/render")
async def create_render_job(req: StudioRenderRequest):
    """
    Queues a creator-grade 9:16 vertical render job:
    1. Downloads exact clip segment with pads [start-4s, end+8s]
    2. Transcribes with word timestamps (faster-whisper)
    3. Smart trims: snaps to hook sentence, finishes thought without cutting mid-word
    4. YuNet 10fps face tracking & mouth motion active speaker detection
    5. Director hysteresis cuts & solo dynamic zoom
    6. Lanczos 9:16 reframe at CRF 14
    7. ASS dynamic animated subtitles & creator attribution
    8. 20 Mbps loudnorm mastered export
    """
    job = RENDER_ENGINE.create_job(
        video_id=req.video_id,
        clip_index=req.clip_index,
        clip_title=req.clip_title,
        channel_name=req.channel_name,
        start=req.start,
        end=req.end,
        hook_line=req.hook_line or "",
        seo_metadata=req.seo_metadata or {},
        caption_style=req.caption_style,
        language=req.language,
        quality_preset=req.quality_preset,
        dynamic_zoom=req.dynamic_zoom,
        credit_overlay=req.credit_overlay,
        debug_mode=req.debug_mode,
        max_resolution=req.max_resolution,
    )
    return {"job_id": job.job_id, "status": "queued"}

@app.get("/api/render/{job_id}/events")
async def render_job_events(job_id: str, request: Request):
    """Streams live SSE events for the given render job."""
    job = RENDER_ENGINE.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found.")

    async def sse_stream():
        # First send immediate current state
        initial_data = {
            "job_id": job.job_id,
            "stage": job.stage,
            "progress": job.progress,
            "message": job.message,
            "error": job.error,
        }
        if job.output_files:
            initial_data["outputs"] = job.output_files
        yield f"data: {json.dumps(initial_data)}\n\n"

        if job.stage in ("done", "error"):
            return

        q = asyncio.Queue()
        if job_id not in RENDER_ENGINE.listeners:
            RENDER_ENGINE.listeners[job_id] = []
        RENDER_ENGINE.listeners[job_id].append(q)

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("stage") in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield ": ping\n\n"
        finally:
            if job_id in RENDER_ENGINE.listeners and q in RENDER_ENGINE.listeners[job_id]:
                RENDER_ENGINE.listeners[job_id].remove(q)

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@app.post("/api/render/{job_id}/cancel")
async def cancel_render_job(job_id: str):
    """Cancels a queued or in-progress render job."""
    success = RENDER_ENGINE.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or already finished.")
    return {"job_id": job_id, "status": "cancelling"}

@app.post("/api/captions/rebuild")
async def rebuild_captions(req: CaptionsRebuildRequest):
    """Restyles subtitles on top of the cached reframed.mp4 in seconds without redoing tracking/reframing."""
    try:
        final_mp4 = await RENDER_ENGINE.restyle_captions(
            output_dir=req.output_dir,
            new_style=req.new_style,
            new_lines_data=req.new_lines,
            credit_text=req.credit_text
        )
        base_dir = os.path.dirname(OUTPUTS_DIR)
        rel = os.path.relpath(final_mp4, base_dir).replace("\\", "/")
        return {"success": True, "video_url": f"/{rel}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restyle captions: {str(e)}")

class OpenFolderRequest(BaseModel):
    path: str

@app.post("/api/open-folder")
async def open_folder(req: OpenFolderRequest):
    """Opens the directory containing rendered assets on the host machine."""
    folder = req.path
    if not os.path.isabs(folder):
        folder = os.path.join(os.path.dirname(OUTPUTS_DIR), folder.lstrip("/\\"))
    if os.path.exists(folder):
        import subprocess
        if os.name == "nt":
            subprocess.Popen(f'explorer "{folder}"')
        return {"success": True, "opened": folder}
    raise HTTPException(status_code=404, detail="Folder does not exist.")
