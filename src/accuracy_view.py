"""
Accuracy context builder
=========================
Builds the Holt-Winters backtest results shown in the Settings page's
"Accuracy Health" section. Pulled out of app.py's old standalone
/accuracy route into its own module so both the settings blueprint and
app.py (for the old-URL redirect) can build the same data without
duplicating the pivot/chart logic.

This used to compare Holt-Winters against a live-fit ARIMA model too;
ARIMA was dropped (see src/forecasting.py) so this is now a
single-model summary. The "hist_comparison" table below is unrelated
to that -- it just displays RMSE_ARIMA/RMSE_HoltWinters figures that
were already pre-computed and included in an uploaded historical CSV,
if present, so it's left as-is.

Uses forecasting.get_or_backtest_metrics, which is itself cache-aware
(src/models.AccuracyCache, keyed by a hash of each member's series) --
so calling this on every Settings page view is cheap after the first
computation for a given group's current data.
"""

import pandas as pd

from src import charts, forecasting
from src.data_loader import get_dataset
from src.models import GroupSettings


def build_accuracy_context(group_id: int) -> dict:
    tx_df, hist_df, hist_available, meta, members = get_dataset(group_id)
    forecast_cutoff = GroupSettings.get_or_create(group_id).last_retrained_at

    rows = []
    for m in members:
        series = forecasting.get_member_series(m, tx_df, hist_df, hist_available, forecast_cutoff)
        metrics = forecasting.get_or_backtest_metrics(group_id, m, series)
        if not metrics:
            continue
        for model_name, vals in metrics.items():
            rows.append({"member": m, "model": model_name, **vals})

    acc_df = pd.DataFrame(rows)
    best_model = None
    bar_charts = {}
    pivot_rows = []

    if not acc_df.empty:
        avg = acc_df.groupby("model")[["RMSE", "MAE", "MAPE"]].mean().reset_index()
        if avg["RMSE"].notna().any():
            best_model = avg.loc[avg["RMSE"].idxmin(), "model"]
            for metric in ("RMSE", "MAE", "MAPE"):
                bar_charts[metric] = charts.accuracy_bar_chart(avg, metric).to_json()

        pivot = acc_df.pivot(index="member", columns="model", values=["RMSE", "MAE", "MAPE"]).round(2)
        for member_id in pivot.index:
            row = {"member": member_id}
            for metric in ("RMSE", "MAE", "MAPE"):
                key = f"Holt-Winters_{metric}"
                try:
                    row[key] = pivot.loc[member_id, (metric, "Holt-Winters")]
                except KeyError:
                    row[key] = None
            pivot_rows.append(row)

    hist_comparison = []
    if hist_available and hist_df.get("RMSE_HoltWinters") is not None and hist_df["RMSE_HoltWinters"].notna().any():
        hist_avg = hist_df.groupby("MemberID")[["RMSE_HoltWinters", "RMSE_ARIMA"]].mean().round(1)
        for member_id, row in hist_avg.iterrows():
            hist_comparison.append({"member": member_id, "hw": row["RMSE_HoltWinters"], "arima": row["RMSE_ARIMA"]})

    return {
        "acc_has_members": bool(members),
        "acc_best_model": best_model,
        "acc_bar_charts": bar_charts,
        "acc_pivot_rows": pivot_rows,
        "acc_hist_comparison": hist_comparison,
        "acc_hist_available": hist_available,
    }
