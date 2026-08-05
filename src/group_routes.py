"""
Group routes
============
Create a new stokvel group, join one via invite code, switch the active
group, and open a one-click sample preview workspace.

Switching re-checks membership against the DB before trusting the
group_id — a user can never activate a group they don't belong to.
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from src.data_loader import seed_group_with_sample_data
from src.forms import ExitSamplePreviewForm, GroupCreateForm, GroupJoinForm, PreviewSampleForm
from src.models import Group, GroupMembership, GroupSettings, db

bp = Blueprint("groups", __name__, url_prefix="/groups")

SAMPLE_PREVIEW_PREFIX = "Sample Preview"


def is_sample_preview_group(group) -> bool:
    """True when this group is a one-click sample demo workspace."""
    if group is None:
        return False
    name = getattr(group, "name", "") or ""
    return name.startswith(SAMPLE_PREVIEW_PREFIX)




@bp.route("/")
@login_required
def index():
    create_form = GroupCreateForm()
    join_form = GroupJoinForm()
    preview_form = PreviewSampleForm()
    memberships = (
        GroupMembership.query.filter_by(user_id=current_user.id)
        .order_by(GroupMembership.joined_at.asc())
        .all()
    )
    active_group_id = session.get("active_group_id")
    active_membership = None
    if active_group_id is not None:
        active_membership = next((m for m in memberships if m.group_id == active_group_id), None)
    if active_membership is None and memberships:
        active_membership = memberships[0]

    return render_template(
        "groups/index.html",
        memberships=memberships,
        active_group_id=active_group_id,
        active_membership=active_membership,
        create_form=create_form,
        join_form=join_form,
        preview_form=preview_form,
        is_fresh=len(memberships) == 0,
    )


@bp.route("/create", methods=["POST"])
@login_required
def create():
    form = GroupCreateForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("groups.index"))

    group = Group(name=form.name.data.strip(), region=(form.region.data or "").strip() or None)
    db.session.add(group)
    db.session.flush()

    membership = GroupMembership(user_id=current_user.id, group_id=group.id, role="admin")
    db.session.add(membership)
    db.session.commit()

    GroupSettings.get_or_create(group.id)
    # Intentionally empty — real groups start clean. Sample data is opt-in
    # via "Preview with sample data" on the get-started hub.

    session["active_group_id"] = group.id
    flash(
        f"Created '{group.name}'. Your ledger is empty — add members, upload data, "
        "or open Data Source when you're ready.",
        "success",
    )
    return redirect(url_for("overview"))


@bp.route("/preview-sample", methods=["POST"])
@login_required
def preview_sample():
    """Spin up (or reopen) a sample workspace so new users can explore
    balances, forecasts, and charts without uploading anything first."""
    form = PreviewSampleForm()
    if not form.validate_on_submit():
        return redirect(url_for("groups.index"))

    # Reuse an existing sample-preview group for this user if they already
    # opened one — avoids littering the account with demo workspaces.
    existing = (
        GroupMembership.query.filter_by(user_id=current_user.id, role="admin")
        .join(Group)
        .filter(Group.name.like(f"{SAMPLE_PREVIEW_PREFIX}%"))
        .order_by(GroupMembership.joined_at.desc())
        .first()
    )

    if existing is not None:
        group = existing.group
        seed_group_with_sample_data(group.id)
        session["active_group_id"] = group.id
        flash(f"Reopened '{group.name}' with fresh sample data.", "success")
        return redirect(url_for("overview"))

    label = f"{SAMPLE_PREVIEW_PREFIX} — {current_user.name.split()[0]}"
    group = Group(name=label[:150], region="Demo")
    db.session.add(group)
    db.session.flush()

    db.session.add(GroupMembership(user_id=current_user.id, group_id=group.id, role="admin"))
    db.session.commit()

    GroupSettings.get_or_create(group.id)
    seed_group_with_sample_data(group.id)

    session["active_group_id"] = group.id
    flash(
        "Sample preview is ready — explore Overview, Forecasts, and Payments. "
        "Create a real group from the menu when you want to start fresh.",
        "success",
    )
    return redirect(url_for("overview"))


@bp.route("/join", methods=["POST"])
@login_required
def join():
    form = GroupJoinForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("groups.index"))

    code = form.invite_code.data.strip().upper()
    group = Group.query.filter_by(invite_code=code).first()
    if group is None:
        flash("That invite code doesn't match any group.", "error")
        return redirect(url_for("groups.index"))

    existing = GroupMembership.query.filter_by(user_id=current_user.id, group_id=group.id).first()
    if existing is None:
        db.session.add(GroupMembership(user_id=current_user.id, group_id=group.id, role="member"))
        db.session.commit()
        flash(f"Joined '{group.name}'.", "success")
    else:
        flash(f"You're already a member of '{group.name}'.", "success")

    session["active_group_id"] = group.id
    return redirect(url_for("overview"))



@bp.route("/exit-sample-preview", methods=["POST"])
@login_required
def exit_sample_preview():
    """Leave the active sample-preview workspace and return to the hub.

    The demo group is removed when this user is its only member (the usual
    case), so the account stays tidy. If they still belong to other groups,
    the first remaining one becomes active.
    """
    form = ExitSamplePreviewForm()
    if not form.validate_on_submit():
        return redirect(url_for("groups.index"))

    group_id = session.get("active_group_id")
    membership = None
    if group_id is not None:
        membership = GroupMembership.query.filter_by(
            user_id=current_user.id, group_id=group_id
        ).first()

    if membership is None or not is_sample_preview_group(membership.group):
        flash("You're not in a sample preview right now.", "error")
        return redirect(url_for("groups.index"))

    group = membership.group
    group_name = group.name
    remaining = GroupMembership.query.filter_by(group_id=group.id).filter(
        GroupMembership.user_id != current_user.id
    ).count()

    db.session.delete(membership)
    db.session.commit()

    # Only the previewing user belongs to a sample workspace — clean it up.
    if remaining == 0:
        from src.models import (
            AccuracyCache,
            AuditLog,
            ChatMessage,
            ForecastCache,
            GroupCustomField,
            GroupSettings,
            HistoricalForecast,
            Notification,
            OnboardingProgress,
            PaymentTransaction,
            PendingMember,
            PendingTransaction,
            Transaction,
            WithdrawalApproval,
            WithdrawalRequest,
        )
        # Child rows first (approvals hang off withdrawal requests).
        wr_ids = [r.id for r in WithdrawalRequest.query.filter_by(group_id=group.id).all()]
        if wr_ids:
            WithdrawalApproval.query.filter(WithdrawalApproval.request_id.in_(wr_ids)).delete(
                synchronize_session=False
            )
        for model in (
            WithdrawalRequest,
            PaymentTransaction,
            PendingTransaction,
            PendingMember,
            Transaction,
            HistoricalForecast,
            ForecastCache,
            AccuracyCache,
            Notification,
            ChatMessage,
            AuditLog,
            GroupCustomField,
            OnboardingProgress,
            GroupSettings,
        ):
            model.query.filter_by(group_id=group.id).delete(synchronize_session=False)
        db.session.delete(group)
        db.session.commit()

    next_membership = (
        GroupMembership.query.filter_by(user_id=current_user.id)
        .order_by(GroupMembership.joined_at.asc())
        .first()
    )
    session["active_group_id"] = next_membership.group_id if next_membership else None

    flash(f"Left '{group_name}'. You're back at the start hub.", "success")
    return redirect(url_for("groups.index"))


@bp.route("/switch/<int:group_id>", methods=["POST"])
@login_required
def switch(group_id):
    membership = GroupMembership.query.filter_by(user_id=current_user.id, group_id=group_id).first()
    if membership is None:
        abort(403)

    session["active_group_id"] = group_id
    flash(f"Switched to '{membership.group.name}'.", "success")
    return redirect(request.referrer or url_for("overview"))
