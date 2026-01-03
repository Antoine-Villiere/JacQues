from __future__ import annotations

from typing import Any, Callable
import json

from ..config import Settings
from .. import db
from . import commands, rag, web_search
from .llm import LLMClient
from .tooling import build_tools, execute_tool


SYSTEM_PROMPT = (
    "You are Jacques, a capable assistant. "
    "You manage multiple conversations with memory, answer questions, "
    "and use tools proactively when helpful. "
    "If the user refers to an uploaded image, check available images and use "
    "image_describe to analyze the relevant file. "
    "If details are missing, ask a brief follow-up question. "
    "When tools are used, summarize what was done and the result. "
    "Decide yourself when to update memory: only store stable preferences "
    "or enduring facts the user would expect you to remember. "
    "If unsure, ask first. Use the memory_append tool when appropriate. "
    "Use email_draft to compose emails and open the user's mail app when asked. "
    "Use task_schedule for reminders or recurring tasks (cron syntax) and do not store reminders in memory. "
    "When editing Word/Excel/PDF files, preserve original formatting; "
    "avoid rewriting entire documents when a targeted edit suffices. "
    "You can generate plots with plot_generate or plot_fred_series and show the image. "
    "For market indices, prefer plot_fred_series (e.g., NASDAQCOM for Nasdaq Composite)."
)

AUTO_TITLE_INTERVAL = 6


def respond(
    conversation_id: int,
    user_message: str,
    settings: Settings,
    use_rag: bool = True,
    use_web: bool = False,
    on_tool_event: Callable[[str, str], None] | None = None,
) -> str:
    command_reply = commands.handle_command(user_message, settings, conversation_id)
    if command_reply is not None:
        return command_reply

    history = db.get_messages(conversation_id, limit=settings.max_history_messages)
    history_for_llm = [row for row in history if row["role"] in {"user", "assistant"}]

    llm = LLMClient(settings)
    if not llm.available():
        return _fallback_response(user_message, settings, use_rag, use_web, conversation_id)

    tools, tool_map = build_tools(
        settings, conversation_id=conversation_id, use_rag=use_rag, use_web=use_web
    )

    messages = [{"role": "system", "content": _build_system_prompt()}]
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
        db.add_message(conversation_id, "tool", content)

    reply = _run_tool_loop(
        llm,
        messages,
        tools,
        tool_map,
        settings,
        conversation_id,
        log_tool_event,
        on_tool_event,
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
) -> str:
    command_reply = commands.handle_command(user_message, settings, conversation_id)
    if command_reply is not None:
        if on_token:
            on_token(command_reply)
        return command_reply

    history = db.get_messages(conversation_id, limit=settings.max_history_messages)
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
        db.add_message(conversation_id, "tool", content)

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
    )
    return reply or "No response generated."


def maybe_update_conversation_title(
    conversation_id: int, settings: Settings, force_first: bool = False
) -> str | None:
    conversation = db.get_conversation(conversation_id)
    if not conversation:
        return None
    auto_title = conversation["auto_title"]
    if auto_title is not None and int(auto_title) == 0:
        return None

    messages = db.get_messages(conversation_id)
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
        "Create a short French conversation title (3-6 words). "
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
                    "content": "You write short, polished French conversation titles.",
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


def _run_tool_loop(
    llm: LLMClient,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_map: dict[str, Any],
    settings: Settings,
    conversation_id: int,
    log_tool_event: Callable[[str], None] | None = None,
    on_tool_event: Callable[[str, str], None] | None = None,
) -> str:
    if not tools:
        try:
            response = llm.chat(messages, model=settings.reasoning_model)
        except Exception as exc:
            return f"LLM error: {exc}"
        return str(response.get("content") or "").strip()

    steps = 0
    used_tools = False
    latest_sources: str | None = None
    tool_summaries: list[tuple[str, str]] = []
    summary_prompted = False
    last_tool_calls: list[dict[str, Any]] | None = None
    while steps < settings.max_tool_calls:
        try:
            response = llm.chat(messages, model=settings.reasoning_model, tools=tools)
        except Exception as exc:
            return f"LLM error: {exc}"
        tool_calls = response.get("tool_calls") or []
        content = response.get("content") or ""
        if not tool_calls:
            final_content = str(content).strip()
            if used_tools and settings.text_model != settings.reasoning_model:
                try:
                    text_response = llm.chat(
                        messages, model=settings.text_model, tools=tools
                    )
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
            if name == "web_search" and result.strip().lower().startswith("sources:"):
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
        response = llm.chat(messages, model=settings.text_model, tools=tools)
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
) -> str:
    def stream_or_chat(model: str, toolset: list[dict[str, Any]] | None):
        if settings.llm_streaming and on_token:
            iterator, state = llm.stream_chat(messages, model=model, tools=toolset)
            for token in iterator:
                on_token(token)
            content = "".join(state["content_parts"]).strip()
            tool_calls = _ordered_tool_calls(state["tool_calls"])
            return content, tool_calls
        response = llm.chat(messages, model=model, tools=toolset)
        return str(response.get("content") or "").strip(), response.get("tool_calls") or []

    if not tools:
        content, _ = stream_or_chat(settings.reasoning_model, None)
        return content

    steps = 0
    used_tools = False
    latest_sources: str | None = None
    tool_summaries: list[tuple[str, str]] = []
    summary_prompted = False
    last_tool_calls: list[dict[str, Any]] | None = None
    while steps < settings.max_tool_calls:
        content, tool_calls = stream_or_chat(settings.reasoning_model, tools)
        if not tool_calls:
            if used_tools and settings.text_model != settings.reasoning_model:
                text_content, text_tool_calls = stream_or_chat(settings.text_model, tools)
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
            if name == "web_search" and result.strip().lower().startswith("sources:"):
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
    final_content, _ = stream_or_chat(settings.text_model, tools)
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
        "outil",
        "outils",
        "j'ai utilise",
        "j’ai utilise",
        "j ai utilise",
        "used the tool",
    ]
    return not any(marker in lowered for marker in markers)


def _append_tool_summary(
    answer: str,
    tool_summaries: list[tuple[str, str]],
    sources: str | None,
) -> str:
    text = answer.strip() if answer else ""
    if tool_summaries and _needs_tool_summary(text):
        lines = []
        for name, result in tool_summaries:
            if name == "web_search":
                summary = "retrieved web sources"
            elif name in {"plot_generate", "plot_fred_series"}:
                summary = "generated a plot image"
            elif name == "image_generate":
                summary = "generated an image"
            else:
                summary = _clip_text(result)
            lines.append(f"- {name}: {summary}")
        summary_block = "Tools used:\n" + "\n".join(lines)
        text = f"{text}\n\n{summary_block}".strip()
    return _maybe_append_sources(text, sources)


def _fallback_response(
    user_message: str,
    settings: Settings,
    use_rag: bool,
    use_web: bool,
    conversation_id: int,
) -> str:
    context_blocks = []
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


def _build_system_prompt() -> str:
    stored_prompt = db.get_setting("system_prompt")
    base_prompt = stored_prompt.strip() if stored_prompt and stored_prompt.strip() else SYSTEM_PROMPT
    memory = db.get_setting("global_memory") or ""
    memory = memory.strip()
    if memory:
        return f"{base_prompt}\n\nGlobal memory:\n{memory}"
    return base_prompt
