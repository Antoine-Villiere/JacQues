import sqlite3
from datetime import datetime, timezone

from .config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active_branch INTEGER
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
                branch_id INTEGER,
                edit_of INTEGER,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                parent_branch INTEGER NOT NULL,
                pivot_message_id INTEGER NOT NULL,
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
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                task_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                cron TEXT NOT NULL,
                timezone TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                last_run TEXT,
                last_status TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        auto_title_added = _ensure_column(
            conn, "conversations", "auto_title", "INTEGER"
        )
        archived_added = _ensure_column(conn, "conversations", "archived", "INTEGER")
        active_branch_added = _ensure_column(
            conn, "conversations", "active_branch", "INTEGER"
        )
        branch_id_added = _ensure_column(conn, "messages", "branch_id", "INTEGER")
        edit_of_added = _ensure_column(conn, "messages", "edit_of", "INTEGER")
        documents_added = _ensure_column(conn, "documents", "conversation_id", "INTEGER")
        images_added = _ensure_column(conn, "images", "conversation_id", "INTEGER")
        if auto_title_added:
            conn.execute(
                "UPDATE conversations SET auto_title = 1 WHERE auto_title IS NULL"
            )
        if archived_added:
            conn.execute(
                "UPDATE conversations SET archived = 0 WHERE archived IS NULL"
            )
        if active_branch_added:
            conn.execute(
                "UPDATE conversations SET active_branch = 0 WHERE active_branch IS NULL"
            )
        if branch_id_added:
            conn.execute("UPDATE messages SET branch_id = 0 WHERE branch_id IS NULL")
        if edit_of_added:
            conn.execute("UPDATE messages SET edit_of = NULL WHERE edit_of IS NULL")
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_convo_id "
            "ON messages(conversation_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_convo_branch_id "
            "ON messages(conversation_id, branch_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_convo_role "
            "ON messages(conversation_id, role, branch_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_branches_convo "
            "ON message_branches(conversation_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_convo "
            "ON documents(conversation_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_convo "
            "ON images(conversation_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_convo "
            "ON scheduled_tasks(conversation_id, enabled, id)"
        )
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            "INSERT INTO conversations (title, created_at, auto_title, archived, active_branch) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, _now(), 1, 0, 0),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_conversations(include_archived: bool = False) -> list[sqlite3.Row]:
    with get_connection() as conn:
        if include_archived:
            cursor = conn.execute(
                "SELECT id, title, created_at, auto_title, archived, active_branch FROM conversations "
                "ORDER BY created_at DESC"
            )
        else:
            cursor = conn.execute(
                "SELECT id, title, created_at, auto_title, archived, active_branch FROM conversations "
                "WHERE archived = 0 OR archived IS NULL "
                "ORDER BY created_at DESC"
            )
        return list(cursor.fetchall())


def list_archived_conversations() -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, title, created_at, auto_title, archived, active_branch FROM conversations "
            "WHERE archived = 1 ORDER BY created_at DESC"
        )
        return list(cursor.fetchall())


