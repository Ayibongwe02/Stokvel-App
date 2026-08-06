"""
Assistant routes
================
JSON chat endpoint used by the floating chat widget in base.html, plus
a small history/notifications endpoint. Everything here is scoped to
the current user's active group via get_active_membership() — same
pattern as every other route in the app.
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from src import assistant
from src.data_loader import get_dataset
from src.group_access import get_active_membership
from src.models import AuditLog, ChatMessage, Notification, db

bp = Blueprint("assistant", __name__, url_prefix="/assistant")


def _build_group_context(membership):
    group = membership.group
    tx_df, hist_df, hist_available, meta, members = get_dataset(group.id)
    context = {
        "group_name": group.name,
        "member_count": len(members),
        "your_role": membership.role,
    }
    if not tx_df.empty:
        latest_balances = tx_df.sort_values("date").groupby("member_id").last()["balance"]
        context["total_balance"] = float(latest_balances.sum())
        context["total_contrib"] = float(tx_df["contribution_amount"].sum())
        context["total_withdraw"] = float(tx_df["withdrawal_amount"].sum())
    return context


def _execute_tool(name, tool_input, group_id):
    member_id = tool_input.get("member_id", "unknown")
    if name == "send_reminder":
        message = tool_input.get("message", "Please remember to contribute.")
        db.session.add(Notification(group_id=group_id, target_user_id=None, kind="reminder", message=f"[{member_id}] {message}"))
        AuditLog.record(current_user.id, group_id, "assistant_reminder", f"member={member_id}")
        db.session.commit()
        return f"Reminder raised for member {member_id}."
    if name == "flag_at_risk":
        reason = tool_input.get("reason", "")
        db.session.add(Notification(group_id=group_id, target_user_id=None, kind="at_risk", message=f"[{member_id}] {reason}"))
        AuditLog.record(current_user.id, group_id, "assistant_flag_at_risk", f"member={member_id}: {reason}")
        db.session.commit()
        return f"Flagged member {member_id} as at-risk for admins to review."
    return "Unknown tool — no action taken."


@bp.route("/chat", methods=["POST"])
@login_required
def chat():
    membership = get_active_membership()
    if membership is None:
        return jsonify(error="Join or create a group first."), 400

    payload = request.get_json(silent=True) or {}
    user_message = (payload.get("message") or "").strip()
    if not user_message:
        return jsonify(error="Empty message."), 400

    db.session.add(ChatMessage(user_id=current_user.id, group_id=membership.group_id, role="user", content=user_message))
    db.session.commit()

    group_context = _build_group_context(membership)
    result = assistant.chat(
        user_message,
        group_context,
        execute_tool=lambda name, inp: _execute_tool(name, inp, membership.group_id),
    )

    db.session.add(
        ChatMessage(user_id=current_user.id, group_id=membership.group_id, role="assistant", content=result["reply"])
    )
    db.session.commit()

    return jsonify(reply=result["reply"], actions_taken=result["actions_taken"])


@bp.route("/history", methods=["GET"])
@login_required
def history():
    membership = get_active_membership()
    group_id = membership.group_id if membership else None
    rows = (
        ChatMessage.query.filter_by(user_id=current_user.id, group_id=group_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(50)
        .all()
    )
    return jsonify(messages=[{"role": r.role, "content": r.content} for r in rows])


@bp.route("/notifications", methods=["GET"])
@login_required
def notifications():
    membership = get_active_membership()
    if membership is None:
        return jsonify(notifications=[])
    rows = (
        Notification.query.filter_by(group_id=membership.group_id)
        .order_by(Notification.created_at.desc())
        .limit(20)
        .all()
    )
    return jsonify(
        notifications=[
            {"kind": n.kind, "message": n.message, "is_read": n.is_read, "created_at": n.created_at.isoformat()}
            for n in rows
        ]
    )
