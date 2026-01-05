from __future__ import annotations

import base64
import csv
import json
import os
import time
from datetime import datetime, timezone, timedelta, date
from urllib.parse import urlencode, quote
from dataclasses import dataclass
import threading
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo
from uuid import uuid4
import subprocess
import sys

from ..config import (
    BASE_DIR,
    DATA_DIR,
    EXPORTS_DIR,
    GENERATED_DIR,
    RAG_INDEX_DIR,
    Settings,
    UPLOADS_DIR,
)
from ..utils import safe_filename
from .. import db
from . import (
    doc_ingest,
    file_ops,
    image_gen,
    market_data,
    plotting,
    rag,
    vision,
    web_search,
    scheduler as task_scheduler,
)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], Settings, int], str]


OSASCRIPT_LOCK = threading.Lock()
OSASCRIPT_TIMEOUT = 60
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _setting_enabled(key: str, default: bool = True) -> bool:
    value = db.get_setting(key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_tools(
    settings: Settings,
    conversation_id: int,
    use_rag: bool = True,
    use_web: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, ToolSpec]]:
    tools: list[ToolSpec] = []
    web_enabled = _setting_enabled("tools_web_enabled", True)
    mail_enabled = _setting_enabled("tools_mail_enabled", True)
    calendar_enabled = _setting_enabled("tools_calendar_enabled", True)
    code_enabled = _setting_enabled("tools_code_enabled", True)
    macos_enabled = _setting_enabled("tools_macos_enabled", True)

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

    if mail_enabled:
        tools.extend(
            [
                ToolSpec(
                    name="email_draft",
                    description="Create an email draft and open it in the user's mail app.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "to": {"type": ["string", "array"]},
                            "subject": {"type": "string"},
                            "body": {"type": "string"},
                            "cc": {"type": ["string", "array"]},
                            "bcc": {"type": ["string", "array"]},
                        },
                    },
                    handler=_tool_email_draft,
                ),
                ToolSpec(
                    name="mail_reply",
                    description="Reply to an existing Apple Mail message.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "mail_id": {"type": "integer"},
                            "message_id": {"type": "string"},
                            "account": {"type": "string"},
                            "mailbox": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["body"],
                    },
                    handler=_tool_mail_reply,
                ),
                ToolSpec(
                    name="mail_search",
                    description="Search Apple Mail and return matching messages.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "account": {"type": "string"},
                            "mailbox": {"type": "string"},
                            "since_days": {"type": "integer"},
                            "limit": {"type": "integer"},
                            "search_body": {"type": "boolean"},
                            "only_inbox": {"type": "boolean"},
                        },
                    },
                    handler=_tool_mail_search,
                ),
                ToolSpec(
                    name="mail_read",
                    description="Read a specific Apple Mail message by id.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "mail_id": {"type": "integer"},
                            "message_id": {"type": "string"},
                            "account": {"type": "string"},
                            "mailbox": {"type": "string"},
                            "max_chars": {"type": "integer"},
                        },
                    },
                    handler=_tool_mail_read,
                ),
            ]
        )

    if calendar_enabled:
        tools.extend(
            [
                ToolSpec(
                    name="calendar_list",
                    description="List Apple Calendar calendars and whether they are writable.",
                    parameters={"type": "object", "properties": {}},
                    handler=_tool_calendar_list,
                ),
                ToolSpec(
                    name="calendar_find",
                    description="Find calendar events by title and date range.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "start": {"type": "string"},
                            "end": {"type": "string"},
                            "calendar": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                    },
                    handler=_tool_calendar_find,
                ),
                ToolSpec(
                    name="calendar_event",
                    description="Create a calendar event (.ics) that opens in the user's calendar app.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "start": {"type": "string"},
                            "end": {"type": "string"},
                            "duration_minutes": {"type": "integer"},
                            "all_day": {"type": "boolean"},
                            "timezone": {"type": "string"},
                            "calendar": {"type": "string"},
                            "location": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["title", "start"],
                    },
                    handler=_tool_calendar_event,
                ),
            ]
        )

    if macos_enabled:
        tools.append(
            ToolSpec(
                name="macos_script",
                description="Run an AppleScript snippet to control native macOS apps.",
                parameters={
                    "type": "object",
                    "properties": {
                        "script": {"type": "string"},
                    },
                    "required": ["script"],
                },
                handler=_tool_macos_script,
            )
        )

    tools.extend(
        [
            ToolSpec(
                name="task_schedule",
                description="Schedule a recurring task (cron) for reminders or web digests.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "task_type": {"type": "string", "enum": ["web_digest", "reminder"]},
                        "cron": {
                            "type": "string",
                            "description": "Cron expression: min hour day month dow",
                        },
                        "timezone": {"type": "string"},
                        "query": {"type": "string"},
                        "message": {"type": "string"},
                        "limit": {"type": "integer"},
                        "use_llm": {"type": "boolean"},
                        "enabled": {"type": "boolean"},
                    },
                    "required": ["cron"],
                },
                handler=_tool_task_schedule,
            ),
            ToolSpec(
                name="task_list",
                description="List scheduled tasks for this conversation.",
                parameters={"type": "object", "properties": {}},
                handler=_tool_task_list,
            ),
            ToolSpec(
                name="task_delete",
                description="Delete a scheduled task by id.",
                parameters={
                    "type": "object",
                    "properties": {"task_id": {"type": "integer"}},
                    "required": ["task_id"],
                },
                handler=_tool_task_delete,
            ),
            ToolSpec(
                name="task_enable",
                description="Enable or disable a scheduled task.",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "integer"},
                        "enabled": {"type": "boolean"},
                    },
                    "required": ["task_id", "enabled"],
                },
                handler=_tool_task_enable,
            ),
        ]
    )

    if code_enabled:
        tools.extend(
            [
                ToolSpec(
                    name="project_list_files",
                    description="List files in the local project directory.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "pattern": {"type": "string"},
                            "recursive": {"type": "boolean"},
                            "include_hidden": {"type": "boolean"},
                            "max": {"type": "integer"},
                        },
                    },
                    handler=_tool_project_list_files,
                ),
                ToolSpec(
                    name="project_read_file",
                    description="Read a file from the local project directory.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                            "max_chars": {"type": "integer"},
                        },
                        "required": ["path"],
                    },
                    handler=_tool_project_read_file,
                ),
                ToolSpec(
                    name="project_search",
                    description="Search for text in project files.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "path": {"type": "string"},
                            "max_results": {"type": "integer"},
                            "include_hidden": {"type": "boolean"},
                        },
                        "required": ["query"],
                    },
                    handler=_tool_project_search,
                ),
                ToolSpec(
                    name="project_replace",
                    description="Replace text in a project file (targeted update).",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                            "count": {"type": "integer"},
                        },
                        "required": ["path", "old_text", "new_text"],
                    },
                    handler=_tool_project_replace,
                ),
                ToolSpec(
                    name="python_run",
                    description=(
                        "Run a short Python snippet or a script file in the project workspace "
                        "for quick calculations, file generation, or utilities."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "path": {"type": "string"},
                            "args": {"type": "array", "items": {"type": "string"}},
                            "stdin": {"type": "string"},
                            "timeout": {"type": "integer"},
                        },
                    },
                    handler=_tool_python_run,
                ),
                ToolSpec(
                    name="python",
                    description="Alias of python_run for local Python snippets.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "path": {"type": "string"},
                            "args": {"type": "array", "items": {"type": "string"}},
                            "stdin": {"type": "string"},
                            "timeout": {"type": "integer"},
                        },
                    },
                    handler=_tool_python_run,
                ),
            ]
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
                name="excel_read_sheet",
                description="Read data from a specific sheet in an Excel workbook.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "sheet_name": {"type": ["string", "integer"]},
                        "document_id": {"type": "integer"},
                        "max_rows": {"type": "integer"},
                        "max_cols": {"type": "integer"},
                    },
                    "required": ["filename"],
                },
                handler=_tool_excel_read_sheet,
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

    if use_web and web_enabled:
        tools.extend(
            [
                ToolSpec(
                    name="web_search",
                    description="Search the web for information.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                            "country": {"type": "string"},
                            "search_lang": {"type": "string"},
                            "freshness": {"type": "string"},
                            "result_filter": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                    handler=_tool_web_search,
                ),
                ToolSpec(
                    name="news_search",
                    description="Search the news (Brave News API).",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                            "country": {"type": "string"},
                            "search_lang": {"type": "string"},
                            "freshness": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                    handler=_tool_news_search,
                ),
                ToolSpec(
                    name="web_fetch",
                    description="Fetch and extract text from a URL.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "selector": {"type": "string"},
                            "max_chars": {"type": "integer"},
                        },
                        "required": ["url"],
                    },
                    handler=_tool_web_fetch,
                ),
                ToolSpec(
                    name="stock_history",
                    description=(
                        "Fetch daily stock price history (OHLCV) from Stooq. "
                        "Use for equities performance and return analysis."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "start_date": {"type": "string"},
                            "end_date": {"type": ["string", "null"]},
                            "max_points": {"type": "integer"},
                            "filename": {"type": "string"},
                        },
                        "required": ["symbol", "start_date"],
                    },
                    handler=_tool_stock_history,
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


