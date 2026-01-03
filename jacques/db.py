import sqlite3
from datetime import datetime

from .config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pdf_highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                page_number INTEGER,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
            """
        )
        auto_title_added = _ensure_column(
            conn, "conversations", "auto_title", "INTEGER"
        )
        documents_added = _ensure_column(conn, "documents", "conversation_id", "INTEGER")
        images_added = _ensure_column(conn, "images", "conversation_id", "INTEGER")
        if auto_title_added:
            conn.execute(
                "UPDATE conversations SET auto_title = 1 WHERE auto_title IS NULL"
            )
        if documents_added or images_added:
            convo_id = _latest_conversation_id(conn)
            if convo_id is not None:
                conn.execute(
                    "UPDATE documents SET conversation_id = ? WHERE conversation_id IS NULL",
                    (convo_id,),
                )
                conn.execute(
                    "UPDATE images SET conversation_id = ? WHERE conversation_id IS NULL",
                    (convo_id,),
                )
        conn.commit()


def _now() -> str:
    return datetime.utcnow().isoformat()


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, col_type: str
) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column in existing:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    return True


def _latest_conversation_id(conn: sqlite3.Connection) -> int | None:
    cursor = conn.execute(
        "SELECT id FROM conversations ORDER BY created_at DESC LIMIT 1"
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def create_conversation(title: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (title, created_at, auto_title) VALUES (?, ?, ?)",
            (title, _now(), 1),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_conversations() -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, title, created_at, auto_title FROM conversations "
            "ORDER BY created_at DESC"
        )
        return list(cursor.fetchall())


def get_conversation(conversation_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, title, created_at, auto_title FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        return cursor.fetchone()


def update_conversation_title(
    conversation_id: int, title: str, auto_title: bool | None = None
) -> None:
    with get_connection() as conn:
        if auto_title is None:
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, conversation_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET title = ?, auto_title = ? WHERE id = ?",
                (title, 1 if auto_title else 0, conversation_id),
            )
        conn.commit()


def delete_conversation(conversation_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute(
            """
            DELETE FROM pdf_highlights
            WHERE document_id IN (
                SELECT id FROM documents WHERE conversation_id = ?
            )
            """,
            (conversation_id,),
        )
        conn.execute("DELETE FROM documents WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM images WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()


def add_message(conversation_id: int, role: str, content: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, _now()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_message_content(message_id: int, content: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
        conn.commit()


def append_message_content(message_id: int, delta: str) -> None:
    if not delta:
        return
    with get_connection() as conn:
        conn.execute(
            "UPDATE messages SET content = COALESCE(content, '') || ? WHERE id = ?",
            (delta, message_id),
        )
        conn.commit()


def get_messages(conversation_id: int, limit: int | None = None) -> list[sqlite3.Row]:
    with get_connection() as conn:
        if limit is None:
            cursor = conn.execute(
                "SELECT id, role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            )
            return list(cursor.fetchall())
        cursor = conn.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        rows = list(cursor.fetchall())
        rows.reverse()
        return rows


def get_latest_tool_message(conversation_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content, created_at
            FROM messages
            WHERE conversation_id = ? AND role = 'tool'
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id,),
        )
        return cursor.fetchone()


def get_latest_web_search_message(conversation_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content, created_at
            FROM messages
            WHERE conversation_id = ?
              AND role = 'tool'
              AND content LIKE '%Tool result: **web_search**%'
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id,),
        )
        return cursor.fetchone()


def get_latest_assistant_message(conversation_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content, created_at
            FROM messages
            WHERE conversation_id = ? AND role = 'assistant'
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id,),
        )
        return cursor.fetchone()


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,),
        )
        row = cursor.fetchone()
        if row:
            return row["value"]
    return default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, _now()),
        )
        conn.commit()


def is_path_used(table: str, path: str) -> bool:
    if table not in {"documents", "images"}:
        raise ValueError("Invalid table name.")
    with get_connection() as conn:
        cursor = conn.execute(
            f"SELECT 1 FROM {table} WHERE path = ? LIMIT 1",
            (path,),
        )
        return cursor.fetchone() is not None


def add_document(conversation_id: int, name: str, path: str, doc_type: str, text: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO documents (conversation_id, name, path, doc_type, text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, name, path, doc_type, text, _now()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_documents(conversation_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, path, doc_type, created_at
            FROM documents
            WHERE conversation_id = ?
            ORDER BY id DESC
            """,
            (conversation_id,),
        )
        return list(cursor.fetchall())


def get_document_texts(conversation_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, name, text FROM documents WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        )
        docs = list(cursor.fetchall())
        if not docs:
            return []

        highlight_map: dict[int, list[sqlite3.Row]] = {}
        highlight_cursor = conn.execute(
            """
            SELECT document_id, page_number, text
            FROM pdf_highlights
            WHERE document_id IN (
                SELECT id FROM documents WHERE conversation_id = ?
            )
            ORDER BY id ASC
            """,
            (conversation_id,),
        )
        for row in highlight_cursor.fetchall():
            highlight_map.setdefault(int(row["document_id"]), []).append(row)

        results: list[dict] = []
        for doc in docs:
            text = doc["text"]
            highlights = highlight_map.get(int(doc["id"]), [])
            if highlights:
                lines = []
                for highlight in highlights:
                    page = highlight["page_number"]
                    suffix = f"p{page}" if page else "p?"
                    lines.append(f"- {suffix}: {highlight['text']}")
                text = f"{text}\n\nHighlights:\n" + "\n".join(lines)
            results.append({"id": doc["id"], "name": doc["name"], "text": text})
        return results


def get_document_by_id(document_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, conversation_id, name, path, doc_type, text, created_at
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        )
        return cursor.fetchone()


def get_document_by_name(conversation_id: int, name: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, conversation_id, name, path, doc_type, text, created_at
            FROM documents
            WHERE conversation_id = ? AND name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, name),
        )
        return cursor.fetchone()


def update_document_text(document_id: int, text: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET text = ? WHERE id = ?",
            (text, document_id),
        )
        conn.commit()


def add_pdf_highlight(document_id: int, page_number: int | None, text: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO pdf_highlights (document_id, page_number, text, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (document_id, page_number, text, _now()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_pdf_highlights(document_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, document_id, page_number, text, created_at
            FROM pdf_highlights
            WHERE document_id = ?
            ORDER BY id ASC
            """,
            (document_id,),
        )
        return list(cursor.fetchall())


def add_image(
    conversation_id: int, name: str, path: str, description: str | None = None
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO images (conversation_id, name, path, description, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, name, path, description, _now()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_images(conversation_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, path, description, created_at
            FROM images
            WHERE conversation_id = ?
            ORDER BY id DESC
            """,
            (conversation_id,),
        )
        return list(cursor.fetchall())


def get_image_by_name(conversation_id: int, name: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, path, description, created_at
            FROM images
            WHERE conversation_id = ? AND name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, name),
        )
        return cursor.fetchone()


def get_image_by_id(image_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, conversation_id, name, path, description, created_at
            FROM images
            WHERE id = ?
            """,
            (image_id,),
        )
        return cursor.fetchone()
