"""Loop health helpers for Herald (PERSO-816)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant; assume UTC when the string has no offset."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def latest_coordinator_finished_at(runs: list[dict[str, Any]]) -> datetime | None:
    """Pick the newest finished coordinator run from a runs_list page."""
    best: datetime | None = None
    for run in runs:
        if not isinstance(run, dict):
            continue
        role = run.get("role")
        if role is not None and role != "coordinator":
            continue
        for key in ("finished_at", "ended_at", "completed_at"):
            raw = run.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                finished = parse_instant(raw)
            except ValueError:
                continue
            if best is None or finished > best:
                best = finished
            break
    return best


def coordinator_stale(
    *,
    unprocessed_question_count: int,
    last_coordinator_finished_at: datetime | None,
    now: datetime,
    stale_after_minutes: int = 60,
) -> bool:
    """True when Questions wait but Coordinator has not finished a run recently."""
    if unprocessed_question_count <= 0:
        return False
    if last_coordinator_finished_at is None:
        return True
    age_seconds = (now - last_coordinator_finished_at).total_seconds()
    return age_seconds > stale_after_minutes * 60


def loop_health_payload(
    *,
    unprocessed_question_count: int,
    last_coordinator_finished_at: datetime | None,
    now: datetime,
    stale_after_minutes: int = 60,
) -> dict[str, Any]:
    stale = coordinator_stale(
        unprocessed_question_count=unprocessed_question_count,
        last_coordinator_finished_at=last_coordinator_finished_at,
        now=now,
        stale_after_minutes=stale_after_minutes,
    )
    status = "degraded" if stale else "ok"
    out: dict[str, Any] = {
        "status": status,
        "unprocessed_questions_for_coordinator": unprocessed_question_count,
    }
    if last_coordinator_finished_at is not None:
        out["coordinator_last_finished_at"] = last_coordinator_finished_at.isoformat()
    if stale:
        out["alerts"] = [
            {
                "code": "coordinator_stale",
                "message": (
                    "Coordinator has unprocessed Questions but no finished run within "
                    f"{stale_after_minutes} minutes."
                ),
            }
        ]
    return out