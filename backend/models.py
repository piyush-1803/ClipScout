from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# Configurable score weights for overall virality score
VIRALITY_WEIGHTS: Dict[str, float] = {
    "hook_strength": 0.30,
    "emotional_intensity": 0.20,
    "insight_or_novelty": 0.20,
    "shareability": 0.15,
    "standalone_clarity": 0.10,
    "retention_pacing": 0.05,
}

# Heatmap blending weights when YouTube audience replay data is available
REPLAY_SCORE_WEIGHTS: Dict[str, float] = {
    "llm_weight": 0.75,
    "replay_weight": 0.25,
}

def calculate_virality_score(sub_scores: "SubScores") -> float:
    score = (
        sub_scores.hook_strength * VIRALITY_WEIGHTS["hook_strength"]
        + sub_scores.emotional_intensity * VIRALITY_WEIGHTS["emotional_intensity"]
        + sub_scores.insight_or_novelty * VIRALITY_WEIGHTS["insight_or_novelty"]
        + sub_scores.shareability * VIRALITY_WEIGHTS["shareability"]
        + sub_scores.standalone_clarity * VIRALITY_WEIGHTS["standalone_clarity"]
        + sub_scores.retention_pacing * VIRALITY_WEIGHTS["retention_pacing"]
    )
    return round(score, 1)

def get_score_label(score: float) -> str:
    if score >= 80.0:
        return "🔥 Viral potential"
    elif score >= 65.0:
        return "👍 Strong"
    elif score >= 50.0:
        return "😐 Decent"
    else:
        return "Weak"

def format_timestamp(seconds: float) -> str:
    total_seconds = int(max(0, round(seconds)))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

class TranscriptSegment(BaseModel):
    start: float
    duration: float
    text: str

class VideoMetadata(BaseModel):
    video_id: str
    title: str
    channel: str
    duration: float
    duration_formatted: str
    thumbnail_url: Optional[str] = None
    heatmap: Optional[List[Dict[str, float]]] = None

class SubScores(BaseModel):
    hook_strength: float = Field(default=50.0, ge=0.0, le=100.0)
    emotional_intensity: float = Field(default=50.0, ge=0.0, le=100.0)
    insight_or_novelty: float = Field(default=50.0, ge=0.0, le=100.0)
    shareability: float = Field(default=50.0, ge=0.0, le=100.0)
    standalone_clarity: float = Field(default=50.0, ge=0.0, le=100.0)
    retention_pacing: float = Field(default=50.0, ge=0.0, le=100.0)

class SEOMetadata(BaseModel):
    title: str = Field(description="Max 60 chars, curiosity-driven, keyword-rich")
    description: str = Field(description="Max 150 chars")
    hashtags: List[str] = Field(default_factory=list, description="5-8 hashtags")
    keywords: List[str] = Field(default_factory=list, description="5-10 keywords")
    seo_score: float = Field(default=75.0, ge=0.0, le=100.0)

class RawLLMClipCandidate(BaseModel):
    start: float
    end: float
    hook_line: str
    reasoning: str
    sub_scores: SubScores
    seo: SEOMetadata

class RawChunkAnalysisResult(BaseModel):
    candidates: List[RawLLMClipCandidate] = Field(default_factory=list)

class ClipCandidate(BaseModel):
    rank: int = 1
    start: float
    end: float
    start_formatted: str
    end_formatted: str
    duration: float
    virality_score: float
    sub_scores: SubScores
    score_label: str
    reasoning: str
    hook_line: str
    seo: SEOMetadata
    replay_peak: Optional[float] = None
    replay_mean: Optional[float] = None
    is_most_replayed: bool = False
    replay_score: Optional[float] = None

class TranscriptResponse(BaseModel):
    video: VideoMetadata
    segments: List[TranscriptSegment]

class AnalyzeRequest(BaseModel):
    video_id: str
    url: str
    segments: Optional[List[TranscriptSegment]] = None
    output_language: Optional[str] = "same as transcript"
    target_clips: int = Field(default=10, ge=1, le=25)
    model: str = "auto"
    provider: str = "gemini"  # "gemini" or "openai_compat"
    base_url: Optional[str] = None

class TestKeyRequest(BaseModel):
    provider: str = "gemini"
    model: str = "auto"
    base_url: Optional[str] = None

class TestKeyResponse(BaseModel):
    success: bool
    message: str
    model: str

class ModelItem(BaseModel):
    id: str
    name: str

class ListModelsRequest(BaseModel):
    provider: str = "gemini"
    base_url: Optional[str] = None

class ListModelsResponse(BaseModel):
    provider: str
    models: List[ModelItem]

class DownloadClipRequest(BaseModel):
    video_id: str
    start: float
    end: float
    title: Optional[str] = "clip"

class DownloadBatchRequest(BaseModel):
    video_id: str
    clips: List[DownloadClipRequest]

class RenderShortRequest(BaseModel):
    video_id: str
    video_title: str
    channel_name: str
    start: float
    end: float
    hook_title: str
    hook_line: Optional[str] = ""
    reasoning: Optional[str] = ""
    hashtags: Optional[List[str]] = Field(default_factory=list)
    segments: Optional[List[TranscriptSegment]] = Field(default_factory=list)
    add_sfx: bool = True

class RenderShortResponse(BaseModel):
    success: bool
    filename: str
    download_url: str
    stream_url: str
    file_size_bytes: int
    duration: float
    seo_package: Dict[str, Any]

RenderShortResponse.model_rebuild()

class RenderShortBatchRequest(BaseModel):
    video_id: str
    video_title: str
    channel_name: str
    clips: List[RenderShortRequest]

class StudioRenderRequest(BaseModel):
    video_id: str
    clip_index: int = 1
    clip_title: str
    channel_name: str
    start: float
    end: float
    hook_line: Optional[str] = ""
    seo_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    caption_style: str = "creator_classic"  # "creator_classic" | "active_word_pop" | "clean_outline"
    language: str = "auto"                  # "auto" | "en" | "hinglish" | "hi"
    quality_preset: str = "final"           # "preview" | "final"
    dynamic_zoom: bool = True
    credit_overlay: bool = True
    debug_mode: bool = False
    max_resolution: int = 1080

class CaptionsRebuildRequest(BaseModel):
    output_dir: str
    new_style: str
    new_lines: Optional[List[Dict[str, Any]]] = None
    credit_text: Optional[str] = None

StudioRenderRequest.model_rebuild()
CaptionsRebuildRequest.model_rebuild()

class AnalysisProgressEvent(BaseModel):
    stage: str  # "fetching" | "chunking" | "analyzing" | "ranking" | "done" | "error"
    progress: float  # 0 to 100
    message: str
    current_chunk: Optional[int] = None
    total_chunks: Optional[int] = None
    results: Optional[List[ClipCandidate]] = None
    video: Optional[VideoMetadata] = None
    error: Optional[str] = None
