from __future__ import annotations

from pathlib import Path
from typing import List
import json
import re
import time
from urllib.parse import quote
import sqlite3
import threading
import warnings

warnings.filterwarnings(
    "ignore",
    message="Valid config keys have changed in V2:",
    category=UserWarning,
)

from dotenv import load_dotenv
from flask import abort, send_from_directory, request, jsonify
import requests
import dash
from dash import dcc, html, dash_table, Input, Output, State, no_update, ALL, MATCH

from jacques import db
from jacques.config import (
    BASE_DIR,
    DATA_DIR,
    IMAGES_DIR,
    UPLOADS_DIR,
    Settings,
    ensure_dirs,
)
from jacques.services import assistant, doc_ingest, file_ops, pdf_tools, rag, vision
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
        assistant.maybe_update_conversation_title(
            conversation_id, settings, force_first=True
        )
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


def _data_url(path: str) -> str:
    if not path:
        return ""
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(DATA_DIR)
    except ValueError:
        return ""
    return f"/files/{quote(relative.as_posix(), safe='/')}"


def _absolute_file_url(path: str) -> str:
    relative = _data_url(path)
    if not relative:
        return ""
    base = (settings.app_base_url or "").rstrip("/")
    if not base:
        return relative
    return f"{base}{relative}"


def _load_word_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx is required for Word editing") from exc
    doc = Document(str(path))
    lines = [para.text for para in doc.paragraphs]
    return "\n".join(lines).strip()