def _snapshot_images(directory: Path) -> dict[str, float]:
    snapshots: dict[str, float] = {}
    if not directory.exists():
        return snapshots
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in _IMAGE_EXTENSIONS:
            continue
        try:
            snapshots[path.name] = path.stat().st_mtime
        except Exception:
            continue
    return snapshots


def _detect_new_images(
    directory: Path, before: dict[str, float], start_time: float
) -> list[Path]:
    if not directory.exists():
        return []
    found: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in _IMAGE_EXTENSIONS:
            continue
        try:
            mtime = path.stat().st_mtime
        except Exception:
            continue
        if path.name not in before or mtime >= start_time - 1:
            found.append(path)
    found.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0)
    return found


def _iter_data_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    skip_dirs = {RAG_INDEX_DIR}
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        if any(current_path == skip or skip in current_path.parents for skip in skip_dirs):
            dirnames[:] = []
            continue
        for name in filenames:
            files.append(current_path / name)
    return files


def _snapshot_files(root: Path) -> dict[Path, float]:
    snapshots: dict[Path, float] = {}
    for path in _iter_data_files(root):
        if not path.is_file():
            continue
        try:
            snapshots[path] = path.stat().st_mtime
        except Exception:
            continue
    return snapshots


def _detect_new_files(
    root: Path, before: dict[Path, float], start_time: float
) -> list[Path]:
    found: list[Path] = []
    for path in _iter_data_files(root):
        if not path.is_file():
            continue
        if path not in before:
            found.append(path)
            continue
    return found


def _should_skip_generated_file(path: Path) -> bool:
    name = path.name
    if not name:
        return True
    if name in {".DS_Store"}:
        return True
    if name.startswith("jacques.db"):
        return True
    if name.endswith(".db") or name.endswith(".db-wal") or name.endswith(".db-shm"):
        return True
    return False


def _extract_data_uri_image(text: str) -> tuple[str, bytes, str] | None:
    if not text:
        return None
    marker = "data:image/"
    idx = text.find(marker)
    if idx < 0:
        return None
    tail = text[idx:]
    end = len(tail)
    for sep in (" ", "\n", "\r", "\t", ")", "\"", "'"):
        pos = tail.find(sep)
        if pos != -1:
            end = min(end, pos)
    uri = tail[:end].strip()
    if ";base64," not in uri:
        return None
    header, b64data = uri.split(",", 1)
    if not header.lower().startswith("data:image/"):
        return None
    mime = header.split(";", 1)[0].split("/", 1)[1].lower()
    cleaned = "".join(b64data.split())
    if not cleaned:
        return None
    try:
        payload = base64.b64decode(cleaned, validate=False)
    except Exception:
        return None
    return mime, payload, uri


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


def _tool_email_draft(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    def normalize_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        if not text:
            return []
        parts = [item.strip() for item in text.replace(";", ",").split(",")]
        return [part for part in parts if part]

    to_list = normalize_list(args.get("to"))
    cc_list = normalize_list(args.get("cc"))
    bcc_list = normalize_list(args.get("bcc"))
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "").strip()

    mailto = "mailto:" + ",".join(to_list)
    params: dict[str, str] = {}
    if subject:
        params["subject"] = subject
    if body:
        params["body"] = body
    if cc_list:
        params["cc"] = ",".join(cc_list)
    if bcc_list:
        params["bcc"] = ",".join(bcc_list)
    if params:
        mailto = f"{mailto}?{urlencode(params, quote_via=quote)}"

    status_line = "Email draft ready."
    apple_result = _create_mail_draft_apple_mail(
        to_list, cc_list, bcc_list, subject, body
    )
    if apple_result is not None:
        ok, message = apple_result
        if ok:
            status_line = "Apple Mail draft created."
        else:
            status_line = f"Apple Mail automation failed: {message}"

    return (
        f"{status_line}\n"
        f"Mailto: {mailto}\n"
        f"To: {', '.join(to_list) if to_list else '-'}\n"
        f"Subject: {subject or '-'}"
    )


def _osascript_literal(value: str) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _osascript_text_block(value: str) -> str:
    if not value:
        return '""'
    parts = []
    for line in str(value).splitlines():
        parts.append(_osascript_literal(line))
    return " & return & ".join(parts)


