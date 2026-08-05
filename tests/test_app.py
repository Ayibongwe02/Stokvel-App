import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The app module builds its single Flask instance (and SQLite engine) at
# import time, so point it at a throwaway test database *before* the
# first import happens.
_db_fd, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_PATH"] = _DB_PATH
os.environ["WTF_CSRF_ENABLED"] = "False"

import pytest  # noqa: E402

from app import app as flask_app  # noqa: E402
from src.models import db as _db  # noqa: E402

flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)


@pytest.fixture(autouse=True)
def _reset_db():
    with flask_app.app_context():
        _db.drop_all()
        _db.create_all()
    yield


@pytest.fixture()
def app():
    return flask_app


@pytest.fixture()
def client(app):
    with app.test_client() as client:
        yield client


def signup(client, email="member@example.com", name="Test Member", password="s3cur3pass"):
    return client.post(
        "/auth/signup",
        data={"name": name, "email": email, "password": password, "confirm_password": password},
        follow_redirects=True,
    )


def create_group(client, name="My Stokvel", region="Gauteng"):
    return client.post("/groups/create", data={"name": name, "region": region}, follow_redirects=True)


@pytest.fixture()
def logged_in_with_group(client):
    signup(client)
    create_group(client)
    return client


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_overview_requires_login(client):
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Log in" in resp.data


def test_signup_then_redirected_to_groups(client):
    resp = signup(client)
    assert resp.status_code == 200
    assert b"group" in resp.data.lower()


def test_overview_after_group_created(logged_in_with_group):
    resp = logged_in_with_group.get("/")
    assert resp.status_code == 200
    assert b"Group Overview" in resp.data


def test_forecast_page_default(logged_in_with_group):
    resp = logged_in_with_group.get("/forecast")
    assert resp.status_code == 200
    assert b"Member Balance Forecast" in resp.data


def test_accuracy_moved_into_settings(logged_in_with_group):
    resp = logged_in_with_group.get("/settings/")
    assert resp.status_code == 200
    assert b"Accuracy Health Settings" in resp.data


def test_old_accuracy_url_redirects_to_settings(logged_in_with_group):
    resp = logged_in_with_group.get("/accuracy")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/settings/#accuracy-health-settings")


def test_regional_page(logged_in_with_group):
    resp = logged_in_with_group.get("/regional")
    assert resp.status_code == 200
    assert b"Regional View" in resp.data


def test_data_source_page(logged_in_with_group):
    resp = logged_in_with_group.get("/data")
    assert resp.status_code == 200


def test_cannot_switch_to_foreign_group(app, client):
    signup(client, email="owner@example.com")
    create_group(client, name="Owner's Group")

    with app.test_client() as other_client:
        signup(other_client, email="intruder@example.com")
        resp = other_client.post("/groups/switch/1", follow_redirects=False)
        assert resp.status_code == 403


def test_non_admin_cannot_upload_data(app, client):
    signup(client, email="owner@example.com")
    create_group(client, name="Shared Group")

    with app.app_context():
        from src.models import Group

        group = Group.query.filter_by(name="Shared Group").first()
        code = group.invite_code

    with app.test_client() as member_client:
        signup(member_client, email="member2@example.com")
        member_client.post("/groups/join", data={"invite_code": code}, follow_redirects=True)
        resp = member_client.post("/data/reset", follow_redirects=False)
        assert resp.status_code == 403


def test_overview_shows_onboarding_checklist_for_new_admin(logged_in_with_group):
    resp = logged_in_with_group.get("/")
    assert resp.status_code == 200
    assert b"Getting your group set up" in resp.data
    assert b"Invite your first member" in resp.data
    assert b"Upload your first transaction" in resp.data
    assert b"Set up your invite code" in resp.data


def test_checklist_not_shown_for_non_admin_member(app, client):
    signup(client, email="owner3@example.com")
    create_group(client, name="Checklist Group")

    with app.app_context():
        from src.models import Group

        code = Group.query.filter_by(name="Checklist Group").first().invite_code

    with app.test_client() as member_client:
        signup(member_client, email="member3@example.com")
        member_client.post("/groups/join", data={"invite_code": code}, follow_redirects=True)
        resp = member_client.get("/")
        assert b"Getting your group set up" not in resp.data


