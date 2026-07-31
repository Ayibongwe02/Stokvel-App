"""
Data loading & processing
==========================
Reads a group's transactions + historical-forecast rows out of SQLite
(scoped by group_id), validates uploaded CSVs, and builds the
per-member metadata lookup used across every page of the dashboard.

This replaces the old single global stokvel_dataset.csv /
forecasting_dashboard.csv pair — each stokvel group now owns its own
rows in the `transactions` and `historical_forecasts` tables.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.models import HistoricalForecast, Transaction, db

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BASE_DIR / "data" / "samples"

REQUIRED_TX_COLS = {"member_id", "date", "contribution_amount", "withdrawal_amount", "balance"}
REQUIRED_HIST_COLS = {"MemberID", "Date", "Balance"}


class DataValidationError(Exception):
    """Raised when an uploaded CSV is missing required columns."""


def validate_csv(df: pd.DataFrame, required: set, label: str) -> None:
    missing = required - set(df.columns)
    if missing:
        raise DataValidationError(f"{label} is missing required column(s): {', '.join(sorted(missing))}")


# --------------------------------------------------------------------------
# Reading a group's data out of the database
# --------------------------------------------------------------------------
def load_raw(group_id: int):
    """Load a group's transaction + historical rows out of SQLite as
    DataFrames shaped exactly like the old CSVs were."""
    tx_rows = Transaction.query.filter_by(group_id=group_id).all()
    if tx_rows:
        tx_raw = pd.DataFrame(
            [
                {
                    "member_id": r.member_id,
                    "date": r.date,
                    "contribution_amount": r.contribution_amount,
                    "withdrawal_amount": r.withdrawal_amount,
                    "balance": r.balance,
                    "contribution_frequency": r.contribution_frequency,
                    "region": r.region,
                    "category": r.category,
                }
                for r in tx_rows
            ]
        )
    else:
        tx_raw = pd.DataFrame(columns=sorted(REQUIRED_TX_COLS | {"contribution_frequency", "region", "category"}))

    hist_rows = HistoricalForecast.query.filter_by(group_id=group_id).all()
    if hist_rows:
        hist_raw = pd.DataFrame(
            [
                {
                    "MemberID": r.member_id,
                    "Date": r.date,
                    "Balance": r.balance,
                    "Forecast_Balance": r.forecast_balance,
                    "RMSE_HoltWinters": r.rmse_holt_winters,
                    "RMSE_ARIMA": r.rmse_arima,
                    "MAE": r.mae,
                    "MAPE": r.mape,
                    "Region": r.region,
                    "Member_Category": r.member_category,
                    "Forecast_Horizon": r.forecast_horizon,
                }
                for r in hist_rows
            ]
        )
    else:
        hist_raw = pd.DataFrame(columns=sorted(REQUIRED_HIST_COLS))

    return tx_raw, hist_raw


def process_data(tx_raw: pd.DataFrame, hist_raw: pd.DataFrame):
    """Clean + type-cast both frames and build a MemberID -> metadata dict
    (region, category, historical forecast horizon)."""
    tx = tx_raw.copy()
    tx["date"] = pd.to_datetime(tx["date"])
    if "contribution_frequency" not in tx.columns:
        tx["contribution_frequency"] = "Unknown"

    hist_available = not hist_raw.empty
    hist = hist_raw.copy()
    if hist_available:
        hist["Date"] = pd.to_datetime(hist["Date"])
        if "MAPE" in hist.columns:
            hist["MAPE_num"] = hist["MAPE"].astype(str).str.replace("%", "").astype(float)
        for col in ["RMSE_HoltWinters", "RMSE_ARIMA", "MAE", "MAPE_num"]:
            if col not in hist.columns:
                hist[col] = np.nan
        for col in ["Region", "Member_Category", "Forecast_Horizon"]:
            if col not in hist.columns:
                hist[col] = "Unknown"

    meta = {}
    if hist_available:
        meta = (
            hist.sort_values("Date")
            .groupby("MemberID")
            .last()[["Region", "Member_Category", "Forecast_Horizon"]]
            .to_dict("index")
        )
    for m in tx["member_id"].unique():
        if m not in meta:
            meta[m] = {
                "Region": tx.loc[tx["member_id"] == m, "region"].iloc[0] if "region" in tx.columns else "Unknown",
                "Member_Category": (
                    tx.loc[tx["member_id"] == m, "category"].iloc[0] if "category" in tx.columns else "Unknown"
                ),
                "Forecast_Horizon": "Unknown",
            }

    members = sorted(set(hist["MemberID"]) | set(tx["member_id"])) if hist_available else sorted(
        tx["member_id"].unique()
    )
    return tx, hist, hist_available, meta, members


def get_dataset(group_id: int):
    """One-call convenience wrapper used by routes."""
    tx_raw, hist_raw = load_raw(group_id)
    return process_data(tx_raw, hist_raw)


# --------------------------------------------------------------------------
# Writing uploaded / sample CSVs into the database, scoped to a group
# --------------------------------------------------------------------------
def replace_group_transactions(group_id: int, tx_df: pd.DataFrame) -> int:
    """Replace all of a group's transaction rows with the contents of
    tx_df (already validated). Returns the row count inserted."""
    Transaction.query.filter_by(group_id=group_id).delete()
    df = tx_df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for col in ("contribution_frequency", "region", "category"):
        if col not in df.columns:
            df[col] = None
    rows = [
        Transaction(
            group_id=group_id,
            member_id=str(row["member_id"]),
            date=row["date"],
            contribution_amount=float(row["contribution_amount"]),
            withdrawal_amount=float(row["withdrawal_amount"]),
            balance=float(row["balance"]),
            contribution_frequency=row.get("contribution_frequency") or "Unknown",
            region=row.get("region"),
            category=row.get("category"),
        )
        for _, row in df.iterrows()
    ]
    db.session.bulk_save_objects(rows)
    db.session.commit()
    return len(rows)


def replace_group_historical(group_id: int, hist_df: pd.DataFrame) -> int:
    """Replace all of a group's historical-forecast rows with the
    contents of hist_df (already validated)."""
    HistoricalForecast.query.filter_by(group_id=group_id).delete()
    df = hist_df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    hist_optional_cols = [
        "Forecast_Balance", "RMSE_HoltWinters", "RMSE_ARIMA", "MAE",
        "MAPE", "Region", "Member_Category", "Forecast_Horizon",
    ]
    for col in hist_optional_cols:
        if col not in df.columns:
            df[col] = None
    if "MAPE" in df.columns:
        df["MAPE"] = pd.to_numeric(df["MAPE"].astype(str).str.replace("%", "", regex=False), errors="coerce")
    rows = [
        HistoricalForecast(
            group_id=group_id,
            member_id=str(row["MemberID"]),
            date=row["Date"],
            balance=row.get("Balance"),
            forecast_balance=row.get("Forecast_Balance"),
            rmse_holt_winters=row.get("RMSE_HoltWinters"),
            rmse_arima=row.get("RMSE_ARIMA"),
            mae=row.get("MAE"),
            mape=row.get("MAPE"),
            region=row.get("Region") or "Unknown",
            member_category=row.get("Member_Category") or "Unknown",
            forecast_horizon=row.get("Forecast_Horizon") or "Unknown",
        )
        for _, row in df.iterrows()
    ]
    db.session.bulk_save_objects(rows)
    db.session.commit()
    return len(rows)


def seed_group_with_sample_data(group_id: int) -> None:
    """Used on group creation, and by the 'reset to sample data' button."""
    tx_df = pd.read_csv(SAMPLES_DIR / "stokvel_dataset.csv")
    validate_csv(tx_df, REQUIRED_TX_COLS, "Sample transactions CSV")
    replace_group_transactions(group_id, tx_df)

    hist_path = SAMPLES_DIR / "forecasting_dashboard.csv"
    if hist_path.exists():
        hist_df = pd.read_csv(hist_path)
        validate_csv(hist_df, REQUIRED_HIST_COLS, "Sample historical CSV")
        replace_group_historical(group_id, hist_df)


def group_is_using_sample_data(group_id: int) -> bool:
    """Best-effort check: true if the group's row count still matches
    the bundled sample (used only to label the Data Source page)."""
    tx_rows = Transaction.query.filter_by(group_id=group_id).count()
    try:
        sample_len = len(pd.read_csv(SAMPLES_DIR / "stokvel_dataset.csv"))
    except FileNotFoundError:
        return False
    return tx_rows == sample_len
