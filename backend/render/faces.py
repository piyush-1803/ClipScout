import os
import urllib.request
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import cv2
import numpy as np

YUNET_MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"
MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
YUNET_PATH = os.path.join(MODELS_DIR, YUNET_MODEL_FILENAME)

YUNET_URLS = [
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"
]

def ensure_yunet_model() -> str:
    """Ensures YuNet model is present on disk and valid, auto-downloading if necessary."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    if os.path.exists(YUNET_PATH) and os.path.getsize(YUNET_PATH) > 100000:
        return YUNET_PATH

    for url in YUNET_URLS:
        try:
            import httpx
            resp = httpx.get(url, follow_redirects=True, timeout=30.0)
            if resp.status_code == 200 and len(resp.content) > 100000:
                with open(YUNET_PATH, "wb") as f:
                    f.write(resp.content)
                return YUNET_PATH
        except Exception:
            continue

    if os.path.exists(YUNET_PATH) and os.path.getsize(YUNET_PATH) > 100000:
        return YUNET_PATH
    raise RuntimeError("Failed to download or verify OpenCV YuNet face detection ONNX model.")

@dataclass
class FaceDetection:
    frame_idx: int
    timestamp: float
    bbox: Tuple[float, float, float, float]  # x, y, w, h in original resolution
    confidence: float
    landmarks: Optional[List[Tuple[float, float]]] = None  # 5 points: re, le, nose, rm, lm
    mouth_roi: Optional[Tuple[float, float, float, float]] = None  # x, y, w, h for mouth region

@dataclass
class FaceTrack:
    track_id: int
    detections: Dict[int, FaceDetection] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    color: Tuple[int, int, int] = (0, 255, 0)

    def get_detection(self, frame_idx: int) -> Optional[FaceDetection]:
        return self.detections.get(frame_idx)

    def is_active_at(self, t: float) -> bool:
        return self.start_time <= t <= self.end_time

def compute_iou(boxA: Tuple[float, float, float, float], boxB: Tuple[float, float, float, float]) -> float:
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

    interW = max(0.0, xB - xA)
    interH = max(0.0, yB - yA)
    interArea = interW * interH

    areaA = boxA[2] * boxA[3]
    areaB = boxB[2] * boxB[3]
    unionArea = areaA + areaB - interArea
    if unionArea <= 0:
        return 0.0
    return interArea / unionArea

def compute_centroid_distance(boxA: Tuple[float, float, float, float], boxB: Tuple[float, float, float, float]) -> float:
    cA = (boxA[0] + boxA[2] / 2.0, boxA[1] + boxA[3] / 2.0)
    cB = (boxB[0] + boxB[2] / 2.0, boxB[1] + boxB[3] / 2.0)
    return float(np.hypot(cA[0] - cB[0], cA[1] - cB[1]))

class FaceTracker:
    def __init__(self, model_path: Optional[str] = None, conf_threshold: float = 0.65):
        self.model_path = model_path or ensure_yunet_model()
        self.conf_threshold = conf_threshold
        self.detector = None

    def _init_detector(self, width: int, height: int):
        self.detector = cv2.FaceDetectorYN.create(
            model=self.model_path,
            config="",
            input_size=(width, height),
            score_threshold=self.conf_threshold,
            nms_threshold=0.3,
            top_k=5000
        )

    def analyze_video(
        self,
        video_path: str,
        sample_fps: float = 10.0,
        target_width: int = 640
    ) -> Tuple[List[FaceTrack], Dict[int, List[FaceDetection]], float, Tuple[int, int]]:
        """
        Processes video frames at sample_fps (downscaled to ~target_width for speed)
        and tracks faces into coherent identity tracks.
        Returns: (tracks, frame_detections_map, video_duration, (orig_w, orig_h))
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video for face analysis: {video_path}")

        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / native_fps if native_fps > 0 else 0.0

        scale = target_width / float(orig_w) if orig_w > target_width else 1.0
        proc_w = int(orig_w * scale)
        proc_h = int(orig_h * scale)
        # Ensure dimensions are even for model input
        proc_w -= proc_w % 2
        proc_h -= proc_h % 2

        self._init_detector(proc_w, proc_h)

        frame_step = max(1, int(round(native_fps / sample_fps)))
        frame_idx = 0
        current_time = 0.0

        all_detections_by_frame: Dict[int, List[FaceDetection]] = {}
        active_tracks: List[FaceTrack] = []
        finished_tracks: List[FaceTrack] = []
        next_track_id = 1

        colors = [
            (50, 205, 50), (255, 140, 0), (30, 144, 255),
            (255, 20, 147), (148, 0, 211), (0, 255, 255)
        ]

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_step == 0:
                current_time = frame_idx / native_fps
                resized = cv2.resize(frame, (proc_w, proc_h), interpolation=cv2.INTER_LINEAR)
                _, faces = self.detector.detect(resized)

                frame_detections: List[FaceDetection] = []
                if faces is not None:
                    for f in faces:
                        score = float(f[-1])
                        if score < self.conf_threshold:
                            continue

                        # Coordinates on downscaled frame -> mapped back to original scale
                        rx = float(f[0]) / scale
                        ry = float(f[1]) / scale
                        rw = float(f[2]) / scale
                        rh = float(f[3]) / scale

                        # Clamp to frame
                        rx = max(0.0, min(orig_w - 10, rx))
                        ry = max(0.0, min(orig_h - 10, ry))
                        rw = max(10.0, min(orig_w - rx, rw))
                        rh = max(10.0, min(orig_h - ry, rh))

                        # 5 landmarks (x, y): re(4,5), le(6,7), nose(8,9), rm(10,11), lm(12,13)
                        landmarks = []
                        if len(f) >= 14:
                            for p_i in range(4, 14, 2):
                                landmarks.append((float(f[p_i]) / scale, float(f[p_i+1]) / scale))

                        # Mouth ROI: lower third of the face box (robust fallback if landmarks jitter)
                        mouth_y = ry + 0.62 * rh
                        mouth_h = 0.38 * rh
                        mouth_roi = (rx, mouth_y, rw, mouth_h)

                        frame_detections.append(FaceDetection(
                            frame_idx=frame_idx,
                            timestamp=current_time,
                            bbox=(rx, ry, rw, rh),
                            confidence=score,
                            landmarks=landmarks,
                            mouth_roi=mouth_roi
                        ))

                all_detections_by_frame[frame_idx] = frame_detections

                # Match detections to active tracks
                assigned_tracks = set()
                assigned_dets = set()

                for det_i, det in enumerate(frame_detections):
                    best_match = None
                    best_dist = float("inf")
                    best_iou = 0.0

                    for tr in active_tracks:
                        if tr.track_id in assigned_tracks:
                            continue

                        # Find last known detection of this track
                        last_det = list(tr.detections.values())[-1]
                        iou = compute_iou(det.bbox, last_det.bbox)
                        dist = compute_centroid_distance(det.bbox, last_det.bbox)

                        # Match criteria: either good overlap (IoU >= 0.25) or close centroid (< 15% frame diagonal)
                        diag = np.hypot(orig_w, orig_h)
                        if (iou > 0.25 or dist < 0.15 * diag) and dist < best_dist:
                            best_dist = dist
                            best_iou = iou
                            best_match = tr

                    if best_match:
                        best_match.detections[frame_idx] = det
                        best_match.end_time = current_time
                        assigned_tracks.add(best_match.track_id)
                        assigned_dets.add(det_i)

                # Unassigned detections become new tracks
                for det_i, det in enumerate(frame_detections):
                    if det_i not in assigned_dets:
                        new_track = FaceTrack(
                            track_id=next_track_id,
                            detections={frame_idx: det},
                            start_time=current_time,
                            end_time=current_time,
                            color=colors[(next_track_id - 1) % len(colors)]
                        )
                        next_track_id += 1
                        active_tracks.append(new_track)

                # Check for inactive tracks (no detection in > 0.8s)
                still_active = []
                for tr in active_tracks:
                    if current_time - tr.end_time > 0.8:
                        # Only keep tracks that appeared in at least 3 sampled frames (>0.3s)
                        if len(tr.detections) >= 3:
                            finished_tracks.append(tr)
                    else:
                        still_active.append(tr)
                active_tracks = still_active

            frame_idx += 1

        cap.release()

        # Finalize remaining tracks
        for tr in active_tracks:
            if len(tr.detections) >= 3:
                finished_tracks.append(tr)

        # Sort tracks by duration descending
        finished_tracks.sort(key=lambda t: t.end_time - t.start_time, reverse=True)
        return finished_tracks, all_detections_by_frame, duration, (orig_w, orig_h)
