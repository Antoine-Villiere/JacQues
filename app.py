from __future__ import annotations

from pathlib import Path
from typing import List
import re
from urllib.parse import urlparse, quote
import sqlite3
import threading

from dotenv import load_dotenv
from flask import abort, send_from_directory, request, jsonify
import dash
from dash import dcc, html, dash_table, Input, Output, State, no_update, ALL

from jacques import db
from jacques.config import (
    BASE_DIR,
    DATA_DIR,
    IMAGES_DIR,
    UPLOADS_DIR,
    Settings,
    ensure_dirs,
)
from jacques.services import assistant, doc_ingest, file_ops, pdf_tools, rag, vision, web_search
from jacques.utils import decode_upload, safe_filename


load_dotenv(BASE_DIR / ".env", override=True)
ensure_dirs()

db.init_db()
settings = Settings()
STREAMING_STATUS: dict[int, bool] = {}
STREAMING_LOCK = threading.Lock()
TOOL_STATUS: dict[int, dict[str, str]] = {}
TOOL_LOCK = threading.Lock()
INITIAL_SYSTEM_PROMPT = db.get_setting("system_prompt") or assistant.SYSTEM_PROMPT
INITIAL_GLOBAL_MEMORY = db.get_setting("global_memory") or ""


def _set_streaming(conversation_id: int, value: bool) -> None:
    with STREAMING_LOCK:
        STREAMING_STATUS[conversation_id] = value


def _is_streaming(conversation_id: int) -> bool:
    with STREAMING_LOCK:
        return STREAMING_STATUS.get(conversation_id, False)


def _set_tool_status(conversation_id: int, name: str | None, stage: str) -> None:
    with TOOL_LOCK:
        if not name:
            TOOL_STATUS.pop(conversation_id, None)
            return
        TOOL_STATUS[conversation_id] = {"name": name, "stage": stage}


def _get_tool_status(conversation_id: int) -> dict[str, str] | None:
    with TOOL_LOCK:
        return TOOL_STATUS.get(conversation_id)


def _ensure_default_conversation() -> int:
    conversations = db.list_conversations()
    if conversations:
        return int(conversations[0]["id"])
    return db.create_conversation("Conversation 1")


def _conversation_options() -> list[dict[str, str]]:
    return [
        {"label": row["title"], "value": str(row["id"])}
        for row in db.list_conversations()
    ]


def _message_class(role: str) -> str:
    if role in {"user", "assistant", "tool"}:
        return f"message message-{role}"
    return "message message-tool"


def _tool_message_is_error(content: str) -> bool:
    lowered = content.lower()
    markers = [
        "failed",
        "error",
        "invalid tool arguments",
        "unknown tool",
        "exception",
        "traceback",
    ]
    return any(marker in lowered for marker in markers)


def _render_messages(rows: List[sqlite3.Row]):
    if not rows:
        return [html.Div("No messages yet.", className="status")]
    rendered = []
    for row in rows:
        role = row["role"]
        if role == "tool" and not _tool_message_is_error(row["content"] or ""):
            continue
        rendered.append(
            html.Div(
                className=_message_class(role),
                children=[
                    html.Div(role.upper(), className="message-role"),
                    dcc.Markdown(
                        row["content"],
                        className="message-content",
                        link_target="_blank",
                    ),
                ],
            )
        )
    return rendered


def _doc_label(doc_type: str) -> tuple[str, str]:
    mapping = {
        ".pdf": ("PDF", "pdf"),
        ".docx": ("DOC", "doc"),
        ".xlsx": ("XLS", "xls"),
        ".xls": ("XLS", "xls"),
        ".xlsm": ("XLS", "xls"),
        ".csv": ("CSV", "csv"),
    }
    return mapping.get(doc_type, ("DOC", "file"))


def _asset_pill(label: str, name: str, kind: str) -> html.Div:
    return html.Div(
        className=f"asset-pill asset-pill--{kind}",
        children=[
            html.Span(label, className="asset-kind"),
            html.Span(name, className="asset-name"),
        ],
    )


def _file_item(label: str, name: str, detail: str, item_id: dict) -> html.Button:
    return html.Button(
        children=[
            html.Div(label, className="file-item-kind"),
            html.Div(
                [
                    html.Div(name, className="file-item-name"),
                    html.Div(detail, className="file-item-meta"),
                ],
                className="file-item-text",
            ),
        ],
        id=item_id,
        n_clicks=0,
        className="file-item",
    )


def _render_assets_row(conversation_id: int, limit: int = 8):
    docs = db.list_documents(conversation_id)
    images = db.list_images(conversation_id)

    items = []
    for doc in docs[:limit]:
        label, kind = _doc_label(doc["doc_type"])
        items.append(_asset_pill(label, doc["name"], kind))

    remaining = limit - len(items)
    if remaining > 0:
        for img in images[:remaining]:
            items.append(_asset_pill("IMG", img["name"], "img"))

    if not items:
        return html.Div("Drop files here to attach context.", className="status")
    return html.Div(items, className="asset-row")


