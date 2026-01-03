from __future__ import annotations

from pathlib import Path
from typing import Iterable


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
            matches = page.search(text, regex=False)
            if not matches:
                continue
            for match in matches:
                x0 = float(match.get("x0", 0))
                x1 = float(match.get("x1", 0))
                top = float(match.get("top", 0))
                bottom = float(match.get("bottom", 0))
                rects_by_page.setdefault(page_index, []).append(
                    (x0, top, x1, bottom, float(page.height))
                )
    return rects_by_page


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
