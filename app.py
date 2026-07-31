"""
Stokvel Forecasting Platform
=============================
Flask multi-tenant rebuild: live statistical forecasting (Holt-Winters)
over savings-group contribution and balance data. Each stokvel "group"
owns its own transaction data in SQLite; users sign up, create or join
a group via invite code, and every dashboard page operates on their
currently active group only.

Run locally:   python app.py
Run in Docker: docker compose up --build
"""

import os
from pathlib import Path

import pandas as pd
from flask import Flask, flash, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from src import charts, forecasting
from src.auth_routes import bp as auth_bp
from src.data_loader import (
    DataValidationError,
    REQUIRED_HIST_COLS,
    REQUIRED_TX_COLS,
    get_dataset,
    group_is_using_sample_data,
    replace_group_historical,
    replace_group_transactions,
    seed_group_with_sample_data,
    validate_csv,
)
from src.assistant_routes import bp as assistant_bp
from src.extensions import csrf, login_manager
from src.forms import ResetDataForm, UploadForm
from src.group_access import admin_required, get_active_membership, group_required
from src.group_routes import bp as groups_bp
from src.models import Notification, User, db
from src.payments_routes import bp as payments_bp
from src.payments_routes import notify as payments_notify
from src.settings_routes import bp as settings_bp

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("ANVIL_SECRET_KEY", "dev-secret-key-change-in-production")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB upload cap

    DATA_DIR.mkdir(exist_ok=True)
    db_path = os.environ.get("DATABASE_PATH", str(DATA_DIR / "app.db"))
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(assistant_bp)
    csrf.exempt(payments_notify)  # PayFast's ITN webhook is server-to-server, authenticated by signature instead

    with app.app_context():
        db.create_all()

    return app


app = create_app()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --------------------------------------------------------------------------
# Dashboard pages — all scoped to the logged-in user's active group
# --------------------------------------------------------------------------
@app.route("/")
def overview():
    if not current_user.is_authenticated:
        return render_template("splash.html")

    membership = get_active_membership()
    if membership is None:
        return redirect(url_for("groups.index"))
    g.active_membership = membership
    g.active_group = membership.group

    tx_df, hist_df, hist_available, meta, members = get_dataset(g.active_group.id)
    if not members:
        return render_template("empty.html")

    latest_balances = tx_df.sort_values("date").groupby("member_id").last()["balance"]
    total_balance = float(latest_balances.sum())
    total_contrib = float(tx_df["contribution_amount"].sum())
    total_withdraw = float(tx_df["withdrawal_amount"].sum())
    net_flow = total_contrib - total_withdraw

    rows = []
    for m in members:
        s = tx_df[tx_df["member_id"] == m].sort_values("date")
        rows.append({
            "member": m,
            "region": meta[m]["Region"],
            "category": meta[m]["Member_Category"],
            "balance": float(s["balance"].iloc[-1]) if not s.empty else None,
            "contributed": float(s["contribution_amount"].sum()),
            "withdrawn": float(s["withdrawal_amount"].sum()),
        })

    charts_json = {
        "growth": charts.balance_growth_chart(tx_df, members).to_json(),
        "category": charts.category_pie_chart(meta, members).to_json(),
        "region": charts.region_bar_chart(meta, members).to_json(),
    }

    return render_template(
        "overview.html",
        total_balance=total_balance,
        total_contrib=total_contrib,
        total_withdraw=total_withdraw,
        net_flow=net_flow,
        rows=rows,
        charts_json=charts_json,
    )


@app.route("/forecast")
@group_required
def forecast():
    tx_df, hist_df, hist_available, meta, members = get_dataset(g.active_group.id)
    if not members:
        return render_template("empty.html")

    member = request.args.get("member", members[0])
    if member not in members:
        member = members[0]
    horizon = max(1, min(12, request.args.get("horizon", 6, type=int)))

    series = forecasting.get_member_series(member, tx_df, hist_df, hist_available)
    meta_m = meta[member]
    chart_json = None
    warning = None
    hw_note = None

    if len(series) < 4:
        warning = "Not enough historical data points for this member to fit a reliable model."
    else:
        idx_future = forecasting.future_index(series.index.max(), horizon)
        hw_fc, hw_resid, hw_note = forecasting.get_or_fit_forecast(
            g.active_group.id, member, "holt_winters", series, horizon
        )

        fig = charts.member_forecast_chart(series, idx_future, hw_fc, hw_resid)
        chart_json = fig.to_json()

    tx_m = tx_df[tx_df["member_id"] == member].sort_values("date")
    flow_json = charts.contributions_withdrawals_chart(tx_m).to_json() if not tx_m.empty else None

    return render_template(
        "forecast.html",
        members=members,
        member=member,
        horizon=horizon,
        meta_m=meta_m,
        chart_json=chart_json,
        flow_json=flow_json,
        warning=warning,
        hw_note=hw_note,
        series_table=list(zip(series.index.strftime("%Y-%m-%d"), series.values)) if len(series) else [],
    )


