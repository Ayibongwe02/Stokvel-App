"""
Forecasting engine
===================
Holt-Winters (damped additive ETS), fit live on each member's balance
series, plus a train/holdout backtest used for the Model Accuracy
page. Ported from the original Streamlit prototype.

This used to also fit an auto-tuned ARIMA model alongside Holt-Winters
(first via pmdarima, then via a lightweight statsmodels grid search).
ARIMA was removed outright -- Holt-Winters alone was already accurate
and fast, and running a second model on every fit doubled the CPU/
memory cost of every /forecast and /accuracy request for comparison
info nobody was acting on. If you want it back, the ARIMA-fitting
functions are straightforward to re-add: an ARIMA(order).fit() call
plus an order-search loop, same shape as fit_holt_winters below.
"""

import gc
import hashlib
import json
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.models import AccuracyCache, ForecastCache, db

warnings.filterwarnings("ignore")


def get_member_series(
    member_id: str, tx_df: pd.DataFrame, hist_df: pd.DataFrame, hist_available: bool, forecast_cutoff=None
) -> pd.Series:
    """Chronological balance series for a member, built from live 2026
    transactions, falling back to the 2024-2025 historical dataset when
    there isn't enough live history yet.

    forecast_cutoff (optional): when given, any 'manual' transaction
    created after this timestamp is excluded from the series -- this
    is what keeps a manual edit from silently changing a forecast
    before an admin has explicitly hit Retrain. CSV uploads and
    PayFast payments are never filtered; only 'manual' rows are."""
    live = tx_df[tx_df["member_id"] == member_id].sort_values("date")
    if forecast_cutoff is not None and "source" in live.columns:
        is_late_manual = (live["source"] == "manual") & (live["created_at"] > forecast_cutoff)
        live = live[~is_late_manual]
    h = hist_df[hist_df["MemberID"] == member_id].sort_values("Date") if hist_available else pd.DataFrame()
    if len(live) >= 5 or h.empty:
        s = live.set_index("date")["balance"].astype(float)
    else:
        s = h.set_index("Date")["Balance"].astype(float)
    return s[~s.index.duplicated(keep="last")]


def series_hash(series: pd.Series) -> str:
    """Stable fingerprint of a member's series, used as a cache key so a
    cached forecast/accuracy row is only reused while the underlying data
    hasn't changed (new upload, reset, or new live transactions)."""
    payload = ",".join(f"{ts.isoformat()}:{val}" for ts, val in series.items())
    return hashlib.sha256(payload.encode()).hexdigest()


def fit_holt_winters(series: pd.Series, horizon: int):
    model = ExponentialSmoothing(series.values, trend="add", damped_trend=True, seasonal=None)
    fit = model.fit(optimized=True)
    forecast = fit.forecast(horizon)
    resid = series.values - fit.fittedvalues
    del model, fit
    gc.collect()
    return forecast, resid


def backtest_metrics(series: pd.Series, holdout: int = 3):
    """Fit on train, evaluate on held-out tail -> RMSE / MAE / MAPE for
    Holt-Winters. Returns None if there isn't enough history to backtest."""
    holdout = min(holdout, max(1, len(series) // 4))
    if len(series) < holdout + 4:
        return None
    train, test = series.iloc[:-holdout], series.iloc[-holdout:]
    results = {}
    for name, fitter in [("Holt-Winters", fit_holt_winters)]:
        try:
            preds, _ = fitter(train, holdout)
            err = test.values - preds
            rmse = float(np.sqrt(np.mean(err ** 2)))
            mae = float(np.mean(np.abs(err)))
            mape = float(np.mean(np.abs(err / np.where(test.values == 0, 1, test.values))) * 100)
            results[name] = {"RMSE": rmse, "MAE": mae, "MAPE": mape}
        except Exception:
            results[name] = {"RMSE": np.nan, "MAE": np.nan, "MAPE": np.nan}
    return results


def future_index(last_date, periods, freq="MS"):
    return pd.date_range(last_date + pd.offsets.MonthBegin(1), periods=periods, freq=freq)


_MODEL_FITTERS = {"holt_winters": fit_holt_winters}


def get_or_fit_forecast(group_id: int, member_id: str, model: str, series: pd.Series, horizon: int):
    """Returns (forecast, resid, note). Reads ForecastCache first; only
    calls the real fitter (and writes the cache row) on a miss."""
    h = series_hash(series)
    row = ForecastCache.query.filter_by(
        group_id=group_id, member_id=member_id, model=model, horizon=horizon
    ).first()
    if row and row.data_hash == h:
        return (
            np.array(json.loads(row.forecast_json)),
            np.array(json.loads(row.resid_json)),
            row.note,
        )

    note = None
    try:
        forecast, resid = _MODEL_FITTERS[model](series, horizon)
    except Exception as exc:
        note = f"{model} could not be fit for this series: {exc}"
        return None, None, note

    payload = dict(
        data_hash=h,
        forecast_json=json.dumps(np.asarray(forecast).tolist()),
        resid_json=json.dumps(np.asarray(resid).tolist()),
        note=note,
    )
    if row:
        for k, v in payload.items():
            setattr(row, k, v)
    else:
        db.session.add(ForecastCache(group_id=group_id, member_id=member_id, model=model, horizon=horizon, **payload))
    db.session.commit()
    return forecast, resid, note


def get_or_backtest_metrics(group_id: int, member_id: str, series: pd.Series, holdout: int = 3):
    """Cache-aware version of backtest_metrics for the /accuracy page --
    the most expensive route since it touches every member x both models."""
    h = series_hash(series)
    cached = AccuracyCache.query.filter_by(group_id=group_id, member_id=member_id).filter(
        AccuracyCache.data_hash == h
    ).all()
    if len(cached) == 1:
        return {row.model: {"RMSE": row.rmse, "MAE": row.mae, "MAPE": row.mape} for row in cached}

    metrics = backtest_metrics(series, holdout=holdout)
    if not metrics:
        return None

    for model_name, vals in metrics.items():
        row = AccuracyCache.query.filter_by(group_id=group_id, member_id=member_id, model=model_name).first()
        if row:
            row.data_hash, row.rmse, row.mae, row.mape = h, vals["RMSE"], vals["MAE"], vals["MAPE"]
        else:
            db.session.add(AccuracyCache(
                group_id=group_id, member_id=member_id, model=model_name, data_hash=h,
                rmse=vals["RMSE"], mae=vals["MAE"], mape=vals["MAPE"],
            ))
    db.session.commit()
    return metrics
