"""
Payments routes
================
Deposits: hosted PayFast checkout, confirmed only via ITN webhook
(never on browser redirect). Withdrawals: member requests, admin(s)
approve per GroupSettings.required_approvals, then an admin marks it
paid (real payout-API wiring is a drop-in for later; the manual
"admin confirms it was sent" path is the safe default since payout/
disbursement API access often needs a higher merchant tier than basic
collections).
"""

import uuid
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from src import payments
from src.forms import ContributeForm, WithdrawalDecisionForm, WithdrawalRequestForm
from src.group_access import get_active_membership, group_required
from src.models import (
    AuditLog,
    GroupSettings,
    Notification,
    PaymentTransaction,
    Transaction,
    WithdrawalApproval,
    WithdrawalRequest,
    db,
)

bp = Blueprint("payments", __name__, url_prefix="/payments")


@bp.route("/", methods=["GET"])
@group_required
def index():
    membership = get_active_membership()
    group_id = membership.group_id

    my_payments = (
        PaymentTransaction.query.filter_by(user_id=current_user.id, group_id=group_id)
        .order_by(PaymentTransaction.created_at.desc())
        .limit(20)
        .all()
    )
    withdrawals = (
        WithdrawalRequest.query.filter_by(group_id=group_id)
        .order_by(WithdrawalRequest.created_at.desc())
        .limit(20)
        .all()
    )
    settings = GroupSettings.get_or_create(group_id)

    return render_template(
        "payments.html",
        contribute_form=ContributeForm(),
        withdraw_form=WithdrawalRequestForm(),
        decision_form=WithdrawalDecisionForm(),
        my_payments=my_payments,
        withdrawals=withdrawals,
        settings=settings,
        sandbox=payments.SANDBOX,
        is_admin=(membership.role == "admin"),
    )


@bp.route("/contribute", methods=["POST"])
@group_required
def contribute():
    membership = get_active_membership()
    form = ContributeForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("payments.index"))

    try:
        amount = float(form.amount.data)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Enter a valid amount.", "error")
        return redirect(url_for("payments.index"))

    m_payment_id = uuid.uuid4().hex
    tx = PaymentTransaction(
        m_payment_id=m_payment_id,
        user_id=current_user.id,
        group_id=membership.group_id,
        amount=amount,
        status="pending",
    )
    db.session.add(tx)
    AuditLog.record(current_user.id, membership.group_id, "contribution_initiated", f"R{amount:.2f}")
    db.session.commit()

    base = request.url_root.rstrip("/")
    payload = payments.build_checkout_payload(
        m_payment_id=m_payment_id,
        amount=amount,
        item_name=f"Stokvel contribution — {membership.group.name}",
        return_url=f"{base}{url_for('payments.return_ok')}",
        cancel_url=f"{base}{url_for('payments.return_cancel')}",
        notify_url=f"{base}{url_for('payments.notify')}",
        email=current_user.email,
    )
    return render_template("payfast_redirect.html", checkout_url=payments.CHECKOUT_URL, payload=payload)


@bp.route("/return/ok")
@login_required
def return_ok():
    flash("Payment submitted — it will reflect once PayFast confirms it (usually seconds).", "success")
    return redirect(url_for("payments.index"))


@bp.route("/return/cancel")
@login_required
def return_cancel():
    flash("Payment cancelled.", "error")
    return redirect(url_for("payments.index"))


