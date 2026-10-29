import os
import json
import subprocess
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np

from .shots import ShotDecision
from .faces import FaceTrack

def render_reframed_video(
    input_video_path: str,
    shots: List[ShotDecision],
    output_reframed_path: str,
    total_duration: float,
    crf: int = 14,
    preset: str = "fast"
) -> str:
    """
    Renders high-quality intermediate 9:16 vertical video using FFmpeg filter_complex
    with hard cuts between shots and lanczos scaling.
    """
    if not shots:
        raise ValueError("Cannot reframe without shots.")

    working_dir = os.path.dirname(output_reframed_path)
    os.makedirs(working_dir, exist_ok=True)

    # If single shot
    if len(shots) == 1:
        shot = shots[0]
        if shot.layout == "face":
            c = shot.crop
            vfilter = (
                f"[0:v]crop={c['w']}:{c['h']}:{c['x']}:{c['y']},"
                f"scale=1080:1920:flags=lanczos,setsar=1[v]"
            )
        else:
            vfilter = (
                "[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:6,scale=1080:1920:flags=fast_bilinear[bg];"
                "[0:v]scale=1080:-2[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
            )

        cmd = [
            "ffmpeg", "-y", "-i", input_video_path,
            "-filter_complex", vfilter,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", preset,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_reframed_path
        ]
        res = subprocess.run(cmd, cwd=working_dir, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg single-shot reframe failed: {res.stderr[-400:]}")
        return output_reframed_path

    # Multi-shot filter graph with concat
    filter_parts = []
    concat_inputs = []

    for idx, s in enumerate(shots):
        dur = max(0.01, s.end_time - s.start_time)
        v_label = f"v{idx}"

        if s.layout == "face":
            c = s.crop
            filter_parts.append(
                f"[0:v]trim=start={s.start_time}:end={s.end_time},setpts=PTS-STARTPTS,"
                f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']},"
                f"scale=1080:1920:flags=lanczos,setsar=1[{v_label}]"
            )
        else:
            bg_label = f"bg{idx}"
            fg_label = f"fg{idx}"
            filter_parts.append(
                f"[0:v]trim=start={s.start_time}:end={s.end_time},setpts=PTS-STARTPTS,scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:6,scale=1080:1920:flags=fast_bilinear[{bg_label}];"
                f"[0:v]trim=start={s.start_time}:end={s.end_time},setpts=PTS-STARTPTS,scale=1080:-2[{fg_label}];"
                f"[{bg_label}][fg_label]overlay=(W-w)/2:(H-h)/2,setsar=1[{v_label}]"
            )
        concat_inputs.append(f"[{v_label}]")

    concat_line = "".join(concat_inputs) + f"concat=n={len(shots)}:v=1:a=0[v]"
    filter_complex = ";".join(filter_parts) + ";" + concat_line

    cmd = [
        "ffmpeg", "-y", "-i", input_video_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_reframed_path
    ]

    res = subprocess.run(cmd, cwd=working_dir, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg multi-shot reframe failed: {res.stderr[-400:]}")
    return output_reframed_path

def render_debug_overlay_video(
    input_video_path: str,
    tracks: List[FaceTrack],
    speaking_scores: Dict[int, Dict[float, float]],
    shots: List[ShotDecision],
    output_debug_path: str
) -> str:
    """
    Renders debug.mp4 displaying:
    - Bounding boxes colored by track ID
    - Speaking score progress bar for each face
    - Active speaker banner and shot change markers
    """
    cap = cv2.VideoCapture(input_video_path)
    if not cap.isOpened():
        return ""

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    temp_raw_avi = output_debug_path + ".tmp.mp4"
    out = cv2.VideoWriter(temp_raw_avi, fourcc, fps, (width, height))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t = frame_idx / fps

        # Find current active shot
        current_shot = None
        for s in shots:
            if s.start_time <= t <= s.end_time:
                current_shot = s
                break

        # Draw header banner
        spk_text = current_shot.speaker_label if current_shot else "none"
        layout_text = current_shot.layout if current_shot else "fit"
        cv2.rectangle(frame, (10, 10), (width - 10, 60), (0, 0, 0), -1)
        cv2.putText(
            frame,
            f"TIME: {t:.2f}s | ACTIVE: {spk_text} ({layout_text.upper()}) | SHOTS: {len(shots)}",
            (25, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (0, 255, 255),
            2
        )

        # Draw detected face boxes and speaking score bars
        for tr in tracks:
            det = tr.get_detection(frame_idx)
            # Find nearest detection within 0.15s
            if not det:
                for f_offset in range(-3, 4):
                    det = tr.get_detection(frame_idx + f_offset)
                    if det:
                        break

            if det:
                x, y, w, h = [int(v) for v in det.bbox]
                score = speaking_scores.get(tr.track_id, {}).get(round(t, 2), 0.0)
                is_active = (current_shot and current_shot.face_track_id == tr.track_id)
                box_color = (0, 255, 0) if is_active else tr.color

                # Box
                thickness = 3 if is_active else 2
                cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, thickness)

                # Track ID and score label
                label = f"ID:{tr.track_id} Score:{score:.2f}"
                cv2.rectangle(frame, (x, y - 24), (x + 180, y), (0, 0, 0), -1)
                cv2.putText(frame, label, (x + 5, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 1)

                # Speaking Score meter bar below face
                bar_w = int(w * score)
                cv2.rectangle(frame, (x, y + h + 4), (x + w, y + h + 14), (50, 50, 50), -1)
                cv2.rectangle(frame, (x, y + h + 4), (x + bar_w, y + h + 14), (0, 255, 0) if score > 0.4 else (0, 165, 255), -1)

        out.write(frame)
        frame_idx += 1

    cap.release()
    out.release()

    # Mux original audio into debug.mp4 via ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-i", temp_raw_avi,
        "-i", input_video_path,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
        "-map", "0:v", "-map", "1:a?",
        "-c:a", "aac",
        output_debug_path
    ]
    subprocess.run(cmd, capture_output=True)
    if os.path.exists(temp_raw_avi):
        try:
            os.remove(temp_raw_avi)
        except Exception:
            pass

    return output_debug_path
