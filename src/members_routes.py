"""
Members routes
===============
Two things live here:

1. Admin pre-registration: an admin fills in a name (and whatever
   extended details they already have -- banking, ID, occupation,
   next-of-kin, custom fields) and gets back a shareable invite-link
   token. Whoever opens that link just sets an email + password; the
   account and group membership are created for them, pre-filled with
   everything the admin already captured.

2. Per-group custom fields: admin-defined extra membership fields
   (e.g. "Employer", "Stand number") that show up as inputs on the
   pre-registration form and get stored per-member.
"""

import json
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user

from src.group_access import get_active_membership
from src.forms import (
    ClaimInviteForm,
    CustomFieldForm,
    DeleteCustomFieldForm,
    PreRegisterMemberForm,
    RevokePendingMemberForm,
)
from src.models import AuditLog, GroupCustomField, GroupMembership, PendingMember, User, UserProfile, db

bp = Blueprint("members", __name__)

_PROFILE_FIELDS = ("phone", "id_number", "bank_account_holder", "bank_name", "bank_account_number", "bank_branch_code")
_MEMBERSHIP_FIELDS = ("occupation", "next_of_kin_name", "next_of_kin_phone")


def _require_admin():
    membership = get_active_membership()
    if membership is None or membership.role != "admin":
        abort(403)
    return membership


# --------------------------------------------------------------------------
# Admin: pre-register a member
# --------------------------------------------------------------------------
@bp.route("/settings/members/pre-register", methods=["POST"])
@login_required
def pre_register():
    membership = _require_admin()
    form = PreRegisterMemberForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("settings.index"))

    profile_data = {f: (getattr(form, f).data or "").strip() or None for f in _PROFILE_FIELDS}
    membership_data = {f: (getattr(form, f).data or "").strip() or None for f in _MEMBERSHIP_FIELDS}

    custom_defs = GroupCustomField.query.filter_by(group_id=membership.group_id).all()
    custom_values = {}
    for cf in custom_defs:
        val = (request.form.get(f"custom_{cf.key}") or "").strip()
        if val:
            custom_values[cf.key] = val
    membership_data["custom_fields"] = custom_values

    pending = PendingMember(
        group_id=membership.group_id,
        invited_by=current_user.id,
        token=PendingMember.generate_token(),
        name=form.name.data.strip(),
        email=(form.email.data or "").strip().lower() or None,
        role=form.role.data if form.role.data in ("member", "admin") else "member",
        profile_json=json.dumps(profile_data),
        membership_json=json.dumps(membership_data),
    )
    db.session.add(pending)
    AuditLog.record(current_user.id, membership.group_id, "member_preregistered", f"name={pending.name}")
    db.session.commit()

    invite_link = url_for("members.claim_invite", token=pending.token, _external=True)
    flash(f"Invite link created for {pending.name}: {invite_link}", "success")
    return redirect(url_for("settings.index"))


@bp.route("/settings/members/pending/revoke", methods=["POST"])
@login_required
def revoke_pending():
    membership = _require_admin()
    form = RevokePendingMemberForm()
    if not form.validate_on_submit():
        return redirect(url_for("settings.index"))

    try:
        pending_id = int(form.pending_id.data)
    except (TypeError, ValueError):
        abort(400)

    pending = PendingMember.query.filter_by(id=pending_id, group_id=membership.group_id).first()
    if pending is None:
        abort(404)
    if pending.status == "pending":
        pending.status = "revoked"
        AuditLog.record(current_user.id, membership.group_id, "member_preregistration_revoked", f"pending #{pending.id}")
        db.session.commit()
        flash("Invite revoked.", "success")
    return redirect(url_for("settings.index"))


# --------------------------------------------------------------------------
# Public: claim an invite link
# --------------------------------------------------------------------------
@bp.route("/invite/<token>", methods=["GET", "POST"])
def claim_invite(token):
    pending = PendingMember.query.filter_by(token=token).first()
    if pending is None or pending.status != "pending":
        return render_template("invite_invalid.html")

    form = ClaimInviteForm(email=pending.email or "")
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists — log in instead.", "error")
            return render_template("invite_claim.html", pending=pending, form=form)

        user = User(email=email, name=pending.name)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()  # get user.id

        gm = GroupMembership(user_id=user.id, group_id=pending.group_id, role=pending.role)
        m_data = pending.membership_data()
        for f in _MEMBERSHIP_FIELDS:
            if m_data.get(f):
                setattr(gm, f, m_data[f])
        gm.set_custom_fields(m_data.get("custom_fields") or {})
        db.session.add(gm)

        profile = UserProfile(user_id=user.id)
        p_data = pending.profile_data()
        for f in _PROFILE_FIELDS:
            if p_data.get(f):
                setattr(profile, f, p_data[f])
        db.session.add(profile)

        pending.status = "claimed"
        pending.claimed_at = datetime.now(timezone.utc)
        pending.claimed_user_id = user.id

        AuditLog.record(user.id, pending.group_id, "member_preregistration_claimed", f"pending #{pending.id}")
        db.session.commit()

        login_user(user)
        flash(f"Welcome, {user.name} — your account and membership are set up.", "success")
        return redirect(url_for("overview"))

    return render_template("invite_claim.html", pending=pending, form=form)


# --------------------------------------------------------------------------
# Admin: custom fields
# --------------------------------------------------------------------------
@bp.route("/settings/custom-fields/add", methods=["POST"])
@login_required
def add_custom_field():
    membership = _require_admin()
    form = CustomFieldForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("settings.index"))

    label = form.label.data.strip()
    key = GroupCustomField.slugify(label)
    if GroupCustomField.query.filter_by(group_id=membership.group_id, key=key).first():
        flash(f"A field like '{label}' already exists for this group.", "error")
        return redirect(url_for("settings.index"))

    max_order = db.session.query(db.func.max(GroupCustomField.sort_order)).filter_by(group_id=membership.group_id).scalar() or 0
    field = GroupCustomField(group_id=membership.group_id, key=key, label=label, sort_order=max_order + 1)
    db.session.add(field)
    AuditLog.record(current_user.id, membership.group_id, "custom_field_added", label)
    db.session.commit()
    flash(f"Added custom field '{label}'.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/settings/custom-fields/delete", methods=["POST"])
@login_required
def delete_custom_field():
    membership = _require_admin()
    form = DeleteCustomFieldForm()
    if not form.validate_on_submit():
        return redirect(url_for("settings.index"))

    try:
        field_id = int(form.field_id.data)
    except (TypeError, ValueError):
        abort(400)

    field = GroupCustomField.query.filter_by(id=field_id, group_id=membership.group_id).first()
    if field is None:
        abort(404)

    AuditLog.record(current_user.id, membership.group_id, "custom_field_removed", field.label)
    db.session.delete(field)
    db.session.commit()
    flash("Custom field removed.", "success")
    return redirect(url_for("settings.index"))
