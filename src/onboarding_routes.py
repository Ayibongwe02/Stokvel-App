"""
Onboarding checklist routes
===========================
Two admin-only, idempotent actions on the server-side per-group
checklist: dismiss one step, or hide the whole widget. Both just flip
a flag on `OnboardingProgress` and redirect back to wherever the admin
was -- see src/onboarding.py for how those flags feed into what's
shown. Like `groups.switch` and `auth.logout`, these are plain
same-origin forms protected by the app-wide CSRFProtect rather than a
dedicated FlaskForm class.
"""

from flask import Blueprint, g, redirect, request, url_for

from src.group_access import admin_required
from src.models import OnboardingProgress, db
from src.onboarding import STEP_KEYS

bp = Blueprint("onboarding_progress", __name__, url_prefix="/onboarding")


@bp.route("/checklist/step", methods=["POST"])
@admin_required
def dismiss_step():
    step = request.form.get("step", "")
    if step in STEP_KEYS:
        progress = OnboardingProgress.get_or_create(g.active_group.id)
        setattr(progress, f"{step}_dismissed", True)
        db.session.commit()
    return redirect(request.referrer or url_for("overview"))


@bp.route("/checklist/hide", methods=["POST"])
@admin_required
def hide_checklist():
    progress = OnboardingProgress.get_or_create(g.active_group.id)
    progress.widget_dismissed = True
    db.session.commit()
    return redirect(request.referrer or url_for("overview"))