def _stream_response(
    conversation_id: int,
    user_message: str,
    use_rag: bool,
    use_web: bool,
    assistant_message_id: int,
) -> None:
    streamed = False

    def on_token(token: str) -> None:
        nonlocal streamed
        streamed = True
        db.append_message_content(assistant_message_id, token)

    def on_tool_event(name: str, stage: str) -> None:
        _set_tool_status(conversation_id, name, stage)

    reply = ""
    try:
        reply = assistant.respond_streaming(
            conversation_id,
            user_message,
            settings,
            use_rag=use_rag,
            use_web=use_web,
            on_token=on_token,
            on_tool_event=on_tool_event,
        )
    except Exception as exc:
        reply = f"LLM error: {exc}"
    finally:
        if reply:
            db.update_message_content(assistant_message_id, reply)
        elif not streamed:
            db.update_message_content(assistant_message_id, "No response generated.")
        _set_streaming(conversation_id, False)


def _latest_tool_name(conversation_id: int) -> str | None:
    row = db.get_latest_tool_message(conversation_id)
    if not row:
        return None
    content = row["content"] or ""
    match = re.search(r"Tool (?:call|result): \\*\\*(.+?)\\*\\*", content)
    if match:
        return match.group(1).strip()
    return None


def _maybe_delete_file(path: str, table: str) -> None:
    if not path:
        return
    if db.is_path_used(table, path):
        return
    file_path = Path(path)
    if file_path.exists():
        file_path.unlink()


def _parse_sources_from_tool(content: str) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("- ["):
            continue
        match = re.search(r"\\[(.*?)\\]\\((.*?)\\)", line)
        if not match:
            continue
        title = match.group(1).strip()
        url = match.group(2).strip()
        snippet = line[match.end() :].lstrip(" —-").strip()
        sources.append({"title": title, "url": url, "snippet": snippet})
    return sources


def _source_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path.split("/")[0]
    return host.replace("www.", "")


def _empty_source_preview():
    return [
        html.Div(
            className="preview-header",
            children=[
                html.Div("Source preview", className="preview-title"),
                html.Button("Clear", id="clear-source-preview", className="icon-btn"),
            ],
        ),
        html.Div("Select a source to preview.", className="preview-empty"),
    ]


def _data_url(path: str) -> str:
    if not path:
        return ""
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(DATA_DIR)
    except ValueError:
        return ""
    return f"/files/{relative.as_posix()}"


def _load_word_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx is required for Word editing") from exc
    doc = Document(str(path))
    lines = [para.text for para in doc.paragraphs]
    return "\n".join(lines).strip()


def _load_table_data(path: Path, sheet_name: str | None = None):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for table editing") from exc
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        return df, []
    if sheet_name:
        df = pd.read_excel(path, sheet_name=sheet_name)
    else:
        df = pd.read_excel(path, sheet_name=0)
    sheets = []
    try:
        xls = pd.ExcelFile(path)
        sheets = list(xls.sheet_names)
    except Exception:
        sheets = []
    return df, sheets


default_convo_id = _ensure_default_conversation()

app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "Jacques Assistant"

ALLOWED_FILE_DIRS = {"generated", "images", "uploads"}


@app.server.route("/files/<path:asset_path>")
def serve_files(asset_path: str):
    safe_path = Path(asset_path)
    if safe_path.is_absolute() or ".." in safe_path.parts:
        abort(404)
    if not safe_path.parts or safe_path.parts[0] not in ALLOWED_FILE_DIRS:
        abort(404)
    full_path = (DATA_DIR / safe_path).resolve()
    if not full_path.exists() or DATA_DIR not in full_path.parents:
        abort(404)
    return send_from_directory(DATA_DIR, safe_path.as_posix())

