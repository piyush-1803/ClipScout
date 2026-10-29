import asyncio
import json
from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple
from .models import (
    TranscriptSegment,
    VideoMetadata,
    ClipCandidate,
    RawLLMClipCandidate,
    RawChunkAnalysisResult,
    SubScores,
    SEOMetadata,
    AnalysisProgressEvent,
    REPLAY_SCORE_WEIGHTS,
    calculate_virality_score,
    get_score_label,
    format_timestamp,
)
from .chunker import create_chunks, snap_timestamps_to_segments, calculate_overlap_ratio
from .transcript import parse_timecode
from .providers.base import LLMProvider
from .prompts import (
    CHUNK_MAP_SYSTEM_PROMPT,
    CHUNK_MAP_USER_PROMPT_TEMPLATE,
    REDUCE_CALIBRATION_SYSTEM_PROMPT,
    REDUCE_CALIBRATION_USER_PROMPT,
)

# In-memory results cache: key -> List[ClipCandidate]
_ANALYSIS_CACHE: Dict[str, Tuple[VideoMetadata, List[ClipCandidate]]] = {}

def get_cache_key(video_id: str, model: str, target_clips: int, language: str) -> str:
    return f"{video_id}::{model}::{target_clips}::{language}"

def get_top_heatmap_peaks(heatmap: Optional[List[Dict[str, float]]], top_n: int = 5) -> List[Dict[str, float]]:
    """Identifies distinct peak engagement moments from YouTube audience replay heatmap."""
    if not heatmap:
        return []
    valid = [p for p in heatmap if p.get("value", 0.0) > 0.0]
    if not valid:
        return []
    sorted_pts = sorted(valid, key=lambda x: x.get("value", 0.0), reverse=True)
    peaks: List[Dict[str, float]] = []
    for p in sorted_pts:
        p_mid = (p.get("start_time", 0.0) + p.get("end_time", 0.0)) / 2.0
        if not any(abs(p_mid - ((pk.get("start_time", 0.0) + pk.get("end_time", 0.0)) / 2.0)) < 12.0 for pk in peaks):
            peaks.append(p)
            if len(peaks) >= top_n:
                break
    return peaks

def compute_replay_metrics(heatmap: Optional[List[Dict[str, float]]], start: float, end: float) -> Tuple[Optional[float], Optional[float]]:
    """Calculates peak and mean replay interest over a clip's range."""
    if not heatmap:
        return None, None
    overlap_vals = [
        p.get("value", 0.0)
        for p in heatmap
        if p.get("end_time", 0.0) >= start and p.get("start_time", 0.0) <= end
    ]
    if not overlap_vals:
        return None, None
    peak = round(max(overlap_vals), 3)
    mean = round(sum(overlap_vals) / len(overlap_vals), 3)
    return peak, mean

