from __future__ import annotations

import shlex
from pathlib import Path

from ..config import EXPORTS_DIR, GENERATED_DIR, Settings
from .. import db
from ..utils import safe_filename
from . import file_ops, image_gen, rag, web_search


def handle_command(text: str, settings: Settings, conversation_id: int) -> str | None:
    if not text.strip().startswith("/"):
        return None

    parts = shlex.split(text)
    command = parts[0][1:] if parts else ""
    args = parts[1:]

    if command in {"help", "?"}:
        return _help_text()
    if command == "excel":
        return _excel_command(args)
    if command == "word":
        return _word_command(args)
    if command == "web":
        return _web_command(args, settings)
    if command in {"img", "image"}:
        return _image_command(args, settings, conversation_id)
    if command == "doc":
        return _doc_command(args, conversation_id)
    if command == "rag":
        return _rag_command(args, conversation_id)

    return "Unknown command. Try /help."


def _help_text() -> str:
    return (
        "Commands:\n"
        "/excel create <file.xlsx> [sheet]\n"
        "/excel add-sheet <file.xlsx> <sheet>\n"
        "/excel set <file.xlsx> <sheet> <cell> <value>\n"
        "/word create <file.docx>\n"
        "/word append <file.docx> <text>\n"
        "/word replace <file.docx> <old> <new>\n"
        "/img create <file.png> <prompt>\n"
        "/web <query or url>\n"
        "/doc list\n"
        "/rag rebuild"
    )


def _excel_command(args: list[str]) -> str:
    if not args:
        return "Usage: /excel <create|add-sheet|set> ..."
    action = args[0]
    if action == "create" and len(args) >= 2:
        filename = safe_filename(args[1])
        sheet = args[2] if len(args) >= 3 else "Sheet1"
        path = EXPORTS_DIR / filename
        file_ops.create_excel(path, sheet)
        return f"Excel created at {path}"
    if action == "add-sheet" and len(args) >= 3:
        filename = safe_filename(args[1])
        sheet = args[2]
        path = EXPORTS_DIR / filename
        file_ops.add_sheet(path, sheet)
        return f"Sheet added to {path}"
    if action == "set" and len(args) >= 5:
        filename = safe_filename(args[1])
        sheet = args[2]
        cell = args[3]
        value = " ".join(args[4:])
        path = EXPORTS_DIR / filename
        file_ops.set_cell(path, sheet, cell, value)
        return f"Cell {cell} updated in {path}"
    return "Usage: /excel create|add-sheet|set ..."


def _word_command(args: list[str]) -> str:
    if not args:
        return "Usage: /word <create|append|replace> ..."
    action = args[0]
    if action == "create" and len(args) >= 2:
        filename = safe_filename(args[1])
        path = EXPORTS_DIR / filename
        file_ops.create_word(path)
        return f"Word created at {path}"
    if action == "append" and len(args) >= 3:
        filename = safe_filename(args[1])
        text = " ".join(args[2:])
        path = EXPORTS_DIR / filename
        file_ops.append_paragraph(path, text)
        return f"Paragraph appended to {path}"
    if action == "replace" and len(args) >= 4:
        filename = safe_filename(args[1])
        old = args[2]
        new = " ".join(args[3:])
        path = EXPORTS_DIR / filename
        file_ops.replace_text(path, old, new)
        return f"Replaced text in {path}"
    return "Usage: /word create|append|replace ..."


def _image_command(args: list[str], settings: Settings, conversation_id: int) -> str:
    if not args or args[0] != "create" or len(args) < 3:
        return "Usage: /img create <file.png> <prompt>"
    filename = safe_filename(args[1])
    prompt = " ".join(args[2:])
    path = GENERATED_DIR / filename
    image_gen.generate_image(prompt, path, settings)
    db.add_image(conversation_id, filename, str(path), f"Generated: {prompt}")
    url = f"/files/generated/{filename}"
    return f"Image created: {filename}\n\n![{filename}]({url})"


def _web_command(args: list[str], settings: Settings) -> str:
    if not args:
        return "Usage: /web <query or url>"
    query = " ".join(args)
    results = web_search.search(query, settings)
    summary = web_search.summarize_results(results)
    if web_search.is_url(query) and results:
        fetched = web_search.fetch_url(query, settings)
        summary += f"\n\nContent: {fetched[:800]}"
    return summary or "No results."


def _doc_command(args: list[str], conversation_id: int) -> str:
    if args and args[0] == "list":
        docs = db.list_documents(conversation_id)
        if not docs:
            return "No documents ingested."
        lines = [f"- {doc['name']} ({doc['doc_type']})" for doc in docs]
        return "Documents:\n" + "\n".join(lines)
    return "Usage: /doc list"


def _rag_command(args: list[str], conversation_id: int) -> str:
    if args and args[0] == "rebuild":
        rag.build_index(conversation_id)
        return "RAG index rebuilt."
    return "Usage: /rag rebuild"
