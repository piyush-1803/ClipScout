import os
import json
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

# Ensure PyAV compatibility across all versions (av 14+ removed metadata_errors parameter)
try:
    import av
    _orig_av_open = av.open
    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _safe_av_open
except Exception:
    pass

@dataclass
class WordTimestamp:
    word: str
    start: float
    end: float
    probability: float

@dataclass
class SentenceSegment:
    text: str
    start: float
    end: float
    words: List[WordTimestamp]

_WHISPER_MODEL_CACHE: Dict[str, Any] = {}

def get_whisper_model(model_size: str = "small", device: str = "auto") -> Any:
    """Loads and caches faster-whisper model in int8 format without requiring PyTorch."""
    global _WHISPER_MODEL_CACHE
    cache_key = f"{model_size}_{device}"
    if cache_key in _WHISPER_MODEL_CACHE:
        return _WHISPER_MODEL_CACHE[cache_key]

    from faster_whisper import WhisperModel

    selected_device = "cpu"
    compute_type = "int8"
    if device == "cuda" or (device == "auto" and os.environ.get("CUDA_VISIBLE_DEVICES") not in (None, "", "-1")):
        try:
            # Check if CUDA available
            import ctranslate2
            if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
                selected_device = "cuda"
                compute_type = "float16"
        except Exception:
            pass

    model = WhisperModel(model_size, device=selected_device, compute_type=compute_type)
    _WHISPER_MODEL_CACHE[cache_key] = model
    return model

def transcribe_audio_words(
    audio_path: str,
    language: str = "auto",
    model_size: str = "small"
) -> Tuple[List[WordTimestamp], List[SentenceSegment], str]:
    """
    Transcribes audio with word-level timestamps using faster-whisper.
    Returns: (words, sentences, detected_language)
    """
    model = get_whisper_model(model_size=model_size)

    lang_code = None
    if language in ("en", "english"):
        lang_code = "en"
    elif language in ("hi", "hindi", "hinglish"):
        lang_code = "hi"

    segments, info = model.transcribe(
        audio_path,
        language=lang_code,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400)
    )

    detected_lang = info.language or "en"
    all_words: List[WordTimestamp] = []
    sentences: List[SentenceSegment] = []

    for seg in segments:
        seg_words: List[WordTimestamp] = []
        if seg.words:
            for w in seg.words:
                clean_word = w.word.strip()
                if clean_word:
                    wt = WordTimestamp(
                        word=clean_word,
                        start=round(float(w.start), 3),
                        end=round(float(w.end), 3),
                        probability=round(float(w.probability), 2)
                    )
                    all_words.append(wt)
                    seg_words.append(wt)

        clean_text = seg.text.strip()
        if clean_text:
            sentences.append(SentenceSegment(
                text=clean_text,
                start=round(float(seg.start), 3),
                end=round(float(seg.end), 3),
                words=seg_words
            ))

    return all_words, sentences, detected_lang

async def romanize_words_to_hinglish(
    words: List[WordTimestamp],
    llm_provider: Optional[Any] = None
) -> List[WordTimestamp]:
    """
    Romanizes Devanagari Hindi words into natural modern Hinglish.
    1. Uses LLM provider for contextual conversational romanization (e.g. "kya", "nahi", "samajh").
    2. Fallback to indic-transliteration if LLM unavailable or length mismatch.
    """
    if not words:
        return []

    word_texts = [w.word for w in words]
    # Check if there are Devanagari characters
    has_devanagari = any(re.search(r'[\u0900-\u097F]', w) for w in word_texts)
    if not has_devanagari:
        return words  # Already Latin / English

    romanized_texts: Optional[List[str]] = None

    # 1. Try LLM Provider if provided
    if llm_provider:
        prompt = (
            "You are a linguistic transliteration engine. Convert these Hindi Devanagari words into modern colloquial Hinglish (Latin alphabet).\n"
            "Rules:\n"
            "- Use standard WhatsApp/YouTube conversational Hinglish spelling (e.g. 'kya', 'nahi', 'hai', 'bahut', 'achha').\n"
            "- Keep any English words in standard English spelling.\n"
            "- CRITICAL: Output a JSON array with EXACTLY the same number of words in the exact same order.\n\n"
            f"Input words array ({len(word_texts)} items):\n{json.dumps(word_texts, ensure_ascii=False)}\n\n"
            "Output JSON format:\n{\"romanized\": [\"word1\", \"word2\", ...]}"
        )
        for attempt in range(2):
            try:
                res = await llm_provider.generate_json(
                    system_prompt="You convert Devanagari words to conversational Hinglish array with exact 1-to-1 length matching.",
                    user_prompt=prompt
                )
                items = res.get("romanized") if isinstance(res, dict) else (res if isinstance(res, list) else None)
                if isinstance(items, list) and len(items) == len(word_texts):
                    romanized_texts = [str(item).strip() for item in items]
                    break
            except Exception:
                continue

    # 2. Fallback to indic-transliteration
    if not romanized_texts or len(romanized_texts) != len(word_texts):
        try:
            from indic_transliteration import sanscript
            romanized_texts = []
            for w in word_texts:
                if re.search(r'[\u0900-\u097F]', w):
                    # Transliterate ITRANS then lowercase & clean
                    t = sanscript.transliterate(w, sanscript.DEVANAGARI, sanscript.ITRANS)
                    # Clean ITRANS diacritics into natural colloquial Hinglish
                    t = t.lower().replace("aa", "a").replace("ii", "i").replace("uu", "u")
                    t = t.replace(".n", "n").replace(".m", "n").replace("shh", "sh")
                    romanized_texts.append(t)
                else:
                    romanized_texts.append(w)
        except Exception:
            romanized_texts = word_texts

    # Build updated WordTimestamp list preserving exact timestamps
    result: List[WordTimestamp] = []
    for orig_w, rom_t in zip(words, romanized_texts):
        result.append(WordTimestamp(
            word=rom_t,
            start=orig_w.start,
            end=orig_w.end,
            probability=orig_w.probability
        ))

    return result
