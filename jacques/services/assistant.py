from __future__ import annotations

from typing import Any, Callable
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import re

from ..config import Settings, detect_system_locale, detect_system_timezone
from .. import db
from . import commands, doc_ingest, rag, web_search
from .llm import LLMClient
from .tooling import build_tools, execute_tool


SYSTEM_PROMPT = (
    "You are Jacques, a capable assistant. "
    "Respond in the user's language. Default to English if unsure. "
    "You manage multiple conversations with memory, answer questions, "
    "and use tools proactively when helpful. "
    "If the user refers to an uploaded image, check available images and use "
    "image_describe to analyze the relevant file. "
    "If the user mentions @\"filename\" or @filename, treat it as a direct reference to that document. "
    "If details are missing, ask a brief follow-up question. "
    "When tools are used, summarize what was done and the result. "
    "If the user asks multiple tasks in one message, handle every item and use multiple tools if needed. "
    "Never include tool call logs or a 'Tools used' section in the response. "
    "Decide yourself when to update memory: only store stable preferences "
    "or enduring facts the user would expect you to remember. "
    "If unsure, ask first. Use the memory_append tool when appropriate. "
    "Use email_draft to compose emails and open the user's mail app when asked. "
    "Use mail_search and mail_read to access Apple Mail when asked; never delete or send emails. "
    "For email recaps (e.g., today/yesterday), use mail_search with since_days and only_inbox. "
    "Use calendar_list and calendar_find to inspect calendars/events, then calendar_event to create events; "
    "if multiple calendars exist, prefer a writable calendar or ask for the name. "
    "Use task_schedule for reminders or recurring tasks (cron syntax) and do not store reminders in memory. "
    "Use project_list_files, project_read_file, project_search, and project_replace to inspect or update the project; avoid overwriting full files. "
    "Use python_run (or python) for quick local scripts (calculations, time, file generation). "
    "Use excel_read_sheet to read data from specific Excel sheets when referenced. "
    "Use news_search for current news queries. Use web_fetch with a URL (and optional CSS selector) to scrape specific sites. "
    "Use stock_history to fetch stock price history when asked for market performance, then analyze returns/patterns and plot with plot_generate. "
    "When editing Word/Excel/PDF files, preserve original formatting; "
    "avoid rewriting entire documents when a targeted edit suffices. "
    "You can generate plots with plot_generate or plot_fred_series and show the image. "
    "For market indices, prefer plot_fred_series (e.g., NASDAQCOM for Nasdaq Composite). "
    "Use macos_script (AppleScript) for native macOS automation when requested; avoid destructive actions without confirmation. "
)

AUTO_TITLE_INTERVAL = 6
_DOC_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".xlsm", ".csv"}


def respond(
    conversation_id: int,
    user_message: str,
    settings: Settings,
    use_rag: bool = True,
    use_web: bool = False,
    on_tool_event: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    active_file: dict | None = None,
    branch_id: int | None = None,
) -> str:
    command_reply = commands.handle_command(user_message, settings, conversation_id)
    if command_reply is not None:
        return command_reply

    if branch_id is None:
        branch_id = db.get_conversation_active_branch(conversation_id)
    history = db.get_messages_for_branch(
        conversation_id, branch_id=branch_id, limit=settings.max_history_messages
    )
    history_for_llm = [row for row in history if row["role"] in {"user", "assistant"}]

    llm = LLMClient(settings)
    if not llm.available():
        return _fallback_response(user_message, settings, use_rag, use_web, conversation_id)

    tools, tool_map = build_tools(
        settings, conversation_id=conversation_id, use_rag=use_rag, use_web=use_web
    )

    messages = [{"role": "system", "content": _build_system_prompt()}]
    active_context = _active_file_context(active_file)
    if active_context:
        messages.append({"role": "system", "content": active_context})
    doc_context, doc_updated = _doc_context_from_mentions(user_message, conversation_id)
    if doc_updated:
        rag.build_index(conversation_id)
    if doc_context:
        messages.append(
            {
                "role": "system",
                "content": f"Document references:\n{doc_context}",
            }
        )
    if use_rag:
        rag_context = rag.format_results(
            rag.search(user_message, settings, conversation_id), max_chars=900
        )
        if rag_context:
            messages.append(
                {
                    "role": "system",
                    "content": f"RAG context:\n{rag_context}",
                }
            )
    image_context = _image_context(conversation_id)
    if image_context:
        messages.append(
            {
                "role": "system",
                "content": f"Images available:\n{image_context}",
            }
        )
    for row in history_for_llm:
        messages.append({"role": row["role"], "content": row["content"]})
    last_user = (
        history_for_llm[-1]["content"]
        if history_for_llm and history_for_llm[-1]["role"] == "user"
        else None
    )
    if last_user != user_message:
        messages.append({"role": "user", "content": user_message})

    def log_tool_event(content: str) -> None:
        db.add_message(conversation_id, "tool", content, branch_id=branch_id)

    reply = _run_tool_loop(
        llm,
        messages,
        tools,
        tool_map,
        settings,
        conversation_id,
        log_tool_event,
        on_tool_event,
        should_cancel,
        _tool_budget(user_message, settings),
    )
    return reply or "No response generated."