def _run_osascript(lines: list[str]) -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "macOS required"
    args = ["osascript"]
    for line in lines:
        args.extend(["-e", line])
    try:
        with OSASCRIPT_LOCK:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=OSASCRIPT_TIMEOUT,
            )
    except subprocess.TimeoutExpired:
        return False, "AppleScript timed out."
    except Exception as exc:
        return False, f"AppleScript failed: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, (result.stdout or "").strip()


def _tool_macos_script(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    script = str(args.get("script", "")).strip()
    if not script:
        return "Provide an AppleScript snippet to run."
    lines = [line for line in script.splitlines() if line.strip()]
    if not lines:
        return "Provide an AppleScript snippet to run."
    ok, output = _run_osascript(lines)
    if ok:
        return output or "AppleScript executed."
    return f"AppleScript failed: {output}"


def _create_mail_draft_apple_mail(
    to_list: list[str],
    cc_list: list[str],
    bcc_list: list[str],
    subject: str,
    body: str,
) -> tuple[bool, str] | None:
    if sys.platform != "darwin":
        return None
    subject_text = _osascript_literal(subject or "")
    body_text = _osascript_text_block(body or "")
    lines = [
        'tell application "Mail"',
        f"set messageContent to {body_text}",
        (
            "set newMessage to make new outgoing message "
            f'with properties {{subject:{subject_text}, content:messageContent, visible:true}}'
        ),
        "tell newMessage",
    ]
    for addr in to_list:
        lines.append(
            f"make new to recipient at end of to recipients "
            f"with properties {{address:{_osascript_literal(addr)}}}"
        )
    for addr in cc_list:
        lines.append(
            f"make new cc recipient at end of cc recipients "
            f"with properties {{address:{_osascript_literal(addr)}}}"
        )
    for addr in bcc_list:
        lines.append(
            f"make new bcc recipient at end of bcc recipients "
            f"with properties {{address:{_osascript_literal(addr)}}}"
        )
    lines.extend(
        [
            "end tell",
            "activate",
            "end tell",
        ]
    )
    return _run_osascript(lines)


def _parse_datetime(value: str, tz: ZoneInfo) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _ical_escape(value: str) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("\n", "\\n")
    text = text.replace(",", "\\,").replace(";", "\\;")
    return text


def _tool_calendar_event(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    title = str(args.get("title") or "").strip()
    if not title:
        return "Provide a title for the event."
    tz_name = str(args.get("timezone") or settings.app_timezone or "UTC").strip()
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
        tz_name = "UTC"

    all_day = bool(args.get("all_day"))
    start_raw = args.get("start")
    end_raw = args.get("end")
    duration = args.get("duration_minutes")
    calendar_name = str(args.get("calendar") or "").strip()
    if not calendar_name:
        calendar_name = str(db.get_setting("default_calendar") or "").strip()
    location = str(args.get("location") or "").strip()
    description = str(args.get("description") or "").strip()

    ics_lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Jacques//Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uuid4()}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_ical_escape(title)}",
    ]

    if all_day:
        start_date = _parse_date(str(start_raw)) or _parse_date(str(title))
        if not start_date:
            return "Provide a start date for the all-day event (YYYY-MM-DD)."
        end_date = _parse_date(str(end_raw)) if end_raw else start_date + timedelta(days=1)
        if end_date <= start_date:
            end_date = start_date + timedelta(days=1)
        ics_lines.append(f"DTSTART;VALUE=DATE:{start_date.strftime('%Y%m%d')}")
        ics_lines.append(f"DTEND;VALUE=DATE:{end_date.strftime('%Y%m%d')}")
    else:
        start_dt = _parse_datetime(str(start_raw), tz)
        if not start_dt:
            return "Provide a valid start datetime (ISO 8601)."
        if end_raw:
            end_dt = _parse_datetime(str(end_raw), tz)
        else:
            minutes = int(duration) if isinstance(duration, int) and duration > 0 else 60
            end_dt = start_dt + timedelta(minutes=minutes)
        if not end_dt:
            return "Provide a valid end datetime (ISO 8601)."
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=30)
        ics_lines.append(
            f"DTSTART;TZID={tz_name}:{start_dt.astimezone(tz).strftime('%Y%m%dT%H%M%S')}"
        )
        ics_lines.append(
            f"DTEND;TZID={tz_name}:{end_dt.astimezone(tz).strftime('%Y%m%dT%H%M%S')}"
        )

    if location:
        ics_lines.append(f"LOCATION:{_ical_escape(location)}")
    if description:
        ics_lines.append(f"DESCRIPTION:{_ical_escape(description)}")
    ics_lines.append("END:VEVENT")
    ics_lines.append("END:VCALENDAR")

    stem = safe_filename(title.lower().replace(" ", "_")) or "event"
    filename = f"{stem}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.ics"
    path = GENERATED_DIR / filename
    path.write_text("\n".join(ics_lines), encoding="utf-8")

    url = f"/files/generated/{filename}"
    status_line = "Calendar event ready."
    apple_result = _create_calendar_event_apple_calendar(
        title=title,
        start_raw=str(start_raw),
        end_raw=str(end_raw) if end_raw else "",
        all_day=all_day,
        tz=tz,
        calendar_name=calendar_name,
        location=location,
        description=description,
    )
    if apple_result is not None:
        ok, message = apple_result
        if ok:
            status_line = f"Apple Calendar event created (id {message or 'ok'})."
        else:
            status_line = f"Apple Calendar automation failed: {message}"

    return (
        f"{status_line}\n"
        f"Title: {title}\n"
        f"Start: {start_raw}\n"
        f"End: {end_raw or ''}\n"
        f"Calendar: {calendar_name or 'default writable'}\n"
        f"ICS: {url}"
    )


