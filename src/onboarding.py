"""
Onboarding checklist (Part 2)
=============================
A dismissible checklist for new group admins, shown on the Overview
page (including its empty-ledger variant). Unlike the modal tour --
which is per-browser via localStorage and fires once per role variant
-- this widget is backed by `OnboardingProgress`, one row per group, so
it reads the same for every admin of that group and survives across
devices.

Each step auto-completes itself once the admin has actually done the
underlying thing, where that's detectable from real data. Steps with
no natural completion signal (e.g. "look at your invite code") rely on
the admin dismissing them by hand. Either way, a step's dismissal is
independent of the others -- there's no single all-or-nothing flag.
"""

from src.data_loader import group_is_using_sample_data
from src.models import GroupMembership, OnboardingProgress, PendingMember, Transaction


def _invite_member_done(group_id: int) -> bool:
    # More than just the creating admin has ever joined this group...
    if GroupMembership.query.filter_by(group_id=group_id).count() > 1:
        return True
    # ...or the admin has at least pre-registered someone, even if that
    # person hasn't claimed their invite link yet.
    return PendingMember.query.filter_by(group_id=group_id).count() > 0


def _upload_data_done(group_id: int) -> bool:
    # Bundled sample data has been replaced with the group's own CSV...
    if not group_is_using_sample_data(group_id):
        return True
    # ...or at least one real (non-CSV-upload) transaction exists --
    # a payment, or a manually confirmed contribution/withdrawal.
    return (
        Transaction.query.filter_by(group_id=group_id)
        .filter(Transaction.source.in_(["manual", "payment"]))
        .count()
        > 0
    )


# Each step: a stable `key` (matches an OnboardingProgress column prefix),
# display copy, a link to where the admin can go act on it, and an
# optional auto-detection function. Steps with `auto_done=None` can only
# ever be completed by the admin dismissing them.
STEPS = [
    {
        "key": "invite_member",
        "title": "Invite your first member",
        "description": "Pre-register someone by name and role, or share your invite code so they can join themselves.",
        "action_label": "Go to Settings",
        "action_endpoint": "settings.index",
        "auto_done": _invite_member_done,
    },
    {
        "key": "upload_data",
        "title": "Upload your first transaction",
        "description": "Replace the bundled sample data with your group's real contributions from the Data Source tab.",
        "action_label": "Go to Data Source",
        "action_endpoint": "data_source",
        "auto_done": _upload_data_done,
    },
    {
        "key": "invite_code",
        "title": "Set up your invite code",
        "description": "Share your group's invite code with members from Settings, or regenerate it first if you'd rather start fresh.",
        "action_label": "Go to Settings",
        "action_endpoint": "settings.index",
        "auto_done": None,
    },
]

STEP_KEYS = [step["key"] for step in STEPS]


def get_checklist(group_id: int) -> dict | None:
    """Returns the checklist context for the Overview template, or None
    if it shouldn't be shown at all (dismissed, or every step done)."""
    progress = OnboardingProgress.get_or_create(group_id)
    if progress.widget_dismissed:
        return None

    steps = []
    any_pending = False
    for step in STEPS:
        dismissed = getattr(progress, f"{step['key']}_dismissed")
        auto_done = bool(step["auto_done"](group_id)) if step["auto_done"] else False
        done = dismissed or auto_done
        if not done:
            any_pending = True
        steps.append({**step, "done": done})

    if not any_pending:
        return None

    return {"steps": steps}
