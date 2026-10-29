from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import numpy as np
from .faces import FaceTrack, FaceDetection

@dataclass
class ShotDecision:
    shot_index: int
    start_time: float
    end_time: float
    face_track_id: Optional[int]
    speaker_label: str
    layout: str  # "face" | "fit"
    crop: Dict[str, int]  # x, y, w, h
    zoom_scale: float = 1.0

def compute_916_crop_for_face(
    face_bbox: Tuple[float, float, float, float],
    frame_w: int,
    frame_h: int,
    zoom_scale: float = 1.15,
    target_aspect: float = 9.0 / 16.0
) -> Dict[str, int]:
    """
    Computes a static 9:16 crop centered on the face with eyes placed ~38% from the top.
    Clamps strictly inside the frame boundaries.
    """
    fx, fy, fw, fh = face_bbox
    face_cx = fx + fw / 2.0
    eye_cy = fy + fh * 0.38  # approximate eye line

    # In 9:16, height dominates. We base crop size on frame_h / zoom_scale.
    crop_h = min(frame_h, int(round(frame_h / zoom_scale)))
    crop_w = int(round(crop_h * target_aspect))

    # Ensure crop_w doesn't exceed source frame width
    if crop_w > frame_w:
        crop_w = frame_w
        crop_h = int(round(crop_w / target_aspect))

    # Center horizontally on face center
    crop_x = int(round(face_cx - crop_w / 2.0))
    # Vertically place eye line at 38% from the top of the crop
    crop_y = int(round(eye_cy - 0.38 * crop_h))

    # Clamp strictly inside frame boundaries
    crop_x = max(0, min(frame_w - crop_w, crop_x))
    crop_y = max(0, min(frame_h - crop_h, crop_y))

    # Make dimensions even for ffmpeg compatibility
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2
    crop_x -= crop_x % 2
    crop_y -= crop_y % 2

    return {"x": int(crop_x), "y": int(crop_y), "w": int(crop_w), "h": int(crop_h)}

