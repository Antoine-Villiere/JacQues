# Jacques Assistant (Dash)

Jacques is a full-featured local assistant built with Python + Dash. It supports
multi-conversation chat, per-conversation RAG, document ingestion (PDF/Word/Excel/CSV),
image analysis, web and news search, plotting, and real tool calling via LiteLLM
with Groq models. It can also create real Apple Mail drafts and Apple Calendar
events on macOS (no sending, no deleting).

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open `http://127.0.0.1:8050`.

## Configuration (.env)

```bash
GROQ_API_KEY=your_key
TEXT_MODEL=groq/openai/gpt-oss-120b
REASONING_MODEL=groq/openai/gpt-oss-120b
VISION_MODEL=groq/meta-llama/llama-4-maverick-17b-128e-instruct
VISION_ENABLED=true
IMAGE_PROVIDER=openai
IMAGE_API_KEY=your_key
IMAGE_MODEL=gpt-image-1
BRAVE_API_KEY=your_key
BRAVE_COUNTRY=FR
BRAVE_SEARCH_LANG=fr
WEB_TIMEOUT=10
RAG_TOP_K=4
MAX_HISTORY_MESSAGES=40
MAX_TOOL_CALLS=4
LLM_STREAMING=true
APP_BASE_URL=http://127.0.0.1:8050
ONLYOFFICE_URL=http://127.0.0.1:8080
ONLYOFFICE_JWT=
APP_TIMEZONE=Europe/Zurich
JACQUES_DATA_DIR=~/.jacques
```

Notes:
- `GROQ_API_KEY` is enough for Groq through LiteLLM.
- `BRAVE_API_KEY` enables web + news search (Brave Search API).
- `LLM_STREAMING=true` streams tokens in the UI.
- `APP_BASE_URL` must be reachable by OnlyOffice for callbacks.
- `ONLYOFFICE_URL` points to the Document Server (optional).
- `JACQUES_DATA_DIR` controls where local data is stored (default `~/.jacques`).

## Core features

- Multi-conversation chat with SQLite persistence.
- Automatic RAG when documents exist (TF-IDF index per conversation).
- Ingestion: PDF, Word, Excel, CSV.
- Word/Excel edits with formatting preservation.
- Image analysis (vision) and image generation.
- Plotting (`plot_generate`, `plot_fred_series`).
- Stock price history (`stock_history`) for market analysis.
- Web search + news search (Brave API).
- Web scraping for specific sites via CSS selector.
- Task scheduler with cron (APScheduler).
- Apple Mail draft creation and Apple Calendar event creation (macOS only).
- Per-conversation files and images are isolated.
- Streaming responses and tool status indicator.
- System prompt + global memory editor in Settings.
- Type `@` in the input to mention documents from the current conversation.

## UI notes

- Files are listed on the right and open in an off-canvas editor/viewer.
- PDFs open in the built-in viewer on the right panel.
- OnlyOffice editor can be launched from Settings (optional, best formatting fidelity).
- Tool calls are hidden in chat unless a tool error occurs.

## Tools (automatic)

Documents and RAG:
- `list_documents`, `rag_search`, `rag_rebuild`

Images:
- `list_images`, `image_describe`, `image_generate`

Email (Apple Mail, macOS):
- `email_draft` creates a real draft (no sending, no deletion)
- `mail_search` and `mail_read` allow reading messages on request

Calendar (Apple Calendar, macOS):
- `calendar_event` creates a real calendar event

Tasks:
- `task_schedule`, `task_list`, `task_delete`, `task_enable`

Web:
- `web_search`, `news_search`, `web_fetch` (supports CSS selector), `stock_history`

Project access:
- `project_list_files`, `project_search`, `project_read_file`, `project_replace`, `python_run`

## Apple Mail / Calendar automation (macOS)

This uses AppleScript under the hood.
You must allow automation in:
System Settings -> Privacy & Security -> Automation
Enable Calendar/Mail for the terminal/python process.

Jacques will never delete or send emails. Drafts only.

## macOS automation (AppleScript)

When enabled, `macos_script` can run AppleScript snippets for native app control.
Prefer non-destructive actions and ask before running anything irreversible.

## Storage

Default location:
- `~/.jacques/jacques.db`
- `~/.jacques/uploads` (documents)
- `~/.jacques/images` (imported images)
- `~/.jacques/generated` (generated images, plots, ics)

To store data inside the repo, set:
```
JACQUES_DATA_DIR=./data
```

## Troubleshooting

- OnlyOffice black/blank frame: verify `ONLYOFFICE_URL`, `APP_BASE_URL`, and Docker.
- Mail/Calendar not creating: check macOS Automation permissions.
- Web search returns empty: check `BRAVE_API_KEY`.