def _create_calendar_event_apple_calendar(
    title: str,
    start_raw: str,
    end_raw: str,
    all_day: bool,
    tz: ZoneInfo,
    calendar_name: str,
    location: str,
    description: str,
) -> tuple[bool, str] | None:
    if sys.platform != "darwin":
        return None
    start_dt = _parse_datetime(start_raw, tz) if start_raw else None
    end_dt = _parse_datetime(end_raw, tz) if end_raw else None
    if all_day:
        start_date = _parse_date(start_raw)
        if not start_date:
            return False, "Invalid start date"
        if not end_dt:
            end_date = _parse_date(end_raw) if end_raw else start_date + timedelta(days=1)
        else:
            end_date = end_dt.date()
        if end_date <= start_date:
            end_date = start_date + timedelta(days=1)
        start_dt = datetime.combine(start_date, datetime.min.time(), tz)
        end_dt = datetime.combine(end_date, datetime.min.time(), tz)
    else:
        if not start_dt:
            return False, "Invalid start datetime"
        if not end_dt:
            end_dt = start_dt + timedelta(minutes=60)
    start_str = start_dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        'tell application "Calendar"',
        "activate",
        "if (count of calendars) is 0 then error \"No calendars available\"",
        f"set calendarName to {_osascript_literal(calendar_name)}",
        "set targetCal to missing value",
        "if calendarName is not \"\" then",
        "set targetCals to calendars whose name is calendarName and writable is true",
        "if (count of targetCals) is 0 then error \"No writable calendar named \" & calendarName",
        "set targetCal to item 1 of targetCals",
        "else",
        "set targetCals to calendars whose writable is true",
        "if (count of targetCals) is 0 then error \"No writable calendars available\"",
        "set targetCal to item 1 of targetCals",
        "end if",
        "try",
        "set visible of targetCal to true",
        "end try",
        (
            "set newEvent to make new event at end of events of targetCal "
            f"with properties {{summary:{_osascript_literal(title)}, "
            f"start date:date {_osascript_literal(start_str)}, "
            f"end date:date {_osascript_literal(end_str)}, "
            f"location:{_osascript_literal(location)}, "
            f"description:{_osascript_literal(description)}, "
            f"allday event:{'true' if all_day else 'false'}}}"
        ),
        "return id of newEvent",
        "end tell",
    ]
    return _run_osascript(lines)