app.layout = html.Div(
    id="theme-root",
    className="app-shell",
    **{"data-theme": "light"},
    children=[
        dcc.Store(id="chat-refresh", data=0),
        dcc.Store(id="docs-refresh", data=0),
        dcc.Store(id="images-refresh", data=0),
        dcc.Store(
            id="stream-state",
            data={"convo_id": str(default_convo_id), "is_streaming": False},
        ),
        dcc.Store(id="sources-data", data=[]),
        dcc.Store(id="settings-open", data=False),
        dcc.Store(id="active-file", data=None),
        dcc.Interval(id="stream-interval", interval=120, n_intervals=0),
        html.Div(
            className="sidebar",
            children=[
                html.Div("Jacques", className="brand"),
                html.Div(
                    className="section",
                    children=[
                        html.Div(
                            className="section-header",
                            children=[
                                html.H3("Conversations"),
                                html.Button(
                                    "SYS",
                                    id="open-settings-btn",
                                    className="icon-btn",
                                    **{
                                        "data-tooltip": "System prompt & global memory."
                                    },
                                ),
                            ],
                        ),
                        dcc.Input(
                            id="new-convo-title",
                            placeholder="New conversation title",
                            type="text",
                        ),
                        html.Button("Create", id="new-convo-btn"),
                        dcc.RadioItems(
                            id="convo-dropdown",
                            options=_conversation_options(),
                            value=str(default_convo_id),
                            className="convo-list",
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            className="main",
            children=[
                html.Div(
                    className="chat-header",
                    children=[
                        html.Div(id="chat-title", className="chat-title"),
                        html.Div(
                            className="header-actions",
                            children=[
                                dcc.Checklist(
                                    id="theme-toggle",
                                    options=[{"label": "Dark mode", "value": "dark"}],
                                    value=[],
                                    className="theme-toggle",
                                ),
                                html.Div("Jacques Assistant", className="badge"),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    className="content-shell",
                    children=[
                        html.Div(
                            className="chat-stack",
                            children=[
                                html.Div(id="chat-window", className="chat-window"),
                                html.Div(
                                    className="input-panel",
                                    children=[
                                        html.Div(id="tool-status", className="tool-status"),
                                        html.Div(id="asset-row"),
                                        dcc.Upload(
                                            id="upload-assets",
                                            className="upload-wrap",
                                            multiple=True,
                                            disable_click=True,
                                            accept="image/*,.pdf,.docx,.xlsx,.xls,.xlsm,.csv",
                                            children=html.Div(
                                                className="chat-input upload-zone",
                                                children=[
                                                    dcc.Textarea(
                                                        id="user-input",
                                                        placeholder="Ask Jacques or drop files here",
                                                    ),
                                                    html.Button(
                                                        "Send",
                                                        id="send-btn",
                                                        className="send-btn",
                                                    ),
                                                    html.Div(
                                                        "Drag & drop files here",
                                                        className="upload-hint",
                                                    ),
                                                ],
                                            ),
                                        ),
                                        html.Div(id="upload-status", className="status"),
                                        html.Div(id="stream-status", className="status"),
                                        html.Div(id="action-status", className="status"),
                                    ],
                                ),
                            ],
                        ),
                        html.Div(
                            className="side-panel",
                            children=[
                                dcc.Tabs(
                                    id="side-tabs",
                                    value="sources",
                                    className="side-tabs",
                                    children=[
                                        dcc.Tab(
                                            label="Sources",
                                            value="sources",
                                            className="side-tab",
                                            selected_className="side-tab side-tab--active",
                                            children=[
                                                html.Div(
                                                    id="sources-list",
                                                    className="sources-list",
                                                ),
                                                html.Div(
                                                    id="source-preview",
                                                    className="source-preview",
                                                    children=_empty_source_preview(),
                                                ),
                                            ],
                                        ),
                                        dcc.Tab(
                                            label="Fichiers",
                                            value="files",
                                            className="side-tab",
                                            selected_className="side-tab side-tab--active",
                                            children=[
                                                html.Div(
                                                    id="files-list",
                                                    className="files-list",
                                                )
                                            ],
                                        ),
                                    ],
                                )
                            ],
                        ),
                    ],
                ),
                html.Div(
                    id="file-offcanvas",
                    className="offcanvas",
                    children=[
                        html.Div(
                            className="offcanvas-header",
                            children=[
                                html.Div(
                                    id="file-editor-title",
                                    className="offcanvas-title",
                                ),
                                html.Button(
                                    "Close",
                                    id="close-file-btn",
                                    className="icon-btn",
                                ),
                            ],
                        ),
                        html.Div(
                            id="file-editor-body",
                            className="offcanvas-body",
                        ),
                        html.Div(id="file-save-status", className="status"),
                    ],
                ),
            ],
        ),
        html.Div(
            id="settings-modal",
            className="modal",
            children=[
                html.Div(id="settings-backdrop", className="modal-backdrop"),
                html.Div(
                    className="modal-card",
                    children=[
                        html.Div(
                            className="modal-header",
                            children=[
                                html.Div(
                                    "SYSTEM PROMPT | GLOBAL MEMORY",
                                    className="modal-title",
                                ),
                                html.Button(
                                    "X",
                                    id="close-settings-btn",
                                    className="icon-btn",
                                ),
                            ],
                        ),
                        html.Div(
                            className="modal-body",
                            children=[
                                html.Div("System prompt", className="field-label"),
                                dcc.Textarea(
                                    id="system-prompt-input",
                                    value=INITIAL_SYSTEM_PROMPT,
                                    className="settings-textarea settings-textarea--prompt",
                                    rows=6,
                                ),
                                html.Button(
                                    "Save prompt",
                                    id="save-prompt-btn",
                                    className="settings-btn secondary",
                                ),
                                html.Div(id="prompt-status", className="status"),
                                html.Div("Global memory", className="field-label"),
                                dcc.Textarea(
                                    id="global-memory-input",
                                    value=INITIAL_GLOBAL_MEMORY,
                                    className="settings-textarea settings-textarea--memory",
                                    rows=5,
                                ),
                                html.Button(
                                    "Save memory",
                                    id="save-memory-btn",
                                    className="settings-btn",
                                ),
                                html.Div(id="memory-status", className="status"),
                                html.Div(
                                    "Saved memory (future chats)", className="field-label"
                                ),
                                html.Div(id="memory-preview", className="memory-preview"),
                                html.Button(
                                    "Delete conversation",
                                    id="delete-convo-btn",
                                    className="settings-btn danger",
                                    **{
                                        "data-tooltip": "Deletes this conversation and its assets."
                                    },
                                ),
                                html.Div(id="convo-status", className="status"),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    ],
)


@app.callback(
    Output("convo-dropdown", "options", allow_duplicate=True),
    Output("convo-dropdown", "value", allow_duplicate=True),
    Output("new-convo-title", "value"),
    Input("new-convo-btn", "n_clicks"),
    State("new-convo-title", "value"),
    prevent_initial_call=True,
)
def create_conversation(n_clicks: int, title: str | None):
    if not n_clicks:
        return no_update, no_update, no_update
    clean_title = (title or "").strip() or f"Conversation {len(db.list_conversations()) + 1}"
    convo_id = db.create_conversation(clean_title)
    return _conversation_options(), str(convo_id), ""


@app.callback(
    Output("chat-window", "children"),
    Output("chat-title", "children"),
    Input("convo-dropdown", "value"),
    Input("chat-refresh", "data"),
)
def refresh_chat(convo_id: str | None, refresh: int):
    if not convo_id:
        return [html.Div("Select a conversation.", className="status")], ""
    conversation = db.get_conversation(int(convo_id))
    rows = db.get_messages(int(convo_id))
    title = conversation["title"] if conversation else "Conversation"
    return _render_messages(rows), title


@app.callback(
    Output("chat-refresh", "data", allow_duplicate=True),
    Output("action-status", "children"),
    Output("user-input", "value"),
    Input("send-btn", "n_clicks"),
    State("chat-refresh", "data"),
    State("convo-dropdown", "value"),
    State("user-input", "value"),
    prevent_initial_call=True,
)
def send_message(
    n_clicks: int,
    refresh_value: int,
    convo_id: str | None,
    user_text: str | None,
):
    if not n_clicks:
        return no_update, no_update, no_update
    message = (user_text or "").strip()
    if not message:
        return no_update, "Type a message first.", ""
    if not convo_id:
        convo_id = str(db.create_conversation("Conversation 1"))

    use_rag = bool(db.list_documents(int(convo_id)))
    use_web = True

    conversation_id = int(convo_id)
    if _is_streaming(conversation_id):
        return no_update, "A response is already streaming.", ""

    db.add_message(conversation_id, "user", message)

    def on_tool_event(name: str, stage: str) -> None:
        _set_tool_status(conversation_id, name, stage)

    if settings.llm_streaming:
        assistant_message_id = db.add_message(conversation_id, "assistant", "")
        _set_streaming(conversation_id, True)
        thread = threading.Thread(
            target=_stream_response,
            args=(
                conversation_id,
                message,
                use_rag,
                use_web,
                assistant_message_id,
            ),
            daemon=True,
        )
        thread.start()
        return refresh_value + 1, "Streaming response...", ""

    reply = assistant.respond(
        conversation_id,
        message,
        settings,
        use_rag=use_rag,
        use_web=use_web,
        on_tool_event=on_tool_event,
    )
    db.add_message(conversation_id, "assistant", reply)
    return refresh_value + 1, "Response generated.", ""


@app.callback(
    Output("docs-refresh", "data"),
    Output("images-refresh", "data"),
    Output("upload-status", "children"),
    Input("upload-assets", "contents"),
    State("upload-assets", "filename"),
    State("convo-dropdown", "value"),
    State("docs-refresh", "data"),
    State("images-refresh", "data"),
    prevent_initial_call=True,
)
def upload_assets(contents_list, filenames, convo_id, docs_refresh, images_refresh):
    if not contents_list or not filenames:
        return no_update, no_update, no_update
    if not convo_id:
        convo_id = str(db.create_conversation("Conversation 1"))
    conversation_id = int(convo_id)

    doc_updated = False
    image_updated = False
    messages = []
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    doc_exts = {".pdf", ".docx", ".xlsx", ".xls", ".xlsm", ".csv"}

    for contents, filename in zip(contents_list, filenames):
        safe_name = safe_filename(filename)
        data, _ = decode_upload(contents)
        suffix = Path(safe_name).suffix.lower()
        if suffix in image_exts:
            path = IMAGES_DIR / safe_name
            path.write_bytes(data)
            try:
                description = vision.describe_image(path, settings)
            except Exception as exc:
                description = f"Vision failed: {exc}"
            db.add_image(conversation_id, safe_name, str(path), description)
            image_updated = True
            messages.append(f"Stored {safe_name}")
        elif suffix in doc_exts:
            path = UPLOADS_DIR / safe_name
            path.write_bytes(data)
            try:
                text = doc_ingest.extract_text(path)
                db.add_document(
                    conversation_id, safe_name, str(path), path.suffix.lower(), text
                )
                doc_updated = True
                messages.append(f"Ingested {safe_name}")
            except Exception as exc:
                messages.append(f"Failed {safe_name}: {exc}")
        else:
            messages.append(f"Unsupported file: {safe_name}")

    if doc_updated:
        rag.build_index(conversation_id)

    docs_next = (docs_refresh or 0) + 1 if doc_updated else no_update
    images_next = (images_refresh or 0) + 1 if image_updated else no_update
    status = " | ".join(messages) if messages else "Upload complete."
    return docs_next, images_next, status


@app.callback(
    Output("asset-row", "children"),
    Input("docs-refresh", "data"),
    Input("images-refresh", "data"),
    Input("convo-dropdown", "value"),
)
def refresh_assets(docs_refresh: int, images_refresh: int, convo_id: str | None):
    if not convo_id:
        return html.Div("No conversation selected.", className="status")
    return _render_assets_row(int(convo_id))


@app.callback(
    Output("sources-data", "data"),
    Output("sources-list", "children"),
    Input("chat-refresh", "data"),
    Input("stream-interval", "n_intervals"),
    State("convo-dropdown", "value"),
)
def refresh_sources(refresh_value: int, n_intervals: int, convo_id: str | None):
    if not convo_id:
        return [], ""
    row = db.get_latest_web_search_message(int(convo_id))
    if not row:
        return [], ""
    sources = _parse_sources_from_tool(row["content"] or "")
    if not sources:
        return [], ""

    items = []
    for idx, source in enumerate(sources):
        title = source.get("title") or _source_domain(source.get("url", "")) or "Source"
        domain = _source_domain(source.get("url", ""))
        snippet = source.get("snippet") or ""
        items.append(
            html.Button(
                children=[
                    html.Div(title, className="source-title"),
                    html.Div(domain, className="source-domain"),
                    html.Div(snippet, className="source-snippet"),
                ],
                id={"type": "source-item", "index": idx},
                n_clicks=0,
                className="source-item",
            )
        )

    return sources, html.Div(
        [
            html.Div("Sources", className="sources-title"),
            html.Div(items, className="sources-items"),
        ],
        className="sources-block",
    )


@app.callback(
    Output("files-list", "children"),
    Input("docs-refresh", "data"),
    Input("images-refresh", "data"),
    Input("convo-dropdown", "value"),
)
def refresh_files(docs_refresh: int, images_refresh: int, convo_id: str | None):
    if not convo_id:
        return html.Div("No conversation selected.", className="status")
    conversation_id = int(convo_id)
    docs = db.list_documents(conversation_id)
    images = db.list_images(conversation_id)
    if not docs and not images:
        return html.Div("No files yet.", className="status")

    items = []
    for doc in docs:
        label, kind = _doc_label(doc["doc_type"])
        items.append(
            _file_item(
                label,
                doc["name"],
                doc["doc_type"].upper(),
                {"type": "file-item", "index": f"doc-{doc['id']}"},
            )
        )

    for img in images:
        items.append(
            _file_item(
                "IMG",
                img["name"],
                "IMAGE",
                {"type": "file-item", "index": f"img-{img['id']}"},
            )
        )

    return html.Div(
        [
            html.Div("Files", className="sources-title"),
            html.Div(items, className="files-items"),
        ],
        className="files-block",
    )


@app.callback(
    Output("active-file", "data"),
    Input({"type": "file-item", "index": ALL}, "n_clicks"),
    Input("close-file-btn", "n_clicks"),
    State("convo-dropdown", "value"),
    prevent_initial_call=True,
)
def select_file(
    file_clicks: list[int],
    close_clicks: int | None,
    convo_id: str | None,
):
    trigger = dash.callback_context.triggered_id
    if trigger == "close-file-btn":
        return None
    if not isinstance(trigger, dict) or trigger.get("type") != "file-item":
        return no_update
    if not convo_id:
        return no_update

    index = str(trigger.get("index", ""))
    if index.startswith("doc-"):
        doc_id = int(index.split("-", 1)[1])
        doc = db.get_document_by_id(doc_id)
        if not doc or str(doc["conversation_id"]) != str(convo_id):
            return no_update
        return {
            "kind": "doc",
            "id": doc_id,
            "name": doc["name"],
            "path": doc["path"],
            "doc_type": doc["doc_type"],
        }
    if index.startswith("img-"):
        image_id = int(index.split("-", 1)[1])
        image = db.get_image_by_id(image_id)
        if not image or str(image["conversation_id"]) != str(convo_id):
            return no_update
        return {
            "kind": "img",
            "id": image_id,
            "name": image["name"],
            "path": image["path"],
        }
    return no_update


@app.callback(
    Output("file-offcanvas", "className"),
    Output("file-editor-title", "children"),
    Output("file-editor-body", "children"),
    Input("active-file", "data"),
)
def render_file_offcanvas(active_file: dict | None):
    if not active_file:
        return "offcanvas", "", ""

    name = active_file.get("name") or "File"
    kind = active_file.get("kind")
    path_str = active_file.get("path") or ""
    path = Path(path_str)

    if kind == "img":
        url = _data_url(path_str)
        body = html.Div(
            [
                html.Img(src=url, className="file-image"),
                html.Div(name, className="file-meta"),
            ],
            className="file-viewer",
        )
        return "offcanvas offcanvas--open", name, body

    doc_type = (active_file.get("doc_type") or path.suffix).lower()
    if doc_type == ".pdf":
        file_url = _data_url(path_str)
        iframe_src = f"/assets/pdf_viewer.html?file={quote(file_url)}&doc_id={active_file.get('id')}"
        body = html.Div(
            [
                html.Iframe(src=iframe_src, className="pdf-frame"),
            ],
            className="file-viewer",
        )
        return "offcanvas offcanvas--open", name, body

    if doc_type == ".docx":
        try:
            text = _load_word_text(path)
            status = ""
        except Exception as exc:
            text = ""
            status = f"Word load failed: {exc}"
        body = html.Div(
            [
                dcc.Textarea(
                    id="word-editor",
                    value=text,
                    className="file-textarea",
                ),
                html.Button("Save changes", id="save-word-btn", className="send-btn"),
                html.Div(status, className="status"),
            ],
            className="file-editor",
        )
        return "offcanvas offcanvas--open", name, body

    if doc_type in {".xlsx", ".xls", ".xlsm", ".csv"}:
        sheet_value = None
        try:
            df, sheets = _load_table_data(path)
            if sheets:
                sheet_value = sheets[0]
                df, _ = _load_table_data(path, sheet_name=sheet_value)
            status = ""
        except Exception as exc:
            df = None
            sheets = []
            status = f"Table load failed: {exc}"

        if df is None:
            body = html.Div(status, className="status")
        else:
            df = df.fillna("")
            columns = [{"name": col, "id": col} for col in df.columns]
            table = dash_table.DataTable(
                id="excel-editor",
                data=df.to_dict("records"),
                columns=columns,
                editable=True,
                page_size=12,
                style_table={"overflowX": "auto"},
                style_cell={
                    "minWidth": "120px",
                    "width": "160px",
                    "maxWidth": "260px",
                    "whiteSpace": "normal",
                },
            )
            sheet_select = ""
            if sheets:
                sheet_select = dcc.Dropdown(
                    id="sheet-selector",
                    options=[{"label": sheet, "value": sheet} for sheet in sheets],
                    value=sheet_value,
                    clearable=False,
                    className="sheet-selector",
                )
            body = html.Div(
                [
                    sheet_select,
                    table,
                    html.Button("Save changes", id="save-table-btn", className="send-btn"),
                    html.Div(status, className="status"),
                ],
                className="file-editor",
            )
        return "offcanvas offcanvas--open", name, body

    return "offcanvas offcanvas--open", name, html.Div(
        "Unsupported file type.", className="status"
    )


@app.callback(
    Output("excel-editor", "data"),
    Output("excel-editor", "columns"),
    Input("sheet-selector", "value"),
    State("active-file", "data"),
    prevent_initial_call=True,
)
def switch_excel_sheet(sheet_name: str | None, active_file: dict | None):
    if not active_file or not sheet_name:
        return no_update, no_update
    path = Path(active_file.get("path") or "")
    try:
        df, _ = _load_table_data(path, sheet_name=sheet_name)
    except Exception:
        return no_update, no_update
    df = df.fillna("")
    columns = [{"name": col, "id": col} for col in df.columns]
    return df.to_dict("records"), columns


@app.callback(
    Output("file-save-status", "children"),
    Output("docs-refresh", "data", allow_duplicate=True),
    Input("save-word-btn", "n_clicks"),
    Input("save-table-btn", "n_clicks"),
    State("word-editor", "value"),
    State("excel-editor", "data"),
    State("excel-editor", "columns"),
    State("sheet-selector", "value"),
    State("active-file", "data"),
    State("docs-refresh", "data"),
    prevent_initial_call=True,
)
def save_file_edits(
    save_word: int | None,
    save_table: int | None,
    word_text: str | None,
    table_data: list[dict] | None,
    table_columns: list[dict] | None,
    sheet_name: str | None,
    active_file: dict | None,
    docs_refresh: int,
):
    trigger = dash.callback_context.triggered_id
    if not active_file or not trigger:
        return no_update, no_update
    if active_file.get("kind") != "doc":
        return "Only documents can be edited.", no_update

    doc_id = int(active_file.get("id") or 0)
    doc_row = db.get_document_by_id(doc_id)
    if not doc_row:
        return "Document not found.", no_update

    path = Path(doc_row["path"])
    doc_type = (doc_row["doc_type"] or path.suffix).lower()

    try:
        if trigger == "save-word-btn":
            if doc_type != ".docx":
                return "This file is not a Word document.", no_update
            file_ops.write_word(path, word_text or "")
        elif trigger == "save-table-btn":
            if doc_type not in {".xlsx", ".xls", ".xlsm", ".csv"}:
                return "This file is not a table.", no_update
            try:
                import pandas as pd
            except ImportError as exc:
                return f"Pandas is required: {exc}", no_update
            columns = [col["id"] for col in (table_columns or [])]
            df = pd.DataFrame(table_data or [], columns=columns)
            if doc_type == ".csv":
                df.to_csv(path, index=False)
            else:
                sheet = sheet_name or "Sheet1"
                with pd.ExcelWriter(
                    path, engine="openpyxl", mode="a", if_sheet_exists="replace"
                ) as writer:
                    df.to_excel(writer, sheet_name=sheet, index=False)
        else:
            return no_update, no_update
    except Exception as exc:
        return f"Save failed: {exc}", no_update

    try:
        text = doc_ingest.extract_text(path)
        db.update_document_text(doc_id, text)
        rag.build_index(int(doc_row["conversation_id"]))
    except Exception:
        pass

    return "Saved changes.", (docs_refresh or 0) + 1


@app.callback(
    Output("theme-root", "data-theme"),
    Input("theme-toggle", "value"),
)
def toggle_theme(theme_value: list[str] | None):
    return "dark" if theme_value and "dark" in theme_value else "light"


@app.callback(
    Output("settings-open", "data"),
    Input("open-settings-btn", "n_clicks"),
    Input("close-settings-btn", "n_clicks"),
    Input("settings-backdrop", "n_clicks"),
    State("settings-open", "data"),
    prevent_initial_call=True,
)
def toggle_settings_modal(
    open_clicks: int | None,
    close_clicks: int | None,
    backdrop_clicks: int | None,
    is_open: bool,
):
    trigger = dash.callback_context.triggered_id
    if trigger == "open-settings-btn":
        return True
    if trigger in {"close-settings-btn", "settings-backdrop"}:
        return False
    return is_open


@app.callback(
    Output("settings-modal", "className"),
    Input("settings-open", "data"),
)
def render_settings_modal(is_open: bool):
    return "modal modal--open" if is_open else "modal"


@app.callback(
    Output("prompt-status", "children"),
    Output("system-prompt-input", "value"),
    Input("save-prompt-btn", "n_clicks"),
    State("system-prompt-input", "value"),
    prevent_initial_call=True,
)
def save_system_prompt(n_clicks: int, prompt_text: str | None):
    if not n_clicks:
        return no_update, no_update
    prompt = (prompt_text or "").strip()
    if not prompt:
        db.set_setting("system_prompt", "")
        return "System prompt reset to default.", assistant.SYSTEM_PROMPT
    db.set_setting("system_prompt", prompt)
    return "System prompt saved.", prompt


@app.callback(
    Output("memory-status", "children"),
    Output("global-memory-input", "value"),
    Input("save-memory-btn", "n_clicks"),
    State("global-memory-input", "value"),
    prevent_initial_call=True,
)
def save_global_memory(n_clicks: int, memory_text: str | None):
    if not n_clicks:
        return no_update, no_update
    memory = (memory_text or "").strip()
    db.set_setting("global_memory", memory)
    status = "Global memory saved." if memory else "Global memory cleared."
    return status, memory


@app.callback(
    Output("memory-preview", "children"),
    Input("chat-refresh", "data"),
    Input("memory-status", "children"),
)
def refresh_memory_preview(refresh_value: int, memory_status: str | None):
    memory = db.get_setting("global_memory") or ""
    if not memory.strip():
        return html.Div("No saved memory yet.", className="status")
    return dcc.Markdown(memory, link_target="_blank")


@app.callback(
    Output("convo-dropdown", "options", allow_duplicate=True),
    Output("convo-dropdown", "value", allow_duplicate=True),
    Output("convo-status", "children"),
    Input("delete-convo-btn", "n_clicks"),
    State("convo-dropdown", "value"),
    prevent_initial_call=True,
)
def delete_conversation(n_clicks: int, convo_id: str | None):
    if not n_clicks:
        return no_update, no_update, no_update
    if not convo_id:
        return no_update, no_update, "Select a conversation first."
    conversation_id = int(convo_id)
    if _is_streaming(conversation_id):
        return no_update, no_update, "Wait for the streaming response to finish."
    _set_tool_status(conversation_id, None, "idle")

    docs = db.list_documents(conversation_id)
    images = db.list_images(conversation_id)
    db.delete_conversation(conversation_id)
    rag.delete_index(conversation_id)
    _set_streaming(conversation_id, False)

    for doc in docs:
        _maybe_delete_file(doc["path"], "documents")
    for img in images:
        _maybe_delete_file(img["path"], "images")

    conversations = db.list_conversations()
    if conversations:
        next_value = str(conversations[0]["id"])
    else:
        next_value = str(db.create_conversation("Conversation 1"))

    return _conversation_options(), next_value, "Conversation deleted."


@app.callback(
    Output("tool-status", "children"),
    Input("chat-refresh", "data"),
    Input("stream-interval", "n_intervals"),
    State("convo-dropdown", "value"),
)
def refresh_tool_status(refresh_value: int, n_intervals: int, convo_id: str | None):
    if not convo_id:
        return ""
    conversation_id = int(convo_id)
    state = _get_tool_status(conversation_id) or {}
    tool_name = state.get("name") or _latest_tool_name(conversation_id)
    stage = state.get("stage", "result") if tool_name else "idle"

    if tool_name:
        if stage == "call":
            text = f"Outil en cours: {tool_name}"
            loader_class = "tool-loader"
        else:
            text = f"Dernier outil: {tool_name}"
            loader_class = "tool-loader tool-loader--idle"
    else:
        text = "Aucun outil appele."
        loader_class = "tool-loader tool-loader--idle"
    return html.Div(
        [
            html.Span(text, className="tool-status-text"),
            html.Span(className=loader_class),
        ],
        className="tool-status-row",
    )


@app.callback(
    Output("source-preview", "children"),
    Input({"type": "source-item", "index": ALL}, "n_clicks"),
    Input("clear-source-preview", "n_clicks"),
    Input("convo-dropdown", "value"),
    State("sources-data", "data"),
    prevent_initial_call=True,
)
def open_source_preview(
    source_clicks: list[int],
    clear_clicks: int | None,
    convo_id: str | None,
    sources: list[dict[str, str]],
):
    trigger = dash.callback_context.triggered_id
    if trigger in {"clear-source-preview", "convo-dropdown"}:
        return _empty_source_preview()
    if not isinstance(trigger, dict) or trigger.get("type") != "source-item":
        return _empty_source_preview()

    index = int(trigger.get("index", 0))
    if not sources or index >= len(sources):
        return _empty_source_preview()

    source = sources[index]
    url = source.get("url", "")
    title = source.get("title") or _source_domain(url) or "Source"
    snippet = source.get("snippet") or ""
    preview_text = ""
    if url:
        try:
            preview_text = web_search.fetch_url(url, settings)
        except Exception as exc:
            preview_text = f"Preview failed: {exc}"
    preview_text = preview_text.strip()
    if preview_text:
        max_len = 2000
        if len(preview_text) > max_len:
            preview_text = preview_text[:max_len].rsplit(" ", 1)[0] + "..."

    return [
        html.Div(
            className="preview-header",
            children=[
                html.Div(title, className="preview-title"),
                html.Button(
                    "Clear",
                    id="clear-source-preview",
                    className="icon-btn",
                ),
            ],
        ),
        html.Div(
            className="preview-meta",
            children=[
                html.A(url, href=url, target="_blank", rel="noreferrer"),
                html.Span(_source_domain(url), className="preview-domain"),
            ],
        ),
        html.Div(snippet, className="preview-snippet"),
        html.Div(
            preview_text or "No preview available.",
            className="preview-body",
        ),
    ]


@app.callback(
    Output("chat-refresh", "data", allow_duplicate=True),
    Output("stream-status", "children"),
    Output("stream-state", "data"),
    Input("stream-interval", "n_intervals"),
    State("chat-refresh", "data"),
    State("convo-dropdown", "value"),
    State("stream-state", "data"),
    prevent_initial_call=True,
)
def poll_stream(
    n_intervals: int,
    refresh_value: int,
    convo_id: str | None,
    stream_state: dict | None,
):
    if not convo_id:
        return no_update, "", stream_state or {}
    conversation_id = int(convo_id)
    is_streaming = _is_streaming(conversation_id)
    was_streaming = False
    if stream_state and stream_state.get("convo_id") == convo_id:
        was_streaming = bool(stream_state.get("is_streaming"))

    next_state = {"convo_id": convo_id, "is_streaming": is_streaming}

    if is_streaming:
        return (refresh_value or 0) + 1, "Streaming...", next_state
    if was_streaming and not is_streaming:
        return (refresh_value or 0) + 1, "", next_state
    return no_update, "", next_state


if __name__ == "__main__":
    app.run_server(debug=True)
