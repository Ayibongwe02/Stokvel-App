"""
Database models
================
SQLite-backed models (via Flask-SQLAlchemy) that replace the old flat
CSV files. Transactions and historical forecast rows are scoped by
`group_id` so each stokvel group's data is fully isolated.
"""

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
    role = db.Column(db.String(20), nullable=False, default="member")  # 'admin' | 'member'
    joined_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship("User", back_populates="memberships")
    group = db.relationship("Group", back_populates="memberships")


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


# --------------------------------------------------------------------------
# Phase 1: profile, group settings, audit log
# --------------------------------------------------------------------------
class UserProfile(db.Model):
    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    phone = db.Column(db.String(32), nullable=True)
    notify_email = db.Column(db.Boolean, nullable=False, default=True)
    notify_in_app = db.Column(db.Boolean, nullable=False, default=True)
    language = db.Column(db.String(16), nullable=False, default="en")

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
    withdrawal_approval_threshold = db.Column(db.Float, nullable=False, default=0.0)  # amount above which >1 approval is required
    required_approvals = db.Column(db.Integer, nullable=False, default=1)

    group = db.relationship("Group", backref=db.backref("settings", uselist=False))

    @staticmethod
    def get_or_create(group_id: int) -> "GroupSettings":
        settings = GroupSettings.query.filter_by(group_id=group_id).first()
        if settings is None:
            settings = GroupSettings(group_id=group_id)
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


# --------------------------------------------------------------------------
# Phase 3/4: payments
# --------------------------------------------------------------------------
class PaymentMethod(db.Model):
    """Stores only a gateway-issued token reference — never raw card data."""

    __tablename__ = "payment_methods"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider = db.Column(db.String(40), nullable=False, default="payfast")
    token_reference = db.Column(db.String(255), nullable=True)
    label = db.Column(db.String(80), nullable=True)  # e.g. "Card ending 4242" — display only
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
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | complete | failed | cancelled
    pf_payment_id = db.Column(db.String(64), nullable=True)  # PayFast's own id, for idempotency
    created_at = db.Column(db.DateTime, default=_utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User")
    group = db.relationship("Group")


class WithdrawalRequest(db.Model):
    __tablename__ = "withdrawal_requests"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    member_id = db.Column(db.String(64), nullable=True)  # links to Transaction.member_id for balance context
    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | approved | rejected | paid
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
    decision = db.Column(db.String(20), nullable=False)  # approved | rejected
    created_at = db.Column(db.DateTime, default=_utcnow)

    request = db.relationship("WithdrawalRequest", back_populates="approvals")
    admin = db.relationship("User")


# --------------------------------------------------------------------------
# Phase 2: AI assistant
# --------------------------------------------------------------------------
class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=True)
    role = db.Column(db.String(20), nullable=False)  # user | assistant
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
    model = db.Column(db.String(20), nullable=False)  # 'holt_winters' (only model since ARIMA was removed)
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
    model = db.Column(db.String(20), nullable=False)  # 'Holt-Winters' (only model since ARIMA was removed)
    data_hash = db.Column(db.String(64), nullable=False)
    rmse = db.Column(db.Float, nullable=True)
    mae = db.Column(db.Float, nullable=True)
    mape = db.Column(db.Float, nullable=True)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)


class Notification(db.Model):
    """In-app notifications, including ones the AI assistant raises via
    its tool calls (reminders, at-risk flags) — always pending admin/member
    visibility, never an automatic financial action."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False, index=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # null = whole group/admins
    kind = db.Column(db.String(40), nullable=False)  # reminder | at_risk | info
    message = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(40), nullable=False, default="assistant")
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