@app.route("/accuracy")
@group_required
def accuracy():
    # Model Accuracy now lives inside Settings as "Accuracy Health
    # Settings" -- keep this URL alive so old links/bookmarks still land
    # somewhere useful instead of 404ing.
    return redirect(url_for("settings.index") + "#accuracy-health-settings")


@app.route("/regional")
@group_required
def regional():
    tx_df, hist_df, hist_available, meta, members = get_dataset(g.active_group.id)
    if not members:
        return render_template("empty.html")

    reg_map = {m: meta[m]["Region"] for m in members}
    tx_df = tx_df.copy()
    tx_df["region"] = tx_df["member_id"].map(reg_map)

    reg_summary = tx_df.groupby("region").agg(
        total_contrib=("contribution_amount", "sum"),
        total_withdraw=("withdrawal_amount", "sum"),
        avg_balance=("balance", "mean"),
        members=("member_id", "nunique"),
    ).round(0)

    freq_tab = tx_df.groupby(["region", "contribution_frequency"])["member_id"].nunique().unstack(fill_value=0)

    return render_template(
        "regional.html",
        reg_summary=reg_summary.reset_index().to_dict("records"),
        flow_json=charts.regional_flow_chart(reg_summary).to_json(),
        box_json=charts.regional_box_chart(tx_df).to_json(),
        freq_columns=list(freq_tab.columns),
        freq_rows=[{"region": idx, **row.to_dict()} for idx, row in freq_tab.iterrows()],
    )


@app.route("/data")
@group_required
def data_source():
    upload_form = UploadForm()
    reset_form = ResetDataForm()
    return render_template(
        "data.html",
        using_sample=group_is_using_sample_data(g.active_group.id),
        is_admin=(g.active_membership.role == "admin"),
        upload_form=upload_form,
        reset_form=reset_form,
    )


@app.route("/data/upload", methods=["POST"])
@admin_required
def data_upload():
    form = UploadForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("data_source"))

    tx_file = form.tx_file.data
    hist_file = form.hist_file.data

    if tx_file and tx_file.filename:
        try:
            tx_df = pd.read_csv(tx_file)
            validate_csv(tx_df, REQUIRED_TX_COLS, "Transactions CSV")
            n = replace_group_transactions(g.active_group.id, tx_df)
            flash(f"Loaded {n} transaction rows.", "success")
        except DataValidationError as exc:
            flash(str(exc), "error")
        except Exception as exc:
            flash(f"Couldn't read that transactions CSV: {exc}", "error")

    if hist_file and hist_file.filename:
        try:
            hist_df = pd.read_csv(hist_file)
            validate_csv(hist_df, REQUIRED_HIST_COLS, "Historical forecast CSV")
            n = replace_group_historical(g.active_group.id, hist_df)
            flash(f"Loaded {n} historical forecast rows.", "success")
        except DataValidationError as exc:
            flash(str(exc), "error")
        except Exception as exc:
            flash(f"Couldn't read that historical CSV: {exc}", "error")

    return redirect(url_for("data_source"))


@app.route("/data/reset", methods=["POST"])
@admin_required
def data_reset():
    form = ResetDataForm()
    if form.validate_on_submit():
        seed_group_with_sample_data(g.active_group.id)
        flash("Restored bundled sample data.", "success")
    return redirect(url_for("data_source"))


# --------------------------------------------------------------------------
# Ops
# --------------------------------------------------------------------------
@app.route("/healthz")
def healthz():
    return jsonify(status="ok"), 200


@app.context_processor
def inject_nav():
    user_groups = []
    active_group = None
    unread_notifications = 0
    if current_user.is_authenticated:
        user_groups = current_user.groups()
        active_group = getattr(g, "active_group", None)
        if active_group:
            unread_notifications = Notification.query.filter_by(
                group_id=active_group.id, is_read=False
            ).count()
    return {
        "active_endpoint": request.endpoint,
        "user_groups": user_groups,
        "active_group": active_group,
        "unread_notifications": unread_notifications,
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(host="0.0.0.0", port=port, debug=debug)
