"""
Database models
================
SQLite-backed models (via Flask-SQLAlchemy) that replace the old flat
CSV files. Transactions and historical forecast rows are scoped by
`group_id` so each stokvel group's data is fully isolated.
"""

import json
import secrets
import string
from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def _utcnow():
    return datetime.now(timezone.utc)


def _generate_invite_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    memberships = db.relationship(
        "GroupMembership", back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def groups(self):
        return [m.group for m in self.memberships]

    def membership_for(self, group_id: int):
        for m in self.memberships:
            if m.group_id == group_id:
                return m
        return None

    def is_admin_of(self, group_id: int) -> bool:
        m = self.membership_for(group_id)
        return bool(m and m.role == "admin")


class Group(db.Model):
    __tablename__ = "groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    region = db.Column(db.String(120), nullable=True)
    invite_code = db.Column(db.String(16), unique=True, nullable=False, default=_generate_invite_code)
    created_at = db.Column(db.DateTime, default=_utcnow)

    memberships = db.relationship(
        "GroupMembership", back_populates="group", cascade="all, delete-orphan"
    )
    transactions = db.relationship(
        "Transaction", back_populates="group", cascade="all, delete-orphan"
    )
    historical_rows = db.relationship(
        "HistoricalForecast", back_populates="group", cascade="all, delete-orphan"
    )

    def regenerate_invite_code(self) -> str:
        self.invite_code = _generate_invite_code()
        return self.invite_code

    def member_count(self) -> int:
        return len(self.memberships)


class GroupMembership(db.Model):
    __tablename__ = "group_members"
    __table_args__ = (db.UniqueConstraint("user_id", "group_id", name="uq_user_group"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="member")
    joined_at = db.Column(db.DateTime, default=_utcnow)
    occupation = db.Column(db.String(120), nullable=True)
    next_of_kin_name = db.Column(db.String(120), nullable=True)
    next_of_kin_phone = db.Column(db.String(32), nullable=True)
    custom_fields_json = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="memberships")
    group = db.relationship("Group", back_populates="memberships")

    def custom_fields(self) -> dict:
        if not self.custom_fields_json:
            return {}
        try:
            return json.loads(self.custom_fields_json)
        except (TypeError, ValueError):
            return {}

    def set_custom_fields(self, values: dict) -> None:
        self.custom_fields_json = json.dumps(values or {})


class Transaction(db.Model):
    """Replaces the old stokvel_dataset.csv, scoped per group."""

    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    member_id = db.Column(db.String(64), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    contribution_amount = db.Column(db.Float, nullable=False, default=0.0)
    withdrawal_amount = db.Column(db.Float, nullable=False, default=0.0)
    balance = db.Column(db.Float, nullable=False)
    contribution_frequency = db.Column(db.String(40), nullable=True, default="Unknown")
    region = db.Column(db.String(120), nullable=True)
    category = db.Column(db.String(120), nullable=True)
    source = db.Column(db.String(20), nullable=False, default="upload")
    entered_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    group = db.relationship("Group", back_populates="transactions")


class HistoricalForecast(db.Model):
    """Replaces the old forecasting_dashboard.csv, scoped per group."""

    __tablename__ = "historical_forecasts"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    member_id = db.Column(db.String(64), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    balance = db.Column(db.Float, nullable=True)
    forecast_balance = db.Column(db.Float, nullable=True)
    rmse_holt_winters = db.Column(db.Float, nullable=True)
    rmse_arima = db.Column(db.Float, nullable=True)
    mae = db.Column(db.Float, nullable=True)
    mape = db.Column(db.Float, nullable=True)
    region = db.Column(db.String(120), nullable=True, default="Unknown")
    member_category = db.Column(db.String(120), nullable=True, default="Unknown")
    forecast_horizon = db.Column(db.String(60), nullable=True, default="Unknown")

    group = db.relationship("Group", back_populates="historical_rows")


class UserProfile(db.Model):
    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    phone = db.Column(db.String(32), nullable=True)
    notify_email = db.Column(db.Boolean, nullable=False, default=True)
    notify_in_app = db.Column(db.Boolean, nullable=False, default=True)
    language = db.Column(db.String(16), nullable=False, default="en")
    id_number = db.Column(db.String(20), nullable=True)
    bank_account_holder = db.Column(db.String(120), nullable=True)
    bank_name = db.Column(db.String(80), nullable=True)
    bank_account_number = db.Column(db.String(34), nullable=True)
    bank_branch_code = db.Column(db.String(10), nullable=True)

    user = db.relationship("User", backref=db.backref("profile", uselist=False))

    @staticmethod
    def get_or_create(user_id: int) -> "UserProfile":
        profile = UserProfile.query.filter_by(user_id=user_id).first()
        if profile is None:
            profile = UserProfile(user_id=user_id)
            db.session.add(profile)
            db.session.commit()
        return profile


class GroupSettings(db.Model):
    __tablename__ = "group_settings"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), unique=True, nullable=False)
    contribution_amount = db.Column(db.Float, nullable=True)
    contribution_frequency = db.Column(db.String(40), nullable=False, default="Monthly")
    payout_rules = db.Column(db.Text, nullable=True)
    withdrawal_approval_threshold = db.Column(db.Float, nullable=False, default=0.0)
    required_approvals = db.Column(db.Integer, nullable=False, default=1)
    last_retrained_at = db.Column(db.DateTime, nullable=True)

    group = db.relationship("Group", backref=db.backref("settings", uselist=False))

    @staticmethod
    def get_or_create(group_id: int) -> "GroupSettings":
        settings = GroupSettings.query.filter_by(group_id=group_id).first()
        if settings is None:
            settings = GroupSettings(group_id=group_id, last_retrained_at=_utcnow())
            db.session.add(settings)
            db.session.commit()
        return settings


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=True, index=True)
    action = db.Column(db.String(80), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow, index=True)

    actor = db.relationship("User")

    @staticmethod
    def record(actor_id, group_id, action, detail=""):
        entry = AuditLog(actor_id=actor_id, group_id=group_id, action=action, detail=detail)
        db.session.add(entry)
        return entry