@bp.route("/notify", methods=["POST"])
def notify():
    """PayFast ITN webhook. No login/CSRF here by design — it's a
    server-to-server call from PayFast, authenticated by signature
    instead. Idempotent on m_payment_id so a duplicate webhook can't
    double-credit a contribution."""
    data = request.form.to_dict()

    if not payments.verify_itn_signature(data):
        return "invalid signature", 400

    m_payment_id = data.get("m_payment_id")
    tx = PaymentTransaction.query.filter_by(m_payment_id=m_payment_id).first()
    if tx is None:
        return "unknown payment", 404

    if tx.status == "complete":
        return "ok", 200

    payment_status = data.get("payment_status", "").upper()
    tx.pf_payment_id = data.get("pf_payment_id")

    if payment_status == "COMPLETE":
        tx.status = "complete"
        tx.confirmed_at = datetime.now(timezone.utc)

        latest = (
            Transaction.query.filter_by(group_id=tx.group_id, member_id=str(tx.user_id))
            .order_by(Transaction.date.desc())
            .first()
        )
        running_balance = (latest.balance if latest else 0.0) + tx.amount
        db.session.add(
            Transaction(
                group_id=tx.group_id,
                member_id=str(tx.user_id),
                date=tx.confirmed_at.date(),
                contribution_amount=tx.amount,
                withdrawal_amount=0.0,
                balance=running_balance,
                contribution_frequency="Unknown",
            )
        )
        AuditLog.record(tx.user_id, tx.group_id, "contribution_confirmed", f"R{tx.amount:.2f} pf_id={tx.pf_payment_id}")
    else:
        tx.status = "failed"
        AuditLog.record(tx.user_id, tx.group_id, "contribution_failed", payment_status)

    db.session.commit()
    return "ok", 200


@bp.route("/withdraw", methods=["POST"])
@group_required
def request_withdrawal():
    membership = get_active_membership()
    form = WithdrawalRequestForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("payments.index"))

    try:
        amount = float(form.amount.data)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Enter a valid amount.", "error")
        return redirect(url_for("payments.index"))

    settings = GroupSettings.get_or_create(membership.group_id)
    needed = settings.required_approvals
    if settings.withdrawal_approval_threshold and amount > settings.withdrawal_approval_threshold:
        needed = max(needed, 2)

    wr = WithdrawalRequest(
        group_id=membership.group_id,
        requested_by=current_user.id,
        member_id=form.member_id.data or str(current_user.id),
        amount=amount,
        reason=form.reason.data,
        approvals_needed=needed,
    )
    db.session.add(wr)
    AuditLog.record(current_user.id, membership.group_id, "withdrawal_requested", f"R{amount:.2f}")
    db.session.commit()
    flash("Withdrawal request submitted for admin approval.", "success")
    return redirect(url_for("payments.index"))


@bp.route("/withdraw/decide", methods=["POST"])
@group_required
def decide_withdrawal():
    membership = get_active_membership()
    if membership.role != "admin":
        abort(403)

    form = WithdrawalDecisionForm()
    if not form.validate_on_submit():
        return redirect(url_for("payments.index"))

    wr = WithdrawalRequest.query.filter_by(id=int(form.request_id.data), group_id=membership.group_id).first()
    if wr is None:
        abort(404)

    decision = form.decision.data
    if decision in ("approved", "rejected"):
        if wr.status != "pending":
            flash("This request has already been decided.", "error")
            return redirect(url_for("payments.index"))

        existing = WithdrawalApproval.query.filter_by(request_id=wr.id, admin_id=current_user.id).first()
        if existing is None:
            db.session.add(WithdrawalApproval(request_id=wr.id, admin_id=current_user.id, decision=decision))

        if decision == "rejected":
            wr.status = "rejected"
            wr.decided_at = datetime.now(timezone.utc)
        else:
            db.session.flush()
            if wr.approvals_count() >= wr.approvals_needed:
                wr.status = "approved"
                wr.decided_at = datetime.now(timezone.utc)

        AuditLog.record(current_user.id, membership.group_id, f"withdrawal_{decision}", f"request #{wr.id}")

    elif decision == "paid" and wr.status == "approved":
        wr.status = "paid"
        latest = (
            Transaction.query.filter_by(group_id=wr.group_id, member_id=wr.member_id)
            .order_by(Transaction.date.desc())
            .first()
        )
        running_balance = (latest.balance if latest else 0.0) - wr.amount
        db.session.add(
            Transaction(
                group_id=wr.group_id,
                member_id=wr.member_id,
                date=datetime.now(timezone.utc).date(),
                contribution_amount=0.0,
                withdrawal_amount=wr.amount,
                balance=running_balance,
                contribution_frequency="Unknown",
            )
        )
        AuditLog.record(current_user.id, membership.group_id, "withdrawal_paid", f"request #{wr.id}")

    db.session.commit()
    flash("Withdrawal request updated.", "success")
    return redirect(url_for("payments.index"))