def get_conversation(conversation_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, title, created_at, auto_title, archived, active_branch FROM conversations WHERE id = ?",
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


def get_conversation_active_branch(conversation_id: int) -> int:
    conversation = get_conversation(conversation_id)
    if not conversation:
        return 0
    value = conversation["active_branch"]
    return int(value) if value is not None else 0


def set_conversation_active_branch(conversation_id: int, branch_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE conversations SET active_branch = ? WHERE id = ?",
            (branch_id, conversation_id),
        )
        conn.commit()


def set_conversation_archived(conversation_id: int, archived: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE conversations SET archived = ? WHERE id = ?",
            (1 if archived else 0, conversation_id),
        )
        conn.commit()


def archive_all_conversations() -> None:
    with get_connection() as conn:
        conn.execute("UPDATE conversations SET archived = 1")
        conn.commit()


def unarchive_all_conversations() -> None:
    with get_connection() as conn:
        conn.execute("UPDATE conversations SET archived = 0")
        conn.commit()


def delete_conversation(conversation_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute(
            "DELETE FROM message_branches WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.execute(
            "DELETE FROM scheduled_tasks WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.execute("DELETE FROM documents WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM images WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()


def add_message(
    conversation_id: int,
    role: str,
    content: str,
    branch_id: int | None = None,
    edit_of: int | None = None,
) -> int:
    if branch_id is None:
        branch_id = get_conversation_active_branch(conversation_id)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at, branch_id, edit_of)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, _now(), branch_id, edit_of),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_message(message_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, conversation_id, role, content, created_at, branch_id, edit_of "
            "FROM messages WHERE id = ?",
            (message_id,),
        )
        return cursor.fetchone()


def add_branch(conversation_id: int, parent_branch: int, pivot_message_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO message_branches (conversation_id, parent_branch, pivot_message_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, parent_branch, pivot_message_id, _now()),
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
                "SELECT id, role, content, created_at, branch_id, edit_of FROM messages "
                "WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            )
            return list(cursor.fetchall())
        cursor = conn.execute(
            "SELECT id, role, content, created_at, branch_id, edit_of FROM messages "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        rows = list(cursor.fetchall())
        rows.reverse()
        return rows


def list_message_branches(conversation_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, parent_branch, pivot_message_id, created_at
            FROM message_branches
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        )
        return list(cursor.fetchall())


def _branch_chain(
    conn: sqlite3.Connection, conversation_id: int, branch_id: int
) -> list[sqlite3.Row]:
    if branch_id == 0:
        return []
    chain = []
    current = branch_id
    while current:
        row = conn.execute(
            """
            SELECT id, parent_branch, pivot_message_id
            FROM message_branches
            WHERE id = ? AND conversation_id = ?
            """,
            (current, conversation_id),
        ).fetchone()
        if not row:
            break
        chain.append(row)
        current = int(row["parent_branch"])
    chain.reverse()
    return chain


def get_branch_chain(conversation_id: int, branch_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return _branch_chain(conn, conversation_id, branch_id)


def get_messages_for_branch(
    conversation_id: int, branch_id: int | None = None, limit: int | None = None
) -> list[sqlite3.Row]:
    if branch_id is None:
        branch_id = get_conversation_active_branch(conversation_id)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, role, content, created_at, branch_id, edit_of
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        )
        rows = list(cursor.fetchall())
        if not rows:
            return []
        branch_map: dict[int, list[sqlite3.Row]] = {}
        base_rows: list[sqlite3.Row] = []
        for row in rows:
            row_branch = int(row["branch_id"] or 0)
            if row_branch == 0:
                base_rows.append(row)
            else:
                branch_map.setdefault(row_branch, []).append(row)

        timeline = base_rows
        for branch in _branch_chain(conn, conversation_id, int(branch_id)):
            pivot_id = int(branch["pivot_message_id"])
            branch_msgs = branch_map.get(int(branch["id"]), [])
            if not branch_msgs:
                continue
            pivot_idx = next(
                (idx for idx, msg in enumerate(timeline) if int(msg["id"]) == pivot_id),
                None,
            )
            if pivot_idx is None:
                timeline = timeline + branch_msgs
            else:
                timeline = timeline[:pivot_idx] + branch_msgs

        if limit is not None and len(timeline) > limit:
            timeline = timeline[-limit:]
        return timeline


def get_latest_tool_message(
    conversation_id: int, branch_id: int | None = None
) -> sqlite3.Row | None:
    if branch_id is None:
        branch_id = get_conversation_active_branch(conversation_id)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content, created_at
            FROM messages
            WHERE conversation_id = ?
              AND role = 'tool'
              AND COALESCE(branch_id, 0) = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, branch_id),
        )
        return cursor.fetchone()


def get_latest_tool_message_by_name(
    conversation_id: int, name: str, branch_id: int | None = None
) -> sqlite3.Row | None:
    if branch_id is None:
        branch_id = get_conversation_active_branch(conversation_id)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content, created_at
            FROM messages
            WHERE conversation_id = ?
              AND role = 'tool'
              AND COALESCE(branch_id, 0) = ?
              AND content LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, branch_id, f"%Tool result: **{name}**%"),
        )
        return cursor.fetchone()