def respond_streaming(
    conversation_id: int,
    user_message: str,
    settings: Settings,
    use_rag: bool = True,
    use_web: bool = False,
    on_token: Callable[[str], None] | None = None,
    on_tool_event: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    active_file: dict | None = None,
    branch_id: int | None = None,
) -> str:
    command_reply = commands.handle_command(user_message, settings, conversation_id)
    if command_reply is not None:
        if on_token:
            on_token(command_reply)
        return command_reply

    if branch_id is None:
        branch_id = db.get_conversation_active_branch(conversation_id)
    history = db.get_messages_for_branch(
        conversation_id, branch_id=branch_id, limit=settings.max_history_messages
    )
    history_for_llm = [row for row in history if row["role"] in {"user", "assistant"}]

    llm = LLMClient(settings)
    if not llm.available():
        fallback = _fallback_response(user_message, settings, use_rag, use_web, conversation_id)
        if on_token:
            on_token(fallback)
        return fallback

    tools, tool_map = build_tools(
        settings, conversation_id=conversation_id, use_rag=use_rag, use_web=use_web
    )

    messages = [{"role": "system", "content": _build_system_prompt()}]
    active_context = _active_file_context(active_file)
    if active_context:
        messages.append({"role": "system", "content": active_context})
    doc_context, doc_updated = _doc_context_from_mentions(user_message, conversation_id)
    if doc_updated:
        rag.build_index(conversation_id)
    if doc_context:
        messages.append(
            {
                "role": "system",
                "content": f"Document references:\n{doc_context}",
            }
        )
    if use_rag:
        rag_context = rag.format_results(
            rag.search(user_message, settings, conversation_id), max_chars=900
        )
        if rag_context:
            messages.append(
                {
                    "role": "system",
                    "content": f"RAG context:\n{rag_context}",
                }
            )
    image_context = _image_context(conversation_id)
    if image_context:
        messages.append(
            {
                "role": "system",
                "content": f"Images available:\n{image_context}",
            }
        )
    for row in history_for_llm:
        messages.append({"role": row["role"], "content": row["content"]})
    last_user = (
        history_for_llm[-1]["content"]
        if history_for_llm and history_for_llm[-1]["role"] == "user"
        else None
    )
    if last_user != user_message:
        messages.append({"role": "user", "content": user_message})

    def log_tool_event(content: str) -> None:
        db.add_message(conversation_id, "tool", content, branch_id=branch_id)

    reply = _run_tool_loop_streaming(
        llm,
        messages,
        tools,
        tool_map,
        settings,
        conversation_id,
        log_tool_event,
        on_token,
        on_tool_event,
        should_cancel,
        _tool_budget(user_message, settings),
    )
    return reply or "No response generated."


