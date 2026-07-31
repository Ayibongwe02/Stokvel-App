"""
Group routes
============
Create a new stokvel group, join one via invite code, and switch the
active group. Switching re-checks membership against the DB before
trusting the group_id — a user can never activate a group they don't
belong to, no matter what's in the request.
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from src.data_loader import seed_group_with_sample_data
from src.forms import GroupCreateForm, GroupJoinForm
from src.models import Group, GroupMembership, db

bp = Blueprint("groups", __name__, url_prefix="/groups")


@bp.route("/")
@login_required
def index():
    create_form = GroupCreateForm()
    join_form = GroupJoinForm()
    memberships = (
        GroupMembership.query.filter_by(user_id=current_user.id)
        .order_by(GroupMembership.joined_at.asc())
        .all()
    )
    active_group_id = session.get("active_group_id")
    return render_template(
        "groups/index.html",
        memberships=memberships,
        active_group_id=active_group_id,
        create_form=create_form,
        join_form=join_form,
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
    db.session.flush()  # get group.id before commit

    membership = GroupMembership(user_id=current_user.id, group_id=group.id, role="admin")
    db.session.add(membership)
    db.session.commit()

    seed_group_with_sample_data(group.id)

    session["active_group_id"] = group.id
    flash(f"Created '{group.name}'. Loaded with sample data — upload your own from Data Source.", "success")
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


@bp.route("/switch/<int:group_id>", methods=["POST"])
@login_required
def switch(group_id):
    membership = GroupMembership.query.filter_by(user_id=current_user.id, group_id=group_id).first()
    if membership is None:
        # Not a member of this group — refuse, don't just fall through.
        abort(403)

    session["active_group_id"] = group_id
    flash(f"Switched to '{membership.group.name}'.", "success")
    return redirect(request.referrer or url_for("overview"))
