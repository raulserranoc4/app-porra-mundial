from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, MutableMapping


def _cache_key(player_id) -> str:
    return f"prediction_cache_{player_id}"


def _pending_key(player_id) -> str:
    return f"pending_match_ids_{player_id}"


def _loaded_key(player_id) -> str:
    return f"prediction_cache_loaded_{player_id}"


def load_user_predictions_cached_or_state(
    state: MutableMapping,
    player_id,
    loader: Callable[[], list[dict]],
    force_refresh: bool = False,
) -> dict:
    key = _cache_key(player_id)
    if force_refresh or key not in state or not state.get(_loaded_key(player_id)):
        records = [dict(row) for row in loader()]
        state[key] = {
            row["match_id"]: row
            for row in records
            if row.get("match_id") is not None
        }
        state[_pending_key(player_id)] = None
        state[_loaded_key(player_id)] = True
    return state[key]


def init_prediction_widget_value(
    state: MutableMapping,
    key: str,
    db_value,
    default=0,
):
    if key not in state:
        state[key] = default if db_value is None else db_value
    return state[key]


def mark_prediction_saved(
    state: MutableMapping,
    player_id,
    match_number,
    payload: dict,
    match_id=None,
) -> None:
    cache = state.setdefault(_cache_key(player_id), {})
    cache_id = match_id
    if cache_id is None:
        cache_id = next(
            (
                existing_id
                for existing_id, row in cache.items()
                if row.get("match_number") == match_number
            ),
            f"match_number:{match_number}",
        )
    was_saved = cache_id in cache
    cache[cache_id] = {
        **cache.get(cache_id, {}),
        **payload,
        "match_id": match_id or cache.get(cache_id, {}).get("match_id"),
        "match_number": match_number,
        "updated_at": datetime.now(timezone.utc),
    }
    state.setdefault("saved_predictions", {})[match_number] = dict(payload)
    state.setdefault("save_status_by_match", {})[match_number] = "saved"
    progress = state.get("progress_counts")
    if progress and not was_saved:
        key = "group_saved" if int(match_number) <= 72 else "knockout_saved"
        progress[key] = min(progress[key] + 1, progress[key.replace("saved", "total")])


def get_progress_counts(
    state: MutableMapping,
    player_id,
    group_match_ids: set,
    knockout_match_numbers: set,
) -> dict[str, int]:
    cache = state.get(_cache_key(player_id), {})
    group_saved = sum(match_id in cache for match_id in group_match_ids)
    cached_numbers = {
        row.get("match_number")
        for row in cache.values()
        if row.get("match_number") is not None
    }
    knockout_saved = len(cached_numbers & knockout_match_numbers)
    counts = {
        "group_saved": group_saved,
        "group_total": len(group_match_ids),
        "knockout_saved": knockout_saved,
        "knockout_total": len(knockout_match_numbers),
    }
    state["progress_counts"] = counts
    return counts


def get_or_init_pending_match_ids(
    state: MutableMapping,
    player_id,
    all_group_match_ids: set,
) -> set:
    key = _pending_key(player_id)
    if state.get(key) is None:
        cache = state.get(_cache_key(player_id), {})
        state[key] = set(all_group_match_ids) - set(cache)
    return state[key]


def reset_pending_match_ids(state: MutableMapping, player_id) -> None:
    state[_pending_key(player_id)] = None