def maybe_update_conversation_title(
    conversation_id: int,
    settings: Settings,
    force_first: bool = False,
    branch_id: int | None = None,
) -> str | None:
    conversation = db.get_conversation(conversation_id)
    if not conversation:
        return None
    auto_title = conversation["auto_title"]
    if auto_title is not None and int(auto_title) == 0:
        return None

    if branch_id is None:
        branch_id = db.get_conversation_active_branch(conversation_id)
    messages = db.get_messages_for_branch(conversation_id, branch_id=branch_id)
    user_messages = [row["content"] for row in messages if row["role"] == "user"]
    assistant_messages = [row["content"] for row in messages if row["role"] == "assistant"]
    if not user_messages:
        return None

    should_update = False
    if force_first and len(user_messages) == 1 and assistant_messages:
        should_update = True
    elif len(user_messages) >= 2 and len(user_messages) % AUTO_TITLE_INTERVAL == 0:
        should_update = True

    if not should_update:
        return None

    first = (user_messages[0] or "").strip()
    recent = [msg.strip() for msg in user_messages[-2:] if msg.strip()]
    if not first and not recent:
        return None

    title = _generate_conversation_title(first, recent, settings)
    if not title:
        return None
    current = (conversation["title"] or "").strip()
    if title == current:
        return None

    db.update_conversation_title(conversation_id, title, auto_title=True)
    return title


def _generate_conversation_title(
    first: str, recent: list[str], settings: Settings
) -> str:
    llm = LLMClient(settings)
    fallback = _fallback_title(first or (recent[-1] if recent else "Conversation"))
    if not llm.available():
        return fallback

    def clip(text: str, limit: int = 320) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit].rsplit(" ", 1)[0]

    first_text = clip(first)
    recent_text = "\n".join(f"- {clip(msg, 220)}" for msg in recent) or "- (none)"
    prompt = (
        "Create a short English conversation title (3-6 words). "
        "Use Title Case, no quotes, no emojis. "
        "Blend the first topic with the most recent topics.\n\n"
        f"First topic: {first_text}\n"
        f"Recent topics:\n{recent_text}\n\n"
        "Title:"
    )
    try:
        response = llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "You write short, polished English conversation titles.",
                },
                {"role": "user", "content": prompt},
            ],
            model=settings.text_model,
            tools=None,
            stream=False,
        )
        raw = str(response.get("content") or "").strip()
    except Exception:
        return fallback

    if not raw:
        return fallback

    title = raw.splitlines()[0].strip().strip('"').strip("'")
    if len(title) > 60:
        title = title[:60].rsplit(" ", 1)[0]
    return title or fallback