def _format_word_preview(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx is required for Word editing") from exc
    doc = Document(str(path))
    lines = []
    for idx, para in enumerate(doc.paragraphs, start=1):
        text = para.text.strip()
        if text:
            lines.append(f"{idx}. {text}")
    return "\n".join(lines).strip() or "No text content found."


def _format_word_preview_html(path: Path) -> str:
    try:
        import mammoth
    except ImportError:
        return ""
    with path.open("rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
    html_body = (result.value or "").strip()
    if not html_body:
        return ""
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <style>
      body {{
        font-family: "Times New Roman", serif;
        color: #111;
        background: #fff;
        padding: 20px 24px;
        line-height: 1.5;
      }}
      h1, h2, h3, h4, h5, h6 {{
        font-family: "Times New Roman", serif;
        margin: 0 0 0.6em;
      }}
      p {{
        margin: 0 0 0.85em;
      }}
      table {{
        border-collapse: collapse;
        width: 100%;
        margin: 0 0 1em;
      }}
      td, th {{
        border: 1px solid #ddd;
        padding: 6px 8px;
      }}
    </style>
  </head>
  <body>
    {html_body}
  </body>
</html>"""


def _render_word_preview(path: Path):
    html_doc = _format_word_preview_html(path)
    if html_doc:
        return html.Iframe(srcDoc=html_doc, className="docx-frame")
    preview = _format_word_preview(path)
    return html.Pre(preview, className="file-preview")


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


def _coerce_cell_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


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


@app.server.route("/pdf_highlight", methods=["POST"])
def handle_pdf_highlight():
    payload = request.get_json(silent=True) or {}
    doc_id = int(payload.get("doc_id") or 0)
    text = str(payload.get("text") or "").strip()
    page_number = payload.get("page")
    page_value = None
    if page_number is not None and str(page_number).strip():
        try:
            page_value = int(page_number)
        except ValueError:
            page_value = None

    if not doc_id or not text:
        return jsonify({"success": False, "message": "Missing highlight data."}), 400
    doc = db.get_document_by_id(doc_id)
    if not doc:
        return jsonify({"success": False, "message": "Document not found."}), 404
    path = Path(doc["path"]).resolve()
    if path.suffix.lower() != ".pdf":
        return jsonify({"success": False, "message": "Not a PDF file."}), 400
    if DATA_DIR not in path.parents:
        return jsonify({"success": False, "message": "Invalid file path."}), 400

    try:
        count = pdf_tools.highlight_text(path, text, page_value)
    except Exception as exc:
        return jsonify({"success": False, "message": f"Highlight failed: {exc}"}), 500

    if count == 0:
        return jsonify(
            {"success": False, "message": "No matching text found."}
        ), 200

    db.add_pdf_highlight(doc_id, page_value, text)
    try:
        rag.build_index(int(doc["conversation_id"]))
    except Exception:
        pass

    return jsonify(
        {"success": True, "message": f"Highlighted {count} match(es)."}
    )


@app.server.route("/onlyoffice/<int:doc_id>")
def onlyoffice_editor(doc_id: int):
    if not settings.onlyoffice_url:
        abort(404)
    doc = db.get_document_by_id(doc_id)
    if not doc:
        abort(404)

    path = Path(doc["path"])
    if not path.exists():
        abort(404)

    file_url = _absolute_file_url(doc["path"])
    if not file_url:
        abort(404)

    file_type = path.suffix.lstrip(".").lower()
    key_seed = f"{doc_id}-{int(path.stat().st_mtime)}-{path.name}"
    key = str(abs(hash(key_seed)))
    callback_url = f"{settings.app_base_url.rstrip('/')}/onlyoffice_callback?doc_id={doc_id}"

    config = {
        "document": {
            "fileType": file_type,
            "key": key,
            "title": doc["name"],
            "url": file_url,
        },
        "editorConfig": {
            "mode": "edit",
            "callbackUrl": callback_url,
        },
    }

    token_script = ""
    if settings.onlyoffice_jwt:
        try:
            import jwt
        except ImportError:
            return (
                "PyJWT is required for ONLYOFFICE_JWT. Install PyJWT.",
                500,
            )
        token = jwt.encode(config, settings.onlyoffice_jwt, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        config["token"] = token
        token_script = f'var token = "{token}";'

    docserver = settings.onlyoffice_url.rstrip("/")
    html = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{doc["name"]}</title>
    <style>
      html, body {{
        margin: 0;
        padding: 0;
        height: 100%;
        background: #0f141b;
      }}
      #editor {{
        height: 100%;
        width: 100%;
      }}
    </style>
  </head>
  <body>
    <div id="editor"></div>
    <script src="{docserver}/web-apps/apps/api/documents/api.js"></script>
    <script>
      {token_script}
      var config = {json.dumps(config)};
      var docEditor = new DocsAPI.DocEditor("editor", config);
    </script>
  </body>
</html>"""
    return html, 200, {"Content-Type": "text/html"}


@app.server.route("/onlyoffice_callback", methods=["POST"])
def onlyoffice_callback():
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    download_url = payload.get("url")
    doc_id = request.args.get("doc_id")
    if not doc_id:
        return jsonify({"error": 0})
    try:
        doc_id_int = int(doc_id)
    except ValueError:
        return jsonify({"error": 0})

    if status in {2, 6} and download_url:
        doc = db.get_document_by_id(doc_id_int)
        if doc:
            path = Path(doc["path"])
            try:
                response = requests.get(download_url, timeout=settings.web_timeout)
                response.raise_for_status()
                path.write_bytes(response.content)
                text = doc_ingest.extract_text(path)
                db.update_document_text(doc_id_int, text)
                rag.build_index(int(doc["conversation_id"]))
            except Exception:
                pass
    return jsonify({"error": 0})

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
        dcc.Store(id="settings-open", data=False),
        dcc.Store(id="active-file", data=None),
        dcc.Store(id="scroll-trigger", data=0),
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
                                html.Div(
                                    className="section-actions",
                                    children=[
                                        html.Button(
                                            "+",
                                            id="new-convo-btn",
                                            className="icon-btn icon-btn--add",
                                            **{
                                                "data-tooltip": "New conversation."
                                            },
                                        ),
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
                            ],
                        ),
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
                        html.Div(
                            className="chat-title-block",
                            children=[
                                html.Div(
                                    className="chat-title-row",
                                    children=[
                                        html.Div(
                                            id="chat-title", className="chat-title"
                                        ),
                                        html.Button(
                                            "✎",
                                            id="edit-title-btn",
                                            className="icon-btn icon-btn--edit",
                                            **{
                                                "data-tooltip": "Rename conversation."
                                            },
                                        ),
                                    ],
                                ),
                                html.Div(
                                    id="title-edit-row",
                                    className="title-edit-row",
                                    children=[
                                        dcc.Input(
                                            id="title-edit-input",
                                            type="text",
                                            placeholder="New title",
                                        ),
                                        html.Button(
                                            "Save",
                                            id="save-title-btn",
                                            className="icon-btn",
                                        ),
                                        html.Button(
                                            "Cancel",
                                            id="cancel-title-btn",
                                            className="icon-btn",
                                        ),
                                    ],
                                ),
                            ],
                        ),
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
                                html.Div(
                                    id="files-list",
                                    className="files-list",
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
    Input("new-convo-btn", "n_clicks"),
    prevent_initial_call=True,
)
def create_conversation(n_clicks: int):
    if not n_clicks:
        return no_update, no_update
    clean_title = f"Conversation {len(db.list_conversations()) + 1}"
    convo_id = db.create_conversation(clean_title)
    return _conversation_options(), str(convo_id)


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
    Output("convo-dropdown", "options", allow_duplicate=True),
    Input("chat-refresh", "data"),
    prevent_initial_call=True,
)
def refresh_conversation_options(refresh_value: int):
    return _conversation_options()


@app.callback(
    Output("title-edit-row", "className"),
    Output("title-edit-input", "value"),
    Output("chat-refresh", "data", allow_duplicate=True),
    Output("convo-dropdown", "options", allow_duplicate=True),
    Input("edit-title-btn", "n_clicks"),
    Input("cancel-title-btn", "n_clicks"),
    Input("save-title-btn", "n_clicks"),
    Input("convo-dropdown", "value"),
    State("title-edit-input", "value"),
    State("chat-refresh", "data"),
    prevent_initial_call=True,
)
def edit_conversation_title(
    edit_clicks: int | None,
    cancel_clicks: int | None,
    save_clicks: int | None,
    convo_id: str | None,
    new_title: str | None,
    refresh_value: int,
):
    trigger = dash.callback_context.triggered_id
    if trigger == "edit-title-btn":
        if not convo_id:
            return "title-edit-row", "", no_update, no_update
        conversation = db.get_conversation(int(convo_id))
        title = conversation["title"] if conversation else ""
        return "title-edit-row title-edit-row--open", title, no_update, no_update
    if trigger in {"cancel-title-btn", "convo-dropdown"}:
        return "title-edit-row", "", no_update, no_update
    if trigger == "save-title-btn":
        if not convo_id:
            return "title-edit-row", "", no_update, no_update
        title = (new_title or "").strip()
        if not title:
            return "title-edit-row", "", no_update, no_update
        db.update_conversation_title(int(convo_id), title, auto_title=False)
        return (
            "title-edit-row",
            "",
            (refresh_value or 0) + 1,
            _conversation_options(),
        )
    return "title-edit-row", "", no_update, no_update


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
    assistant.maybe_update_conversation_title(
        conversation_id, settings, force_first=True
    )
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
        detail = doc["doc_type"].lstrip(".").upper()
        items.append(
            _file_item(
                label,
                doc["name"],
                detail,
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
            html.Div("Fichiers", className="sources-title"),
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
    if path_str and not path.exists():
        return (
            "offcanvas offcanvas--open",
            name,
            html.Div("File not found on disk.", className="status"),
        )

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
        iframe_src = f"/assets/pdf_viewer.html?file={file_url}&doc_id={active_file.get('id')}"
        body = html.Div(
            [
                html.Div(
                    "Select text in the PDF and click Highlight selection.",
                    className="status",
                ),
                html.Iframe(src=iframe_src, className="pdf-frame"),
            ],
            className="file-viewer",
        )
        return "offcanvas offcanvas--open", name, body

    if doc_type == ".docx":
        if settings.onlyoffice_url:
            iframe_src = f"/onlyoffice/{active_file.get('id')}"
            body = html.Div(
                [
                    html.Div(
                        "OnlyOffice editor actif.",
                        className="status",
                    ),
                    html.Iframe(src=iframe_src, className="office-frame"),
                ],
                className="file-viewer",
            )
            return "offcanvas offcanvas--open", name, body

        try:
            preview_component = _render_word_preview(path)
            status = (
                "OnlyOffice non configure. Le rendu peut differer du document."
            )
        except Exception as exc:
            preview_component = html.Pre("", className="file-preview")
            status = f"Word load failed: {exc}"
        doc_id = active_file.get("id")
        body = html.Div(
            [
                html.Div("Preview (read-only)", className="field-label"),
                preview_component,
                html.Div("Append paragraph", className="field-label"),
                dcc.Textarea(
                    id={"type": "word-input", "name": "append", "doc": doc_id},
                    className="file-textarea file-textarea--compact",
                    placeholder="New paragraph text",
                ),
                html.Button(
                    "Append",
                    id={"type": "word-action", "name": "append", "doc": doc_id},
                    className="send-btn",
                ),
                html.Div("Find and replace", className="field-label"),
                dcc.Input(
                    id={"type": "word-input", "name": "find", "doc": doc_id},
                    type="text",
                    placeholder="Find text",
                ),
                dcc.Input(
                    id={"type": "word-input", "name": "replace", "doc": doc_id},
                    type="text",
                    placeholder="Replace with",
                ),
                html.Button(
                    "Replace",
                    id={"type": "word-action", "name": "replace", "doc": doc_id},
                    className="send-btn",
                ),
                html.Div(status, className="status"),
            ],
            className="file-editor",
        )
        return "offcanvas offcanvas--open", name, body

    if doc_type in {".xlsx", ".xls", ".xlsm", ".csv"}:
        if doc_type != ".csv" and settings.onlyoffice_url:
            iframe_src = f"/onlyoffice/{active_file.get('id')}"
            body = html.Div(
                [
                    html.Div(
                        "OnlyOffice editor actif.",
                        className="status",
                    ),
                    html.Iframe(src=iframe_src, className="office-frame"),
                ],
                className="file-viewer",
            )
            return "offcanvas offcanvas--open", name, body

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
            df = df.where(df.notna(), "")
            columns = [{"name": str(col), "id": str(col)} for col in df.columns]
            doc_id = active_file.get("id")
            table = dash_table.DataTable(
                id={"type": "excel-editor", "doc": doc_id},
                data=df.to_dict("records"),
                columns=columns,
                editable=True,
                page_size=12,
                selected_cells=[],
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
                    id={"type": "excel-sheet", "doc": doc_id},
                    options=[{"label": sheet, "value": sheet} for sheet in sheets],
                    value=sheet_value,
                    clearable=False,
                    className="sheet-selector",
                )
            body = html.Div(
                [
                    sheet_select,
                    dcc.Store(id={"type": "excel-selection", "doc": doc_id}, data=""),
                    table,
                    html.Div(
                        id={"type": "excel-preview", "doc": doc_id},
                        className="status",
                    ),
                    html.Button(
                        "Envoyer la selection au chat",
                        id={"type": "excel-action", "name": "send-selection", "doc": doc_id},
                        className="icon-btn",
                    ),
                    html.Button(
                        "Save changes",
                        id={"type": "excel-action", "name": "save", "doc": doc_id},
                        className="send-btn",
                    ),
                    html.Div(status, className="status"),
                ],
                className="file-editor",
            )
        return "offcanvas offcanvas--open", name, body

    return "offcanvas offcanvas--open", name, html.Div(
        "Unsupported file type.", className="status"
    )


@app.callback(
    Output({"type": "excel-editor", "doc": MATCH}, "data"),
    Output({"type": "excel-editor", "doc": MATCH}, "columns"),
    Input({"type": "excel-sheet", "doc": MATCH}, "value"),
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
    df = df.where(df.notna(), "")
    columns = [{"name": str(col), "id": str(col)} for col in df.columns]
    return df.to_dict("records"), columns


@app.callback(
    Output({"type": "excel-selection", "doc": MATCH}, "data"),
    Output({"type": "excel-preview", "doc": MATCH}, "children"),
    Input({"type": "excel-editor", "doc": MATCH}, "selected_cells"),
    State({"type": "excel-editor", "doc": MATCH}, "data"),
    State({"type": "excel-editor", "doc": MATCH}, "columns"),
    prevent_initial_call=True,
)
def update_excel_selection(
    selected_cells: list[dict] | None,
    table_data: list[dict] | None,
    table_columns: list[dict] | None,
):
    if not selected_cells:
        return "", "Aucune selection."
    if len(selected_cells) > 200:
        return "", "Selection trop grande (max 200 cellules)."

    data = table_data or []
    columns = [col["id"] for col in (table_columns or [])]
    lines = []
    for cell in selected_cells:
        row_idx = int(cell.get("row", 0))
        col_id = cell.get("column_id")
        value = ""
        if 0 <= row_idx < len(data):
            value = data[row_idx].get(col_id, "")
        lines.append(f"R{row_idx + 2} {col_id}: {value}")
    text = "Excel selection:\n" + "\n".join(lines)
    preview = f"{len(selected_cells)} cellules selectionnees."
    return text, preview


@app.callback(
    Output("user-input", "value", allow_duplicate=True),
    Input({"type": "excel-action", "name": "send-selection", "doc": ALL}, "n_clicks"),
    State({"type": "excel-selection", "doc": ALL}, "data"),
    State({"type": "excel-selection", "doc": ALL}, "id"),
    State("user-input", "value"),
    prevent_initial_call=True,
)
def send_excel_selection(
    n_clicks: list[int] | None,
    selection_texts: list[str] | None,
    selection_ids: list[dict] | None,
    current_text: str | None,
):
    trigger = dash.callback_context.triggered_id
    if not trigger or not isinstance(trigger, dict):
        return no_update
    doc_id = trigger.get("doc")
    selection_text = ""
    for item_id, text in zip(selection_ids or [], selection_texts or []):
        if item_id.get("doc") == doc_id:
            selection_text = text or ""
            break
    if not selection_text:
        return no_update
    current = current_text or ""
    prefix = "\n\n" if current.strip() else ""
    return f"{current}{prefix}{selection_text}\n"


@app.callback(
    Output("file-save-status", "children", allow_duplicate=True),
    Output("docs-refresh", "data", allow_duplicate=True),
    Input({"type": "word-action", "name": ALL, "doc": ALL}, "n_clicks"),
    State({"type": "word-input", "name": ALL, "doc": ALL}, "value"),
    State({"type": "word-input", "name": ALL, "doc": ALL}, "id"),
    State("active-file", "data"),
    State("docs-refresh", "data"),
    prevent_initial_call=True,
)
def save_word_edits(
    clicks: list[int] | None,
    input_values: list[str] | None,
    input_ids: list[dict] | None,
    active_file: dict | None,
    docs_refresh: int,
):
    trigger = dash.callback_context.triggered_id
    if not active_file or not trigger or not isinstance(trigger, dict):
        return no_update, no_update
    if active_file.get("kind") != "doc":
        return "Only documents can be edited.", no_update

    doc_id = int(active_file.get("id") or 0)
    doc_row = db.get_document_by_id(doc_id)
    if not doc_row:
        return "Document not found.", no_update

    path = Path(doc_row["path"])
    doc_type = (doc_row["doc_type"] or path.suffix).lower()
    if doc_type != ".docx":
        return "This file is not a Word document.", no_update

    values = {}
    for item_id, value in zip(input_ids or [], input_values or []):
        name = item_id.get("name")
        values[name] = value

    try:
        action = trigger.get("name")
        if action == "append":
            text = (values.get("append") or "").strip()
            if not text:
                return "Provide text to append.", no_update
            file_ops.append_paragraph(path, text)
        elif action == "replace":
            old = (values.get("find") or "").strip()
            if not old:
                return "Provide text to find.", no_update
            file_ops.replace_text(path, old, values.get("replace") or "")
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
    Output("file-save-status", "children", allow_duplicate=True),
    Output("docs-refresh", "data", allow_duplicate=True),
    Input({"type": "excel-action", "name": "save", "doc": ALL}, "n_clicks"),
    State({"type": "excel-editor", "doc": ALL}, "data"),
    State({"type": "excel-editor", "doc": ALL}, "columns"),
    State({"type": "excel-sheet", "doc": ALL}, "value"),
    State("active-file", "data"),
    State("docs-refresh", "data"),
    prevent_initial_call=True,
)
def save_table_edits(
    save_clicks: list[int] | None,
    table_data_list: list[list[dict]] | None,
    table_columns_list: list[list[dict]] | None,
    sheet_name_list: list[str] | None,
    active_file: dict | None,
    docs_refresh: int,
):
    trigger = dash.callback_context.triggered_id
    if not trigger or not active_file:
        return no_update, no_update
    if active_file.get("kind") != "doc":
        return "Only documents can be edited.", no_update

    doc_id = int(active_file.get("id") or 0)
    doc_row = db.get_document_by_id(doc_id)
    if not doc_row:
        return "Document not found.", no_update

    path = Path(doc_row["path"])
    doc_type = (doc_row["doc_type"] or path.suffix).lower()
    if doc_type not in {".xlsx", ".xls", ".xlsm", ".csv"}:
        return "This file is not a table.", no_update

    table_data = (table_data_list or [None])[0]
    table_columns = (table_columns_list or [None])[0]
    sheet_name = (sheet_name_list or [None])[0]

    try:
        columns = [col["id"] for col in (table_columns or [])]
        if doc_type == ".csv":
            try:
                import pandas as pd
            except ImportError as exc:
                return f"Pandas is required: {exc}", no_update
            df = pd.DataFrame(table_data or [], columns=columns)
            df.to_csv(path, index=False)
        else:
            from openpyxl import load_workbook

            workbook = load_workbook(path)
            sheet = sheet_name or workbook.sheetnames[0]
            if sheet not in workbook.sheetnames:
                return "Sheet not found.", no_update
            ws = workbook[sheet]
            max_cols = len(columns)
            max_rows = max(ws.max_row, (len(table_data or []) + 1))
            for col_idx, header in enumerate(columns, start=1):
                ws.cell(row=1, column=col_idx).value = header
            for row_idx in range(2, max_rows + 1):
                row_data = None
                if table_data and row_idx - 2 < len(table_data):
                    row_data = table_data[row_idx - 2]
                for col_idx in range(1, max_cols + 1):
                    header = columns[col_idx - 1]
                    if row_data is None:
                        value = None
                    else:
                        value = _coerce_cell_value(row_data.get(header))
                    ws.cell(row=row_idx, column=col_idx).value = value
            workbook.save(path)
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


app.clientside_callback(
    """
    function(refreshValue, convoId) {
        const el = document.getElementById("chat-window");
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
        return Date.now();
    }
    """,
    Output("scroll-trigger", "data"),
    Input("chat-refresh", "data"),
    Input("convo-dropdown", "value"),
)


if __name__ == "__main__":
    app.run_server(debug=True)
