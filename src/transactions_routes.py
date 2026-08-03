"""
Transactions routes
=====================
Manual ledger entries -- money that moved outside PayFast (cash,
EFT) and needs to be reflected in the app by hand.

Members submit a "pending" entry for themselves; an admin reviews the
queue and confirms (optionally editing the amount/date/note first),
or rejects with a reason. Admins can also backfill an entry directly
for any member, skipping the queue -- both paths end up going through
src.manual_ledger so the audit trail and balance recalculation are
identical either way.
"""

from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, url_for
from flask_login import current_user, login_required

from src import manual_ledger
from src.forms import ManualTransactionBackfillForm, ManualTransactionDecisionForm, ManualTransactionSubmitForm
from src.group_access import get_active_membership, group_required
from src.models import AuditLog, GroupMembership, PendingTransaction, db

bp = Blueprint("transactions", __name__, url_prefix="/transactions")


def _parse_amount(raw):
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _parse_date(raw):
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError, AttributeError):
        return None


@bp.route("/", methods=["GET"])
@group_required
def index():
    membership = g.active_membership
    is_admin = membership.role == "admin"

    my_submissions = (
        PendingTransaction.query.filter_by(group_id=membership.group_id, member_user_id=current_user.id)
        .order_by(PendingTransaction.created_at.desc())
        .limit(20)
        .all()
    )

    queue = []
    group_members = []
    if is_admin:
        queue = (
            PendingTransaction.query.filter_by(group_id=membership.group_id, status="pending")
            .order_by(PendingTransaction.created_at.asc())
            .all()
        )
        group_members = (
            GroupMembership.query.filter_by(group_id=membership.group_id)
            .order_by(GroupMembership.joined_at.asc())
            .all()
        )

    backfill_form = ManualTransactionBackfillForm()
    backfill_form.member_user_id.choices = [(gm.user_id, gm.user.name) for gm in group_members]

    return render_template(
        "transactions.html",
        is_admin=is_admin,
        submit_form=ManualTransactionSubmitForm(),
        decision_form=ManualTransactionDecisionForm(),
        backfill_form=backfill_form,
        my_submissions=my_submissions,
        queue=queue,
    )


@bp.route("/submit", methods=["POST"])
@group_required
def submit():
    membership = g.active_membership
    form = ManualTransactionSubmitForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("transactions.index"))

    amount = _parse_amount(form.amount.data)
    date = _parse_date(form.date.data)
    if amount is None:
        flash("Enter a valid amount.", "error")
        return redirect(url_for("transactions.index"))
    if date is None:
        flash("Enter a valid date (YYYY-MM-DD).", "error")
        return redirect(url_for("transactions.index"))

    pt = PendingTransaction(
        group_id=membership.group_id,
        member_user_id=current_user.id,
        submitted_by=current_user.id,
        entry_type=form.entry_type.data,
        amount=amount,
        date=date,
        note=(form.note.data or "").strip() or None,
        status="pending",
    )
    db.session.add(pt)
    AuditLog.record(current_user.id, membership.group_id, "manual_transaction_submitted", f"{pt.entry_type} R{amount:.2f}")
    db.session.commit()
    flash("Submitted — an admin will confirm it.", "success")
    return redirect(url_for("transactions.index"))


@bp.route("/decide", methods=["POST"])
@group_required
def decide():
    membership = g.active_membership
    if membership.role != "admin":
        abort(403)

    form = ManualTransactionDecisionForm()
    if not form.validate_on_submit():
        return redirect(url_for("transactions.index"))

    try:
        pending_id = int(form.pending_id.data)
    except (TypeError, ValueError):
        abort(400)

    pt = PendingTransaction.query.filter_by(id=pending_id, group_id=membership.group_id).first()
    if pt is None:
        abort(404)
    if pt.status != "pending":
        flash("This entry has already been decided.", "error")
        return redirect(url_for("transactions.index"))

    if form.decision.data == "confirm":
        amount = _parse_amount(form.amount.data) if form.amount.data else None
        date = _parse_date(form.date.data) if form.date.data else None
        if form.amount.data and amount is None:
            flash("Enter a valid amount.", "error")
            return redirect(url_for("transactions.index"))
        if form.date.data and date is None:
            flash("Enter a valid date (YYYY-MM-DD).", "error")
            return redirect(url_for("transactions.index"))
        manual_ledger.confirm_pending_transaction(
            pt, current_user.id, amount=amount, date=date, note=(form.note.data or "").strip() or None
        )
        flash("Entry confirmed and added to the ledger.", "success")
    elif form.decision.data == "reject":
        manual_ledger.reject_pending_transaction(pt, current_user.id, reason=(form.note.data or "").strip())
        flash("Entry rejected.", "success")
    else:
        abort(400)

    return redirect(url_for("transactions.index"))


@bp.route("/backfill", methods=["POST"])
@group_required
def backfill():
    membership = g.active_membership
    if membership.role != "admin":
        abort(403)

    group_members = GroupMembership.query.filter_by(group_id=membership.group_id).all()
    form = ManualTransactionBackfillForm()
    form.member_user_id.choices = [(gm.user_id, gm.user.name) for gm in group_members]

    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("transactions.index"))

    amount = _parse_amount(form.amount.data)
    date = _parse_date(form.date.data)
    if amount is None:
        flash("Enter a valid amount.", "error")
        return redirect(url_for("transactions.index"))
    if date is None:
        flash("Enter a valid date (YYYY-MM-DD).", "error")
        return redirect(url_for("transactions.index"))

    target = GroupMembership.query.filter_by(group_id=membership.group_id, user_id=form.member_user_id.data).first()
    if target is None:
        flash("That member isn't part of this group.", "error")
        return redirect(url_for("transactions.index"))

    manual_ledger.backfill_transaction(
        group_id=membership.group_id,
        member_user_id=target.user_id,
        entry_type=form.entry_type.data,
        amount=amount,
        date=date,
        note=(form.note.data or "").strip() or None,
        admin_user_id=current_user.id,
    )
    flash(f"Added {form.entry_type.data} of R{amount:.2f} for {target.user.name}.", "success")
    return redirect(url_for("transactions.index"))