class GroupCustomField(db.Model):
    """Admin-defined extra membership fields for one group (e.g. "ID
    number", "Employer") -- labels only; values live per-member on
    GroupMembership.custom_fields_json, keyed by `key`."""

    __tablename__ = "group_custom_fields"
    __table_args__ = (db.UniqueConstraint("group_id", "key", name="uq_group_custom_field_key"),)

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    key = db.Column(db.String(60), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)

    group = db.relationship("Group")

    @staticmethod
    def slugify(label: str) -> str:
        slug = "".join(c.lower() if c.isalnum() else "_" for c in label.strip()).strip("_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        return slug or "field"


class PendingMember(db.Model):
    """A slot an admin has pre-registered for someone who hasn't signed
    up yet: a shareable invite-link token that, once used, creates the
    account + group membership pre-filled with whatever the admin
    already captured (name, banking/ID/phone, per-group details)."""

    __tablename__ = "pending_members"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    invited_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="member")
    profile_json = db.Column(db.Text, nullable=True)
    membership_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, default=_utcnow)
    claimed_at = db.Column(db.DateTime, nullable=True)
    claimed_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    group = db.relationship("Group")
    inviter = db.relationship("User", foreign_keys=[invited_by])
    claimed_user = db.relationship("User", foreign_keys=[claimed_user_id])

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(24)

    def profile_data(self) -> dict:
        try:
            return json.loads(self.profile_json) if self.profile_json else {}
        except (TypeError, ValueError):
            return {}

    def membership_data(self) -> dict:
        try:
            return json.loads(self.membership_json) if self.membership_json else {}
        except (TypeError, ValueError):
            return {}


class PendingTransaction(db.Model):
    """Manual ledger entry queue: a member submits a contribution/
    withdrawal they made outside the app (cash, EFT), an admin
    confirms (optionally editing it), edits, or rejects it. Admin
    backfills go through the same table, pre-confirmed by the admin
    who entered them -- so every manual entry has one consistent
    audit trail regardless of who typed it in first."""

    __tablename__ = "pending_transactions"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    member_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    entry_type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, default=_utcnow)
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    decision_note = db.Column(db.String(255), nullable=True)
    resulting_transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"), nullable=True)

    group = db.relationship("Group")
    member_user = db.relationship("User", foreign_keys=[member_user_id])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    decider = db.relationship("User", foreign_keys=[decided_by])
    resulting_transaction = db.relationship("Transaction")


class PaymentMethod(db.Model):
    """Stores only a gateway-issued token reference — never raw card data."""

    __tablename__ = "payment_methods"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider = db.Column(db.String(40), nullable=False, default="payfast")
    token_reference = db.Column(db.String(255), nullable=True)
    label = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship("User")