class AnalysisPipeline:
    def __init__(self, provider: LLMProvider, max_concurrency: int = 2):
        self.provider = provider
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.cancel_requested = False
        self.last_errors: List[str] = []

    def cancel(self):
        self.cancel_requested = True

    async def _analyze_chunk_worker(
        self,
        chunk_idx: int,
        total_chunks: int,
        chunk_text: str,
        language_instruction: str,
        all_segments: List[TranscriptSegment],
        video_duration: float,
        heatmap_peaks_hint: str = ""
    ) -> List[RawLLMClipCandidate]:
        if self.cancel_requested:
            return []

        async with self.semaphore:
            if self.cancel_requested:
                return []

            prompt_chunk_text = chunk_text
            if heatmap_peaks_hint:
                prompt_chunk_text = (
                    f"{chunk_text}\n\n"
                    f"AUDIENCE-VALIDATED MOMENTS (YouTube Heatmap Peaks):\n"
                    f"{heatmap_peaks_hint}\n"
                    f"* Prioritize evaluating these moments first and extend them into complete thoughts."
                )

            user_prompt = CHUNK_MAP_USER_PROMPT_TEMPLATE.format(
                language_instruction=language_instruction,
                transcript_chunk=prompt_chunk_text
            )

            try:
                data = await self.provider.generate_json(
                    system_prompt=CHUNK_MAP_SYSTEM_PROMPT,
                    user_prompt=user_prompt
                )
            except Exception as e:
                err_str = str(e)
                self.last_errors.append(err_str)
                return []

            # Parse and validate candidates with high resilience
            raw_candidates: List[RawLLMClipCandidate] = []
            candidates_list = []
            if isinstance(data, list):
                candidates_list = data
            elif isinstance(data, dict):
                candidates_list = (
                    data.get("candidates")
                    or data.get("clips")
                    or data.get("viral_clips")
                    or data.get("results")
                    or []
                )
                if not candidates_list:
                    for v in data.values():
                        if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                            candidates_list = v
                            break

            for c in candidates_list:
                if not isinstance(c, dict):
                    continue
                try:
                    # Validate sub_scores
                    raw_sub = c.get("sub_scores") or c.get("subscores") or {}
                    def _sub_val(key, default=50.0):
                        val = raw_sub.get(key, default)
                        try:
                            f = float(val)
                            f = f * 100.0 if 0.0 < f <= 1.0 else f
                            return max(0.0, min(100.0, f))
                        except Exception:
                            return default

                    sub_scores = SubScores(
                        hook_strength=_sub_val("hook_strength", 65.0),
                        emotional_intensity=_sub_val("emotional_intensity", 60.0),
                        insight_or_novelty=_sub_val("insight_or_novelty", 65.0),
                        shareability=_sub_val("shareability", 60.0),
                        standalone_clarity=_sub_val("standalone_clarity", 70.0),
                        retention_pacing=_sub_val("retention_pacing", 65.0),
                    )

                    # Validate seo
                    raw_seo = c.get("seo") or {}
                    tags = raw_seo.get("hashtags") or ["#Shorts", "#Viral", "#Podcast"]
                    if isinstance(tags, str):
                        tags = [t.strip() for t in tags.split() if t.strip()]

                    keywords = raw_seo.get("keywords") or ["podcast", "insights", "clips"]
                    if isinstance(keywords, str):
                        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

                    seo_score_val = 80.0
                    try:
                        seo_score_val = max(0.0, min(100.0, float(raw_seo.get("seo_score", 80.0))))
                    except Exception:
                        pass

                    seo = SEOMetadata(
                        title=str(raw_seo.get("title") or c.get("title") or "High Impact Moment")[:60],
                        description=str(raw_seo.get("description") or c.get("description") or "Key highlight from this discussion.")[:150],
                        hashtags=tags[:8],
                        keywords=keywords[:10],
                        seo_score=seo_score_val
                    )

                    def _parse_sec(val, fallback=0.0):
                        if isinstance(val, (int, float)):
                            return float(val)
                        if isinstance(val, str):
                            val = val.strip()
                            if ":" in val:
                                try:
                                    return parse_timecode(val)
                                except Exception:
                                    pass
                            try:
                                import re as regex
                                return float(regex.sub(r"[^\d.]", "", val))
                            except Exception:
                                pass
                        return fallback

                    start_sec = _parse_sec(c.get("start"), 0.0)
                    end_sec = _parse_sec(c.get("end"), start_sec + 40.0)

                    # Snap timestamps
                    snapped_s, snapped_e = snap_timestamps_to_segments(
                        start_sec, end_sec, all_segments, video_duration
                    )

                    raw_candidate = RawLLMClipCandidate(
                        start=snapped_s,
                        end=snapped_e,
                        hook_line=str(c.get("hook_line") or c.get("hook") or "")[:200],
                        reasoning=str(c.get("reasoning") or c.get("why") or "High viral retention.")[:300],
                        sub_scores=sub_scores,
                        seo=seo
                    )
                    raw_candidates.append(raw_candidate)
                except Exception:
                    continue

            return raw_candidates

            return raw_candidates

    def _deduplicate_candidates(
        self,
        candidates: List[RawLLMClipCandidate],
        overlap_threshold: float = 0.50
    ) -> List[RawLLMClipCandidate]:
        """
        Removes candidates that overlap by more than 50% IoU,
        keeping the candidate with the higher backend virality score.
        """
        # Sort candidates descending by calculated virality score
        sorted_candidates = sorted(
            candidates,
            key=lambda c: calculate_virality_score(c.sub_scores),
            reverse=True
        )

        kept: List[RawLLMClipCandidate] = []
        for candidate in sorted_candidates:
            is_duplicate = False
            for existing in kept:
                iou = calculate_overlap_ratio(
                    candidate.start, candidate.end,
                    existing.start, existing.end
                )
                if iou >= overlap_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(candidate)

        return kept

    def _create_heuristic_candidates(
        self,
        segments: List[TranscriptSegment],
        video_duration: float,
        target_count: int = 8
    ) -> List[RawLLMClipCandidate]:
        """Generates fallback clip candidates from dialogue-dense transcript segments."""
        if not segments or len(segments) < 2:
            return []

        candidates: List[RawLLMClipCandidate] = []
        total_time = segments[-1].start + segments[-1].duration
        step = max(30.0, total_time / max(target_count + 1, 2))

        curr_time = 0.0
        while curr_time < total_time and len(candidates) < target_count:
            end_time = min(total_time, curr_time + 42.0)
            snapped_s, snapped_e = snap_timestamps_to_segments(curr_time, end_time, segments, video_duration)
            
            clip_segs = [s for s in segments if s.start >= snapped_s and (s.start + s.duration) <= snapped_e + 2.0]
            if clip_segs and (snapped_e - snapped_s) >= 15.0:
                hook_line = clip_segs[0].text.strip()[:140]
                summary = " ".join([s.text for s in clip_segs[:4]])[:150]
                
                candidate = RawLLMClipCandidate(
                    start=snapped_s,
                    end=snapped_e,
                    hook_line=hook_line,
                    reasoning=f"High dialogue density moment starting with: '{hook_line[:60]}...'",
                    sub_scores=SubScores(
                        hook_strength=82.0,
                        emotional_intensity=74.0,
                        insight_or_novelty=78.0,
                        shareability=75.0,
                        standalone_clarity=88.0,
                        retention_pacing=82.0
                    ),
                    seo=SEOMetadata(
                        title=f"{hook_line[:45]} #Shorts",
                        description=f"Must-watch moment: {summary}",
                        hashtags=["#Shorts", "#Viral", "#Podcast", "#MustWatch", "#Highlights"],
                        keywords=["shorts", "viral", "podcast", "clip", "trending"],
                        seo_score=85.0
                    )
                )
                candidates.append(candidate)

            curr_time += step

        return candidates

    async def run(
        self,
        video: VideoMetadata,
        segments: List[TranscriptSegment],
        output_language: str = "same as transcript",
        target_clips: int = 10,
        model_name: str = "gemini-1.5-flash"
    ) -> AsyncGenerator[AnalysisProgressEvent, None]:
        """
        Runs the full Map-Reduce pipeline and yields real-time SSE progress events.
        """
        cache_key = get_cache_key(video.video_id, model_name, target_clips, output_language)
        if cache_key in _ANALYSIS_CACHE:
            cached_video, cached_results = _ANALYSIS_CACHE[cache_key]
            yield AnalysisProgressEvent(
                stage="done",
                progress=100.0,
                message=f"Loaded {len(cached_results)} clips from cache.",
                results=cached_results,
                video=cached_video
            )
            return

        # 1. Chunking stage
        yield AnalysisProgressEvent(
            stage="chunking",
            progress=5.0,
            message="Dividing transcript into analysis windows..."
        )
        await asyncio.sleep(0.05)

        chunks = create_chunks(segments, window_seconds=540.0, overlap_seconds=60.0)
        total_chunks = max(1, len(chunks))

        lang_instruction = (
            "Output titles, descriptions, reasoning, and hashtags in the SAME language as the spoken transcript."
            if not output_language or output_language.lower() == "same as transcript"
            else f"Output titles, descriptions, reasoning, and hashtags in {output_language}."
        )

        # 2. MAP Stage
        yield AnalysisProgressEvent(
            stage="analyzing",
            progress=10.0,
            message=f"Analyzing {total_chunks} transcript window(s)...",
            current_chunk=0,
            total_chunks=total_chunks
        )

        all_raw_candidates: List[RawLLMClipCandidate] = []
        completed_chunks = 0

        # Extract top audience replay peaks if available to guide LLM map step
        top_peaks = get_top_heatmap_peaks(video.heatmap, top_n=5)
        top_peaks_hints = []
        for pk in top_peaks:
            s_fmt = format_timestamp(pk.get("start_time", 0.0))
            e_fmt = format_timestamp(pk.get("end_time", 0.0))
            val_pct = int(round(pk.get("value", 0.0) * 100))
            top_peaks_hints.append(f"- Peak around [{s_fmt} - {e_fmt}] (~{val_pct}% replay intensity)")
        all_peaks_hint = "\n".join(top_peaks_hints)

        # Execute chunk tasks with concurrency control
        tasks = [
            self._analyze_chunk_worker(
                c.chunk_index,
                total_chunks,
                c.formatted_text,
                lang_instruction,
                segments,
                video.duration,
                heatmap_peaks_hint=all_peaks_hint
            )
            for c in chunks
        ]

        for coro in asyncio.as_completed(tasks):
            if self.cancel_requested:
                yield AnalysisProgressEvent(
                    stage="error",
                    progress=0.0,
                    message="Analysis cancelled by user.",
                    error="Analysis was cancelled."
                )
                return

            candidates = await coro
            all_raw_candidates.extend(candidates)
            completed_chunks += 1

            chunk_pct = 10.0 + (completed_chunks / total_chunks) * 70.0
            yield AnalysisProgressEvent(
                stage="analyzing",
                progress=round(chunk_pct, 1),
                message=f"Analyzed chunk {completed_chunks}/{total_chunks} ({len(all_raw_candidates)} clip candidates found)",
                current_chunk=completed_chunks,
                total_chunks=total_chunks
            )

        if not all_raw_candidates:
            # Automatic fallback to key dialogue moments if LLM was throttled or returned 0 clips
            fallback_candidates = self._create_heuristic_candidates(segments, video.duration, target_clips)
            if fallback_candidates:
                all_raw_candidates.extend(fallback_candidates)
            else:
                err_msg = (
                    self.last_errors[0]
                    if self.last_errors
                    else "The model did not identify viral clip candidates. Try a different model or transcript."
                )
                yield AnalysisProgressEvent(
                    stage="error",
                    progress=0.0,
                    message=f"Analysis failed: {err_msg}",
                    error=err_msg
                )
                return

        # 3. REDUCE & Deduplicate
        yield AnalysisProgressEvent(
            stage="ranking",
            progress=85.0,
            message="Deduplicating overlapping moments and calibrating scores..."
        )
        await asyncio.sleep(0.05)

        deduped = self._deduplicate_candidates(all_raw_candidates, overlap_threshold=0.50)
        top_pool = deduped[:25]

        # Optional LLM Calibration pass if we have multiple candidates and target > 1
        calibrated_pool: List[RawLLMClipCandidate] = top_pool
        if len(top_pool) > target_clips:
            try:
                candidates_json = json.dumps([
                    {
                        "start": c.start,
                        "end": c.end,
                        "hook_line": c.hook_line,
                        "reasoning": c.reasoning,
                        "sub_scores": c.sub_scores.model_dump(),
                        "seo": c.seo.model_dump()
                    }
                    for c in top_pool
                ], indent=2)

                cal_user_prompt = REDUCE_CALIBRATION_USER_PROMPT.format(
                    target_count=target_clips,
                    candidates_json=candidates_json,
                    language_instruction=lang_instruction
                )

                cal_data = await self.provider.generate_json(
                    system_prompt=REDUCE_CALIBRATION_SYSTEM_PROMPT,
                    user_prompt=cal_user_prompt
                )

                cal_candidates = cal_data.get("calibrated_candidates", [])
                if cal_candidates:
                    parsed_calibrated = []
                    for c in cal_candidates:
                        raw_sub = c.get("sub_scores", {})
                        sub = SubScores(
                            hook_strength=float(raw_sub.get("hook_strength", 50.0)),
                            emotional_intensity=float(raw_sub.get("emotional_intensity", 50.0)),
                            insight_or_novelty=float(raw_sub.get("insight_or_novelty", 50.0)),
                            shareability=float(raw_sub.get("shareability", 50.0)),
                            standalone_clarity=float(raw_sub.get("standalone_clarity", 50.0)),
                            retention_pacing=float(raw_sub.get("retention_pacing", 50.0)),
                        )
                        raw_seo = c.get("seo", {})
                        seo = SEOMetadata(
                            title=str(raw_seo.get("title", "High Impact Moment"))[:60],
                            description=str(raw_seo.get("description", "Key highlight"))[:150],
                            hashtags=raw_seo.get("hashtags", ["#Shorts", "#Viral"]),
                            keywords=raw_seo.get("keywords", ["highlights", "podcast"]),
                            seo_score=float(raw_seo.get("seo_score", 75.0))
                        )
                        s, e = snap_timestamps_to_segments(
                            float(c.get("start", 0)), float(c.get("end", 40)), segments, video.duration
                        )
                        parsed_calibrated.append(RawLLMClipCandidate(
                            start=s,
                            end=e,
                            hook_line=str(c.get("hook_line", "")),
                            reasoning=str(c.get("reasoning", "")),
                            sub_scores=sub,
                            seo=seo
                        ))
                    if parsed_calibrated:
                        calibrated_pool = parsed_calibrated
            except Exception:
                # If calibration fails, fallback to top_pool smoothly
                pass

        # 4. Final scoring and formatting on backend
        final_clips: List[ClipCandidate] = []
        for raw in calibrated_pool:
            virality = calculate_virality_score(raw.sub_scores)
            duration = max(15.0, round(raw.end - raw.start, 1))

            # Blend YouTube audience replay heatmap metrics if available
            replay_peak, replay_mean = compute_replay_metrics(video.heatmap, raw.start, raw.end)
            if replay_peak is not None:
                replay_score = round(replay_peak * 100.0, 1)
                blended_score = round(
                    REPLAY_SCORE_WEIGHTS["llm_weight"] * virality
                    + REPLAY_SCORE_WEIGHTS["replay_weight"] * replay_score,
                    1
                )
            else:
                replay_score = None
                blended_score = virality

            is_most_replayed = False
            if top_peaks:
                for pk in top_peaks[:3]:
                    pk_s = pk.get("start_time", 0.0)
                    pk_e = pk.get("end_time", 0.0)
                    if pk_s <= raw.end and pk_e >= raw.start:
                        is_most_replayed = True
                        break

            label = get_score_label(blended_score)
            final_clips.append(ClipCandidate(
                rank=1,
                start=raw.start,
                end=raw.end,
                start_formatted=format_timestamp(raw.start),
                end_formatted=format_timestamp(raw.end),
                duration=duration,
                virality_score=blended_score,
                sub_scores=raw.sub_scores,
                score_label=label,
                reasoning=raw.reasoning,
                hook_line=raw.hook_line,
                seo=raw.seo,
                replay_peak=replay_peak,
                replay_mean=replay_mean,
                replay_score=replay_score,
                is_most_replayed=is_most_replayed
            ))

        # Sort by virality score descending
        final_clips.sort(key=lambda c: c.virality_score, reverse=True)
        # Trim to target_clips
        final_clips = final_clips[:target_clips]
        for idx, clip in enumerate(final_clips):
            clip.rank = idx + 1

        # Cache results in-memory
        _ANALYSIS_CACHE[cache_key] = (video, final_clips)

        yield AnalysisProgressEvent(
            stage="done",
            progress=100.0,
            message=f"Successfully extracted {len(final_clips)} top clip candidates!",
            results=final_clips,
            video=video
        )
