from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta, date
from urllib.parse import urlencode, quote
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo
from uuid import uuid4
import subprocess
import sys

from ..config import GENERATED_DIR, Settings, UPLOADS_DIR
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
                        "location": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["title", "start"],
                },
                handler=_tool_calendar_event,
            ),
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
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, (result.stdout or "").strip()


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
        location=location,
        description=description,
    )
    if apple_result is not None:
        ok, message = apple_result
        if ok:
            status_line = "Apple Calendar event created."
        else:
            status_line = f"Apple Calendar automation failed: {message}"

    return (
        f"{status_line}\n"
        f"Title: {title}\n"
        f"Start: {start_raw}\n"
        f"End: {end_raw or ''}\n"
        f"ICS: {url}"
    )


def _create_calendar_event_apple_calendar(
    title: str,
    start_raw: str,
    end_raw: str,
    all_day: bool,
    tz: ZoneInfo,
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
        "set targetCal to first calendar",
        (
            "set newEvent to make new event at end of events of targetCal "
            f"with properties {{summary:{_osascript_literal(title)}, "
            f"start date:date {_osascript_literal(start_str)}, "
            f"end date:date {_osascript_literal(end_str)}, "
            f"location:{_osascript_literal(location)}, "
            f"description:{_osascript_literal(description)}, "
            f"allday event:{'true' if all_day else 'false'}}}"
        ),
        "end tell",
    ]
    return _run_osascript(lines)


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
            name = f"Rappel: {message}"
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
