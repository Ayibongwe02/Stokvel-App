"""
Group access control
=====================
Every dashboard page operates on the logged-in user's "active group",
tracked in the session as `active_group_id`. This module resolves that
group and enforces membership on every request — a user can never view
another group's data, including via URL manipulation, because routes
never take a group_id from the URL/query string at all; they only ever
use the server-side session + a fresh membership check against the DB.
"""

from functools import wraps

from flask import abort, g, redirect, session, url_for
from flask_login import current_user

from src.models import GroupMembership


def get_active_membership():
    """Return the current user's GroupMembership for their active
    group, re-validated against the DB on every call (never trust a
    stale session value blindly)."""
    if not current_user.is_authenticated:
        return None

    group_id = session.get("active_group_id")
    membership = None
    if group_id is not None:
        membership = GroupMembership.query.filter_by(
            user_id=current_user.id, group_id=group_id
        ).first()

    if membership is None:
        # Active group missing, invalid, or the user was removed from it —
        # fall back to their first remaining group, if any.
        membership = (
            GroupMembership.query.filter_by(user_id=current_user.id)
            .order_by(GroupMembership.joined_at.asc())
            .first()
        )
        session["active_group_id"] = membership.group_id if membership else None

    return membership


def group_required(view):
    """Require login AND an active group membership. Redirects to the
    group picker if the user has no groups yet."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

        membership = get_active_membership()
        if membership is None:
            return redirect(url_for("groups.index"))

        g.active_membership = membership
        g.active_group = membership.group
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Like group_required, but also requires an 'admin' role in the
    active group (invite/remove members, upload data)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

        membership = get_active_membership()
        if membership is None:
            return redirect(url_for("groups.index"))
        if membership.role != "admin":
            abort(403)

        g.active_membership = membership
        g.active_group = membership.group
        return view(*args, **kwargs)

    return wrapped
