import os
import subprocess
import wave
import struct
import numpy as np
import cv2
from typing import List, Dict, Tuple, Optional
from .faces import FaceTrack

def extract_mono_audio_16k(video_path: str, output_wav_path: str) -> str:
    """Extracts 16kHz 16-bit mono PCM WAV for precise VAD calculation."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        output_wav_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_wav_path

def compute_audio_vad_energy(wav_path: str, chunk_duration: float = 0.05) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Computes normalized RMS energy voice activity flag across time chunks.
    Returns: (timestamps, voiced_flags, sample_rate)
    """
    with wave.open(wav_path, "rb") as wf:
        sample_rate = wf.getframerate()
        n_samples = wf.getnframes()
        raw = wf.readframes(n_samples)

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    chunk_samples = int(chunk_duration * sample_rate)
    n_chunks = max(1, len(audio) // chunk_samples)

    timestamps = []
    energies = []

    for i in range(n_chunks):
        chunk = audio[i * chunk_samples : (i + 1) * chunk_samples]
        rms = float(np.sqrt(np.mean(chunk**2))) if len(chunk) > 0 else 0.0
        energies.append(rms)
        timestamps.append((i + 0.5) * chunk_duration)

    energies = np.array(energies)
    if len(energies) == 0:
        return np.array([0.0]), np.array([0.0]), float(sample_rate)

    # Dynamic noise floor: threshold is 1.6x background floor
    sorted_e = np.sort(energies)
    noise_floor = float(np.mean(sorted_e[: max(1, int(len(sorted_e) * 0.25))]))
    peak_e = float(np.percentile(energies, 95))
    threshold = max(0.015, noise_floor + (peak_e - noise_floor) * 0.15)

    voiced_flags = np.clip((energies - threshold) / max(0.01, peak_e - threshold), 0.0, 1.0)
    return np.array(timestamps), voiced_flags, float(sample_rate)

class ActiveSpeakerDetector:
    def __init__(self, sample_fps: float = 10.0, smoothing_window_seconds: float = 0.3):
        self.sample_fps = sample_fps
        self.smoothing_window = smoothing_window_seconds

    def compute_speaking_scores(
        self,
        video_path: str,
        tracks: List[FaceTrack],
        wav_path: Optional[str] = None
    ) -> Dict[int, Dict[float, float]]:
        """
        Computes continuous speaking score [0..1] for each face track at every timestamp.
        speaking_score(track, t) = mouth_motion(track, t) * voiced_audio_flag(t) (smoothed).
        Returns: {track_id: {timestamp: score}}
        """
        if not tracks:
            return {}

        # 1. Audio VAD
        clean_temp_wav = False
        if not wav_path or not os.path.exists(wav_path):
            temp_wav = video_path + "_temp_vad.wav"
            try:
                extract_mono_audio_16k(video_path, temp_wav)
                wav_path = temp_wav
                clean_temp_wav = True
            except Exception:
                wav_path = None

        vad_times = np.array([0.0])
        vad_flags = np.array([1.0])
        if wav_path and os.path.exists(wav_path):
            try:
                vad_times, vad_flags, _ = compute_audio_vad_energy(wav_path)
            except Exception:
                pass
            if clean_temp_wav and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass

        def get_vad_at(t: float) -> float:
            if len(vad_times) == 0:
                return 1.0
            idx = int(np.clip(np.searchsorted(vad_times, t), 0, len(vad_flags) - 1))
            return float(vad_flags[idx])

        # 2. Extract mouth-region visual motion for each track
        cap = cv2.VideoCapture(video_path)
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_step = max(1, int(round(native_fps / self.sample_fps)))

        track_mouth_patches: Dict[int, Dict[int, np.ndarray]] = {t.track_id: {} for t in tracks}
        frame_timestamps: Dict[int, float] = {}

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_step == 0:
                t = frame_idx / native_fps
                frame_timestamps[frame_idx] = t
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                for tr in tracks:
                    det = tr.get_detection(frame_idx)
                    if det and det.mouth_roi:
                        mx, my, mw, mh = [int(v) for v in det.mouth_roi]
                        mx = max(0, min(frame.shape[1] - 1, mx))
                        my = max(0, min(frame.shape[0] - 1, my))
                        mw = max(1, min(frame.shape[1] - mx, mw))
                        mh = max(1, min(frame.shape[0] - my, mh))

                        patch = gray[my : my + mh, mx : mx + mw]
                        if patch.size > 0:
                            # Standardize patch size for motion metric
                            std_patch = cv2.resize(patch, (32, 24), interpolation=cv2.INTER_AREA)
                            track_mouth_patches[tr.track_id][frame_idx] = std_patch

            frame_idx += 1
        cap.release()

        # 3. Calculate raw motion * VAD
        raw_scores: Dict[int, List[Tuple[float, float]]] = {t.track_id: [] for t in tracks}
        sorted_frame_indices = sorted(frame_timestamps.keys())

        for tr in tracks:
            t_id = tr.track_id
            prev_patch = None

            for f_idx in sorted_frame_indices:
                t = frame_timestamps[f_idx]
                patch = track_mouth_patches[t_id].get(f_idx)

                if patch is not None:
                    if prev_patch is not None:
                        # Mean absolute frame difference
                        diff = np.mean(np.abs(patch.astype(np.float32) - prev_patch.astype(np.float32)))
                        norm_motion = float(np.clip(diff / 18.0, 0.0, 1.0))
                    else:
                        norm_motion = 0.2
                    prev_patch = patch

                    vad = get_vad_at(t)
                    # Combined motion x voice flag
                    combined = norm_motion * (0.3 + 0.7 * vad)
                    raw_scores[t_id].append((t, combined))
                else:
                    prev_patch = None
                    raw_scores[t_id].append((t, 0.0))

        # 4. Smooth over ~300ms window
        smooth_span = max(1, int(round(self.smoothing_window * self.sample_fps)))
        final_scores: Dict[int, Dict[float, float]] = {t.track_id: {} for t in tracks}

        for tr in tracks:
            t_id = tr.track_id
            pairs = raw_scores[t_id]
            if not pairs:
                continue

            vals = [p[1] for p in pairs]
            smoothed = np.convolve(vals, np.ones(smooth_span) / smooth_span, mode="same")

            for (t, _), s_val in zip(pairs, smoothed):
                final_scores[t_id][t] = float(np.clip(s_val, 0.0, 1.0))

        return final_scores