def get_latest_tool_call_message_by_name(
    conversation_id: int, name: str, branch_id: int | None = None
) -> sqlite3.Row | None:
    if branch_id is None:
        branch_id = get_conversation_active_branch(conversation_id)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content, created_at
            FROM messages
            WHERE conversation_id = ?
              AND role = 'tool'
              AND COALESCE(branch_id, 0) = ?
              AND content LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, branch_id, f"%Tool call: **{name}**%"),
        )
        return cursor.fetchone()


def get_latest_web_search_message(
    conversation_id: int, branch_id: int | None = None
) -> sqlite3.Row | None:
    if branch_id is None:
        branch_id = get_conversation_active_branch(conversation_id)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content, created_at
            FROM messages
            WHERE conversation_id = ?
              AND role = 'tool'
              AND COALESCE(branch_id, 0) = ?
              AND content LIKE '%Tool result: **web_search**%'
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, branch_id),
        )
        return cursor.fetchone()


def get_latest_assistant_message(
    conversation_id: int, branch_id: int | None = None
) -> sqlite3.Row | None:
    if branch_id is None:
        branch_id = get_conversation_active_branch(conversation_id)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content, created_at
            FROM messages
            WHERE conversation_id = ?
              AND role = 'assistant'
              AND COALESCE(branch_id, 0) = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, branch_id),
        )
        return cursor.fetchone()


def get_latest_message_id(conversation_id: int) -> int | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id,),
        )
        row = cursor.fetchone()
        return int(row["id"]) if row else None


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

        results: list[dict] = []
        for doc in docs:
            text = doc["text"]
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


def add_scheduled_task(
    conversation_id: int,
    name: str,
    task_type: str,
    payload: str,
    cron: str,
    timezone: str,
    enabled: bool = True,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scheduled_tasks (
                conversation_id, name, task_type, payload, cron, timezone, enabled, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                name,
                task_type,
                payload,
                cron,
                timezone,
                1 if enabled else 0,
                _now(),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_scheduled_tasks(conversation_id: int | None = None) -> list[sqlite3.Row]:
    with get_connection() as conn:
        if conversation_id is None:
            cursor = conn.execute(
                """
                SELECT id, conversation_id, name, task_type, payload, cron, timezone,
                       enabled, last_run, last_status, created_at
                FROM scheduled_tasks
                ORDER BY id DESC
                """
            )
        else:
            cursor = conn.execute(
                """
                SELECT id, conversation_id, name, task_type, payload, cron, timezone,
                       enabled, last_run, last_status, created_at
                FROM scheduled_tasks
                WHERE conversation_id = ?
                ORDER BY id DESC
                """,
                (conversation_id,),
            )
        return list(cursor.fetchall())


def get_scheduled_task(task_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, conversation_id, name, task_type, payload, cron, timezone,
                   enabled, last_run, last_status, created_at
            FROM scheduled_tasks
            WHERE id = ?
            """,
            (task_id,),
        )
        return cursor.fetchone()


def delete_scheduled_task(task_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.commit()


def set_scheduled_task_enabled(task_id: int, enabled: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, task_id),
        )
        conn.commit()


def update_scheduled_task_status(
    task_id: int,
    last_run: str | None,
    last_status: str | None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduled_tasks
            SET last_run = ?, last_status = ?
            WHERE id = ?
            """,
            (last_run, last_status, task_id),
        )
        conn.commit()


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