def _fallback_title(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return "Conversation"
    words = cleaned.split()[:6]
    title = " ".join(words)
    return title[:60]


def _tool_budget(user_message: str, settings: Settings) -> int:
    base = settings.max_tool_calls
    text = (user_message or "").strip()
    if not text:
        return base
    segments = [seg.strip() for seg in re.split(r"[\\n;]+", text) if seg.strip()]
    if len(segments) < 2:
        pieces = [seg.strip() for seg in re.split(r"[.!?]+", text) if seg.strip()]
    else:
        pieces = segments
    task_count = max(1, len(pieces))
    if task_count >= 3:
        return max(base, 8)
    if task_count >= 2:
        return max(base, 6)
    return base


def _is_tool_json_error(exc: Exception) -> bool:
    message = str(exc)
    return "Failed to parse tool call arguments as JSON" in message


def _run_tool_loop(
    llm: LLMClient,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_map: dict[str, Any],
    settings: Settings,
    conversation_id: int,
    log_tool_event: Callable[[str], None] | None = None,
    on_tool_event: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    max_steps: int | None = None,
) -> str:
    if should_cancel and should_cancel():
        return "Stopped by user."
    if not tools:
        try:
            response = llm.chat(messages, model=settings.reasoning_model)
        except Exception as exc:
            return f"LLM error: {exc}"
        return str(response.get("content") or "").strip()

    steps = 0
    step_budget = max_steps if isinstance(max_steps, int) and max_steps > 0 else settings.max_tool_calls
    used_tools = False
    latest_sources: str | None = None
    tool_summaries: list[tuple[str, str]] = []
    summary_prompted = False
    last_tool_calls: list[dict[str, Any]] | None = None
    while steps < step_budget:
        if should_cancel and should_cancel():
            return "Stopped by user."
        try:
            response = llm.chat(messages, model=settings.reasoning_model, tools=tools)
        except Exception as exc:
            if _is_tool_json_error(exc):
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Tool calls must use strict JSON with double quotes and no trailing commas. "
                            "If you cannot provide valid JSON, respond without tools."
                        ),
                    }
                )
                try:
                    response = llm.chat(messages, model=settings.reasoning_model, tools=tools)
                except Exception as inner_exc:
                    if _is_tool_json_error(inner_exc):
                        messages.append(
                            {
                                "role": "system",
                                "content": "Do not call tools. Respond with the final answer only.",
                            }
                        )
                        try:
                            response = llm.chat(messages, model=settings.text_model, tools=None)
                        except Exception as final_exc:
                            return f"LLM error: {final_exc}"
                        return str(response.get("content") or "").strip()
                    return f"LLM error: {inner_exc}"
            else:
                return f"LLM error: {exc}"
        tool_calls = response.get("tool_calls") or []
        content = response.get("content") or ""
        if not tool_calls:
            final_content = str(content).strip()
            if used_tools and settings.text_model != settings.reasoning_model:
                try:
                    messages.append(
                        {
                            "role": "system",
                            "content": "Provide the final answer now. Do not call tools.",
                        }
                    )
                    text_response = llm.chat(messages, model=settings.text_model, tools=None)
                except Exception as exc:
                    return f"LLM error: {exc}"
                text_content = str(text_response.get("content") or "").strip()
                return _append_tool_summary(
                    text_content or final_content, tool_summaries, latest_sources
                )
            return _append_tool_summary(final_content, tool_summaries, latest_sources)

        if last_tool_calls is not None and tool_calls == last_tool_calls:
            messages.append(
                {
                    "role": "system",
                    "content": "Tool calls are repeating. Provide a final answer without tools.",
                }
            )
            break

        used_tools = True
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        last_tool_calls = tool_calls
        for call in tool_calls:
            if should_cancel and should_cancel():
                return "Stopped by user."
            function = call.get("function", {})
            name = function.get("name")
            raw_args = function.get("arguments", "{}")
            if log_tool_event:
                log_tool_event(_format_tool_call(name, raw_args))
            if on_tool_event and name:
                on_tool_event(name, "call")
            result = execute_tool(name, raw_args, tool_map, settings, conversation_id)
            if log_tool_event:
                log_tool_event(_format_tool_result(name, result))
            if on_tool_event and name:
                on_tool_event(name, "result")
            if name in {"web_search", "news_search"} and result.strip().lower().startswith("sources:"):
                latest_sources = result
            if name:
                tool_summaries.append((name, result))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": result,
                }
            )
        if used_tools and not summary_prompted:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "After using tools, explain what you did and the result in your final answer."
                    ),
                }
            )
            summary_prompted = True
        steps += 1

    messages.append(
        {
            "role": "system",
            "content": "Tool budget reached. Provide the best possible final answer now.",
        }
    )
    try:
        messages.append(
            {
                "role": "system",
                "content": "Do not call tools. Respond with the final answer only.",
            }
        )
        response = llm.chat(messages, model=settings.text_model, tools=None)
    except Exception as exc:
        return f"LLM error: {exc}"
    return _append_tool_summary(
        str(response.get("content") or "").strip(), tool_summaries, latest_sources
    )


