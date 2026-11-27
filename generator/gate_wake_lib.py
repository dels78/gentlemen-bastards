"""Pure wake-gate helpers (PERSO-816). Tested here; inlined in gate.py.tmpl at render."""

from __future__ import annotations

from typing import Any


def artifact_kind(item: dict[str, Any]) -> str | None:
    kind = item.get("kind") or item.get("type")
    return kind if isinstance(kind, str) else None


def wake_from_unfiltered_window(
    items: list[dict[str, Any]],
    wake_kinds: frozenset[str],
    *,
    limit: int = 500,
) -> bool:
    """Legacy gate shape: one unfiltered list, client-side kind filter (can starve)."""
    window = items[:limit]
    return any(
        isinstance(item, dict) and artifact_kind(item) in wake_kinds for item in window
    )


def wake_from_per_type_queries(
    per_type_has_items: dict[str, bool],
    wake_kinds: frozenset[str],
) -> bool:
    """Wake iff any wake kind has at least one matching unprocessed artifact."""
    return any(per_type_has_items.get(kind) for kind in wake_kinds)