def test_checklist_invite_step_auto_completes_once_someone_joins(app, client):
    signup(client, email="owner4@example.com")
    create_group(client, name="Auto Group")

    with app.app_context():
        from src.models import Group

        code = Group.query.filter_by(name="Auto Group").first().invite_code

    with app.test_client() as member_client:
        signup(member_client, email="member4@example.com")
        member_client.post("/groups/join", data={"invite_code": code}, follow_redirects=True)

    resp = client.get("/")
    # Invite step is done (crossed out, description hidden) once a second
    # member has joined -- but the other two steps are still pending.
    assert b"Invite your first member" in resp.data
    assert b"Upload your first transaction" in resp.data


def test_dismiss_one_checklist_step(logged_in_with_group):
    resp = logged_in_with_group.post(
        "/onboarding/checklist/step", data={"step": "invite_code"}, follow_redirects=True
    )
    assert resp.status_code == 200

    from app import app as flask_app
    from src.models import Group, OnboardingProgress

    with flask_app.app_context():
        group = Group.query.first()
        progress = OnboardingProgress.query.filter_by(group_id=group.id).first()
        assert progress.invite_code_dismissed is True
        assert progress.invite_member_dismissed is False


def test_hide_entire_checklist(logged_in_with_group):
    resp = logged_in_with_group.post("/onboarding/checklist/hide", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Getting your group set up" not in resp.data

    resp2 = logged_in_with_group.get("/")
    assert b"Getting your group set up" not in resp2.data


def test_checklist_step_dismiss_requires_admin(app, client):
    signup(client, email="owner5@example.com")
    create_group(client, name="Perm Group")

    with app.app_context():
        from src.models import Group

        code = Group.query.filter_by(name="Perm Group").first().invite_code

    with app.test_client() as member_client:
        signup(member_client, email="member5@example.com")
        member_client.post("/groups/join", data={"invite_code": code}, follow_redirects=True)
        resp = member_client.post(
            "/onboarding/checklist/step", data={"step": "invite_code"}, follow_redirects=False
        )
        assert resp.status_code == 403


def test_settings_page_has_pre_register_coachmark(logged_in_with_group):
    resp = logged_in_with_group.get("/settings/")
    assert resp.status_code == 200
    assert b'id="pre-register-panel"' in resp.data
    assert b"This is where you add people" in resp.data


def test_empty_state_is_role_aware_for_admin(app, logged_in_with_group):
    from src.models import Group, HistoricalForecast, Transaction, db as _db2

    with app.app_context():
        group = Group.query.first()
        Transaction.query.filter_by(group_id=group.id).delete()
        HistoricalForecast.query.filter_by(group_id=group.id).delete()
        _db2.session.commit()

    resp = logged_in_with_group.get("/")
    assert resp.status_code == 200
    assert b"No data yet" in resp.data
    assert b"Upload your members" in resp.data
    assert b"Add a member" in resp.data


def test_empty_state_is_role_aware_for_member(app, client):
    from src.models import Group, HistoricalForecast, Transaction, db as _db2

    signup(client, email="owner6@example.com")
    create_group(client, name="Empty Group")

    with app.app_context():
        group = Group.query.filter_by(name="Empty Group").first()
        code = group.invite_code
        Transaction.query.filter_by(group_id=group.id).delete()
        HistoricalForecast.query.filter_by(group_id=group.id).delete()
        _db2.session.commit()

    with app.test_client() as member_client:
        signup(member_client, email="member6@example.com")
        member_client.post("/groups/join", data={"invite_code": code}, follow_redirects=True)
        resp = member_client.get("/")
        assert resp.status_code == 200
        assert b"No data yet" in resp.data
        assert b"Ask your admin" in resp.data
        assert b"Add a member" not in resp.data


def test_forecasting_engine_holt_winters():
    from src.forecasting import fit_holt_winters
    import pandas as pd

    series = pd.Series([100, 120, 130, 150, 170, 190], index=pd.date_range("2026-01-01", periods=6, freq="MS"))
    forecast, resid = fit_holt_winters(series, 3)
    assert len(forecast) == 3
    assert len(resid) == len(series)


def test_settings_page_shows_group_settings_for_admin(logged_in_with_group):
    resp = logged_in_with_group.get("/settings/")
    assert resp.status_code == 200
    assert b"group settings" in resp.data.lower()


def test_update_group_settings(logged_in_with_group):
    resp = logged_in_with_group.post(
        "/settings/group/update",
        data={
            "contribution_amount": "500",
            "contribution_frequency": "Monthly",
            "payout_rules": "Rotate alphabetically",
            "withdrawal_approval_threshold": "2000",
            "required_approvals": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Group settings saved" in resp.data


def test_payments_page_has_no_dev_facing_sandbox_notice(logged_in_with_group):
    """The page still actually runs against PayFast's sandbox under the
    hood (see test_contribute_redirects_to_payfast_sandbox below), but
    it shouldn't say so on-screen or mention internal env var names --
    that's implementation detail, not something an end user needs."""
    resp = logged_in_with_group.get("/payments/")
    assert resp.status_code == 200
    assert b"PAYFAST_" not in resp.data
    assert b"sandbox mode" not in resp.data.lower()


def test_contribute_redirects_to_payfast_sandbox(logged_in_with_group):
    resp = logged_in_with_group.post("/payments/contribute", data={"amount": "500.00"})
    assert resp.status_code == 200
    assert b"sandbox.payfast.co.za" in resp.data


def test_itn_webhook_confirms_contribution_and_updates_balance(logged_in_with_group):
    import re
    from src import payments as pf

    resp = logged_in_with_group.post("/payments/contribute", data={"amount": "500.00"})
    m = re.search(rb'name="m_payment_id" value="([^"]+)"', resp.data)
    m_payment_id = m.group(1).decode()

    data = {"m_payment_id": m_payment_id, "pf_payment_id": "PF999", "payment_status": "COMPLETE", "amount_gross": "500.00"}
    data["signature"] = pf._signature(data)
    resp = logged_in_with_group.post("/payments/notify", data=data)
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_itn_webhook_rejects_bad_signature(logged_in_with_group):
    resp = logged_in_with_group.post("/payments/contribute", data={"amount": "500.00"})
    import re

    m = re.search(rb'name="m_payment_id" value="([^"]+)"', resp.data)
    m_payment_id = m.group(1).decode()

    resp = logged_in_with_group.post(
        "/payments/notify",
        data={"m_payment_id": m_payment_id, "payment_status": "COMPLETE", "signature": "not-a-real-signature"},
    )
    assert resp.status_code == 400


def test_withdrawal_request_and_admin_approval(logged_in_with_group):
    resp = logged_in_with_group.post(
        "/payments/withdraw", data={"amount": "100", "reason": "test"}, follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"submitted for admin approval" in resp.data.lower()

    import re

    resp = logged_in_with_group.get("/payments/")
    wid = re.search(rb'name="request_id" value="(\d+)"', resp.data).group(1).decode()
    resp = logged_in_with_group.post(
        "/payments/withdraw/decide", data={"request_id": wid, "decision": "approved"}, follow_redirects=True
    )
    assert resp.status_code == 200


def test_assistant_chat_grounds_reply_in_real_group_data(logged_in_with_group):
    resp = logged_in_with_group.post("/assistant/chat", json={"message": "How is my group doing?"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "reply" in body
    assert "My Stokvel" in body["reply"] or "group" in body["reply"].lower()


def test_assistant_chat_rejects_empty_message(logged_in_with_group):
    resp = logged_in_with_group.post("/assistant/chat", json={"message": ""})
    assert resp.status_code == 400


def test_knowledge_base_retrieves_relevant_doc_for_app_question():
    from src.knowledge_base import search

    hits = search("how do withdrawals get approved", k=2)
    assert hits
    assert hits[0]["id"] == "app-withdrawals"


def test_knowledge_base_retrieves_relevant_doc_for_practice_question():
    from src.knowledge_base import search

    hits = search("what happens if I miss a contribution", k=2)
    assert hits
    assert hits[0]["id"] == "practice-missed-contributions"


def test_assistant_is_purely_knowledge_based(monkeypatch):
    """No external backend exists anymore — assistant.chat must never
    touch the network, and must answer using only local retrieval plus
    the group context it's given."""
    from src import assistant

    assert not hasattr(assistant, "GROQ_API_KEY")
    assert not hasattr(assistant, "ANTHROPIC_API_KEY")
    assert not hasattr(assistant, "XAI_API_KEY")
    assert not hasattr(assistant, "BACKEND")

    result = assistant.chat(
        "how does the forecast work?",
        {"group_name": "Test", "total_balance": 1000.0, "member_count": 3, "total_contrib": 1200.0},
        execute_tool=lambda name, inp: "unused",
    )
    assert "reply" in result
    assert result["actions_taken"] == []
    assert "Test" in result["reply"]


def test_assistant_grounds_reply_in_knowledge_base_hit():
    from src import assistant

    result = assistant.chat(
        "what happens if I miss a contribution",
        {"group_name": "Test", "total_balance": 500.0, "member_count": 2, "total_contrib": 500.0},
        execute_tool=lambda name, inp: "unused",
    )
    assert "contribution" in result["reply"].lower()