def _run_tool_loop_streaming(
    llm: LLMClient,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_map: dict[str, Any],
    settings: Settings,
    conversation_id: int,
    log_tool_event: Callable[[str], None] | None = None,
    on_token: Callable[[str], None] | None = None,
    on_tool_event: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    max_steps: int | None = None,
) -> str:
    def stream_or_chat(model: str, toolset: list[dict[str, Any]] | None):
        try:
            if settings.llm_streaming and on_token:
                iterator, state = llm.stream_chat(messages, model=model, tools=toolset)
                for token in iterator:
                    if should_cancel and should_cancel():
                        state["cancelled"] = True
                        break
                    on_token(token)
                content = "".join(state["content_parts"]).strip()
                tool_calls = _ordered_tool_calls(state["tool_calls"])
                return content, tool_calls, bool(state.get("cancelled"))
            response = llm.chat(messages, model=model, tools=toolset, stream=False)
            return (
                str(response.get("content") or "").strip(),
                response.get("tool_calls") or [],
                False,
            )
        except Exception as exc:
            if toolset and _is_tool_json_error(exc):
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Tool calls must use strict JSON with double quotes and no trailing commas. "
                            "If you cannot provide valid JSON, respond without tools."
                        ),
                    }
                )
                try:
                    response = llm.chat(messages, model=model, tools=toolset, stream=False)
                    return (
                        str(response.get("content") or "").strip(),
                        response.get("tool_calls") or [],
                        False,
                    )
                except Exception as inner_exc:
                    if _is_tool_json_error(inner_exc):
                        messages.append(
                            {
                                "role": "system",
                                "content": "Do not call tools. Respond with the final answer only.",
                            }
                        )
                        response = llm.chat(messages, model=model, tools=None, stream=False)
                        return (
                            str(response.get("content") or "").strip(),
                            [],
                            False,
                        )
                    raise
            raise

    if not tools:
        content, _, cancelled = stream_or_chat(settings.reasoning_model, None)
        if cancelled:
            return f"{content}\n\n(Stopped by user.)".strip() if content else "Stopped by user."
        return content

    steps = 0
    step_budget = max_steps if isinstance(max_steps, int) and max_steps > 0 else settings.max_tool_calls
    used_tools = False
    latest_sources: str | None = None
    tool_summaries: list[tuple[str, str]] = []
    summary_prompted = False
    last_tool_calls: list[dict[str, Any]] | None = None
    while steps < step_budget:
        if should_cancel and should_cancel():
            return "Stopped by user."
        content, tool_calls, cancelled = stream_or_chat(settings.reasoning_model, tools)
        if cancelled:
            return f"{content}\n\n(Stopped by user.)".strip() if content else "Stopped by user."
        if not tool_calls:
            if used_tools and settings.text_model != settings.reasoning_model:
                messages.append(
                    {
                        "role": "system",
                        "content": "Provide the final answer now. Do not call tools.",
                    }
                )
                text_content, text_tool_calls, cancelled_text = stream_or_chat(
                    settings.text_model, None
                )
                if cancelled_text:
                    return (
                        f"{text_content}\n\n(Stopped by user.)".strip()
                        if text_content
                        else "Stopped by user."
                    )
                if not text_tool_calls:
                    return _append_tool_summary(
                        text_content or content, tool_summaries, latest_sources
                    )
            return _append_tool_summary(content, tool_summaries, latest_sources)

        if last_tool_calls is not None and tool_calls == last_tool_calls:
            messages.append(
                {
                    "role": "system",
                    "content": "Tool calls are repeating. Provide a final answer without tools.",
                }
            )
            break

        used_tools = True
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        last_tool_calls = tool_calls
        for call in tool_calls:
            if should_cancel and should_cancel():
                return "Stopped by user."
            function = call.get("function", {})
            name = function.get("name")
            raw_args = function.get("arguments", "{}")
            if log_tool_event:
                log_tool_event(_format_tool_call(name, raw_args))
            if on_tool_event and name:
                on_tool_event(name, "call")
            result = execute_tool(name, raw_args, tool_map, settings, conversation_id)
            if log_tool_event:
                log_tool_event(_format_tool_result(name, result))
            if on_tool_event and name:
                on_tool_event(name, "result")
            if name in {"web_search", "news_search"} and result.strip().lower().startswith("sources:"):
                latest_sources = result
            if name:
                tool_summaries.append((name, result))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": result,
                }
            )
        if used_tools and not summary_prompted:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "After using tools, explain what you did and the result in your final answer."
                    ),
                }
            )
            summary_prompted = True
        steps += 1

    messages.append(
        {
            "role": "system",
            "content": "Tool budget reached. Provide the best possible final answer now.",
        }
    )
    messages.append(
        {
            "role": "system",
            "content": "Do not call tools. Respond with the final answer only.",
        }
    )
    final_content, _, cancelled = stream_or_chat(settings.text_model, None)
    if cancelled:
        return f"{final_content}\n\n(Stopped by user.)".strip() if final_content else "Stopped by user."
    return _append_tool_summary(final_content, tool_summaries, latest_sources)


