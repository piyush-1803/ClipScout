import os
import json
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from .transcribe import WordTimestamp

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

@dataclass
class CaptionLine:
    start: float
    end: float
    text: str
    words: List[WordTimestamp]

def build_caption_lines(
    words: List[WordTimestamp],
    max_words_per_line: int = 3,
    max_chars_per_line: int = 22,
    max_pause_seconds: float = 0.35,
    min_line_duration: float = 0.25,
    uppercase: bool = False
) -> List[CaptionLine]:
    """
    Groups acoustic word timestamps into punchy, high-retention short lines.
    Breaks on pauses > 0.35s, punctuation, or 2-4 words per line.
    """
    if not words:
        return []

    lines: List[CaptionLine] = []
    current_words: List[WordTimestamp] = []
    line_start = words[0].start

    for i, w in enumerate(words):
        word_text = w.word.upper() if uppercase else w.word
        # Create a copy with case
        w_item = WordTimestamp(word=word_text, start=w.start, end=w.end, probability=w.probability)

        # Check pause gap before this word
        pause = (w.start - current_words[-1].end) if current_words else 0.0
        # Check current line length
        current_len = sum(len(cw.word) for cw in current_words) + len(current_words)
        ends_with_punct = current_words and bool(re.search(r'[.?!,;:]$', current_words[-1].word))

        should_break = (
            current_words and (
                pause > max_pause_seconds
                or ends_with_punct
                or len(current_words) >= max_words_per_line
                or (current_len + len(word_text) + 1) > max_chars_per_line
            )
        )

        if should_break:
            line_end = max(line_start + min_line_duration, current_words[-1].end)
            line_text = " ".join(cw.word for cw in current_words)
            lines.append(CaptionLine(
                start=round(line_start, 3),
                end=round(line_end, 3),
                text=line_text,
                words=current_words
            ))
            current_words = [w_item]
            line_start = w.start
        else:
            current_words.append(w_item)

    if current_words:
        line_end = max(line_start + min_line_duration, current_words[-1].end)
        line_text = " ".join(cw.word for cw in current_words)
        lines.append(CaptionLine(
            start=round(line_start, 3),
            end=round(line_end, 3),
            text=line_text,
            words=current_words
        ))

    # Resolve any overlapping timestamps
    for i in range(len(lines) - 1):
        if lines[i].end > lines[i + 1].start:
            mid = (lines[i].end + lines[i + 1].start) / 2.0
            lines[i].end = round(mid, 3)
            lines[i + 1].start = round(mid, 3)

    return lines

def format_ass_time(seconds: float) -> str:
    """Formats float seconds into ASS timecode: H:MM:SS.cs"""
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

