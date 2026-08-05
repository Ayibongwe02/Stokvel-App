"""
Forms
=====
Flask-WTF forms. Using WTForms (rather than raw HTML forms) is what
gives every POST endpoint CSRF protection for free via Flask-WTF's
CSRFProtect + the hidden {{ form.csrf_token }} field rendered in each
template.
"""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, Regexp


class SignupForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords must match.")]
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


class GroupCreateForm(FlaskForm):
    name = StringField("Group name", validators=[DataRequired(), Length(max=150)])
    region = StringField("Region", validators=[Optional(), Length(max=120)])
    submit = SubmitField("Create group")


class GroupJoinForm(FlaskForm):
    invite_code = StringField(
        "Invite code",
        validators=[
            DataRequired(),
            Length(min=4, max=16),
            Regexp(r"^[A-Za-z0-9]+$", message="Letters and digits only."),
        ],
    )
    submit = SubmitField("Join group")


class PreviewSampleForm(FlaskForm):
    """One-click demo workspace with the bundled sample dataset."""
    submit = SubmitField("Preview with sample data")


class ExitSamplePreviewForm(FlaskForm):
    """Leave the demo workspace and return to the get-started hub."""
    submit = SubmitField("Exit sample preview")


class ProfileForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    submit = SubmitField("Save changes")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField("New password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm new password", validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")]
    )
    submit = SubmitField("Change password")


class InviteRegenerateForm(FlaskForm):
    submit = SubmitField("Regenerate invite code")


class LeaveGroupForm(FlaskForm):
    submit = SubmitField("Leave group")


class RemoveMemberForm(FlaskForm):
    member_user_id = StringField(validators=[DataRequired()])
    submit = SubmitField("Remove")


class UploadForm(FlaskForm):
    tx_file = FileField("Transactions CSV", validators=[Optional(), FileAllowed(["csv"], "CSV files only.")])
    hist_file = FileField(
        "Historical forecast CSV (optional)", validators=[Optional(), FileAllowed(["csv"], "CSV files only.")]
    )
    submit = SubmitField("Upload")


class ResetDataForm(FlaskForm):
    submit = SubmitField("Reset to sample data")


class GroupSwitchForm(FlaskForm):
    group_id = SelectField("Active group", coerce=int)
    submit = SubmitField("Switch")


# --------------------------------------------------------------------------
# Phase 1: settings
# --------------------------------------------------------------------------
class NotificationPrefsForm(FlaskForm):
    phone = StringField("Phone number", validators=[Optional(), Length(max=32)])
    notify_email = SelectField(
        "Email notifications", choices=[("1", "On"), ("0", "Off")], default="1"
    )
    notify_in_app = SelectField(
        "In-app notifications", choices=[("1", "On"), ("0", "Off")], default="1"
    )
    submit = SubmitField("Save notification preferences")


class GroupSettingsForm(FlaskForm):
    contribution_amount = StringField("Contribution amount (ZAR)", validators=[Optional(), Length(max=20)])
    contribution_frequency = SelectField(
        "Contribution frequency",
        choices=[("Weekly", "Weekly"), ("Monthly", "Monthly"), ("Quarterly", "Quarterly")],
        default="Monthly",
    )
    payout_rules = StringField("Payout / rotation rules", validators=[Optional(), Length(max=2000)])
    withdrawal_approval_threshold = StringField(
        "Amount above which extra approval is required (ZAR)", validators=[Optional(), Length(max=20)]
    )
    required_approvals = SelectField(
        "Admin approvals required for withdrawals",
        choices=[("1", "1"), ("2", "2"), ("3", "3")],
        default="1",
    )
    submit = SubmitField("Save group settings")


# --------------------------------------------------------------------------
# Phase 3/4: payments
# --------------------------------------------------------------------------
class ContributeForm(FlaskForm):
    amount = StringField("Amount (ZAR)", validators=[DataRequired(), Length(max=20)])
    submit = SubmitField("Contribute via PayFast")