def _ordered_tool_calls(tool_calls: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = []
    for idx in sorted(tool_calls):
        entry = tool_calls[idx]
        if not entry.get("id"):
            entry["id"] = f"call_{idx}"
        ordered.append(entry)
    return ordered


def _format_tool_call(name: str | None, raw_args: Any) -> str:
    safe_name = name or "tool"
    args_text = _format_tool_args(raw_args)
    return f"Tool call: **{safe_name}**\n```json\n{args_text}\n```"


def _format_tool_result(name: str | None, result: str) -> str:
    safe_name = name or "tool"
    clipped = result.strip()
    if len(clipped) > 800:
        clipped = clipped[:800].rsplit(" ", 1)[0] + "..."
    if name in {"image_generate", "plot_generate", "plot_fred_series", "web_search"}:
        return f"Tool result: **{safe_name}**\n{clipped}"
    return f"Tool result: **{safe_name}**\n```text\n{clipped}\n```"


def _format_tool_args(raw_args: Any) -> str:
    if raw_args is None:
        return "{}"
    if isinstance(raw_args, dict):
        return json.dumps(raw_args, indent=2, ensure_ascii=True)
    if isinstance(raw_args, str):
        text = raw_args.strip()
        if not text:
            return "{}"
        try:
            data = json.loads(text)
            return json.dumps(data, indent=2, ensure_ascii=True)
        except json.JSONDecodeError:
            return text
    return "{}"


def _clip_text(text: str, max_chars: int = 160) -> str:
    clipped = text.strip()
    if len(clipped) <= max_chars:
        return clipped
    return clipped[:max_chars].rsplit(" ", 1)[0] + "..."


def _needs_tool_summary(answer: str) -> bool:
    lowered = answer.lower()
    markers = [
        "tools used",
        "tool used",
        "used the tool",
    ]
    return not any(marker in lowered for marker in markers)


def _append_tool_summary(
    answer: str,
    tool_summaries: list[tuple[str, str]],
    sources: str | None,
) -> str:
    text = answer.strip() if answer else ""
    image_blocks = _collect_tool_images(tool_summaries, text)
    if image_blocks:
        text = f"{text}\n\n{image_blocks}".strip()
    return _maybe_append_sources(text, sources)


def _collect_tool_images(tool_summaries: list[tuple[str, str]], answer: str) -> str:
    if not tool_summaries:
        return ""
    existing = {url for _, url in _extract_markdown_images(answer)}
    blocks: list[str] = []
    seen = set(existing)
    for _, result in tool_summaries:
        for markup, url in _extract_markdown_images(result or ""):
            if url in seen:
                continue
            seen.add(url)
            blocks.append(markup)
    return "\n".join(blocks).strip()


def _extract_markdown_images(text: str) -> list[tuple[str, str]]:
    if not text:
        return []
    matches: list[tuple[str, str]] = []
    for match in re.finditer(r"!\[[^\]]*]\(([^)]+)\)", text):
        url = match.group(1).strip()
        if url:
            matches.append((match.group(0), url))
    return matches


def _fallback_response(
    user_message: str,
    settings: Settings,
    use_rag: bool,
    use_web: bool,
    conversation_id: int,
) -> str:
    context_blocks = []
    doc_context, doc_updated = _doc_context_from_mentions(user_message, conversation_id)
    if doc_updated:
        rag.build_index(conversation_id)
    if doc_context:
        context_blocks.append("Document references:\n" + doc_context)
    if use_rag:
        results = rag.search(user_message, settings, conversation_id)
        rag_context = rag.format_results(results)
        if rag_context:
            context_blocks.append("RAG context:\n" + rag_context)
    if use_web:
        results = web_search.search(user_message, settings)
        web_context = web_search.summarize_results(results)
        if web_context:
            context_blocks.append("Web context:\n" + web_context)

    if context_blocks:
        return (
            "LLM not configured. Here is relevant context I can find:\n\n"
            + "\n\n".join(context_blocks)
        )

    return (
        "LLM not configured. Add an API key to enable full responses. "
        "You can also ingest documents for RAG."
    )


def _maybe_append_sources(answer: str, sources: str | None) -> str:
    if not sources:
        return answer
    if "sources:" in answer.lower():
        return answer
    return f"{answer.rstrip()}\n\n{sources.strip()}"


def _extract_doc_mentions(text: str) -> list[str]:
    if not text:
        return []
    mentions: list[str] = []
    for match in re.finditer(r'@"([^"]+)"', text):
        name = match.group(1).strip()
        if name:
            mentions.append(name)
    for match in re.finditer(r"@([^\s@]+)", text):
        token = match.group(1).strip()
        if not token or token.startswith('"'):
            continue
        name = token.strip(",. ")
        lowered = name.lower()
        if any(lowered.endswith(ext) for ext in _DOC_EXTENSIONS):
            mentions.append(name)
    return list(dict.fromkeys(mentions))


def _resolve_document_by_name(conversation_id: int, name: str) -> Any | None:
    doc = db.get_document_by_name(conversation_id, name)
    if doc:
        return doc
    for row in db.list_documents(conversation_id):
        if str(row["name"]).lower() == name.lower():
            return db.get_document_by_id(int(row["id"]))
    return None


def _refresh_document_text(doc: Any) -> tuple[str, bool]:
    current = (doc["text"] or "").strip()
    if len(current) >= 8:
        return current, False
    path_str = doc["path"] or ""
    if not path_str:
        return current, False
    path = Path(path_str)
    if not path.exists():
        return current, False
    try:
        extracted = doc_ingest.extract_text(path).strip()
    except Exception:
        return current, False
    if extracted and extracted != current:
        db.update_document_text(int(doc["id"]), extracted)
        return extracted, True
    return current, False


def _doc_context_from_mentions(
    user_message: str, conversation_id: int
) -> tuple[str, bool]:
    names = _extract_doc_mentions(user_message)
    if not names:
        return "", False

    updated = False
    text_map = {
        row["id"]: row["text"] for row in db.get_document_texts(conversation_id)
    }
    blocks: list[str] = []
    for name in names:
        doc = _resolve_document_by_name(conversation_id, name)
        if not doc:
            continue
        text = (text_map.get(doc["id"]) or doc["text"] or "").strip()
        if len(text) < 8:
            refreshed, did_update = _refresh_document_text(doc)
            updated = updated or did_update
            text = refreshed
        if text:
            blocks.append(f"[{doc['name']}]\n{_clip_text(text, 1200)}")
    return "\n\n".join(blocks).strip(), updated


def _active_file_context(active_file: dict | None) -> str:
    if not active_file:
        return ""
    name = str(active_file.get("name") or "").strip()
    if not name:
        return ""
    doc_type = str(active_file.get("doc_type") or "").strip()
    kind = str(active_file.get("kind") or "").strip()
    label = doc_type or kind or "file"
    return (
        "Active file open in the UI: "
        f"{name} ({label}). The user is working on this file; prioritize it if relevant."
    )


def _image_context(conversation_id: int, limit: int = 5) -> str:
    images = db.list_images(conversation_id)
    if not images:
        return ""
    lines = []
    for image in images[:limit]:
        name = image["name"]
        description = (image["description"] or "").strip()
        if not description:
            description = "No description available."
        lines.append(f"- {name}: {_clip_text(description, 240)}")
    return "\n".join(lines)


def _format_local_time(tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
    except Exception:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _build_system_prompt() -> str:
    stored_prompt = db.get_setting("system_prompt")
    base_prompt = stored_prompt.strip() if stored_prompt and stored_prompt.strip() else SYSTEM_PROMPT
    custom_instructions = (db.get_setting("custom_instructions") or "").strip()
    nickname = (db.get_setting("user_nickname") or "").strip()
    occupation = (db.get_setting("user_occupation") or "").strip()
    about = (db.get_setting("user_about") or "").strip()
    memory = (db.get_setting("global_memory") or "").strip()
    locale_name = (db.get_setting("app_locale") or "").strip() or detect_system_locale()
    tz_name = (db.get_setting("app_timezone") or "").strip() or detect_system_timezone()
    local_time = _format_local_time(tz_name)

    blocks = [base_prompt, "Language: respond in the user's language unless they request otherwise."]
    blocks.append(
        f"Local settings: timezone={tz_name}, locale={locale_name}, local_time={local_time}."
    )
    profile_lines = []
    if nickname:
        profile_lines.append(f"- Nickname: {nickname}")
    if occupation:
        profile_lines.append(f"- Occupation: {occupation}")
    if about:
        profile_lines.append(f"- About: {about}")
    if profile_lines:
        blocks.append("User profile:\n" + "\n".join(profile_lines))
    if custom_instructions:
        blocks.append("Custom instructions:\n" + custom_instructions)
    if memory:
        blocks.append("Global memory:\n" + memory)
    return "\n\n".join(blocks)
