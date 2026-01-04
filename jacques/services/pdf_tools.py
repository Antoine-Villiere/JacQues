from __future__ import annotations

from pathlib import Path
from typing import Iterable
import re


def highlight_text(path: Path, text: str, page_number: int | None = None) -> int:
    if not text.strip():
        return 0
    rects_by_page = _find_text_rects(path, text, page_number)
    if not rects_by_page:
        return 0
    return _apply_highlights(path, rects_by_page)


def _find_text_rects(
    path: Path, text: str, page_number: int | None
) -> dict[int, list[tuple[float, float, float, float, float]]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required for PDF highlights") from exc

    rects_by_page: dict[int, list[tuple[float, float, float, float, float]]] = {}
    with pdfplumber.open(path) as pdf:
        pages: Iterable[int]
        if page_number:
            pages = [max(page_number - 1, 0)]
        else:
            pages = range(len(pdf.pages))
        for page_index in pages:
            if page_index < 0 or page_index >= len(pdf.pages):
                continue
            page = pdf.pages[page_index]
            rects = _search_page_rects(page, text)
            if not rects:
                continue
            rects_by_page.setdefault(page_index, []).extend(rects)
    return rects_by_page


def _search_page_rects(
    page, text: str
) -> list[tuple[float, float, float, float, float]]:
    page_height = float(page.height)
    for pattern, use_regex in _build_search_patterns(text):
        try:
            matches = page.search(pattern, regex=use_regex, case=False)
        except re.error:
            continue
        if matches:
            return _rects_from_matches(matches, page_height)

    word_rects = _match_words_rects(page, text)
    if word_rects:
        return [(x0, top, x1, bottom, page_height) for x0, top, x1, bottom in word_rects]
    return []


def _build_search_patterns(text: str) -> list[tuple[str, bool]]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    patterns: list[tuple[str, bool]] = []

    def add(pattern: str, regex: bool) -> None:
        entry = (pattern, regex)
        if entry not in patterns:
            patterns.append(entry)

    add(normalized, False)
    add(re.escape(normalized).replace(r"\ ", r"\s+"), True)

    dehyphenated = re.sub(r"-\s+", "", normalized)
    if dehyphenated and dehyphenated != normalized:
        add(dehyphenated, False)
        add(re.escape(dehyphenated).replace(r"\ ", r"\s+"), True)

    flexible = re.escape(normalized).replace(r"\ ", r"(?:\s+|-\s+)")
    add(flexible, True)
    return patterns


def _rects_from_matches(
    matches: list[dict], page_height: float
) -> list[tuple[float, float, float, float, float]]:
    rects: list[tuple[float, float, float, float, float]] = []
    for match in matches:
        x0 = float(match.get("x0", 0))
        x1 = float(match.get("x1", 0))
        top = float(match.get("top", 0))
        bottom = float(match.get("bottom", 0))
        rects.append((x0, top, x1, bottom, page_height))
    return rects


def _match_words_rects(
    page, text: str
) -> list[tuple[float, float, float, float]]:
    tokens = _tokenize_words(text)
    if not tokens:
        return []
    words = page.extract_words(use_text_flow=True)
    if not words:
        return []

    normalized_words: list[str] = []
    word_objects: list[dict] = []
    for word in words:
        normalized = _normalize_word(word.get("text", ""))
        if not normalized:
            continue
        normalized_words.append(normalized)
        word_objects.append(word)

    if len(tokens) > len(normalized_words):
        return []

    rects: list[tuple[float, float, float, float]] = []
    token_len = len(tokens)
    for start in range(len(normalized_words) - token_len + 1):
        if normalized_words[start : start + token_len] == tokens:
            matched = word_objects[start : start + token_len]
            rects.extend(_rects_from_words(matched))
    return rects


def _tokenize_words(text: str) -> list[str]:
    raw_tokens = re.split(r"\s+", text.strip())
    tokens = [_normalize_word(token) for token in raw_tokens]
    return [token for token in tokens if token]


def _normalize_word(token: str) -> str:
    cleaned = re.sub(r"[^\w]+", "", token, flags=re.UNICODE)
    return cleaned.lower()


def _rects_from_words(
    words: list[dict],
) -> list[tuple[float, float, float, float]]:
    lines: dict[float, dict[str, float]] = {}
    for word in words:
        x0 = float(word.get("x0", 0))
        x1 = float(word.get("x1", 0))
        top = float(word.get("top", 0))
        bottom = float(word.get("bottom", 0))
        key = round(top, 1)
        line = lines.setdefault(
            key, {"x0": x0, "x1": x1, "top": top, "bottom": bottom}
        )
        line["x0"] = min(line["x0"], x0)
        line["x1"] = max(line["x1"], x1)
        line["top"] = min(line["top"], top)
        line["bottom"] = max(line["bottom"], bottom)

    rects: list[tuple[float, float, float, float]] = []
    for line in lines.values():
        rects.append((line["x0"], line["top"], line["x1"], line["bottom"]))
    return rects


def _apply_highlights(
    path: Path,
    rects_by_page: dict[int, list[tuple[float, float, float, float, float]]],
) -> int:
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Highlight
    from pypdf.generic import ArrayObject, FloatObject

    reader = PdfReader(str(path))
    writer = PdfWriter()
    highlight_count = 0
    for index, page in enumerate(reader.pages):
        rects = rects_by_page.get(index)
        if rects:
            for rect in rects:
                x0, top, x1, bottom, height = rect
                y0 = height - bottom
                y1 = height - top
                quad_points = ArrayObject(
                    [
                        FloatObject(x0),
                        FloatObject(y1),
                        FloatObject(x1),
                        FloatObject(y1),
                        FloatObject(x1),
                        FloatObject(y0),
                        FloatObject(x0),
                        FloatObject(y0),
                    ]
                )
                annotation = Highlight(
                    rect=(x0, y0, x1, y1),
                    quad_points=quad_points,
                    highlight_color="fff59d",
                )
                page.add_annotation(annotation)
                highlight_count += 1
        writer.add_page(page)

    temp_path = path.with_suffix(".highlight.tmp.pdf")
    with temp_path.open("wb") as handle:
        writer.write(handle)
    temp_path.replace(path)
    return highlight_count
