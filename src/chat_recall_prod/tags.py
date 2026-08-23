"""Tag normalization.

Tags are matched with exact JSONB containment (@>), so case is load-bearing:
`CAD-1728` and `cad-1728` are different tags to Postgres. The corpus grew
both conventions, which made tag search silently miss half the history.
Normalizing at the tool boundary — every write AND every query — makes case
impossible to get wrong from either side. Migration 005 folds existing rows
into the same shape.
"""

from __future__ import annotations


def normalize_tags(tags: list[str] | None) -> list[str] | None:
    """Lowercase, trim, dedupe (order-preserving), and drop empty tags.

    Returns None for None or an empty result so callers' `if tags:` checks
    and NULL-vs-[] storage behavior stay exactly as before.
    """
    if tags is None:
        return None
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        norm = tag.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result or None