def generate_ass_script(
    lines: List[CaptionLine],
    style_preset: str = "creator_classic",
    output_ass_path: str = "captions.ass",
    credit_text: Optional[str] = None,
    credit_duration: float = 6.0,
    video_duration: float = 60.0,
    language: str = "en"
) -> str:
    """
    Renders styled ASS script for 1080x1920 vertical video with:
    - Creator Classic: Yellow bold text on solid red box (BorderStyle=3)
    - Active Word Pop: White text with active word yellow & 110% scale
    - Clean Outline: White bold text, thick black outline & soft shadow
    - Safe-zone positioning (~65% from top, avoiding bottom 20% YouTube Shorts UI)
    - Optional channel credit overlay in the top safe zone
    """
    font_name = "Noto Sans Devanagari" if language == "hi" else "Montserrat ExtraBold"

    # Alignment 2 = bottom center. MarginV = 520 places text at ~68% from top in 1920 height
    margin_v = 520
    font_size = 62

    # ASS Styles
    # Colors in ASS are &HAABBGGRR& (Hex alpha-blue-green-red)
    # Yellow: &H0000FFFF&, Red: &H000000FF&, White: &H00FFFFFF&, Black: &H00000000&
    if style_preset == "creator_classic":
        # Yellow on Solid Red Box (BorderStyle=3 creates opaque background box)
        primary_color = "&H0000FFFF&"  # Yellow
        back_color = "&H000000CC&"     # Crimson Red Box
        border_style = 3
        outline = 16
        shadow = 0
    elif style_preset == "clean_outline":
        primary_color = "&H00FFFFFF&"  # White
        back_color = "&H80000000&"     # Semi-transparent shadow
        border_style = 1
        outline = 6
        shadow = 3
    else:  # "active_word_pop"
        primary_color = "&H00FFFFFF&"  # White default
        back_color = "&H00000000&"
        border_style = 1
        outline = 5
        shadow = 2

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: MainCaption,{font_name},{font_size},{primary_color},&H000000FF&,&H00000000&,{back_color},-1,0,0,0,100,100,1,0,{border_style},{outline},{shadow},2,80,80,{margin_v},1
Style: CreditStyle,Montserrat ExtraBold,34,&H00FFFFFF&,&H000000FF&,&H00000000&,&H80000000&,-1,0,0,0,100,100,1,0,1,3,1,8,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogues: List[str] = []

    # 1. Top Safe-Zone Credit Overlay
    if credit_text:
        c_end = video_duration if credit_duration <= 0 else min(video_duration, credit_duration)
        safe_credit = credit_text.replace("\n", " ").strip()
        dialogues.append(
            f"Dialogue: 1,0:00:00.00,{format_ass_time(c_end)},CreditStyle,,0,0,0,,{safe_credit}"
        )

    # 2. Main Captions Events
    for line in lines:
        t_start = format_ass_time(line.start)
        t_end = format_ass_time(line.end)

        if style_preset == "active_word_pop" and line.words:
            # Active word highlighting per sub-word timestamp
            for w_idx, active_w in enumerate(line.words):
                w_start = format_ass_time(active_w.start)
                w_end = format_ass_time(active_w.end)

                # Format line highlighting only the current active word
                words_markup = []
                for idx, w in enumerate(line.words):
                    if idx == w_idx:
                        # Highlight Yellow + 110% scale
                        words_markup.append(f"{{\\c&H0000FFFF&\\fscx110\\fscy110}}{w.word}{{\\rMainCaption}}")
                    else:
                        words_markup.append(w.word)

                dialogue_text = " ".join(words_markup)
                dialogues.append(
                    f"Dialogue: 0,{w_start},{w_end},MainCaption,,0,0,0,,{dialogue_text}"
                )
        else:
            # Creator classic or Clean Outline
            dialogues.append(
                f"Dialogue: 0,{t_start},{t_end},MainCaption,,0,0,0,,{line.text}"
            )

    content = header + "\n".join(dialogues) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(output_ass_path)), exist_ok=True)
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_ass_path

def rebuild_ass_file(
    captions_data: Dict[str, Any],
    new_style: str,
    output_ass_path: str,
    credit_text: Optional[str] = None,
    credit_duration: float = 6.0,
    video_duration: float = 60.0
) -> str:
    """Rebuilds ASS file from captions.json data with a new style preset."""
    raw_lines = captions_data.get("lines", [])
    lines: List[CaptionLine] = []
    for item in raw_lines:
        w_objs = [
            WordTimestamp(
                word=w["word"],
                start=w["start"],
                end=w["end"],
                probability=w.get("probability", 1.0)
            )
            for w in item.get("words", [])
        ]
        lines.append(CaptionLine(
            start=item["start"],
            end=item["end"],
            text=item["text"],
            words=w_objs
        ))

    lang = captions_data.get("language", "en")
    return generate_ass_script(
        lines=lines,
        style_preset=new_style,
        output_ass_path=output_ass_path,
        credit_text=credit_text,
        credit_duration=credit_duration,
        video_duration=video_duration,
        language=lang
    )