class PaymentTransaction(db.Model):
    """One row per PayFast checkout attempt (deposit). Status flips from
    'pending' to 'complete'/'failed' only when the ITN webhook confirms it —
    never optimistically on redirect."""

    __tablename__ = "payment_transactions"

    id = db.Column(db.Integer, primary_key=True)
    m_payment_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    pf_payment_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User")
    group = db.relationship("Group")


class WithdrawalRequest(db.Model):
    __tablename__ = "withdrawal_requests"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    member_id = db.Column(db.String(64), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    approvals_needed = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=_utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)

    group = db.relationship("Group")
    requester = db.relationship("User")
    approvals = db.relationship("WithdrawalApproval", back_populates="request", cascade="all, delete-orphan")

    def approvals_count(self) -> int:
        return sum(1 for a in self.approvals if a.decision == "approved")


class WithdrawalApproval(db.Model):
    __tablename__ = "withdrawal_approvals"
    __table_args__ = (db.UniqueConstraint("request_id", "admin_id", name="uq_request_admin"),)

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("withdrawal_requests.id"), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    decision = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    request = db.relationship("WithdrawalRequest", back_populates="approvals")
    admin = db.relationship("User")


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)


class ForecastCache(db.Model):
    """Caches a single fitted model's forecast for one member so /forecast
    doesn't re-run Holt-Winters on every page load or nav. Keyed on
    a hash of the member's series -- when the underlying transaction data
    changes (upload/reset/new entries), the hash changes and the old row
    is simply never matched again (and gets overwritten)."""

    __tablename__ = "forecast_cache"
    __table_args__ = (
        db.UniqueConstraint("group_id", "member_id", "model", "horizon", name="uq_forecast_cache"),
    )

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    member_id = db.Column(db.String(64), nullable=False)
    model = db.Column(db.String(20), nullable=False)
    horizon = db.Column(db.Integer, nullable=False)
    data_hash = db.Column(db.String(64), nullable=False)
    forecast_json = db.Column(db.Text, nullable=False)
    resid_json = db.Column(db.Text, nullable=False)
    note = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)


class AccuracyCache(db.Model):
    """Caches backtest RMSE/MAE/MAPE per member+model so /accuracy (the
    single most expensive page -- N members x fit+backtest)
    doesn't recompute on every visit."""

    __tablename__ = "accuracy_cache"
    __table_args__ = (
        db.UniqueConstraint("group_id", "member_id", "model", name="uq_accuracy_cache"),
    )

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    member_id = db.Column(db.String(64), nullable=False)
    model = db.Column(db.String(20), nullable=False)
    data_hash = db.Column(db.String(64), nullable=False)
    rmse = db.Column(db.Float, nullable=True)
    mae = db.Column(db.Float, nullable=True)
    mape = db.Column(db.Float, nullable=True)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)


class OnboardingProgress(db.Model):
    """Server-side, per-group tracker for the admin onboarding checklist
    that lives on the Overview page (see src/onboarding.py). Deliberately
    keyed by *group*, not by user -- so every admin of a group sees the
    same checklist state, and it's consistent across devices, unlike the
    localStorage-based modal tour dismissal flag.

    Each step can be dismissed independently ("dismissible per step, not
    all-or-nothing"); a step also auto-completes itself once the admin
    has actually done the underlying thing (invited someone, uploaded
    real data), so dismissal is only needed for steps with no natural
    completion signal (e.g. reviewing the invite code)."""

    __tablename__ = "onboarding_progress"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), unique=True, nullable=False)
    invite_member_dismissed = db.Column(db.Boolean, nullable=False, default=False)
    upload_data_dismissed = db.Column(db.Boolean, nullable=False, default=False)
    invite_code_dismissed = db.Column(db.Boolean, nullable=False, default=False)
    widget_dismissed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    group = db.relationship("Group")

    @staticmethod
    def get_or_create(group_id: int) -> "OnboardingProgress":
        progress = OnboardingProgress.query.filter_by(group_id=group_id).first()
        if progress is None:
            progress = OnboardingProgress(group_id=group_id)
            db.session.add(progress)
            db.session.commit()
        return progress


class Notification(db.Model):
    """In-app notifications, including ones the AI assistant raises via
    its tool calls (reminders, at-risk flags) — always pending admin/member
    visibility, never an automatic financial action."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    kind = db.Column(db.String(40), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(40), nullable=False, default="assistant")
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