class ShotPlanner:
    def __init__(
        self,
        min_shot_duration: float = 1.5,
        switch_lead_time: float = 0.6,
        interjection_suppression_time: float = 1.0
    ):
        self.min_shot_dur = min_shot_duration
        self.switch_lead = switch_lead_time
        self.interjection_time = interjection_suppression_time

    def plan_shots(
        self,
        tracks: List[FaceTrack],
        speaking_scores: Dict[int, Dict[float, float]],
        total_duration: float,
        frame_dims: Tuple[int, int],
        enable_dynamic_zoom: bool = True,
        sentence_boundaries: Optional[List[float]] = None
    ) -> List[ShotDecision]:
        """
        Builds the shot plan using hysteresis rules:
        - If no face tracks: single continuous 'fit' shot.
        - If single face track (solo speaker): single speaker with dynamic punch-in zoom toggle (1.0x vs 1.18x).
        - If multi-speaker: hard cuts only when alternative speaker leads for >=0.6s and current shot >=1.5s.
        """
        frame_w, frame_h = frame_dims

        # 1. No faces detected -> Fit layout centered on blurred background
        if not tracks:
            return [
                ShotDecision(
                    shot_index=0,
                    start_time=0.0,
                    end_time=round(total_duration, 2),
                    face_track_id=None,
                    speaker_label="wide_view",
                    layout="fit",
                    crop={"x": 0, "y": 0, "w": frame_w, "h": frame_h},
                    zoom_scale=1.0
                )
            ]

        # 2. Solo speaker -> Keep on speaker, with dynamic punch-in zoom on boundaries
        if len(tracks) == 1:
            solo_track = tracks[0]
            # Average face bbox across all detections
            all_dets = list(solo_track.detections.values())
            avg_bbox = (
                float(np.mean([d.bbox[0] for d in all_dets])),
                float(np.mean([d.bbox[1] for d in all_dets])),
                float(np.mean([d.bbox[2] for d in all_dets])),
                float(np.mean([d.bbox[3] for d in all_dets])),
            )

            # Build sentence-aligned zoom cuts every 5-9 seconds if dynamic zoom enabled
            shots: List[ShotDecision] = []
            if enable_dynamic_zoom and total_duration > 7.0:
                cut_points = [0.0]
                current_cut = 0.0
                boundaries = sorted([b for b in (sentence_boundaries or []) if 0.0 < b < total_duration])

                # Pick sentence boundaries around every 6-8 seconds
                for b in boundaries:
                    if b - current_cut >= 5.5:
                        cut_points.append(b)
                        current_cut = b

                if total_duration - cut_points[-1] < 2.0 and len(cut_points) > 1:
                    cut_points.pop()
                cut_points.append(total_duration)

                # Alternate zoom: 1.05x (medium) and 1.22x (punchy close-up)
                zooms = [1.08, 1.24]
                for i in range(len(cut_points) - 1):
                    s_start = cut_points[i]
                    s_end = cut_points[i + 1]
                    z = zooms[i % len(zooms)]
                    crop = compute_916_crop_for_face(avg_bbox, frame_w, frame_h, zoom_scale=z)

                    shots.append(ShotDecision(
                        shot_index=i,
                        start_time=round(s_start, 2),
                        end_time=round(s_end, 2),
                        face_track_id=solo_track.track_id,
                        speaker_label="speaker_1",
                        layout="face",
                        crop=crop,
                        zoom_scale=z
                    ))
                return shots
            else:
                crop = compute_916_crop_for_face(avg_bbox, frame_w, frame_h, zoom_scale=1.15)
                return [
                    ShotDecision(
                        shot_index=0,
                        start_time=0.0,
                        end_time=round(total_duration, 2),
                        face_track_id=solo_track.track_id,
                        speaker_label="speaker_1",
                        layout="face",
                        crop=crop,
                        zoom_scale=1.15
                    )
                ]

        # 3. Multi-Speaker Podcast Hysteresis Engine
        # Sample every 0.1s to evaluate dominant active speaker
        timestamps = np.arange(0.0, total_duration, 0.1)
        track_map = {t.track_id: t for t in tracks}

        # Compute median face bbox for each track
        track_median_boxes = {}
        for tr in tracks:
            dets = list(tr.detections.values())
            if dets:
                track_median_boxes[tr.track_id] = (
                    float(np.median([d.bbox[0] for d in dets])),
                    float(np.median([d.bbox[1] for d in dets])),
                    float(np.median([d.bbox[2] for d in dets])),
                    float(np.median([d.bbox[3] for d in dets])),
                )
            else:
                track_median_boxes[tr.track_id] = (frame_w * 0.25, frame_h * 0.25, frame_w * 0.5, frame_h * 0.5)

        # Determine dominant speaker per 0.1s step
        active_track_history = []
        for t in timestamps:
            best_tid = None
            best_score = -1.0
            for tr in tracks:
                score = speaking_scores.get(tr.track_id, {}).get(round(t, 2), 0.0)
                # If track was detected around this time
                if tr.is_active_at(t) and score > best_score:
                    best_score = score
                    best_tid = tr.track_id

            if best_tid is None:
                # Fallback to the longest active track
                best_tid = tracks[0].track_id
            active_track_history.append(best_tid)

        # Apply hysteresis state machine
        current_speaker = active_track_history[0]
        shot_start = 0.0
        candidate_new_speaker = None
        candidate_start_time = 0.0
        planned_segments = []

        for step_i, t in enumerate(timestamps):
            detected_spk = active_track_history[step_i]

            if detected_spk != current_speaker:
                if candidate_new_speaker != detected_spk:
                    # New speaker starts contesting
                    candidate_new_speaker = detected_spk
                    candidate_start_time = t
                else:
                    # Speaker has been leading continuously
                    lead_duration = t - candidate_start_time
                    shot_duration = t - shot_start

                    # Check switch conditions:
                    # 1. New speaker lead >= switch_lead (0.6s)
                    # 2. Current shot duration >= min_shot_dur (1.5s)
                    if lead_duration >= self.switch_lead and shot_duration >= self.min_shot_dur:
                        planned_segments.append((shot_start, round(candidate_start_time, 2), current_speaker))
                        current_speaker = candidate_new_speaker
                        shot_start = round(candidate_start_time, 2)
                        candidate_new_speaker = None
            else:
                # Current speaker resumed speaking, dismiss short interjection
                candidate_new_speaker = None

        # Add tail shot
        if shot_start < total_duration:
            planned_segments.append((shot_start, round(total_duration, 2), current_speaker))

        # Build final ShotDecisions with crops
        shots: List[ShotDecision] = []
        for idx, (s_start, s_end, tid) in enumerate(planned_segments):
            if s_end - s_start < 0.2 and shots:
                # Merge tiny tail into preceding shot
                shots[-1].end_time = s_end
                continue

            bbox = track_median_boxes.get(tid, (frame_w * 0.25, frame_h * 0.25, frame_w * 0.5, frame_h * 0.5))
            crop = compute_916_crop_for_face(bbox, frame_w, frame_h, zoom_scale=1.18)

            shots.append(ShotDecision(
                shot_index=idx,
                start_time=s_start,
                end_time=s_end,
                face_track_id=tid,
                speaker_label=f"speaker_{tid}",
                layout="face",
                crop=crop,
                zoom_scale=1.18
            ))

        return shots
