"""Session memory beyond the transcript window.

Two layers, kept in the LangGraph checkpoint of the session:

- conversation_summary: a rolling summary of the messages that left the
  transcript window. The window holds at most history_max messages; when it
  overflows, the oldest are moved to summary_backlog until history_keep
  remain, and a background call folds the backlog into the summary.
- shopper_profile: lasting facts the shopper said about themselves (who the
  purchase is for, body size, brands or colours they like or avoid, use,
  style). The semantic model reports them as profile_updates of the turn.
"""

from __future__ import annotations

from collections.abc import Iterable

from .schemas import ProfileUpdate

# Messages waiting for the summary; a summary model that keeps failing must
# not let the checkpoint grow without bound.
MAX_BACKLOG_MESSAGES = 40
MAX_SUMMARY_CHARS = 2000

PROFILE_LABELS = {
    "recipient": "Mua cho",
    "body": "Vóc dáng/size",
    "preferred_brands": "Hãng thích",
    "avoided_brands": "Hãng không muốn",
    "preferred_colors": "Màu thích",
    "avoided_colors": "Màu không muốn",
    "use_case": "Mục đích sử dụng",
    "style": "Phong cách",
    "notes": "Ghi chú khác",
}


def apply_profile_updates(
    profile: dict | None, updates: Iterable[ProfileUpdate | dict]
) -> dict[str, str]:
    """The profile after this turn's updates; set with an empty value or
    remove drops the key, an unknown key or malformed update is ignored."""
    merged = {key: str(value) for key, value in (profile or {}).items() if key in PROFILE_LABELS and value}
    for raw in updates or []:
        try:
            update = raw if isinstance(raw, ProfileUpdate) else ProfileUpdate.model_validate(raw)
        except Exception:
            continue
        if update.action == "remove" or not update.value:
            merged.pop(update.key, None)
        else:
            merged[update.key] = update.value
    return merged


def split_history(
    history: list[dict], keep: int, maximum: int
) -> tuple[list[dict], list[dict]]:
    """(kept, evicted): nothing leaves until the transcript passes maximum,
    then it is cut back to the last keep messages."""
    keep = max(2, min(keep, maximum))
    if len(history) <= maximum:
        return list(history), []
    return list(history[-keep:]), list(history[:-keep])


def extend_backlog(backlog: list[dict] | None, evicted: list[dict]) -> list[dict]:
    return [*(backlog or []), *evicted][-MAX_BACKLOG_MESSAGES:]


def resolved_message(state: dict) -> str:
    """The message as the semantic model rewrote it to stand on its own,
    else the message as typed (fast paths, model down, UI actions)."""
    return str(state.get("standalone_query") or "").strip() or str(state.get("message") or "")


def memory_context(state: dict) -> dict:
    """What the models read about the session besides the recent transcript."""
    context: dict = {}
    summary = str(state.get("conversation_summary") or "").strip()
    if summary:
        context["earlier_conversation_summary"] = summary[:MAX_SUMMARY_CHARS]
    profile = {
        key: value
        for key, value in (state.get("shopper_profile") or {}).items()
        if key in PROFILE_LABELS and value
    }
    if profile:
        context["shopper_profile"] = profile
    return context


def memory_note(state: dict) -> str:
    """The same memory as readable Vietnamese lines for the reply models."""
    lines = []
    summary = str(state.get("conversation_summary") or "").strip()
    if summary:
        lines.append(f"Tóm tắt phần hội thoại trước: {summary[:MAX_SUMMARY_CHARS]}")
    profile = state.get("shopper_profile") or {}
    facts = [
        f"{PROFILE_LABELS[key]}: {value}"
        for key, value in profile.items()
        if key in PROFILE_LABELS and value
    ]
    if facts:
        lines.append("Khách đã cho biết: " + "; ".join(facts))
    return "\n".join(lines)
