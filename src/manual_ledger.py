"""
Manual ledger
=============
Backing logic for admin-confirmed / admin-backfilled transactions.

Every manual entry (whether it started life as a member's pending
submission or was typed straight in by an admin) ends up as one
PendingTransaction row (for the audit trail: who submitted it, who
decided it, when) plus one Transaction row (for the actual ledger --
this is what overview/forecast/regional all read).

Balances are always *recalculated*, never patched in place: whenever
a member's transaction set changes (a manual entry is confirmed,
edited-then-confirmed, or backfilled), every one of that member's
Transaction rows is re-walked in date order and its `balance` column
rewritten as a running total. That's what keeps balances correct
regardless of whether the new entry landed at the end of the ledger
or was backdated into the middle of it.

Forecasts are deliberately NOT recomputed by any of this -- see
retrain_group() at the bottom, which is the only thing that lets a
manual edit actually reach a forecast fit.
"""

from datetime import datetime, timezone

from src.models import AccuracyCache, AuditLog, ForecastCache, GroupSettings, PendingTransaction, Transaction, db


def _utcnow():
    return datetime.now(timezone.utc)


def member_id_for_user(user_id: int) -> str:
    """The convention already used by payments_routes.py: a real
    registered member's rows in `transactions` are keyed by
    str(user.id), not an arbitrary CSV member_id."""
    return str(user_id)


def recalculate_member_balance(group_id: int, member_id: str) -> None:
    """Re-walk this member's transactions in date order (ties broken
    by id, i.e. insertion order) and rewrite `balance` as a running
    contribution-minus-withdrawal total. Call this after any insert,
    edit, or backdated entry -- never trust a balance that was set
    once at insert time."""
    rows = (
        Transaction.query.filter_by(group_id=group_id, member_id=member_id)
        .order_by(Transaction.date.asc(), Transaction.id.asc())
        .all()
    )
    running = 0.0
    for row in rows:
        running += (row.contribution_amount or 0.0) - (row.withdrawal_amount or 0.0)
        row.balance = running


def _apply_pending_transaction(pt: PendingTransaction, decided_by_user_id: int, *, amount=None, date=None, note=None) -> Transaction:
    """Shared by both confirm() and backfill(): writes the Transaction
    row, links it back to the PendingTransaction, recalculates the
    member's balance, and logs it. Caller commits."""
    final_amount = amount if amount is not None else pt.amount
    final_date = date if date is not None else pt.date
    if note is not None:
        pt.note = note

    member_id = member_id_for_user(pt.member_user_id)
    tx = Transaction(
        group_id=pt.group_id,
        member_id=member_id,
        date=final_date,
        contribution_amount=final_amount if pt.entry_type == "contribution" else 0.0,
        withdrawal_amount=final_amount if pt.entry_type == "withdrawal" else 0.0,
        balance=0.0,
        contribution_frequency="Unknown",
        source="manual",
        entered_by=decided_by_user_id,
        created_at=_utcnow(),
    )
    db.session.add(tx)
    db.session.flush()

    pt.amount = final_amount
    pt.date = final_date
    pt.status = "confirmed"
    pt.decided_by = decided_by_user_id
    pt.decided_at = _utcnow()
    pt.resulting_transaction_id = tx.id

    recalculate_member_balance(pt.group_id, member_id)
    return tx


def confirm_pending_transaction(pt: PendingTransaction, admin_user_id: int, *, amount=None, date=None, note=None) -> Transaction:
    """Admin confirms a member-submitted entry, optionally editing the
    amount/date/note first."""
    tx = _apply_pending_transaction(pt, admin_user_id, amount=amount, date=date, note=note)
    AuditLog.record(
        admin_user_id, pt.group_id, "manual_transaction_confirmed",
        f"{pt.entry_type} R{pt.amount:.2f} for user #{pt.member_user_id} (pending #{pt.id})",
    )
    db.session.commit()
    return tx


def reject_pending_transaction(pt: PendingTransaction, admin_user_id: int, reason: str = "") -> None:
    pt.status = "rejected"
    pt.decided_by = admin_user_id
    pt.decided_at = _utcnow()
    pt.decision_note = reason or None
    AuditLog.record(
        admin_user_id, pt.group_id, "manual_transaction_rejected",
        f"pending #{pt.id}" + (f" — {reason}" if reason else ""),
    )
    db.session.commit()


def backfill_transaction(*, group_id: int, member_user_id: int, entry_type: str, amount: float, date, note: str, admin_user_id: int) -> Transaction:
    """Admin types in a historical entry directly (no member
    submission first). Still goes through PendingTransaction, already
    confirmed, so the audit trail is identical in shape to a
    member-submitted-then-confirmed entry."""
    pt = PendingTransaction(
        group_id=group_id,
        member_user_id=member_user_id,
        submitted_by=admin_user_id,
        entry_type=entry_type,
        amount=amount,
        date=date,
        note=note,
        status="pending",
    )
    db.session.add(pt)
    db.session.flush()

    tx = _apply_pending_transaction(pt, admin_user_id)
    AuditLog.record(
        admin_user_id, group_id, "manual_transaction_backfilled",
        f"{entry_type} R{amount:.2f} for user #{member_user_id}",
    )
    db.session.commit()
    return tx


def retrain_group(group_id: int, admin_user_id: int) -> None:
    """Unfreezes forecasts: bumps the cutoff to now() (so every manual
    entry made up to this point is now included in the next fit) and
    clears the forecast/accuracy caches so that next fit actually
    happens instead of serving a stale cached one."""
    settings = GroupSettings.get_or_create(group_id)
    settings.last_retrained_at = _utcnow()

    ForecastCache.query.filter_by(group_id=group_id).delete()
    AccuracyCache.query.filter_by(group_id=group_id).delete()

    AuditLog.record(admin_user_id, group_id, "forecasts_retrained")
    db.session.commit()
