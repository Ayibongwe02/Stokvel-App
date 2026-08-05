"""
AI assistant
============
Fully knowledge-based — no external AI provider, no API keys, no
network calls. Every reply is built from two layers, retrieved fresh
on every question:
  1. Real retrieval over a curated knowledge base (src/knowledge_base.py)
     — half "how this app works", half stokvel financial best practice
     — via TF-IDF, not a hardcoded blob.
  2. Live data — the current user's actual group balance/contribution
     numbers, scoped by group_id the same way every other route is.

This module never contacts an external service. There is no
"backend" to configure and no API key to set — it works out of the
box, the same way, every time.
"""

from src.knowledge_base import search as kb_search


def _build_reply(user_message: str, group_context: dict) -> str:
    hits = kb_search(user_message, k=2)
    lines = []

    total_balance = group_context.get("total_balance")
    if total_balance is not None:
        lines.append(
            f"Your group '{group_context.get('group_name', 'this group')}' has a total "
            f"balance of R{total_balance:,.2f} across {group_context.get('member_count')} "
            f"member(s), with R{group_context.get('total_contrib', 0):,.2f} contributed to date."
        )

    if hits:
        for h in hits:
            lines.append(f"**{h['title']}** — {h['text']}")
    else:
        lines.append(
            "I don't have a closely matching answer for that in my knowledge base — "
            "try rephrasing, or check the Settings/Payments pages directly."
        )

    return "\n\n".join(lines)


def chat(user_message: str, group_context: dict, execute_tool) -> dict:
    """Returns {"reply": str, "actions_taken": [str, ...]}.

    `execute_tool` is accepted for interface compatibility with the
    routes layer (kept in case a future purely-local rule wants to
    raise a reminder/at-risk flag), but this module never calls it
    itself — everything here is retrieval-only, no model in the loop.
    """
    return {"reply": _build_reply(user_message, group_context), "actions_taken": []}
