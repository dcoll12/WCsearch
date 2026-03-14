import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import json
import re
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials
import requests

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Grant Research Dashboard",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Card containers */
.metric-card {
    background: linear-gradient(135deg, #1A1D27 0%, #1e2235 100%);
    border: 1px solid #2E7D32;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    text-align: center;
}
.metric-card h1 { margin: 0; font-size: 2.4rem; color: #4CAF50; }
.metric-card p  { margin: 0; color: #aaa; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px; }

/* Score pill */
.score-pill {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-weight: 700;
    font-size: 0.85rem;
}

/* Status badge */
.status-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Grant card */
.grant-card {
    background: #1A1D27;
    border-left: 4px solid #2E7D32;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.8rem;
    transition: border-color 0.2s;
}
.grant-card:hover { border-left-color: #66BB6A; }
.grant-card h4 { margin: 0 0 4px 0; color: #E8F5E9; font-size: 1rem; }
.grant-card .meta { color: #90A4AE; font-size: 0.82rem; }

/* Sidebar section headers */
.sidebar-section {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #4CAF50;
    margin: 1.2rem 0 0.4rem 0;
}

/* Deadline urgency */
.urgent   { color: #EF5350; }
.soon     { color: #FF9800; }
.upcoming { color: #66BB6A; }
.rolling  { color: #42A5F5; }

/* Progress bar wrapper */
.match-bar-wrap { width: 100%; background: #2a2d3e; border-radius: 20px; height: 8px; margin-top: 4px; }
.match-bar      { height: 8px; border-radius: 20px; }

/* Scrollable grant list */
.scrollable { max-height: 70vh; overflow-y: auto; padding-right: 4px; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
SHEET_ID = "1ixKVIO7xeyuGL9n4Afnz10lJ0-Pyxlsm"
EXPECTED_COLS = [
    "Rank", "Score", "Grant Name", "Grant ID", "Funder",
    "Next Deadline", "Status", "Is Custom", "Rolling",
    "Funding Cycle", "Grant URL", "Description", "Locations"
]

STATUS_COLORS = {
    "Active":        ("#1B5E20", "#66BB6A"),
    "Invited":       ("#0D47A1", "#42A5F5"),
    "Applied":       ("#E65100", "#FFA726"),
    "Awarded":       ("#4A148C", "#CE93D8"),
    "Declined":      ("#B71C1C", "#EF9A9A"),
    "Researching":   ("#1A237E", "#90CAF9"),
    "Not a fit":     ("#37474F", "#78909C"),
    "":              ("#37474F", "#78909C"),
}

# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_from_public_csv(sheet_id: str) -> pd.DataFrame:
    """Load data from a publicly shared Google Sheet as CSV."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        df = pd.read_csv(url)
        return df
    except Exception as e:
        raise RuntimeError(f"Could not fetch sheet: {e}")


def load_from_service_account(sheet_id: str, creds_json: dict) -> pd.DataFrame:
    """Load data using a Google service account (for private sheets)."""
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    ws = sh.get_worksheet(0)
    data = ws.get_all_records()
    return pd.DataFrame(data)


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure expected columns exist and normalise types."""
    for col in EXPECTED_COLS:
        if col not in df.columns:
            df[col] = ""

    # Numeric score
    df["Score"] = pd.to_numeric(df["Score"], errors="coerce").fillna(0)
    df["Rank"]  = pd.to_numeric(df["Rank"],  errors="coerce").fillna(0)

    # Score as 0-100 percentage (assume it's already 0-100; normalise if >100)
    max_score = df["Score"].max()
    if max_score > 100:
        df["Score"] = (df["Score"] / max_score * 100).round(1)
    else:
        df["Score"] = df["Score"].round(1)

    # Deadline parsing — keep as datetime for charts, but also store a plain
    # Python date column (_dl_date) used for ALL filtering so we never hit
    # pandas datetime dtype/resolution mismatches across pandas versions.
    parsed = pd.to_datetime(df["Next Deadline"], errors="coerce", utc=True)
    df["Next Deadline"] = parsed.dt.tz_convert(None)  # tz-naive for display/charts
    df["_dl_date"] = df["Next Deadline"].apply(
        lambda x: x.date() if pd.notna(x) else None
    )

    # Boolean-ish fields
    for col in ("Is Custom", "Rolling"):
        df[col] = df[col].astype(str).str.strip().str.lower().isin(
            ["true", "yes", "1", "x", "✓"]
        )

    # Fill blanks
    for col in ("Grant Name", "Funder", "Status", "Locations", "Description", "Grant ID"):
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["Grant URL"] = df["Grant URL"].fillna("").astype(str).str.strip()

    return df


def match_color(score: float) -> str:
    if score >= 80: return "#4CAF50"
    if score >= 60: return "#8BC34A"
    if score >= 40: return "#FF9800"
    return "#EF5350"


def deadline_label(dt) -> tuple[str, str]:
    """Return (text, css_class) for deadline."""
    if pd.isna(dt):
        return "Rolling / TBD", "rolling"
    today = date.today()
    days = (dt.date() - today).days
    if days < 0:
        return f"Closed ({dt.strftime('%b %d')})", "urgent"
    if days <= 14:
        return f"{days}d left ({dt.strftime('%b %d')})", "urgent"
    if days <= 60:
        return f"{days}d left ({dt.strftime('%b %d')})", "soon"
    return dt.strftime("%b %d, %Y"), "upcoming"


def status_badge_html(status: str) -> str:
    bg, fg = STATUS_COLORS.get(status, ("#37474F", "#78909C"))
    return (
        f'<span class="status-badge" '
        f'style="background:{bg}; color:{fg};">{status or "Unknown"}</span>'
    )


def score_pill_html(score: float) -> str:
    color = match_color(score)
    return (
        f'<span class="score-pill" '
        f'style="background:{color}22; color:{color}; border:1px solid {color}55;">'
        f'{score:.0f}% match</span>'
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.image(
            "https://upload.wikimedia.org/wikipedia/commons/a/a7/Camponotus_flavomarginatus_ant.jpg",
            use_container_width=True,
            caption=None,
        ) if False else None  # placeholder logo slot

        st.markdown("# 🌿 Grant Tracker")
        st.markdown("---")

        # Connection settings
        st.markdown('<div class="sidebar-section">Data Source</div>', unsafe_allow_html=True)
        data_mode = st.radio(
            "Connect via",
            ["Public sheet (CSV)", "Service account (private sheet)"],
            index=0,
            help="Use 'Public sheet' if the Google Sheet is shared as Anyone with link can view. "
                 "Use 'Service account' for private sheets.",
        )

        creds_json = None
        if data_mode == "Service account (private sheet)":
            st.info("Upload your Google service account JSON key.")
            uploaded = st.file_uploader("Service account key (.json)", type="json")
            if uploaded:
                try:
                    creds_json = json.load(uploaded)
                    st.success("Key loaded.")
                except Exception:
                    st.error("Invalid JSON file.")

        if st.button("🔄 Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")
        st.markdown('<div class="sidebar-section">Filters</div>', unsafe_allow_html=True)

        return data_mode, creds_json


# ── Main App ──────────────────────────────────────────────────────────────────
def main():
    data_mode, creds_json = render_sidebar()

    # ── Load data ────────────────────────────────────────────────────────────
    with st.spinner("Loading grant data…"):
        try:
            if data_mode == "Public sheet (CSV)":
                raw_df = load_from_public_csv(SHEET_ID)
            else:
                if creds_json is None:
                    st.warning("Please upload a service account JSON key in the sidebar.")
                    st.stop()
                raw_df = load_from_service_account(SHEET_ID, creds_json)
            df = normalize_df(raw_df.copy())
        except Exception as e:
            st.error(f"**Could not load data:** {e}")
            st.markdown("""
**Troubleshooting:**
1. Make sure the Google Sheet is shared as **"Anyone with the link can view"**
2. Or upload a service account key in the sidebar for private sheets
3. The sheet ID in use is: `1liZmyLwoMShmDAU0ANM8gJzAB5Fx3Ygf6udGCf6gl2Y`
""")
            # Demo data fallback
            st.markdown("---")
            st.markdown("**Showing demo data:**")
            df = demo_data()

    # ── Sidebar filters ───────────────────────────────────────────────────────
    with st.sidebar:
        # Score range
        min_score, max_score = int(df["Score"].min()), int(df["Score"].max())
        score_range = st.slider(
            "Match score %",
            min_score, max(max_score, 1),
            (min_score, max(max_score, 1)),
        )

        # Status filter
        all_statuses = sorted(df["Status"].unique().tolist())
        selected_statuses = st.multiselect(
            "Status",
            all_statuses,
            default=all_statuses,
        )

        # Location filter
        all_locations = sorted(
            set(loc.strip() for locs in df["Locations"] for loc in locs.split(",") if loc.strip())
        )
        selected_locations = st.multiselect("Locations", all_locations, default=[])

        # Deadline filter
        st.markdown('<div class="sidebar-section">Deadline</div>', unsafe_allow_html=True)
        deadline_opts = ["All", "Next 30 days", "Next 90 days", "Overdue", "Rolling / TBD"]
        deadline_filter = st.selectbox("Show deadlines", deadline_opts, index=0)

        # Text search
        st.markdown('<div class="sidebar-section">Search</div>', unsafe_allow_html=True)
        search_query = st.text_input("Search grants", placeholder="Keyword, funder, location…")

        # Sort
        st.markdown('<div class="sidebar-section">Sort</div>', unsafe_allow_html=True)
        sort_by = st.selectbox("Sort by", ["Score (high→low)", "Score (low→high)", "Deadline (soonest)", "Rank", "Funder A-Z"])

    # ── Apply filters ─────────────────────────────────────────────────────────
    filtered = df.copy()

    filtered = filtered[
        (filtered["Score"] >= score_range[0]) &
        (filtered["Score"] <= score_range[1])
    ]

    if selected_statuses:
        filtered = filtered[filtered["Status"].isin(selected_statuses)]

    if selected_locations:
        filtered = filtered[
            filtered["Locations"].apply(
                lambda x: any(loc in x for loc in selected_locations)
            )
        ]

    today = date.today()  # plain Python date — used everywhere for filtering
    today_ts = pd.Timestamp(today)  # used only for charts/Gantt

    def _dl_gte(d, ref): return d is not None and d >= ref
    def _dl_lte(d, ref): return d is not None and d <= ref
    def _dl_lt(d, ref):  return d is not None and d < ref

    if deadline_filter == "Next 30 days":
        cut = today + pd.Timedelta(days=30).to_pytimedelta()
        filtered = filtered[filtered["_dl_date"].apply(lambda d: _dl_gte(d, today) and _dl_lte(d, cut))]
    elif deadline_filter == "Next 90 days":
        cut = today + pd.Timedelta(days=90).to_pytimedelta()
        filtered = filtered[filtered["_dl_date"].apply(lambda d: _dl_gte(d, today) and _dl_lte(d, cut))]
    elif deadline_filter == "Overdue":
        filtered = filtered[filtered["_dl_date"].apply(lambda d: _dl_lt(d, today))]
    elif deadline_filter == "Rolling / TBD":
        filtered = filtered[filtered["_dl_date"].isna() | filtered["Rolling"]]

    if search_query:
        q = search_query.lower()
        filtered = filtered[
            filtered["Grant Name"].str.lower().str.contains(q, na=False) |
            filtered["Funder"].str.lower().str.contains(q, na=False) |
            filtered["Description"].str.lower().str.contains(q, na=False) |
            filtered["Locations"].str.lower().str.contains(q, na=False) |
            filtered["Status"].str.lower().str.contains(q, na=False)
        ]

    # Sort
    if sort_by == "Score (high→low)":
        filtered = filtered.sort_values("Score", ascending=False)
    elif sort_by == "Score (low→high)":
        filtered = filtered.sort_values("Score", ascending=True)
    elif sort_by == "Deadline (soonest)":
        filtered = filtered.sort_values("Next Deadline", ascending=True, na_position="last")
    elif sort_by == "Rank":
        filtered = filtered.sort_values("Rank", ascending=True)
    elif sort_by == "Funder A-Z":
        filtered = filtered.sort_values("Funder", ascending=True)

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown("# 🌿 Grant Research Dashboard")
    st.markdown(
        f"Showing **{len(filtered)}** of **{len(df)}** grants · "
        f"Last refreshed: {datetime.now().strftime('%b %d, %Y %H:%M')}"
    )
    st.markdown("---")

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)

    total_grants = len(df)
    avg_score    = df["Score"].mean() if len(df) > 0 else 0
    high_match   = len(df[df["Score"] >= 70])
    cut30 = today + pd.Timedelta(days=30).to_pytimedelta()
    upcoming_dl = len(df[df["_dl_date"].apply(lambda d: _dl_gte(d, today) and _dl_lte(d, cut30))])
    awarded = len(df[df["Status"].str.lower() == "awarded"])

    kpis = [
        (col1, str(total_grants),          "Total Grants"),
        (col2, f"{avg_score:.0f}%",        "Avg Match Score"),
        (col3, str(high_match),            "High Matches (≥70%)"),
        (col4, str(upcoming_dl),           "Due in 30 Days"),
        (col5, str(awarded),               "Awarded"),
    ]
    for col, val, label in kpis:
        with col:
            st.markdown(
                f'<div class="metric-card"><h1>{val}</h1><p>{label}</p></div>',
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_list, tab_chart, tab_deadline, tab_table = st.tabs([
        "📋 Grant List", "📊 Analytics", "📅 Deadline Calendar", "🗂 Raw Table"
    ])

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 · Grant List
    # ─────────────────────────────────────────────────────────────────────────
    with tab_list:
        if filtered.empty:
            st.info("No grants match the current filters.")
        else:
            st.markdown(f"### {len(filtered)} Grants")
            for _, row in filtered.iterrows():
                score = row["Score"]
                bar_color = match_color(score)
                dl_text, dl_class = deadline_label(row["Next Deadline"])
                url = row["Grant URL"]
                name_html = (
                    f'<a href="{url}" target="_blank" style="color:#E8F5E9;">{row["Grant Name"]}</a>'
                    if url.startswith("http")
                    else f'{row["Grant Name"]}'
                )

                rolling_tag = ' <span style="color:#42A5F5; font-size:0.75rem;">↻ Rolling</span>' if row["Rolling"] else ""
                custom_tag  = ' <span style="color:#CE93D8; font-size:0.75rem;">★ Custom</span>'  if row["Is Custom"] else ""

                with st.expander(
                    f"{'⭐ ' if score >= 80 else ''}{row['Grant Name']} — {row['Funder']}",
                    expanded=False,
                ):
                    c1, c2, c3 = st.columns([3, 2, 2])
                    with c1:
                        st.markdown(
                            f"{score_pill_html(score)} "
                            f"{status_badge_html(row['Status'])}"
                            f"{rolling_tag}{custom_tag}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f'<div class="match-bar-wrap">'
                            f'<div class="match-bar" style="width:{score}%; background:{bar_color};"></div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**Funder:** {row['Funder']}")
                        if row["Locations"]:
                            st.markdown(f"**Locations:** {row['Locations']}")
                        if row["Funding Cycle"]:
                            st.markdown(f"**Cycle:** {row['Funding Cycle']}")
                    with c2:
                        st.markdown(f"**Grant ID:** `{row['Grant ID']}`" if row["Grant ID"] else "")
                        st.markdown(
                            f'**Deadline:** <span class="{dl_class}">{dl_text}</span>',
                            unsafe_allow_html=True,
                        )
                        if url.startswith("http"):
                            st.markdown(f"[🔗 View Grant]({url})")
                    with c3:
                        st.markdown(f"**Match Score:** `{score:.1f}%`")
                        st.markdown(f"**Rank:** #{int(row['Rank'])}" if row["Rank"] else "")

                    if row["Description"]:
                        st.markdown("---")
                        st.markdown(f"**Description:**")
                        st.markdown(row["Description"])

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 · Analytics
    # ─────────────────────────────────────────────────────────────────────────
    with tab_chart:
        if filtered.empty:
            st.info("No data to chart.")
        else:
            row1_c1, row1_c2 = st.columns(2)

            # Score distribution histogram
            with row1_c1:
                fig_hist = px.histogram(
                    filtered,
                    x="Score",
                    nbins=20,
                    title="Match Score Distribution",
                    color_discrete_sequence=["#4CAF50"],
                    template="plotly_dark",
                )
                fig_hist.update_layout(
                    paper_bgcolor="#1A1D27",
                    plot_bgcolor="#1A1D27",
                    bargap=0.05,
                    xaxis_title="Match %",
                    yaxis_title="# Grants",
                    margin=dict(t=40, b=20, l=20, r=20),
                )
                fig_hist.add_vline(
                    x=filtered["Score"].mean(),
                    line_dash="dash",
                    line_color="#FF9800",
                    annotation_text=f"Avg {filtered['Score'].mean():.0f}%",
                    annotation_position="top right",
                )
                st.plotly_chart(fig_hist, use_container_width=True)

            # Status breakdown donut
            with row1_c2:
                status_counts = filtered["Status"].value_counts().reset_index()
                status_counts.columns = ["Status", "Count"]
                colors = [STATUS_COLORS.get(s, ("#37474F", "#78909C"))[1] for s in status_counts["Status"]]
                fig_donut = go.Figure(go.Pie(
                    labels=status_counts["Status"],
                    values=status_counts["Count"],
                    hole=0.55,
                    marker_colors=colors,
                    textinfo="label+percent",
                    hovertemplate="%{label}: %{value} grants<extra></extra>",
                ))
                fig_donut.update_layout(
                    title="Grants by Status",
                    paper_bgcolor="#1A1D27",
                    plot_bgcolor="#1A1D27",
                    font_color="#FAFAFA",
                    showlegend=False,
                    margin=dict(t=40, b=20, l=20, r=20),
                    template="plotly_dark",
                )
                st.plotly_chart(fig_donut, use_container_width=True)

            row2_c1, row2_c2 = st.columns(2)

            # Top funders by avg score
            with row2_c1:
                top_funders = (
                    filtered[filtered["Funder"] != ""]
                    .groupby("Funder")["Score"]
                    .agg(["mean", "count"])
                    .reset_index()
                    .rename(columns={"mean": "Avg Score", "count": "# Grants"})
                    .sort_values("Avg Score", ascending=False)
                    .head(15)
                )
                fig_funders = px.bar(
                    top_funders,
                    x="Avg Score",
                    y="Funder",
                    orientation="h",
                    color="Avg Score",
                    color_continuous_scale=["#EF5350", "#FF9800", "#4CAF50"],
                    title="Top Funders by Avg Match Score",
                    template="plotly_dark",
                    hover_data={"# Grants": True},
                    text="Avg Score",
                )
                fig_funders.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
                fig_funders.update_layout(
                    paper_bgcolor="#1A1D27",
                    plot_bgcolor="#1A1D27",
                    coloraxis_showscale=False,
                    yaxis={"categoryorder": "total ascending"},
                    margin=dict(t=40, b=20, l=20, r=20),
                    xaxis_title="Avg Match %",
                    yaxis_title="",
                )
                st.plotly_chart(fig_funders, use_container_width=True)

            # Score vs Deadline scatter
            with row2_c2:
                scatter_df = filtered[filtered["Next Deadline"].notna()].copy()
                if not scatter_df.empty:
                    scatter_df["Days Until"] = scatter_df["_dl_date"].apply(
                        lambda d: (d - today).days if d is not None else None
                    )
                    scatter_df["Color"] = scatter_df["Score"].apply(match_color)
                    fig_scatter = px.scatter(
                        scatter_df,
                        x="Days Until",
                        y="Score",
                        color="Score",
                        color_continuous_scale=["#EF5350", "#FF9800", "#4CAF50"],
                        size="Score",
                        hover_name="Grant Name",
                        hover_data={"Funder": True, "Status": True, "Score": ":.1f"},
                        title="Match Score vs Days Until Deadline",
                        template="plotly_dark",
                        labels={"Days Until": "Days Until Deadline", "Score": "Match %"},
                    )
                    fig_scatter.update_layout(
                        paper_bgcolor="#1A1D27",
                        plot_bgcolor="#1A1D27",
                        coloraxis_showscale=False,
                        margin=dict(t=40, b=20, l=20, r=20),
                    )
                    fig_scatter.add_vline(x=0, line_dash="dash", line_color="#EF5350", annotation_text="Today")
                    fig_scatter.add_vline(x=30, line_dash="dot", line_color="#FF9800", annotation_text="30d")
                    st.plotly_chart(fig_scatter, use_container_width=True)
                else:
                    st.info("No dated deadlines in current filter set.")

            # Location heatmap (if data available)
            loc_df = (
                pd.DataFrame(
                    [
                        {"Location": loc.strip(), "Score": row["Score"]}
                        for _, row in filtered.iterrows()
                        for loc in row["Locations"].split(",")
                        if loc.strip()
                    ]
                )
            )
            if not loc_df.empty:
                loc_agg = (
                    loc_df.groupby("Location")
                    .agg(Count=("Score", "count"), Avg_Score=("Score", "mean"))
                    .reset_index()
                    .sort_values("Count", ascending=False)
                    .head(20)
                )
                fig_loc = px.bar(
                    loc_agg,
                    x="Location",
                    y="Count",
                    color="Avg_Score",
                    color_continuous_scale=["#EF5350", "#FF9800", "#4CAF50"],
                    title="Grant Coverage by Location",
                    template="plotly_dark",
                    hover_data={"Avg_Score": ":.1f"},
                )
                fig_loc.update_layout(
                    paper_bgcolor="#1A1D27",
                    plot_bgcolor="#1A1D27",
                    coloraxis_colorbar_title="Avg Match %",
                    xaxis_tickangle=-35,
                    margin=dict(t=40, b=80, l=20, r=20),
                    xaxis_title="",
                    yaxis_title="# Grants",
                )
                st.plotly_chart(fig_loc, use_container_width=True)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3 · Deadline Calendar
    # ─────────────────────────────────────────────────────────────────────────
    with tab_deadline:
        dated = filtered[filtered["Next Deadline"].notna()].copy()
        dated = dated.sort_values("Next Deadline")

        if dated.empty:
            st.info("No dated deadlines in current filter set.")
        else:
            # Gantt-style timeline
            dated["Days Until"] = dated["_dl_date"].apply(
                lambda d: (d - today).days if d is not None else None
            )
            dated["Label"] = dated.apply(
                lambda r: f"{r['Grant Name'][:40]} | {r['Score']:.0f}%", axis=1
            )
            dated["Color"] = dated["Score"].apply(match_color)

            today_str = today.isoformat()
            fig_gantt = px.timeline(
                dated.assign(
                    Start=today_str,
                    Finish=dated["_dl_date"].apply(
                        lambda d: d.isoformat() if d is not None else today_str
                    ),
                ),
                x_start="Start",
                x_end="Finish",
                y="Label",
                color="Score",
                color_continuous_scale=["#EF5350", "#FF9800", "#4CAF50"],
                title="Grant Deadline Timeline",
                template="plotly_dark",
                hover_name="Grant Name",
                hover_data={"Funder": True, "Status": True, "Score": ":.0f", "Start": False, "Finish": False},
            )
            fig_gantt.update_layout(
                paper_bgcolor="#1A1D27",
                plot_bgcolor="#1A1D27",
                coloraxis_colorbar_title="Match %",
                yaxis={"categoryorder": "total ascending"},
                height=max(400, len(dated) * 30),
                margin=dict(t=40, b=20, l=20, r=20),
                xaxis_title="",
                yaxis_title="",
            )
            fig_gantt.add_vline(
                x=today_ts.timestamp() * 1000,
                line_dash="dash",
                line_color="#FF9800",
                annotation_text="Today",
            )
            st.plotly_chart(fig_gantt, use_container_width=True)

            # Urgent grants table
            urgent = dated[dated["Days Until"] <= 30].sort_values("Days Until")
            if not urgent.empty:
                st.markdown("### ⚠️ Due within 30 days")
                for _, row in urgent.iterrows():
                    days = int(row["Days Until"])
                    urgency = "🔴" if days <= 7 else "🟡"
                    dl_text, _ = deadline_label(row["Next Deadline"])
                    url = row["Grant URL"]
                    link = f"[{row['Grant Name']}]({url})" if url.startswith("http") else row["Grant Name"]
                    st.markdown(
                        f"{urgency} **{link}** — {row['Funder']} — "
                        f"`{score_pill_html(row['Score'])}` — {dl_text}",
                        unsafe_allow_html=True,
                    )

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 4 · Raw Table
    # ─────────────────────────────────────────────────────────────────────────
    with tab_table:
        display_cols = [
            "Rank", "Score", "Grant Name", "Funder", "Status",
            "Next Deadline", "Locations", "Rolling", "Is Custom", "Funding Cycle", "Grant URL"
        ]
        display_df = filtered[[c for c in display_cols if c in filtered.columns]].copy()
        display_df["Score"] = display_df["Score"].apply(lambda x: f"{x:.1f}%")
        display_df["Next Deadline"] = filtered["_dl_date"].apply(
            lambda d: d.isoformat() if d is not None else "Rolling / TBD"
        )

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Grant URL": st.column_config.LinkColumn("Grant URL", display_text="🔗 Link"),
                "Score": st.column_config.TextColumn("Match %"),
                "Rolling": st.column_config.CheckboxColumn("Rolling"),
                "Is Custom": st.column_config.CheckboxColumn("Custom"),
            },
        )

        # CSV download
        csv = filtered.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download filtered data as CSV",
            data=csv,
            file_name=f"grants_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )


# ── Demo data (fallback) ──────────────────────────────────────────────────────
def demo_data() -> pd.DataFrame:
    today = date.today()
    rows = [
        [1, 92, "Climate Resilience Fund", "G001", "Bezos Earth Fund",
         (pd.Timestamp(today) + pd.Timedelta(days=25)).strftime("%Y-%m-%d"),
         "Active", False, False, "Annual", "https://example.com/1",
         "Supports innovative approaches to climate resilience in underserved communities.", "California, Oregon"],
        [2, 85, "Green Infrastructure Grant", "G002", "Patagonia Environmental",
         (pd.Timestamp(today) + pd.Timedelta(days=60)).strftime("%Y-%m-%d"),
         "Researching", True, False, "Biannual", "https://example.com/2",
         "Funding for urban green infrastructure projects.", "Nationwide"],
        [3, 78, "Community Health Initiative", "G003", "Robert Wood Johnson",
         (pd.Timestamp(today) + pd.Timedelta(days=90)).strftime("%Y-%m-%d"),
         "Applied", False, True, "Rolling", "https://example.com/3",
         "Improving health outcomes in rural and underserved communities.", "Texas, New Mexico"],
        [4, 65, "Watershed Restoration", "G004", "Gordon & Betty Moore",
         (pd.Timestamp(today) - pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
         "Invited", False, False, "Annual", "https://example.com/4",
         "Protecting and restoring critical watershed ecosystems.", "Pacific Northwest"],
        [5, 55, "Youth Environmental Education", "G005", "National Park Foundation",
         "", "Active", False, True, "Rolling", "https://example.com/5",
         "Education programs connecting youth with nature.", "Nationwide"],
        [6, 45, "Sustainable Agriculture", "G006", "W.K. Kellogg Foundation",
         (pd.Timestamp(today) + pd.Timedelta(days=120)).strftime("%Y-%m-%d"),
         "Researching", False, False, "Annual", "",
         "Supporting transition to regenerative agriculture practices.", "Midwest"],
        [7, 88, "Biodiversity Conservation", "G007", "Wilburforce Foundation",
         (pd.Timestamp(today) + pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
         "Active", True, False, "Annual", "https://example.com/7",
         "Protecting endangered species and critical habitat.", "Rocky Mountains"],
        [8, 72, "Clean Energy Access", "G008", "Energy Foundation",
         (pd.Timestamp(today) + pd.Timedelta(days=45)).strftime("%Y-%m-%d"),
         "Awarded", False, False, "Annual", "https://example.com/8",
         "Expanding access to clean, affordable energy for low-income households.", "California"],
    ]
    return pd.DataFrame(rows, columns=EXPECTED_COLS)


if __name__ == "__main__":
    main()