def _tool_calendar_list(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    if sys.platform != "darwin":
        return "Apple Calendar listing requires macOS."
    script_lines = [
        "set outputLines to {}",
        'tell application "Calendar"',
        "repeat with cal in calendars",
        "set lineText to (name of cal as string) & \"||\" & (writable of cal as string)",
        "copy lineText to end of outputLines",
        "end repeat",
        "end tell",
        "set text item delimiters to \"\\n\"",
        "return outputLines as string",
    ]
    ok, output = _run_osascript(script_lines)
    if not ok:
        return f"Calendar list failed: {output}"
    output = output.strip()
    if not output:
        return "No calendars found."
    lines = []
    for line in output.splitlines():
        parts = line.split("||")
        name = parts[0].strip() if parts else "Unknown"
        writable = parts[1].strip() if len(parts) > 1 else "false"
        lines.append(f"- {name} (writable: {writable})")
    return "Calendars:\n" + "\n".join(lines)


def _tool_calendar_find(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    if sys.platform != "darwin":
        return "Apple Calendar search requires macOS."
    title = str(args.get("title") or "").strip()
    calendar_name = str(args.get("calendar") or "").strip()
    if not calendar_name:
        calendar_name = str(db.get_setting("default_calendar") or "").strip()
    limit = args.get("limit")
    max_results = int(limit) if isinstance(limit, int) and limit > 0 else 20
    tz_name = settings.app_timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
        tz_name = "UTC"
    start_raw = str(args.get("start") or "").strip()
    end_raw = str(args.get("end") or "").strip()
    now = datetime.now(tz)
    start_dt = _parse_datetime(start_raw, tz) if start_raw else now - timedelta(days=1)
    end_dt = _parse_datetime(end_raw, tz) if end_raw else now + timedelta(days=30)
    if not start_dt or not end_dt:
        return "Provide valid start/end dates (ISO 8601)."
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    script_lines = [
        f"set calendarName to {_osascript_literal(calendar_name)}",
        f"set titleQuery to {_osascript_literal(title)}",
        f"set maxResults to {max_results}",
        f"set startDate to date {_osascript_literal(start_str)}",
        f"set endDate to date {_osascript_literal(end_str)}",
        "set outputLines to {}",
        'tell application "Calendar"',
        "set targetCals to calendars",
        "if calendarName is not \"\" then",
        "set targetCals to calendars whose name is calendarName",
        "end if",
        "repeat with cal in targetCals",
        "if titleQuery is not \"\" then",
        "set matches to every event of cal whose start date is greater than startDate and start date is less than endDate and summary contains titleQuery",
        "else",
        "set matches to every event of cal whose start date is greater than startDate and start date is less than endDate",
        "end if",
        "repeat with ev in matches",
        "set summaryText to summary of ev as string",
        "set shouldInclude to true",
        "if titleQuery is not \"\" then",
        "if summaryText does not contain titleQuery then",
        "set shouldInclude to false",
        "end if",
        "end if",
        "if shouldInclude then",
        "set lineText to (id of ev as string) & \"||\" & summaryText & \"||\" & (start date of ev as string) & \"||\" & (end date of ev as string) & \"||\" & (name of cal as string)",
        "copy lineText to end of outputLines",
        "if (count of outputLines) >= maxResults then exit repeat",
        "end if",
        "end repeat",
        "if (count of outputLines) >= maxResults then exit repeat",
        "end repeat",
        "end tell",
        "set text item delimiters to \"\\n\"",
        "return outputLines as string",
    ]
    ok, output = _run_osascript(script_lines)
    if not ok:
        return f"Calendar search failed: {output}"
    output = output.strip()
    if not output:
        return "No matching events found."
    lines = []
    for line in output.splitlines():
        parts = line.split("||")
        if len(parts) < 5:
            continue
        event_id, summary, start_text, end_text, cal_name = parts[:5]
        lines.append(f"- id {event_id} | {summary} | {start_text} -> {end_text} | {cal_name}")
    return "Events:\n" + "\n".join(lines)


def _tool_task_schedule(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    cron = str(args.get("cron", "")).strip()
    if not cron:
        return "Provide a cron schedule (min hour day month dow)."
    name = str(args.get("name") or "").strip()
    task_type = str(args.get("task_type") or "web_digest").strip()
    if task_type not in {"web_digest", "reminder"}:
        return "Unsupported task type."
    timezone = str(args.get("timezone") or settings.app_timezone or "UTC").strip()
    payload: dict[str, Any] = {}
    if task_type == "web_digest":
        query = str(args.get("query") or "").strip()
        if not query and not name:
            return "Provide a query for the web digest."
        if not name:
            name = f"Digest: {query}"
        limit = args.get("limit")
        use_llm = args.get("use_llm", True)
        payload = {
            "query": query or name,
            "limit": int(limit) if isinstance(limit, int) and limit > 0 else 5,
            "use_llm": bool(use_llm),
        }
    else:
        message = str(
            args.get("message") or args.get("query") or args.get("name") or ""
        ).strip()
        if not message:
            return "Provide a reminder message."
        if not name:
            name = f"Reminder: {message}"
        payload = {"message": message}
    enabled = args.get("enabled", True)
    task_id = db.add_scheduled_task(
        conversation_id=conversation_id,
        name=name,
        task_type=task_type,
        payload=json.dumps(payload, ensure_ascii=True),
        cron=cron,
        timezone=timezone,
        enabled=bool(enabled),
    )
    if enabled:
        task_scheduler.schedule_task_by_id(task_id, settings)
    return (
        f"Task scheduled (id {task_id}): {name} | cron `{cron}` | "
        f"tz `{timezone}`"
    )


def _tool_task_list(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    tasks = db.list_scheduled_tasks(conversation_id)
    if not tasks:
        return "No scheduled tasks."
    lines = []
    for task in tasks:
        status = "enabled" if task["enabled"] else "disabled"
        last_run = task["last_run"] or "-"
        last_status = task["last_status"] or "-"
        lines.append(
            f"- {task['id']}: {task['name']} | {task['task_type']} | "
            f"cron `{task['cron']}` | tz `{task['timezone']}` | {status} | "
            f"last_run {last_run} | {last_status}"
        )
    return "Scheduled tasks:\n" + "\n".join(lines)


def _tool_task_delete(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    task_id = args.get("task_id")
    if not isinstance(task_id, int):
        return "Provide a valid task_id."
    task = db.get_scheduled_task(task_id)
    if not task or int(task["conversation_id"]) != int(conversation_id):
        return "Task not found."
    db.delete_scheduled_task(task_id)
    task_scheduler.remove_task(task_id)
    return f"Task {task_id} deleted."


def _tool_task_enable(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    task_id = args.get("task_id")
    enabled = args.get("enabled")
    if not isinstance(task_id, int):
        return "Provide a valid task_id."
    if not isinstance(enabled, bool):
        return "Provide enabled=true or false."
    task = db.get_scheduled_task(task_id)
    if not task or int(task["conversation_id"]) != int(conversation_id):
        return "Task not found."
    db.set_scheduled_task_enabled(task_id, enabled)
    if enabled:
        task_scheduler.schedule_task_by_id(task_id, settings)
    else:
        task_scheduler.remove_task(task_id)
    state = "enabled" if enabled else "disabled"
    return f"Task {task_id} {state}."


def _tool_mail_search(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    if sys.platform != "darwin":
        return "Apple Mail search requires macOS."
    query = str(args.get("query") or "").strip()
    account = str(args.get("account") or "").strip()
    mailbox = str(args.get("mailbox") or "").strip()
    if not account:
        account = str(db.get_setting("default_mail_account") or "").strip()
    if not mailbox:
        mailbox = str(db.get_setting("default_mailbox") or "").strip()
    limit = args.get("limit")
    limit_value = int(limit) if isinstance(limit, int) and limit > 0 else 20
    since_days = args.get("since_days")
    use_cutoff = isinstance(since_days, int) and since_days > 0
    if limit is None and use_cutoff:
        limit_value = 50
    search_body = bool(args.get("search_body"))
    only_inbox_value = args.get("only_inbox")
    if only_inbox_value is None:
        only_inbox = bool(use_cutoff and not mailbox)
    else:
        only_inbox = bool(only_inbox_value)

    per_mailbox_limit = min(limit_value, 50)
    script_lines = [
        f"set maxResults to {limit_value}",
        f"set perMailboxLimit to {per_mailbox_limit}",
        f"set searchQuery to {_osascript_literal(query)}",
        f"set accountName to {_osascript_literal(account)}",
        f"set mailboxName to {_osascript_literal(mailbox)}",
        f"set useCutoff to {str(use_cutoff).lower()}",
        f"set searchBody to {str(search_body).lower()}",
        f"set onlyInbox to {str(only_inbox).lower()}",
        "set epochBase to date \"Thursday, January 1, 1970 00:00:00\"",
    ]
    if use_cutoff:
        script_lines.append(f"set cutoffDate to (current date) - ({since_days} * days)")
    script_lines.extend(
        [
            "set outputLines to {}",
            'tell application "Mail"',
            "set targetAccounts to every account",
            "if accountName is not \"\" then",
            "set targetAccounts to (every account whose name is accountName)",
            "if (count of targetAccounts) is 0 then",
            "set targetAccounts to every account",
            "end if",
            "end if",
            "repeat with acc in targetAccounts",
            "set targetMailboxes to mailboxes of acc",
            "if mailboxName is not \"\" then",
            "set targetMailboxes to (mailboxes of acc whose name is mailboxName)",
            "if (count of targetMailboxes) is 0 then",
            "set targetMailboxes to mailboxes of acc",
            "end if",
            "else if onlyInbox then",
            "set targetMailboxes to (mailboxes of acc whose name is \"Inbox\")",
            "if (count of targetMailboxes) is 0 then",
            "set targetMailboxes to (mailboxes of acc whose name is \"INBOX\")",
            "end if",
            "if (count of targetMailboxes) is 0 then",
            "set targetMailboxes to (mailboxes of acc whose name is \"Boite de reception\")",
            "end if",
            "if (count of targetMailboxes) is 0 then",
            "set targetMailboxes to mailboxes of acc",
            "end if",
            "end if",
            "repeat with mbox in targetMailboxes",
            "set mailboxCount to 0",
            "set theMessages to {}",
            "if useCutoff then",
            "if searchQuery is not \"\" then",
            "if searchBody then",
            "set theMessages to (every message of mbox whose date received is greater than cutoffDate and (subject contains searchQuery or sender contains searchQuery or content contains searchQuery))",
            "else",
            "set theMessages to (every message of mbox whose date received is greater than cutoffDate and (subject contains searchQuery or sender contains searchQuery))",
            "end if",
            "else",
            "set theMessages to (every message of mbox whose date received is greater than cutoffDate)",
            "end if",
            "else",
            "if searchQuery is not \"\" then",
            "if searchBody then",
            "set theMessages to (every message of mbox whose subject contains searchQuery or sender contains searchQuery or content contains searchQuery)",
            "else",
            "set theMessages to (every message of mbox whose subject contains searchQuery or sender contains searchQuery)",
            "end if",
            "else",
            "set theMessages to (messages of mbox)",
            "end if",
            "end if",
            "repeat with msg in theMessages",
            "set mailboxCount to mailboxCount + 1",
            "if mailboxCount > perMailboxLimit then exit repeat",
            "set mailId to id of msg as string",
            "set msgId to \"\"",
            "try",
            "set msgId to message id of msg as string",
            "end try",
            "set subjectText to subject of msg as string",
            "set senderText to sender of msg as string",
            "set dateText to date received of msg as string",
            "set mailboxText to name of mbox as string",
            "set accountText to name of acc as string",
            "set epochSeconds to (date received of msg) - epochBase",
            "set lineText to (epochSeconds as string) & \"||\" & mailId & \"||\" & msgId & \"||\" & subjectText & \"||\" & senderText & \"||\" & dateText & \"||\" & mailboxText & \"||\" & accountText",
            "copy lineText to end of outputLines",
            "end repeat",
            "end repeat",
            "end repeat",
            "end tell",
            "set text item delimiters to \"\\n\"",
            "return outputLines as string",
        ]
    )
    ok, output = _run_osascript(script_lines)
    if not ok:
        return f"Mail search failed: {output}"
    output = output.strip()
    if not output:
        return "No matching emails."
    lines = output.splitlines()
    parsed: list[dict[str, Any]] = []
    for line in lines:
        parts = line.split("||")
        if len(parts) < 8:
            continue
        epoch_text, mail_id, message_id, subject, sender, date_text, mailbox_name, account_name = parts[:8]
        try:
            epoch_value = float(epoch_text)
        except ValueError:
            epoch_value = 0.0
        parsed.append(
            {
                "epoch": epoch_value,
                "mail_id": mail_id,
                "message_id": message_id,
                "subject": subject,
                "sender": sender,
                "date_text": date_text,
                "mailbox": mailbox_name,
                "account": account_name,
            }
        )
    if not parsed:
        return "No matching emails."
    parsed.sort(key=lambda item: item["epoch"], reverse=True)
    rendered = []
    for item in parsed[:limit_value]:
        rendered.append(
            f"- id {item['mail_id']} | msgid {item['message_id'] or '-'} | "
            f"{item['subject']} | {item['sender']} | {item['date_text']} | "
            f"{item['account']}/{item['mailbox']}"
        )
    return "Mail results:\n" + "\n".join(rendered) if rendered else "No matching emails."


def _tool_mail_read(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    if sys.platform != "darwin":
        return "Apple Mail read requires macOS."
    mail_id = args.get("mail_id")
    message_id = str(args.get("message_id") or "").strip()
    account = str(args.get("account") or "").strip()
    mailbox = str(args.get("mailbox") or "").strip()
    if not account:
        account = str(db.get_setting("default_mail_account") or "").strip()
    if not mailbox:
        mailbox = str(db.get_setting("default_mailbox") or "").strip()
    max_chars = args.get("max_chars")
    max_chars_value = int(max_chars) if isinstance(max_chars, int) and max_chars > 0 else 4000
    if not isinstance(mail_id, int) and not message_id:
        return "Provide mail_id or message_id."

    script_lines = [
        f"set mailId to {_osascript_literal(str(mail_id) if isinstance(mail_id, int) else '')}",
        f"set messageId to {_osascript_literal(message_id)}",
        f"set accountName to {_osascript_literal(account)}",
        f"set mailboxName to {_osascript_literal(mailbox)}",
        "set foundMessage to missing value",
        'tell application "Mail"',
        "set targetAccounts to every account",
        "if accountName is not \"\" then",
        "set targetAccounts to (every account whose name is accountName)",
        "if (count of targetAccounts) is 0 then",
        "set targetAccounts to every account",
        "end if",
        "end if",
        "repeat with acc in targetAccounts",
        "set targetMailboxes to mailboxes of acc",
        "if mailboxName is not \"\" then",
        "set targetMailboxes to (mailboxes of acc whose name is mailboxName)",
        "if (count of targetMailboxes) is 0 then",
        "set targetMailboxes to mailboxes of acc",
        "end if",
        "end if",
        "repeat with mbox in targetMailboxes",
        "if foundMessage is not missing value then exit repeat",
        "try",
        "if mailId is not \"\" then",
        "set foundMessage to first message of mbox whose id is (mailId as number)",
        "else if messageId is not \"\" then",
        "set foundMessage to first message of mbox whose message id is messageId",
        "end if",
        "end try",
        "end repeat",
        "end repeat",
        "if foundMessage is missing value then return \"\"",
        "set subjectText to subject of foundMessage as string",
        "set senderText to sender of foundMessage as string",
        "set dateText to date received of foundMessage as string",
        "set bodyText to content of foundMessage as string",
        "return subjectText & \"||\" & senderText & \"||\" & dateText & \"||\" & bodyText",
        "end tell",
    ]
    ok, output = _run_osascript(script_lines)
    if not ok:
        return f"Mail read failed: {output}"
    if not output:
        return "Email not found."
    parts = output.split("||", 3)
    if len(parts) < 4:
        return "Email read failed: malformed response."
    subject, sender, date_text, body = parts
    body = body.strip()
    if len(body) > max_chars_value:
        body = body[:max_chars_value].rsplit(" ", 1)[0] + "..."
    return (
        "Email:\n"
        f"Subject: {subject}\n"
        f"From: {sender}\n"
        f"Date: {date_text}\n\n"
        f"{body}"
    )


def _tool_mail_reply(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    if sys.platform != "darwin":
        return "Apple Mail reply requires macOS."
    mail_id = args.get("mail_id")
    message_id = str(args.get("message_id") or "").strip()
    account = str(args.get("account") or "").strip()
    mailbox = str(args.get("mailbox") or "").strip()
    body = str(args.get("body") or "").strip()
    if not account:
        account = str(db.get_setting("default_mail_account") or "").strip()
    if not mailbox:
        mailbox = str(db.get_setting("default_mailbox") or "").strip()
    if not isinstance(mail_id, int) and not message_id:
        return "Provide mail_id or message_id."

    subject_text = _osascript_literal("")
    body_text = _osascript_text_block(body or "")
    script_lines = [
        f"set mailId to {_osascript_literal(str(mail_id) if isinstance(mail_id, int) else '')}",
        f"set messageId to {_osascript_literal(message_id)}",
        f"set accountName to {_osascript_literal(account)}",
        f"set mailboxName to {_osascript_literal(mailbox)}",
        f"set messageContent to {body_text}",
        "set foundMessage to missing value",
        'tell application "Mail"',
        "set targetAccounts to every account",
        "if accountName is not \"\" then",
        "set targetAccounts to (every account whose name is accountName)",
        "if (count of targetAccounts) is 0 then",
        "set targetAccounts to every account",
        "end if",
        "end if",
        "repeat with acc in targetAccounts",
        "set targetMailboxes to mailboxes of acc",
        "if mailboxName is not \"\" then",
        "set targetMailboxes to (mailboxes of acc whose name is mailboxName)",
        "if (count of targetMailboxes) is 0 then",
        "set targetMailboxes to mailboxes of acc",
        "end if",
        "end if",
        "repeat with mbox in targetMailboxes",
        "if foundMessage is not missing value then exit repeat",
        "try",
        "if mailId is not \"\" then",
        "set foundMessage to first message of mbox whose id is (mailId as number)",
        "else if messageId is not \"\" then",
        "set foundMessage to first message of mbox whose message id is messageId",
        "end if",
        "end try",
        "end repeat",
        "end repeat",
        "if foundMessage is missing value then return \"\"",
        "set replyMessage to reply foundMessage with opening window",
        "if messageContent is not \"\" then",
        "set content of replyMessage to messageContent & return & return & content of replyMessage",
        "end if",
        "activate",
        "return \"OK\"",
        "end tell",
    ]
    ok, output = _run_osascript(script_lines)
    if not ok:
        return f"Apple Mail reply failed: {output}"
    if not output:
        return "Email not found."
    return "Apple Mail reply draft created."


def _resolve_project_path(path_value: str | None) -> Path:
    root = BASE_DIR.resolve()
    candidate = (root / (path_value or "")).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    raise ValueError("Path is outside the project root.")


def _tool_project_list_files(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    path_value = str(args.get("path") or ".")
    pattern = str(args.get("pattern") or "").strip()
    recursive = bool(args.get("recursive"))
    include_hidden = bool(args.get("include_hidden"))
    limit = args.get("max")
    max_value = int(limit) if isinstance(limit, int) and limit > 0 else 200
    try:
        base = _resolve_project_path(path_value)
    except ValueError as exc:
        return str(exc)
    if not base.exists():
        return "Path not found."
    entries = []
    if pattern:
        iterator = base.rglob(pattern) if recursive else base.glob(pattern)
    else:
        iterator = base.rglob("*") if recursive else base.iterdir()
    for entry in iterator:
        if not include_hidden:
            if any(part.startswith(".") for part in entry.relative_to(base).parts):
                continue
        rel = entry.relative_to(BASE_DIR).as_posix()
        entries.append(rel + ("/" if entry.is_dir() else ""))
        if len(entries) >= max_value:
            break
    if not entries:
        return "No files found."
    return "Project files:\n" + "\n".join(f"- {item}" for item in entries)


def _tool_project_read_file(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    path_value = str(args.get("path") or "").strip()
    if not path_value:
        return "Provide a file path."
    try:
        path = _resolve_project_path(path_value)
    except ValueError as exc:
        return str(exc)
    if not path.exists() or not path.is_file():
        return "File not found."
    max_chars = args.get("max_chars")
    max_value = int(max_chars) if isinstance(max_chars, int) and max_chars > 0 else 4000
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Read failed: {exc}"
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    if isinstance(start_line, int) or isinstance(end_line, int):
        lines = content.splitlines()
        start = max((start_line or 1) - 1, 0)
        end = min(end_line or len(lines), len(lines))
        content = "\n".join(lines[start:end])
    if len(content) > max_value:
        content = content[:max_value].rsplit(" ", 1)[0] + "..."
    return f"File: {path_value}\n\n{content}"


def _tool_project_search(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "Provide a search query."
    path_value = str(args.get("path") or ".")
    include_hidden = bool(args.get("include_hidden"))
    max_results = args.get("max_results")
    max_value = int(max_results) if isinstance(max_results, int) and max_results > 0 else 40
    try:
        base = _resolve_project_path(path_value)
    except ValueError as exc:
        return str(exc)
    if not base.exists():
        return "Path not found."
    results = []
    for entry in base.rglob("*"):
        if entry.is_dir():
            continue
        if not include_hidden and any(part.startswith(".") for part in entry.relative_to(base).parts):
            continue
        try:
            raw = entry.read_bytes()
        except Exception:
            continue
        if b"\x00" in raw[:1024]:
            continue
        text = raw.decode("utf-8", errors="ignore")
        if query not in text:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if query in line:
                rel = entry.relative_to(BASE_DIR).as_posix()
                snippet = line.strip()
                results.append(f"- {rel}:{idx} {snippet}")
                if len(results) >= max_value:
                    break
        if len(results) >= max_value:
            break
    if not results:
        return "No matches found."
    return "Search results:\n" + "\n".join(results)


def _tool_project_replace(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    path_value = str(args.get("path") or "").strip()
    old_text = str(args.get("old_text") or "")
    new_text = str(args.get("new_text") or "")
    if not path_value or not old_text:
        return "Provide path and old_text."
    try:
        path = _resolve_project_path(path_value)
    except ValueError as exc:
        return str(exc)
    if not path.exists() or not path.is_file():
        return "File not found."
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Read failed: {exc}"
    if old_text not in content:
        return "Text not found."
    count = args.get("count")
    replace_count = int(count) if isinstance(count, int) and count > 0 else -1
    updated = (
        content.replace(old_text, new_text, replace_count)
        if replace_count > 0
        else content.replace(old_text, new_text)
    )
    path.write_text(updated, encoding="utf-8")
    replaced = content.count(old_text) if replace_count < 0 else min(content.count(old_text), replace_count)
    return f"Replaced {replaced} occurrence(s) in {path_value}."


def _tool_python_run(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    code = str(args.get("code") or "").strip()
    path_value = str(args.get("path") or "").strip()
    if not code and not path_value:
        return "Provide code or a script path."
    if code and path_value:
        return "Provide either code or path, not both."

    timeout = args.get("timeout")
    timeout_value = int(timeout) if isinstance(timeout, int) and timeout > 0 else 15
    timeout_value = min(timeout_value, 60)

    extra_args = args.get("args") or []
    if not isinstance(extra_args, list):
        extra_args = [extra_args]
    extra_args = [str(item) for item in extra_args if str(item).strip()]
    stdin_text = str(args.get("stdin") or "")

    generated_dir = GENERATED_DIR
    generated_dir.mkdir(parents=True, exist_ok=True)
    before_images = _snapshot_images(generated_dir)
    before_files = _snapshot_files(DATA_DIR)
    start_time = time.time()

    env = os.environ.copy()
    env["JACQUES_DATA_DIR"] = str(DATA_DIR)
    env["JACQUES_GENERATED_DIR"] = str(GENERATED_DIR)
    env["JACQUES_EXPORTS_DIR"] = str(EXPORTS_DIR)
    env["JACQUES_UPLOADS_DIR"] = str(UPLOADS_DIR)

    if code:
        cmd = [sys.executable, "-c", code]
    else:
        try:
            script_path = _resolve_project_path(path_value)
        except ValueError as exc:
            return str(exc)
        if not script_path.exists() or not script_path.is_file():
            return "Python file not found."
        if script_path.suffix.lower() != ".py":
            return "Script must be a .py file."
        cmd = [sys.executable, str(script_path)]

    cmd.extend(extra_args)
    try:
        result = subprocess.run(
            cmd,
            input=stdin_text if stdin_text else None,
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            timeout=timeout_value,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Python run timed out after {timeout_value}s."
    except Exception as exc:
        return f"Python run failed: {exc}"

    output = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    combined = output
    if err:
        combined = f"{combined}\n\nstderr:\n{err}".strip() if combined else f"stderr:\n{err}"

    extracted = _extract_data_uri_image(combined)
    if extracted:
        mime, payload, uri = extracted
        ext = "png" if mime == "png" else "jpg" if mime in {"jpg", "jpeg"} else "webp"
        filename = (
            f"python_image_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.{ext}"
        )
        path = GENERATED_DIR / filename
        try:
            path.write_bytes(payload)
            combined = combined.replace(uri, f"[image saved: {filename}]")
        except Exception:
            pass

    if not combined:
        combined = "(no output)"
    if len(combined) > 6000:
        combined = combined[:6000].rsplit(" ", 1)[0] + "..."

    new_images = _detect_new_images(generated_dir, before_images, start_time)
    image_blocks: list[str] = []
    for path in new_images:
        filename = path.name
        try:
            db.add_image(
                conversation_id,
                filename,
                str(path),
                "Generated by python",
            )
        except Exception:
            pass
        url = f"/files/generated/{filename}"
        image_blocks.append(f"![{filename}]({url})")
    if image_blocks:
        combined = f"{combined}\n\n" + "\n".join(image_blocks)

    new_files = _detect_new_files(DATA_DIR, before_files, start_time)
    generated_files: list[Path] = []
    for path in new_files:
        if _should_skip_generated_file(path):
            continue
        if GENERATED_DIR in path.parents or path.parent == GENERATED_DIR:
            generated_files.append(path)
            continue
        target_name = safe_filename(path.name) or path.name
        target_path = GENERATED_DIR / target_name
        if target_path.exists():
            stem = target_path.stem
            target_path = GENERATED_DIR / (
                f"{stem}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{target_path.suffix}"
            )
        try:
            path.replace(target_path)
            generated_files.append(target_path)
        except Exception:
            continue

    if generated_files:
        lines = ["Generated files:"]
        for path in generated_files:
            lines.append(f"- {path.resolve()}")
        combined = f"{combined}\n\n" + "\n".join(lines)

    status = "ok" if result.returncode == 0 else f"exit {result.returncode}"
    return f"Python run {status}.\n\n{combined}"


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
    limit = args.get("limit")
    country = str(args.get("country") or "").strip() or None
    search_lang = str(args.get("search_lang") or "").strip() or None
    freshness = str(args.get("freshness") or "").strip() or None
    result_filter = str(args.get("result_filter") or "").strip() or None
    results = web_search.search(
        query,
        settings,
        limit=int(limit) if isinstance(limit, int) and limit > 0 else 5,
        country=country,
        search_lang=search_lang,
        freshness=freshness,
        result_filter=result_filter,
    )
    summary = web_search.summarize_results(results)
    return summary or "No results."


def _tool_news_search(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "Provide a query for news search."
    limit = args.get("limit")
    country = str(args.get("country") or "").strip() or None
    search_lang = str(args.get("search_lang") or "").strip() or None
    freshness = str(args.get("freshness") or "").strip() or None
    results = web_search.news_search(
        query,
        settings,
        limit=int(limit) if isinstance(limit, int) and limit > 0 else 5,
        country=country,
        search_lang=search_lang,
        freshness=freshness,
    )
    summary = web_search.summarize_results(results)
    return summary or "No results."


def _tool_web_fetch(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    url = str(args.get("url", "")).strip()
    if not url:
        return "Provide a URL to fetch."
    selector = str(args.get("selector") or "").strip() or None
    max_chars = args.get("max_chars")
    max_value = int(max_chars) if isinstance(max_chars, int) and max_chars > 0 else 1200
    content = web_search.fetch_url(
        url,
        settings,
        selector=selector,
        max_chars=max_value,
    )
    return content


def _tool_stock_history(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    symbol = str(args.get("symbol", "")).strip()
    start_date = str(args.get("start_date", "")).strip()
    raw_end = args.get("end_date")
    end_date = None if raw_end is None else str(raw_end).strip() or None
    if not symbol or not start_date:
        return "Provide symbol and start_date (YYYY-MM-DD)."

    max_points = args.get("max_points")
    if not isinstance(max_points, int) or max_points <= 0:
        max_points = 400

    filename = safe_filename(args.get("filename", ""))
    if filename and not Path(filename).suffix:
        filename = f"{filename}.csv"

    try:
        data = market_data.fetch_stooq_history(
            symbol=symbol,
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
        return "No data returned for this symbol."

    csv_path = ""
    if filename:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = EXPORTS_DIR / filename
        if path.exists():
            stem = path.stem
            filename = f"{stem}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{path.suffix}"
            path = EXPORTS_DIR / filename
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "open", "high", "low", "close", "volume"])
            for row in data:
                writer.writerow(
                    [
                        row.get("date"),
                        row.get("open"),
                        row.get("high"),
                        row.get("low"),
                        row.get("close"),
                        row.get("volume"),
                    ]
                )
        csv_path = str(path)

    payload = {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "points": data,
        "csv_path": csv_path or None,
    }
    return json.dumps(payload, ensure_ascii=True)


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


def _tool_excel_read_sheet(args: dict[str, Any], settings: Settings, conversation_id: int) -> str:
    filename = safe_filename(args.get("filename", "")).strip()
    if not filename:
        return "Provide an Excel filename."
    if not Path(filename).suffix:
        filename = f"{filename}.xlsx"
    document_id = args.get("document_id")
    sheet_name = args.get("sheet_name")
    max_rows = args.get("max_rows")
    max_cols = args.get("max_cols")
    max_rows_value = int(max_rows) if isinstance(max_rows, int) and max_rows > 0 else 25
    max_cols_value = int(max_cols) if isinstance(max_cols, int) and max_cols > 0 else 16

    doc = None
    if isinstance(document_id, int):
        doc = db.get_document_by_id(document_id)
    if doc is None:
        doc = db.get_document_by_name(conversation_id, filename)
    if doc is None:
        for row in db.list_documents(conversation_id):
            if str(row["name"]).lower() == filename.lower():
                doc = db.get_document_by_id(int(row["id"]))
                break
    if not doc:
        return "Excel file not found in this conversation."

    path = Path(doc["path"])
    if not path.exists():
        return "Excel file path not found."

    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required to read Excel files") from exc

    if sheet_name is None or str(sheet_name).strip() == "":
        try:
            xls = pd.ExcelFile(path)
        except Exception as exc:
            return f"Failed to read workbook: {exc}"
        sheets = ", ".join(xls.sheet_names) if xls.sheet_names else "-"
        return f"Available sheets in {filename}: {sheets}"

    try:
        df = pd.read_excel(path, sheet_name=sheet_name)
    except ValueError as exc:
        return f"Sheet not found: {exc}"
    except Exception as exc:
        return f"Failed to read sheet: {exc}"

    if df.empty:
        return f"Sheet {sheet_name} is empty."

    preview = df.iloc[:max_rows_value, :max_cols_value]
    csv_preview = preview.to_csv(index=False)
    return (
        f"Sheet '{sheet_name}' from {filename} "
        f"(showing {len(preview)} rows, {len(preview.columns)} cols):\n"
        f"```csv\n{csv_preview.strip()}\n```"
    )


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
        filename = f"{stem}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{path.suffix}"
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