class WithdrawalRequestForm(FlaskForm):
    amount = StringField("Amount (ZAR)", validators=[DataRequired(), Length(max=20)])
    member_id = StringField("Member ID (for balance context)", validators=[Optional(), Length(max=64)])
    reason = StringField("Reason", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Request withdrawal")


class WithdrawalDecisionForm(FlaskForm):
    request_id = StringField(validators=[DataRequired()])
    decision = StringField(validators=[DataRequired()])  # "approved" | "rejected" | "paid"
    submit = SubmitField("Submit")


# --------------------------------------------------------------------------
# Phase 2: assistant
# --------------------------------------------------------------------------
class ChatForm(FlaskForm):
    message = StringField("Message", validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField("Send")


# --------------------------------------------------------------------------
# Phase 5: pre-registered members + custom fields
# --------------------------------------------------------------------------
class PreRegisterMemberForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email (optional)", validators=[Optional(), Email(), Length(max=255)])
    role = SelectField("Role", choices=[("member", "Member"), ("admin", "Admin")], default="member")
    phone = StringField("Phone", validators=[Optional(), Length(max=32)])
    id_number = StringField("ID number", validators=[Optional(), Length(max=20)])
    bank_account_holder = StringField("Bank account holder", validators=[Optional(), Length(max=120)])
    bank_name = StringField("Bank name", validators=[Optional(), Length(max=80)])
    bank_account_number = StringField("Bank account number", validators=[Optional(), Length(max=34)])
    bank_branch_code = StringField("Branch code", validators=[Optional(), Length(max=10)])
    occupation = StringField("Occupation", validators=[Optional(), Length(max=120)])
    next_of_kin_name = StringField("Next of kin name", validators=[Optional(), Length(max=120)])
    next_of_kin_phone = StringField("Next of kin phone", validators=[Optional(), Length(max=32)])
    submit = SubmitField("Create invite link")


class RevokePendingMemberForm(FlaskForm):
    pending_id = StringField(validators=[DataRequired()])
    submit = SubmitField("Revoke")


class ClaimInviteForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords must match.")]
    )
    submit = SubmitField("Create account")


class CustomFieldForm(FlaskForm):
    label = StringField("Field label", validators=[DataRequired(), Length(max=120)])
    submit = SubmitField("Add field")


class DeleteCustomFieldForm(FlaskForm):
    field_id = StringField(validators=[DataRequired()])
    submit = SubmitField("Remove")


# --------------------------------------------------------------------------
# Phase 5: manual transactions + retrain
# --------------------------------------------------------------------------
class RetrainForm(FlaskForm):
    submit = SubmitField("Retrain forecasts now")


class ManualTransactionSubmitForm(FlaskForm):
    entry_type = SelectField("Type", choices=[("contribution", "Contribution"), ("withdrawal", "Withdrawal")])
    amount = StringField("Amount (ZAR)", validators=[DataRequired(), Length(max=20)])
    date = StringField("Date", validators=[DataRequired(), Length(max=10)])
    note = StringField("Note", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Submit for confirmation")


class ManualTransactionDecisionForm(FlaskForm):
    pending_id = StringField(validators=[DataRequired()])
    decision = StringField(validators=[DataRequired()])  # 'confirm' | 'reject'
    amount = StringField(validators=[Optional(), Length(max=20)])
    date = StringField(validators=[Optional(), Length(max=10)])
    note = StringField(validators=[Optional(), Length(max=255)])
    submit = SubmitField("Submit")


class ManualTransactionBackfillForm(FlaskForm):
    member_user_id = SelectField("Member", coerce=int)
    entry_type = SelectField("Type", choices=[("contribution", "Contribution"), ("withdrawal", "Withdrawal")])
    amount = StringField("Amount (ZAR)", validators=[DataRequired(), Length(max=20)])
    date = StringField("Date", validators=[DataRequired(), Length(max=10)])
    note = StringField("Note", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Add entry")
