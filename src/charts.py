"""
Chart builders
==============
Every function returns a Plotly figure already themed to match the ledger
UI (templates/base.html renders these with Plotly.js on the client, so
they stay interactive — zoom, pan, hover — unlike a static image export).
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

INK = "#0E1420"
CARD = "#161D2E"
GRID = "#232C42"
TEXT = "#C8CEDC"
MUTED = "#7C879E"
GOLD = "#C9A227"
TEAL = "#3FB8AF"
RUST = "#C1502E"
PALETTE = [GOLD, TEAL, "#8B7FD1", "#5FA8D3", "#D68C45", "#6FBF73"]

LAYOUT_BASE = dict(
    paper_bgcolor=CARD,
    plot_bgcolor=CARD,
    font=dict(family="IBM Plex Mono, monospace", color=TEXT, size=12),
    margin=dict(t=36, l=16, r=16, b=16),
    xaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID),
    yaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID),
    legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=-0.18),
    colorway=PALETTE,
)


def _themed(fig: go.Figure, height=380, title=None) -> go.Figure:
    fig.update_layout(**LAYOUT_BASE, height=height)
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=14, color=TEXT, family="Fraunces, serif")))
    return fig


def balance_growth_chart(tx_df: pd.DataFrame, members: list) -> go.Figure:
    fig = go.Figure()
    for m in members:
        s = tx_df[tx_df["member_id"] == m].sort_values("date")
        if s.empty:
            continue
        fig.add_trace(go.Scatter(x=s["date"], y=s["balance"], mode="lines+markers", name=m,
                                  line=dict(width=2), marker=dict(size=5)))
    return _themed(fig, height=420)


def category_pie_chart(meta: dict, members: list) -> go.Figure:
    counts = pd.Series({m: meta[m]["Member_Category"] for m in members}).value_counts()
    fig = px.pie(names=counts.index, values=counts.values, hole=0.58, color_discrete_sequence=PALETTE)
    fig.update_traces(textfont=dict(family="IBM Plex Mono, monospace"))
    return _themed(fig, height=320)


def region_bar_chart(meta: dict, members: list) -> go.Figure:
    counts = pd.Series({m: meta[m]["Region"] for m in members}).value_counts()
    fig = px.bar(x=counts.index, y=counts.values, labels={"x": "Region", "y": "Members"},
                 color=counts.index, color_discrete_sequence=[GOLD, TEAL, "#8B7FD1"])
    fig.update_layout(showlegend=False)
    return _themed(fig, height=320)


def member_forecast_chart(series: pd.Series, idx_future, hw_fc=None, hw_resid=None) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines+markers",
                              name="Actual balance", line=dict(color=GOLD, width=3)))

    if hw_fc is not None:
        std = np.std(hw_resid) if len(hw_resid) else 0
        upper, lower = hw_fc + 1.96 * std, hw_fc - 1.96 * std
        fig.add_trace(go.Scatter(x=idx_future, y=hw_fc, mode="lines+markers", name="Holt-Winters forecast",
                                  line=dict(color=TEAL, dash="dash")))
        fig.add_trace(go.Scatter(x=list(idx_future) + list(idx_future[::-1]), y=list(upper) + list(lower[::-1]),
                                  fill="toself", fillcolor="rgba(63,184,175,0.15)", line=dict(width=0),
                                  name="Holt-Winters 95% CI"))

    return _themed(fig, height=440)


def contributions_withdrawals_chart(tx_m: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=tx_m["date"], y=tx_m["contribution_amount"], name="Contribution", marker_color=GOLD))
    fig.add_trace(go.Bar(x=tx_m["date"], y=-tx_m["withdrawal_amount"], name="Withdrawal", marker_color=RUST))
    fig.update_layout(barmode="relative")
    return _themed(fig, height=300)


def accuracy_bar_chart(avg: pd.DataFrame, metric: str) -> go.Figure:
    fig = px.bar(avg, x="model", y=metric, color="model", text_auto=".1f",
                 color_discrete_sequence=[GOLD, TEAL])
    fig.update_layout(showlegend=False)
    return _themed(fig, height=280, title=f"Average {metric}")


def regional_flow_chart(reg_summary: pd.DataFrame) -> go.Figure:
    fig = px.bar(reg_summary.reset_index(), x="region", y=["total_contrib", "total_withdraw"],
                 barmode="group", color_discrete_sequence=[GOLD, RUST],
                 labels={"value": "Amount (R)", "region": "Region", "variable": "Type"})
    return _themed(fig, height=360)


def regional_box_chart(tx_df: pd.DataFrame) -> go.Figure:
    fig = px.box(tx_df, x="region", y="balance", color="region", color_discrete_sequence=[GOLD, TEAL])
    fig.update_layout(showlegend=False)
    return _themed(fig, height=360, title="Balance Distribution")
