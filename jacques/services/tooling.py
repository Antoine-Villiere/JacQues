from __future__ import annotations

import json
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import GENERATED_DIR, Settings, UPLOADS_DIR
from ..utils import safe_filename
from .. import db
from . import doc_ingest, file_ops, image_gen, market_data, plotting, rag, vision, web_search


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], Settings, int], str]


def build_tools(
    settings: Settings,
    conversation_id: int,
    use_rag: bool = True,
    use_web: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, ToolSpec]]:
    tools: list[ToolSpec] = []

    tools.append(
        ToolSpec(
            name="list_documents",
            description="List ingested documents for RAG.",
            parameters={"type": "object", "properties": {}},
            handler=_tool_list_documents,
        )
    )

    tools.append(
        ToolSpec(
            name="list_images",
            description="List stored images.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max number of images to return.",
                    }
                },
            },
            handler=_tool_list_images,
        )
    )

    tools.append(
        ToolSpec(
            name="memory_append",
            description="Append a short preference or fact to global memory.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=_tool_memory_append,
        )
    )

    tools.extend(
        [
            ToolSpec(
                name="excel_create",
                description="Create a new Excel workbook.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "sheet_name": {"type": "string"},
                    },
                    "required": ["filename"],
                },
                handler=_tool_excel_create,
            ),
            ToolSpec(
                name="excel_add_sheet",
                description="Add a sheet to an existing Excel workbook.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "sheet_name": {"type": "string"},
                    },
                    "required": ["filename", "sheet_name"],
                },
                handler=_tool_excel_add_sheet,
            ),
            ToolSpec(
                name="excel_set_cell",
                description="Set a cell value in an Excel workbook.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "sheet_name": {"type": "string"},
                        "cell": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["filename", "sheet_name", "cell", "value"],
                },
                handler=_tool_excel_set_cell,
            ),
            ToolSpec(
                name="word_create",
                description="Create a new Word document.",
                parameters={
                    "type": "object",
                    "properties": {"filename": {"type": "string"}},
                    "required": ["filename"],
                },
                handler=_tool_word_create,
            ),
            ToolSpec(
                name="word_append",
                description="Append a paragraph to a Word document.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["filename", "text"],
                },
                handler=_tool_word_append,
            ),
            ToolSpec(
                name="word_replace",
                description="Replace text inside a Word document.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                    },
                    "required": ["filename", "old", "new"],
                },
                handler=_tool_word_replace,
            ),
            ToolSpec(
                name="image_generate",
                description="Generate an image from a prompt.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "prompt": {"type": "string"},
                    },
                    "required": ["filename", "prompt"],
                },
                handler=_tool_image_generate,
            ),
            ToolSpec(
                name="plot_generate",
                description="Generate a plot image from structured data.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "chart_type": {
                            "type": "string",
                            "enum": ["line", "bar", "scatter"],
                        },
                        "title": {"type": "string"},
                        "x": {"type": "array", "items": {"type": "string"}},
                        "y": {"type": "array", "items": {"type": "number"}},
                        "x_label": {"type": "string"},
                        "y_label": {"type": "string"},
                        "spec": {"type": "object"},
                        "series": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "x": {"type": "array", "items": {"type": "string"}},
                                    "y": {"type": "array", "items": {"type": "number"}},
                                    "color": {"type": "string"},
                                },
                                "required": ["y"],
                            },
                        },
                    },
                },
                handler=_tool_plot_generate,
            ),
            ToolSpec(
                name="plot_fred_series",
                description=(
                    "Fetch a time series from FRED and plot it. "
                    "Dates accept YYYY-MM-DD, YYYY-MM, YYYY, or Month YYYY."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "series_id": {"type": "string"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": ["string", "null"]},
                        "filename": {"type": "string"},
                        "title": {"type": "string"},
                        "chart_type": {
                            "type": "string",
                            "enum": ["line", "bar", "scatter"],
                        },
                        "y_label": {"type": "string"},
                        "max_points": {"type": "integer"},
                    },
                    "required": ["series_id", "start_date"],
                },
                handler=_tool_plot_fred_series,
            ),
        ]
    )

    if settings.vision_enabled:
        tools.append(
            ToolSpec(
                name="image_describe",
                description="Describe an existing image by filename.",
                parameters={
                    "type": "object",
                    "properties": {"filename": {"type": "string"}},
                    "required": ["filename"],
                },
                handler=_tool_image_describe,
            )
        )

    if use_rag:
        tools.extend(
            [
                ToolSpec(
                    name="rag_search",
                    description="Search ingested documents with RAG.",
                    parameters={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                    handler=_tool_rag_search,
                ),
                ToolSpec(
                    name="rag_rebuild",
                    description="Rebuild the local RAG index.",
                    parameters={"type": "object", "properties": {}},
                    handler=_tool_rag_rebuild,
                ),
            ]
        )

    if use_web:
        tools.extend(
            [
                ToolSpec(
                    name="web_search",
                    description="Search the web for information.",
                    parameters={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                    handler=_tool_web_search,
                ),
                ToolSpec(
                    name="web_fetch",
                    description="Fetch and extract text from a URL.",
                    parameters={
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                    },
                    handler=_tool_web_fetch,
                ),
            ]
        )

    tool_defs = [
        {"type": "function", "function": _tool_definition(tool)} for tool in tools
    ]
    tool_map = {tool.name: tool for tool in tools}
    return tool_defs, tool_map


def execute_tool(
    name: str | None,
    raw_args: Any,
    tool_map: dict[str, ToolSpec],
    settings: Settings,
    conversation_id: int,
) -> str:
    if not name or name not in tool_map:
        return f"Unknown tool: {name}"

    args, error = _parse_args(raw_args)
    if error:
        return error

    try:
        return tool_map[name].handler(args, settings, conversation_id)
    except Exception as exc:
        return f"Tool {name} failed: {exc}"


def _parse_args(raw_args: Any) -> tuple[dict[str, Any], str | None]:
    if raw_args is None:
        return {}, None
    if isinstance(raw_args, dict):
        return raw_args, None
    if isinstance(raw_args, str):
        payload = raw_args.strip()
        if not payload:
            return {}, None
        try:
            return json.loads(payload), None
        except json.JSONDecodeError:
            return {}, "Invalid tool arguments."
    return {}, "Invalid tool arguments."


def _tool_definition(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }


def _tool_list_documents(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    docs = db.list_documents(conversation_id)
    if not docs:
        return "No documents ingested."
    lines = [f"- {doc['name']} ({doc['doc_type']})" for doc in docs]
    return "Documents:\n" + "\n".join(lines)


def _tool_list_images(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    limit = args.get("limit")
    images = db.list_images(conversation_id)
    if isinstance(limit, int):
        images = images[:limit]
    if not images:
        return "No images available."
    lines = [f"- {img['name']}" for img in images]
    return "Images:\n" + "\n".join(lines)


def _tool_memory_append(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        return "Provide memory text to append."
    current = db.get_setting("global_memory") or ""
    line = text
    if not line.startswith("-"):
        line = f"- {line}"
    updated = current.strip()
    if updated:
        updated = f"{updated}\n{line}"
    else:
        updated = line
    db.set_setting("global_memory", updated)
    return "Global memory updated."


def _tool_rag_search(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "Provide a query for RAG search."
    results = rag.search(query, settings, conversation_id)
    context = rag.format_results(results)
    return context or "No relevant documents found."


def _tool_rag_rebuild(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    rag.build_index(conversation_id)
    return "RAG index rebuilt."


def _tool_web_search(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "Provide a query for web search."
    results = web_search.search(query, settings)
    summary = web_search.summarize_results(results)
    return summary or "No results."


def _tool_web_fetch(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    url = str(args.get("url", "")).strip()
    if not url:
        return "Provide a URL to fetch."
    content = web_search.fetch_url(url, settings)
    if len(content) > 1200:
        content = content[:1200].rsplit(" ", 1)[0] + "..."
    return content


def _tool_excel_create(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "workbook.xlsx"))
    sheet_name = str(args.get("sheet_name", "Sheet1")).strip() or "Sheet1"
    if not Path(filename).suffix:
        filename = f"{filename}.xlsx"
    path = _resolve_doc_path(conversation_id, filename, UPLOADS_DIR)
    file_ops.create_excel(path, sheet_name)
    _upsert_document(conversation_id, filename, path)
    return f"Excel created at {path}"


def _tool_excel_add_sheet(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "workbook.xlsx"))
    sheet_name = str(args.get("sheet_name", "Sheet1")).strip() or "Sheet1"
    path = _resolve_doc_path(conversation_id, filename, UPLOADS_DIR)
    file_ops.add_sheet(path, sheet_name)
    _refresh_document_text(conversation_id, filename, path)
    return f"Sheet added to {path}"


def _tool_excel_set_cell(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "workbook.xlsx"))
    sheet_name = str(args.get("sheet_name", "Sheet1")).strip() or "Sheet1"
    cell = str(args.get("cell", "A1")).strip() or "A1"
    value = str(args.get("value", ""))
    path = _resolve_doc_path(conversation_id, filename, UPLOADS_DIR)
    file_ops.set_cell(path, sheet_name, cell, value)
    _refresh_document_text(conversation_id, filename, path)
    return f"Cell {cell} updated in {path}"


def _tool_word_create(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "document.docx"))
    if not Path(filename).suffix:
        filename = f"{filename}.docx"
    path = _resolve_doc_path(conversation_id, filename, UPLOADS_DIR)
    file_ops.create_word(path)
    _upsert_document(conversation_id, filename, path)
    return f"Word created at {path}"


def _tool_word_append(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "document.docx"))
    text = str(args.get("text", "")).strip()
    if not text:
        return "Provide text to append."
    path = _resolve_doc_path(conversation_id, filename, UPLOADS_DIR)
    file_ops.append_paragraph(path, text)
    _refresh_document_text(conversation_id, filename, path)
    return f"Paragraph appended to {path}"


def _tool_word_replace(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "document.docx"))
    old = str(args.get("old", "")).strip()
    new = str(args.get("new", ""))
    if not old:
        return "Provide text to replace."
    path = _resolve_doc_path(conversation_id, filename, UPLOADS_DIR)
    file_ops.replace_text(path, old, new)
    _refresh_document_text(conversation_id, filename, path)
    return f"Replaced text in {path}"


def _tool_image_generate(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "jacques.png"))
    prompt = str(args.get("prompt", "")).strip()
    if not prompt:
        return "Provide a prompt for image generation."
    path = GENERATED_DIR / filename
    image_gen.generate_image(prompt, path, settings)
    db.add_image(conversation_id, filename, str(path), f"Generated: {prompt}")
    url = f"/files/generated/{filename}"
    return f"Image created: {filename}\n\n![{filename}]({url})"


def _tool_plot_generate(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "plot.png"))
    if not Path(filename).suffix:
        filename = f"{filename}.png"
    if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        filename = f"{Path(filename).stem}.png"

    plot_spec = args.get("spec")
    if not isinstance(plot_spec, dict):
        plot_spec = {key: value for key, value in args.items() if key != "filename"}

    path = GENERATED_DIR / filename
    if path.exists():
        stem = path.stem
        filename = f"{stem}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{path.suffix}"
        path = GENERATED_DIR / filename

    plotting.generate_plot(plot_spec, path)
    title = str(plot_spec.get("title", "")).strip() if isinstance(plot_spec, dict) else ""
    description = f"Plot: {title}" if title else "Plot generated"
    db.add_image(conversation_id, filename, str(path), description)
    url = f"/files/generated/{filename}"
    return f"Plot created: {filename}\n\n![{filename}]({url})"


def _tool_plot_fred_series(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    series_id = str(args.get("series_id", "") or "").strip()
    start_date = str(args.get("start_date", "") or "").strip()
    raw_end = args.get("end_date")
    end_date = None if raw_end is None else str(raw_end).strip() or None
    if not series_id or not start_date:
        return "Provide series_id and start_date (YYYY-MM-DD)."

    filename = safe_filename(args.get("filename", f"{series_id}.png"))
    if not Path(filename).suffix:
        filename = f"{filename}.png"
    if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        filename = f"{Path(filename).stem}.png"

    max_points = args.get("max_points")
    if not isinstance(max_points, int) or max_points <= 0:
        max_points = 400

    try:
        data = market_data.fetch_fred_series(
            series_id=series_id,
            start_date=start_date,
            end_date=end_date,
            timeout=settings.web_timeout,
            max_points=max_points,
        )
    except ValueError as exc:
        return (
            f"{exc}. Use YYYY-MM-DD, YYYY-MM, YYYY, or Month YYYY "
            "(e.g. 2025-07-01 or July 2025)."
        )
    if not data:
        return "No data returned from FRED."

    title = str(args.get("title", "")).strip() or f"{series_id} (FRED)"
    chart_type = str(args.get("chart_type", "line")).strip().lower()
    y_label = str(args.get("y_label", "")).strip() or "Index"

    x_vals = [row[0] for row in data]
    y_vals = [row[1] for row in data]
    plot_spec = {
        "chart_type": chart_type,
        "title": title,
        "x": x_vals,
        "y": y_vals,
        "x_label": "Date",
        "y_label": y_label,
    }

    path = GENERATED_DIR / filename
    plotting.generate_plot(plot_spec, path)
    db.add_image(conversation_id, filename, str(path), f"Plot: {title}")
    url = f"/files/generated/{filename}"
    return f"Plot created: {filename}\n\n![{filename}]({url})"


def _tool_image_describe(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", ""))
    if not filename:
        return "Provide an image filename."
    image_row = db.get_image_by_name(conversation_id, filename)
    if not image_row:
        return "Image not found."
    path = Path(image_row["path"])
    description = vision.describe_image(path, settings)
    return description


def _resolve_doc_path(conversation_id: int, filename: str, fallback_dir: Path) -> Path:
    existing = db.get_document_by_name(conversation_id, filename)
    if existing:
        return Path(existing["path"])
    return fallback_dir / filename


def _upsert_document(conversation_id: int, filename: str, path: Path) -> None:
    try:
        text = doc_ingest.extract_text(path)
    except Exception:
        text = ""
    existing = db.get_document_by_name(conversation_id, filename)
    if existing:
        db.update_document_text(int(existing["id"]), text)
    else:
        db.add_document(
            conversation_id,
            filename,
            str(path),
            path.suffix.lower(),
            text,
        )
    rag.build_index(conversation_id)


def _refresh_document_text(conversation_id: int, filename: str, path: Path) -> None:
    try:
        text = doc_ingest.extract_text(path)
    except Exception:
        text = ""
    existing = db.get_document_by_name(conversation_id, filename)
    if existing:
        db.update_document_text(int(existing["id"]), text)
    else:
        db.add_document(
            conversation_id,
            filename,
            str(path),
            path.suffix.lower(),
            text,
        )
    rag.build_index(conversation_id)
