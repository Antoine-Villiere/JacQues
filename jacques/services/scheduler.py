from __future__ import annotations

from datetime import datetime, timezone
import json
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .. import db
from ..config import Settings
from . import web_search
from .llm import LLMClient


_SCHEDULER = BackgroundScheduler()
_STARTED = False


def start(settings: Settings) -> None:
    global _STARTED
    if _STARTED:
        return
    _SCHEDULER.start()
    _STARTED = True
    reload(settings)


def reload(settings: Settings) -> None:
    if not _STARTED:
        return
    for job in _SCHEDULER.get_jobs():
        _SCHEDULER.remove_job(job.id)
    for task in db.list_scheduled_tasks():
        if task["enabled"]:
            _schedule_task(task, settings)


def schedule_task_by_id(task_id: int, settings: Settings) -> None:
    if not _STARTED:
        start(settings)
    task = db.get_scheduled_task(task_id)
    if not task or not task["enabled"]:
        return
    _schedule_task(task, settings)


def remove_task(task_id: int) -> None:
    if not _STARTED:
        return
    job_id = _job_id(task_id)
    try:
        _SCHEDULER.remove_job(job_id)
    except Exception:
        return


def _job_id(task_id: int) -> str:
    return f"task_{task_id}"


def _normalize_task(task: dict | object) -> dict:
    if isinstance(task, dict):
        return task
    return dict(task)


def _schedule_task(task: dict | object, settings: Settings) -> None:
    task = _normalize_task(task)
    tz_name = task.get("timezone") or settings.app_timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
        tz_name = "UTC"
    try:
        trigger = CronTrigger.from_crontab(task["cron"], timezone=tz)
    except Exception as exc:
        db.update_scheduled_task_status(
            int(task["id"]),
            None,
            f"Cron error: {exc}",
        )
        return
    _SCHEDULER.add_job(
        _run_task,
        trigger=trigger,
        id=_job_id(int(task["id"])),
        replace_existing=True,
        args=[int(task["id"]), settings],
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    db.update_scheduled_task_status(int(task["id"]), None, f"Scheduled ({tz_name})")


def _run_task(task_id: int, settings: Settings) -> None:
    task_row = db.get_scheduled_task(task_id)
    if not task_row or not task_row["enabled"]:
        return
    task = _normalize_task(task_row)
    now = datetime.now(timezone.utc).isoformat()
    status = ""
    try:
        if task["task_type"] == "web_digest":
            status = _run_web_digest(task, settings)
        elif task["task_type"] == "reminder":
            status = _run_reminder(task, settings)
        else:
            status = f"Unknown task type: {task['task_type']}"
    except Exception as exc:
        status = f"Task error: {exc}"
    db.update_scheduled_task_status(task_id, now, status)


def _run_web_digest(task: dict, settings: Settings) -> str:
    task = _normalize_task(task)
    payload = _parse_payload(task.get("payload"))
    query = payload.get("query") or task.get("name") or "Actualites"
    limit = int(payload.get("limit") or 5)
    results = web_search.search(query, settings, limit)
    sources = web_search.summarize_results(results)

    summary = ""
    if payload.get("use_llm", True):
        llm = LLMClient(settings)
        if llm.available():
            prompt = (
                "Resume en francais, 3-5 points cles max. "
                "Reste factuel et cite les sources a la fin.\n\n"
                f"Sources:\n{sources}"
            )
            response = llm.chat(
                [
                    {"role": "system", "content": "You summarize news."},
                    {"role": "user", "content": prompt},
                ],
                model=settings.text_model,
                stream=False,
            )
            summary = str(response.get("content") or "").strip()

    title = task.get("name") or "Tache planifiee"
    header = f"Resultat de tache planifiee: {title}"
    if summary:
        content = f"{header}\n\n{summary}\n\n{sources}"
    else:
        content = f"{header}\n\n{sources}"
    db.add_message(int(task["conversation_id"]), "assistant", content)
    return "ok"


def _run_reminder(task: dict, settings: Settings) -> str:
    task = _normalize_task(task)
    payload = _parse_payload(task.get("payload"))
    message = payload.get("message") or task.get("name") or "Rappel"
    content = f"Rappel programme: {message}"
    db.add_message(int(task["conversation_id"]), "assistant", content)
    return "ok"


def _parse_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
