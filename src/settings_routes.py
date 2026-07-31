"""
Settings routes
================
Account settings (profile, password) plus membership management for
the currently active group: leave the group, regenerate its invite
code (admin only), remove a member (admin only).
"""

from flask import Blueprint, abort, flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from src.accuracy_view import build_accuracy_context
from src.forms import (
    ChangePasswordForm,
    GroupSettingsForm,
    InviteRegenerateForm,
    LeaveGroupForm,
    NotificationPrefsForm,
    ProfileForm,
    RemoveMemberForm,
)
from src.group_access import get_active_membership
from src.models import AuditLog, GroupMembership, GroupSettings, UserProfile, db

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET"])
@login_required
def index():
    membership = get_active_membership()
    profile_form = ProfileForm(name=current_user.name)
    password_form = ChangePasswordForm()
    invite_form = InviteRegenerateForm()
    leave_form = LeaveGroupForm()
    remove_form = RemoveMemberForm()

    user_profile = UserProfile.get_or_create(current_user.id)
    notif_form = NotificationPrefsForm(
        phone=user_profile.phone,
        notify_email="1" if user_profile.notify_email else "0",
        notify_in_app="1" if user_profile.notify_in_app else "0",
    )

    group_members = []
    group_settings = None
    group_settings_form = None
    accuracy_ctx = {
        "acc_has_members": False,
        "acc_best_model": None,
        "acc_bar_charts": {},
        "acc_pivot_rows": [],
        "acc_hist_comparison": [],
        "acc_hist_available": False,
    }
    if membership:
        group_members = (
            GroupMembership.query.filter_by(group_id=membership.group_id)
            .order_by(GroupMembership.joined_at.asc())
            .all()
        )
        group_settings = GroupSettings.get_or_create(membership.group_id)
        group_settings_form = GroupSettingsForm(
            contribution_amount=group_settings.contribution_amount or "",
            contribution_frequency=group_settings.contribution_frequency,
            payout_rules=group_settings.payout_rules or "",
            withdrawal_approval_threshold=group_settings.withdrawal_approval_threshold or "",
            required_approvals=str(group_settings.required_approvals),
        )
        try:
            accuracy_ctx = build_accuracy_context(membership.group_id)
        except Exception:
            flash(
                "Accuracy health couldn't be computed right now — try refreshing "
                "the Settings page in a moment.",
                "error",
            )

    return render_template(
        "settings.html",
        membership=membership,
        group_members=group_members,
        profile_form=profile_form,
        password_form=password_form,
        invite_form=invite_form,
        leave_form=leave_form,
        remove_form=remove_form,
        notif_form=notif_form,
        group_settings=group_settings,
        group_settings_form=group_settings_form,
        **accuracy_ctx,
    )


@bp.route("/notifications", methods=["POST"])
@login_required
def update_notifications():
    form = NotificationPrefsForm()
    if form.validate_on_submit():
        profile = UserProfile.get_or_create(current_user.id)
        profile.phone = form.phone.data.strip() if form.phone.data else None
        profile.notify_email = form.notify_email.data == "1"
        profile.notify_in_app = form.notify_in_app.data == "1"
        db.session.commit()
        flash("Notification preferences saved.", "success")
    else:
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
    return redirect(url_for("settings.index"))


@bp.route("/group/update", methods=["POST"])
@login_required
def update_group_settings():
    membership = get_active_membership()
    if membership is None or membership.role != "admin":
        abort(403)

    form = GroupSettingsForm()
    if form.validate_on_submit():
        settings = GroupSettings.get_or_create(membership.group_id)
        try:
            settings.contribution_amount = float(form.contribution_amount.data) if form.contribution_amount.data else None
            settings.withdrawal_approval_threshold = (
                float(form.withdrawal_approval_threshold.data) if form.withdrawal_approval_threshold.data else 0.0
            )
        except ValueError:
            flash("Amounts must be numbers.", "error")
            return redirect(url_for("settings.index"))
        settings.contribution_frequency = form.contribution_frequency.data
        settings.payout_rules = form.payout_rules.data
        settings.required_approvals = int(form.required_approvals.data)
        AuditLog.record(current_user.id, membership.group_id, "group_settings_updated")
        db.session.commit()
        flash("Group settings saved.", "success")
    else:
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
    return redirect(url_for("settings.index"))


@bp.route("/profile", methods=["POST"])
@login_required
def update_profile():
    form = ProfileForm()
    if form.validate_on_submit():
        current_user.name = form.name.data.strip()
        db.session.commit()
        flash("Profile updated.", "success")
    else:
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
    return redirect(url_for("settings.index"))


@bp.route("/password", methods=["POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Password changed.", "success")
    else:
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
    return redirect(url_for("settings.index"))


@bp.route("/group/invite/regenerate", methods=["POST"])
@login_required
def regenerate_invite():
    membership = get_active_membership()
    if membership is None or membership.role != "admin":
        abort(403)

    form = InviteRegenerateForm()
    if form.validate_on_submit():
        new_code = membership.group.regenerate_invite_code()
        db.session.commit()
        flash(f"New invite code: {new_code}", "success")
    return redirect(url_for("settings.index"))


@bp.route("/group/leave", methods=["POST"])
@login_required
def leave_group():
    membership = get_active_membership()
    if membership is None:
        abort(403)

    form = LeaveGroupForm()
    if not form.validate_on_submit():
        return redirect(url_for("settings.index"))

    group_name = membership.group.name
    group_id = membership.group_id

    if membership.role == "admin":
        other_admins = GroupMembership.query.filter_by(group_id=group_id, role="admin").filter(
            GroupMembership.user_id != current_user.id
        ).count()
        remaining_members = GroupMembership.query.filter_by(group_id=group_id).filter(
            GroupMembership.user_id != current_user.id
        ).count()
        if other_admins == 0 and remaining_members > 0:
            flash("Promote another member to admin before you leave.", "error")
            return redirect(url_for("settings.index"))

    db.session.delete(membership)
    db.session.commit()
    session.pop("active_group_id", None)
    flash(f"Left '{group_name}'.", "success")
    return redirect(url_for("groups.index"))


@bp.route("/group/members/remove", methods=["POST"])
@login_required
def remove_member():
    membership = get_active_membership()
    if membership is None or membership.role != "admin":
        abort(403)

    form = RemoveMemberForm()
    if not form.validate_on_submit():
        return redirect(url_for("settings.index"))

    try:
        target_user_id = int(form.member_user_id.data)
    except (TypeError, ValueError):
        abort(400)

    if target_user_id == current_user.id:
        flash("Use 'Leave group' to remove yourself.", "error")
        return redirect(url_for("settings.index"))

    target = GroupMembership.query.filter_by(user_id=target_user_id, group_id=membership.group_id).first()
    if target is None:
        abort(404)

    db.session.delete(target)
    db.session.commit()
    flash("Member removed.", "success")
    return redirect(url_for("settings.index"))
