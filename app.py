import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import json
import requests
import os
import re
import io
from collections import Counter
from datetime import datetime, date, timedelta
import gspread
from google.oauth2.service_account import Credentials

# Optional document parsing libraries
try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

st.set_page_config(page_title="Grant Research Dashboard", page_icon="🌿", layout="wide", initial_sidebar_state="expanded")

st.markdown("""<style>
.metric-card { background: linear-gradient(135deg, #1A1D27 0%, #1e2235 100%); border: 1px solid #2E7D32; border-radius: 12px; padding: 1.2rem 1.5rem; text-align: center; }
.metric-card h1 { margin: 0; font-size: 2.4rem; color: #4CAF50; }
.metric-card p  { margin: 0; color: #aaa; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px; }
.score-pill { display: inline-block; padding: 3px 10px; border-radius: 20px; font-weight: 700; font-size: 0.85rem; }
.status-badge { display: inline-block; padding: 3px 10px; border-radius: 6px; font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.sidebar-section { font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #4CAF50; margin: 1.2rem 0 0.4rem 0; }
.urgent { color: #EF5350; } .soon { color: #FF9800; } .upcoming { color: #66BB6A; } .rolling { color: #42A5F5; }
.match-bar-wrap { width: 100%; background: #2a2d3e; border-radius: 20px; height: 8px; margin-top: 4px; }
.match-bar { height: 8px; border-radius: 20px; }
.desc-box { background: #1e2235; border-left: 3px solid #2E7D32; padding: 12px 16px; border-radius: 0 8px 8px 0; font-size: 0.88rem; line-height: 1.65; white-space: pre-wrap; word-wrap: break-word; word-break: break-word; color: #d0d0d0; margin-top: 8px; max-height: 300px; overflow-y: auto; }
.match-highlight { background: #1B5E20; border-left: 3px solid #4CAF50; padding: 12px 16px; border-radius: 0 8px 8px 0; font-size: 0.88rem; line-height: 1.65; color: #d0d0d0; margin-top: 8px; }
</style>""", unsafe_allow_html=True)

# Updated sheet ID and columns to match new spreadsheet format
SHEET_ID = "1HGmlZoCiQvRb7CTHqh-ZjqcTTQ_nmGXdogqyYp7mQi8"
SHEET_GID = "969887567"
EXPECTED_COLS = ["Rank", "Score", "Grant Name", "Funder", "Next Deadline", "Status",
                 "Funding Cycle", "Grant URL", "Website URL", "Description"]

STATUS_COLORS = {
    "Active":      ("#1B5E20", "#66BB6A"),
    "Invited":     ("#0D47A1", "#42A5F5"),
    "Applied":     ("#E65100", "#FFA726"),
    "Awarded":     ("#4A148C", "#CE93D8"),
    "Declined":    ("#B71C1C", "#EF9A9A"),
    "Researching": ("#1A237E", "#90CAF9"),
    "Not a fit":   ("#37474F", "#78909C"),
    "":            ("#37474F", "#78909C"),
}

MONDAY_API_URL = "https://api.monday.com/v2"


@st.cache_data(ttl=300, show_spinner=False)
def load_from_public_csv(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={SHEET_GID}"
    return pd.read_csv(url)


def load_from_service_account(sheet_id, creds_json):
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(creds)
    return pd.DataFrame(gc.open_by_key(sheet_id).get_worksheet_by_id(int(SHEET_GID)).get_all_records())


def load_from_uploaded_file(uploaded_file):
    """Load grant data from an uploaded CSV or Excel file."""
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    elif name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file)
    else:
        raise ValueError(f"Unsupported file type: {uploaded_file.name}. Please upload a CSV or Excel file.")


def normalize_df(df):
    for col in EXPECTED_COLS:
        if col not in df.columns:
            df[col] = ""
    df["Rank"] = pd.to_numeric(df["Rank"], errors="coerce").fillna(0).astype(int)
    df["Score"] = pd.to_numeric(df["Score"], errors="coerce").fillna(0)
    mx = df["Score"].max()
    df["Score"] = ((df["Score"] / mx * 100) if mx > 100 else df["Score"]).round(1)

    parsed = pd.to_datetime(df["Next Deadline"], errors="coerce", utc=True)
    df["Next Deadline"] = parsed.dt.tz_convert(None)
    df["_dl_date"] = df["Next Deadline"].apply(lambda x: x.date() if pd.notna(x) else None)

    df["Status"] = df["Status"].fillna("").astype(str).str.strip()
    for col in ("Grant Name", "Funder", "Funding Cycle", "Description", "Website URL"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    df["Grant URL"] = df["Grant URL"].fillna("").astype(str).str.strip()
    return df


def match_color(s):
    return "#4CAF50" if s >= 80 else "#8BC34A" if s >= 60 else "#FF9800" if s >= 40 else "#EF5350"


def deadline_label(dt):
    if pd.isna(dt): return "Rolling / TBD", "rolling"
    days = (dt.date() - date.today()).days
    if days < 0:   return f"Closed ({dt.strftime('%b %d')})", "urgent"
    if days <= 14: return f"{days}d left ({dt.strftime('%b %d')})", "urgent"
    if days <= 60: return f"{days}d left ({dt.strftime('%b %d')})", "soon"
    return dt.strftime("%b %d, %Y"), "upcoming"


def status_badge_html(s):
    bg, fg = STATUS_COLORS.get(s, ("#37474F", "#78909C"))
    return f'<span class="status-badge" style="background:{bg};color:{fg};">{s or "Unknown"}</span>'


def score_pill_html(score):
    c = match_color(score)
    return f'<span class="score-pill" style="background:{c}22;color:{c};border:1px solid {c}55;">{score:.0f}% match</span>'


# ── Document matching helpers ──

def extract_text_from_file(uploaded_file):
    """Extract plain text from a PDF, DOCX, TXT, or CSV file."""
    name = uploaded_file.name.lower()
    raw_bytes = uploaded_file.read()

    if name.endswith(".txt"):
        return raw_bytes.decode("utf-8", errors="ignore")

    if name.endswith(".pdf"):
        if not HAS_PYPDF:
            st.error("pypdf is not installed. Run `pip install pypdf` to enable PDF support.")
            return ""
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if name.endswith(".docx"):
        if not HAS_DOCX:
            st.error("python-docx is not installed. Run `pip install python-docx` to enable DOCX support.")
            return ""
        doc = DocxDocument(io.BytesIO(raw_bytes))
        return "\n".join(para.text for para in doc.paragraphs)

    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(raw_bytes))
        return " ".join(df.astype(str).values.flatten())

    raise ValueError(f"Unsupported file type: {uploaded_file.name}. Use PDF, DOCX, TXT, or CSV.")


# Stop-words to ignore when matching
_STOP_WORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
    "was", "one", "our", "out", "had", "have", "has", "his", "with", "this",
    "that", "from", "they", "will", "been", "more", "when", "who", "its",
    "into", "than", "then", "also", "any", "may", "new", "such", "use",
    "each", "which", "their", "there", "these", "those", "been", "being",
    "both", "other", "through", "during", "before", "after", "above", "below",
    "between", "about", "under", "again", "further", "once", "only", "same",
    "own", "just", "over", "should", "could", "would", "while", "where",
    "very", "most", "some", "what", "well", "even", "make", "many", "how",
}


def _tokenize(text):
    tokens = re.findall(r"\b[a-z]{3,}\b", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS]


def compute_match_scores(profile_text, descriptions):
    """
    Score each grant description against the profile document using
    TF-IDF cosine similarity implemented with plain Python/NumPy.

    Returns a list of floats in [0, 100].
    """
    profile_tokens = _tokenize(profile_text)
    if not profile_tokens:
        return [0.0] * len(descriptions)

    # Build vocabulary from profile + all descriptions
    all_texts = [profile_text] + list(descriptions)
    tokenized = [_tokenize(t) for t in all_texts]

    vocab = sorted({tok for toks in tokenized for tok in toks})
    vocab_index = {w: i for i, w in enumerate(vocab)}
    n_docs = len(tokenized)

    # TF matrix
    tf = np.zeros((n_docs, len(vocab)), dtype=np.float32)
    for d_idx, toks in enumerate(tokenized):
        counts = Counter(toks)
        total = max(len(toks), 1)
        for w, cnt in counts.items():
            if w in vocab_index:
                tf[d_idx, vocab_index[w]] = cnt / total

    # IDF vector
    doc_freq = (tf > 0).sum(axis=0)
    idf = np.log((n_docs + 1) / (doc_freq + 1)) + 1.0

    # TF-IDF
    tfidf = tf * idf

    # Cosine similarity between profile (index 0) and each grant
    profile_vec = tfidf[0]
    grant_vecs = tfidf[1:]

    norms = np.linalg.norm(grant_vecs, axis=1)
    profile_norm = np.linalg.norm(profile_vec)

    if profile_norm == 0:
        return [0.0] * len(descriptions)

    sims = np.dot(grant_vecs, profile_vec) / (norms * profile_norm + 1e-10)

    # Normalise to 0-100
    max_sim = sims.max()
    if max_sim > 0:
        scores = (sims / max_sim * 100).round(1).tolist()
    else:
        scores = [0.0] * len(descriptions)

    return scores


# ── Monday.com helpers ──
def monday_query(api_key, query):
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    resp = requests.post(MONDAY_API_URL, json={"query": query}, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise ValueError(data["errors"][0].get("message", str(data["errors"])))
    return data.get("data", {})


def get_monday_boards(api_key):
    data = monday_query(api_key, "{ boards(limit:50) { id name } }")
    return data.get("boards", [])


def push_grant_to_monday(api_key, board_id, row):
    """Create a Monday.com item for the grant, then add a detailed update comment."""
    name = row["Grant Name"].replace("\\", "\\\\").replace('"', '\\"')
    mutation = f'mutation {{ create_item(board_id: {board_id}, item_name: "{name}") {{ id }} }}'
    data = monday_query(api_key, mutation)
    item_id = data.get("create_item", {}).get("id")

    if item_id:
        deadline = row["_dl_date"].isoformat() if row["_dl_date"] else "Rolling / TBD"
        grant_url = row.get("Grant URL", "")
        website_url = row.get("Website URL", "")
        desc = row.get("Description", "")[:800]
        body = (
            f"**Match Score:** {row['Score']:.0f}%\\n"
            f"**Funder:** {row['Funder']}\\n"
            f"**Deadline:** {deadline}\\n"
            f"**Status:** {row['Status']}\\n"
            f"**Funding Cycle:** {row.get('Funding Cycle', '')}\\n"
        )
        if grant_url:
            body += f"**Grant URL:** {grant_url}\\n"
        if website_url:
            body += f"**Website:** {website_url}\\n"
        if desc:
            body += f"\\n---\\n{desc}"

        body_escaped = body.replace('"', '\\"')
        update_q = f'mutation {{ create_update(item_id: {item_id}, body: "{body_escaped}") {{ id }} }}'
        monday_query(api_key, update_q)

    return item_id


def main():
    with st.sidebar:
        st.markdown("# 🌿 Grant Tracker\n---")
        st.markdown('<div class="sidebar-section">Data Source</div>', unsafe_allow_html=True)
        data_mode = st.radio(
            "Connect via",
            ["Public sheet (CSV)", "Service account (private sheet)", "Upload CSV / Excel file"],
            index=0,
        )
        creds_json = None
        uploaded_grants_file = None

        if data_mode == "Service account (private sheet)":
            uploaded = st.file_uploader("Service account key (.json)", type="json")
            if uploaded:
                try: creds_json = json.load(uploaded)
                except: st.error("Invalid JSON file.")

        elif data_mode == "Upload CSV / Excel file":
            uploaded_grants_file = st.file_uploader(
                "Upload your grants file",
                type=["csv", "xlsx", "xls"],
                help="Upload a CSV or Excel file with columns: Rank, Score, Grant Name, Funder, Next Deadline, Status, Funding Cycle, Grant URL, Website URL, Description",
            )

        if st.button("🔄 Refresh data", use_container_width=True):
            st.cache_data.clear(); st.rerun()
        st.markdown("---")
        st.markdown('<div class="sidebar-section">Filters</div>', unsafe_allow_html=True)

    with st.spinner("Loading grant data…"):
        try:
            if data_mode == "Public sheet (CSV)":
                raw = load_from_public_csv(SHEET_ID)
            elif data_mode == "Service account (private sheet)":
                raw = load_from_service_account(SHEET_ID, creds_json)
            elif data_mode == "Upload CSV / Excel file":
                if uploaded_grants_file is None:
                    st.info("👆 Upload a CSV or Excel grants file in the sidebar to get started.")
                    df = demo_data()
                    raw = None
                else:
                    raw = load_from_uploaded_file(uploaded_grants_file)
            if data_mode != "Upload CSV / Excel file" or uploaded_grants_file is not None:
                df = normalize_df(raw.copy())
        except Exception as e:
            st.error(f"**Could not load data:** {e}\n\nMake sure the sheet is shared as 'Anyone with the link can view'.")
            df = demo_data()

    # ── Sidebar filters ──
    with st.sidebar:
        mn, mx2 = int(df["Score"].min()), int(df["Score"].max())
        score_range = st.slider("Match score %", mn, max(mx2, 1), (mn, max(mx2, 1)))
        all_statuses = sorted(df["Status"].unique())
        selected_statuses = st.multiselect("Status", all_statuses, default=all_statuses)
        st.markdown('<div class="sidebar-section">Deadline</div>', unsafe_allow_html=True)
        deadline_filter = st.selectbox("Show deadlines", ["All", "Next 30 days", "Next 90 days", "Overdue", "Rolling / TBD"])
        st.markdown('<div class="sidebar-section">Search</div>', unsafe_allow_html=True)
        search_query = st.text_input("Search grants", placeholder="Keyword, funder…")
        st.markdown('<div class="sidebar-section">Sort</div>', unsafe_allow_html=True)
        sort_by = st.selectbox("Sort by", ["Rank (low→high)", "Score (high→low)", "Score (low→high)", "Deadline (soonest)", "Funder A-Z"])

    # ── Filtering ──
    f = df.copy()
    f = f[(f["Score"] >= score_range[0]) & (f["Score"] <= score_range[1])]
    if selected_statuses:
        f = f[f["Status"].isin(selected_statuses)]

    today = date.today()
    today_ts = pd.Timestamp(today)

    def gte(d, r): return d is not None and d >= r
    def lte(d, r): return d is not None and d <= r
    def lt(d, r):  return d is not None and d < r

    if deadline_filter == "Next 30 days":
        cut = today + timedelta(days=30)
        f = f[f["_dl_date"].apply(lambda d: gte(d, today) and lte(d, cut))]
    elif deadline_filter == "Next 90 days":
        cut = today + timedelta(days=90)
        f = f[f["_dl_date"].apply(lambda d: gte(d, today) and lte(d, cut))]
    elif deadline_filter == "Overdue":
        f = f[f["_dl_date"].apply(lambda d: lt(d, today))]
    elif deadline_filter == "Rolling / TBD":
        f = f[f["_dl_date"].isna()]

    if search_query:
        q = search_query.lower()
        f = f[
            f["Grant Name"].str.lower().str.contains(q, na=False) |
            f["Funder"].str.lower().str.contains(q, na=False) |
            f["Description"].str.lower().str.contains(q, na=False)
        ]

    sort_map = {
        "Rank (low→high)": ("Rank", True), "Score (high→low)": ("Score", False),
        "Score (low→high)": ("Score", True), "Deadline (soonest)": ("Next Deadline", True),
        "Funder A-Z": ("Funder", True),
    }
    col_s, asc_s = sort_map.get(sort_by, ("Rank", True))
    f = f.sort_values(col_s, ascending=asc_s, na_position="last")

    # ── Header ──
    st.markdown("# 🌿 Grant Research Dashboard")
    st.markdown(f"Showing **{len(f)}** of **{len(df)}** grants · Last refreshed: {datetime.now().strftime('%b %d, %Y %H:%M')}")
    st.markdown("---")

    # ── KPIs ──
    cut30 = today + timedelta(days=30)
    c1, c2, c3, c4, c5 = st.columns(5)
    awarded_count = len(df[df["Status"].str.lower() == "awarded"])
    kpis = [
        (c1, str(len(df)), "Total Grants"),
        (c2, f"{df['Score'].mean():.0f}%" if len(df) else "—", "Avg Match Score"),
        (c3, str(len(df[df["Score"] >= 70])), "High Matches (≥70%)"),
        (c4, str(len(df[df["_dl_date"].apply(lambda d: gte(d, today) and lte(d, cut30))])), "Due in 30 Days"),
        (c5, str(awarded_count), "Awarded"),
    ]
    for col, val, label in kpis:
        with col:
            st.markdown(f'<div class="metric-card"><h1>{val}</h1><p>{label}</p></div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    tab_list, tab_match, tab_chart, tab_deadline, tab_monday, tab_table = st.tabs([
        "📋 Grant List", "🔍 Match by Document", "📊 Analytics", "📅 Deadline Calendar", "📌 Monday.com", "🗂 Raw Table"
    ])

    # ── Tab 1: Grant List ──
    with tab_list:
        if f.empty:
            st.info("No grants match the current filters.")
        else:
            st.markdown(f"### {len(f)} Grants")
            for _, row in f.iterrows():
                score = row["Score"]
                bar_color = match_color(score)
                url = row["Grant URL"]
                website_url = row.get("Website URL", "")
                dl_text, dl_class = deadline_label(row["Next Deadline"])
                rank = row.get("Rank", 0)
                rank_prefix = f"#{rank} · " if rank else ""
                with st.expander(f"{'⭐ ' if score >= 80 else ''}{rank_prefix}{row['Grant Name']} — {row['Funder']}", expanded=False):
                    c1, c2, c3 = st.columns([3, 2, 2])
                    with c1:
                        st.markdown(f"{score_pill_html(score)} {status_badge_html(row['Status'])}", unsafe_allow_html=True)
                        st.markdown(f'<div class="match-bar-wrap"><div class="match-bar" style="width:{score}%;background:{bar_color};"></div></div>', unsafe_allow_html=True)
                        st.markdown(f"**Funder:** {row['Funder']}")
                        if row["Funding Cycle"]: st.markdown(f"**Cycle:** {row['Funding Cycle']}")
                    with c2:
                        st.markdown(f'**Deadline:** <span class="{dl_class}">{dl_text}</span>', unsafe_allow_html=True)
                        if url.startswith("http"): st.markdown(f"[🔗 Grant URL]({url})")
                        if website_url.startswith("http"): st.markdown(f"[🌐 Website]({website_url})")
                    with c3:
                        st.markdown(f"**Match Score:** `{score:.1f}%`")
                    desc = row.get("Description", "").strip()
                    if desc:
                        st.markdown("---")
                        st.markdown("**Description:**")
                        desc_safe = (desc
                                     .replace("&", "&amp;")
                                     .replace("<", "&lt;")
                                     .replace(">", "&gt;"))
                        st.markdown(f'<div class="desc-box">{desc_safe}</div>', unsafe_allow_html=True)

    # ── Tab 2: Match by Document ──
    with tab_match:
        st.markdown("## 🔍 Match by Document")
        st.markdown(
            "Upload a document describing your organization, project, or mission. "
            "The app will score every grant in the current dataset by how well it matches your profile — "
            "no spreadsheet linking required."
        )

        supported_types = ["txt"]
        if HAS_PYPDF:
            supported_types.append("pdf")
        if HAS_DOCX:
            supported_types.append("docx")
        supported_types += ["csv"]

        profile_file = st.file_uploader(
            "Upload your organization profile",
            type=supported_types,
            help=f"Supported: {', '.join(t.upper() for t in supported_types)}. "
                 "Describe your org's mission, focus areas, past work, and priorities.",
        )

        if not HAS_PYPDF or not HAS_DOCX:
            missing = []
            if not HAS_PYPDF: missing.append("`pypdf` (for PDF)")
            if not HAS_DOCX:  missing.append("`python-docx` (for DOCX)")
            st.caption(f"ℹ️ Install {' and '.join(missing)} to enable those file types.")

        if profile_file is not None:
            with st.spinner("Extracting text from document…"):
                try:
                    profile_text = extract_text_from_file(profile_file)
                except Exception as e:
                    st.error(f"Could not read file: {e}")
                    profile_text = ""

            if profile_text.strip():
                word_count = len(profile_text.split())
                st.success(f"Document loaded — {word_count:,} words extracted.")

                with st.expander("Preview extracted text", expanded=False):
                    preview = profile_text[:2000] + ("…" if len(profile_text) > 2000 else "")
                    st.text(preview)

                with st.spinner("Computing match scores…"):
                    descriptions = df["Description"].fillna("").tolist()
                    # Combine grant name and funder into description for richer matching
                    combined = (
                        df["Grant Name"].fillna("") + " " +
                        df["Funder"].fillna("") + " " +
                        df["Description"].fillna("")
                    ).tolist()
                    raw_scores = compute_match_scores(profile_text, combined)

                matched_df = df.copy()
                matched_df["Doc Match %"] = [round(s, 1) for s in raw_scores]
                matched_df = matched_df.sort_values("Doc Match %", ascending=False)

                st.markdown("---")
                st.markdown(f"### Top Matches — {len(matched_df)} grants ranked")

                # Top-match summary bar chart
                top_n = matched_df.head(15).copy()
                fig_top = px.bar(
                    top_n,
                    x="Doc Match %",
                    y="Grant Name",
                    orientation="h",
                    color="Doc Match %",
                    color_continuous_scale=["#EF5350", "#FF9800", "#4CAF50"],
                    title="Top 15 Grants by Document Match Score",
                    template="plotly_dark",
                    text="Doc Match %",
                )
                fig_top.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
                fig_top.update_layout(
                    paper_bgcolor="#1A1D27", plot_bgcolor="#1A1D27",
                    coloraxis_showscale=False,
                    yaxis={"categoryorder": "total ascending"},
                    margin=dict(t=40, b=20, l=20, r=20),
                    xaxis_title="Doc Match %", yaxis_title="",
                )
                st.plotly_chart(fig_top, use_container_width=True)

                # Threshold filter
                min_score = st.slider(
                    "Minimum document match score to display",
                    0, 100, 30,
                    help="Hide grants below this match threshold.",
                )
                display_df = matched_df[matched_df["Doc Match %"] >= min_score]
                st.markdown(f"Showing **{len(display_df)}** grants above {min_score}% document match")

                for _, row in display_df.iterrows():
                    doc_score = row["Doc Match %"]
                    sheet_score = row["Score"]
                    bar_color = match_color(doc_score)
                    url = row["Grant URL"]
                    website_url = row.get("Website URL", "")
                    dl_text, dl_class = deadline_label(row["Next Deadline"])

                    with st.expander(
                        f"{'⭐ ' if doc_score >= 80 else ''}{row['Grant Name']} — {row['Funder']}",
                        expanded=False,
                    ):
                        c1, c2, c3 = st.columns([3, 2, 2])
                        with c1:
                            doc_color = match_color(doc_score)
                            st.markdown(
                                f'<span class="score-pill" style="background:{doc_color}22;color:{doc_color};border:1px solid {doc_color}55;">🔍 {doc_score:.0f}% doc match</span> '
                                f"{status_badge_html(row['Status'])}",
                                unsafe_allow_html=True,
                            )
                            st.markdown(f'<div class="match-bar-wrap"><div class="match-bar" style="width:{doc_score}%;background:{bar_color};"></div></div>', unsafe_allow_html=True)
                            st.markdown(f"**Funder:** {row['Funder']}")
                            if row["Funding Cycle"]: st.markdown(f"**Cycle:** {row['Funding Cycle']}")
                        with c2:
                            st.markdown(f'**Deadline:** <span class="{dl_class}">{dl_text}</span>', unsafe_allow_html=True)
                            if url.startswith("http"): st.markdown(f"[🔗 Grant URL]({url})")
                            if website_url.startswith("http"): st.markdown(f"[🌐 Website]({website_url})")
                        with c3:
                            st.markdown(f"**Doc Match:** `{doc_score:.1f}%`")
                            st.markdown(f"**Sheet Score:** `{sheet_score:.1f}%`")
                        desc = row.get("Description", "").strip()
                        if desc:
                            st.markdown("---")
                            st.markdown("**Description:**")
                            desc_safe = (desc
                                         .replace("&", "&amp;")
                                         .replace("<", "&lt;")
                                         .replace(">", "&gt;"))
                            st.markdown(f'<div class="desc-box">{desc_safe}</div>', unsafe_allow_html=True)

                # Download matched results
                st.markdown("---")
                export_cols = ["Grant Name", "Funder", "Doc Match %", "Score", "Status",
                               "Next Deadline", "Funding Cycle", "Grant URL", "Website URL", "Description"]
                export_df = display_df[[c for c in export_cols if c in display_df.columns]].copy()
                export_df["Next Deadline"] = display_df["_dl_date"].apply(
                    lambda d: d.isoformat() if d else "Rolling / TBD"
                )
                st.download_button(
                    "⬇️ Download matched results as CSV",
                    data=export_df.to_csv(index=False).encode("utf-8"),
                    file_name=f"doc_matched_grants_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )
            else:
                st.warning("Could not extract any text from the uploaded file. Please try a different file.")
        else:
            st.markdown("""
**How it works:**
1. Upload a TXT, PDF, DOCX, or CSV file describing your organization's mission, programs, and focus areas
2. The app analyzes the text and computes a similarity score for every grant based on keyword overlap
3. Grants are re-ranked by how well they match *your specific profile*
4. Download the results as a CSV

**Tips for best results:**
- Include your mission statement, program descriptions, and geographic focus
- Mention specific topics: conservation, health equity, climate resilience, etc.
- Longer, more detailed documents produce more accurate matches
- No Google Sheets connection needed — upload a grants CSV directly via the sidebar
""")

    # ── Tab 3: Analytics ──
    with tab_chart:
        if f.empty:
            st.info("No data to chart.")
        else:
            r1c1, r1c2 = st.columns(2)
            with r1c1:
                fig = px.histogram(f, x="Score", nbins=20, title="Match Score Distribution",
                                   color_discrete_sequence=["#4CAF50"], template="plotly_dark")
                fig.update_layout(paper_bgcolor="#1A1D27", plot_bgcolor="#1A1D27", bargap=0.05,
                                  xaxis_title="Match %", yaxis_title="# Grants", margin=dict(t=40, b=20, l=20, r=20))
                fig.add_vline(x=f["Score"].mean(), line_dash="dash", line_color="#FF9800",
                              annotation_text=f"Avg {f['Score'].mean():.0f}%", annotation_position="top right")
                st.plotly_chart(fig, use_container_width=True)
            with r1c2:
                sc = f["Status"].value_counts().reset_index(); sc.columns = ["Status", "Count"]
                colors = [STATUS_COLORS.get(s, ("#37474F", "#78909C"))[1] for s in sc["Status"]]
                fig2 = go.Figure(go.Pie(labels=sc["Status"], values=sc["Count"], hole=0.55,
                                        marker_colors=colors, textinfo="label+percent"))
                fig2.update_layout(title="Grants by Status", paper_bgcolor="#1A1D27", plot_bgcolor="#1A1D27",
                                   font_color="#FAFAFA", showlegend=False, margin=dict(t=40, b=20, l=20, r=20),
                                   template="plotly_dark")
                st.plotly_chart(fig2, use_container_width=True)
            r2c1, r2c2 = st.columns(2)
            with r2c1:
                tf = (f[f["Funder"] != ""].groupby("Funder")["Score"]
                      .agg(["mean", "count"]).reset_index()
                      .rename(columns={"mean": "Avg Score", "count": "# Grants"})
                      .sort_values("Avg Score", ascending=False).head(15))
                fig3 = px.bar(tf, x="Avg Score", y="Funder", orientation="h", color="Avg Score",
                              color_continuous_scale=["#EF5350", "#FF9800", "#4CAF50"],
                              title="Top Funders by Avg Match Score", template="plotly_dark",
                              hover_data={"# Grants": True}, text="Avg Score")
                fig3.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
                fig3.update_layout(paper_bgcolor="#1A1D27", plot_bgcolor="#1A1D27", coloraxis_showscale=False,
                                   yaxis={"categoryorder": "total ascending"}, margin=dict(t=40, b=20, l=20, r=20),
                                   xaxis_title="Avg Match %", yaxis_title="")
                st.plotly_chart(fig3, use_container_width=True)
            with r2c2:
                sd = f[f["Next Deadline"].notna()].copy()
                if not sd.empty:
                    sd["Days Until"] = sd["_dl_date"].apply(lambda d: (d - today).days if d else None)
                    fig4 = px.scatter(sd, x="Days Until", y="Score", color="Score",
                                      color_continuous_scale=["#EF5350", "#FF9800", "#4CAF50"], size="Score",
                                      hover_name="Grant Name", hover_data={"Funder": True, "Status": True, "Score": ":.1f"},
                                      title="Match Score vs Days Until Deadline", template="plotly_dark",
                                      labels={"Days Until": "Days Until Deadline", "Score": "Match %"})
                    fig4.update_layout(paper_bgcolor="#1A1D27", plot_bgcolor="#1A1D27", coloraxis_showscale=False,
                                       margin=dict(t=40, b=20, l=20, r=20))
                    fig4.add_vline(x=0, line_dash="dash", line_color="#EF5350", annotation_text="Today")
                    fig4.add_vline(x=30, line_dash="dot", line_color="#FF9800", annotation_text="30d")
                    st.plotly_chart(fig4, use_container_width=True)

    # ── Tab 4: Deadline Calendar ──
    with tab_deadline:
        dated = f[f["Next Deadline"].notna()].copy().sort_values("Next Deadline")
        if dated.empty:
            st.info("No dated deadlines in current filter set.")
        else:
            dated["Days Until"] = dated["_dl_date"].apply(lambda d: (d - today).days if d else None)
            dated["Label"] = dated.apply(lambda r: f"{r['Grant Name'][:40]} | {r['Score']:.0f}%", axis=1)
            today_str = today.isoformat()
            fig6 = px.timeline(
                dated.assign(Start=today_str, Finish=dated["_dl_date"].apply(lambda d: d.isoformat() if d else today_str)),
                x_start="Start", x_end="Finish", y="Label", color="Score",
                color_continuous_scale=["#EF5350", "#FF9800", "#4CAF50"],
                title="Grant Deadline Timeline", template="plotly_dark",
                hover_name="Grant Name", hover_data={"Funder": True, "Status": True, "Score": ":.0f", "Start": False, "Finish": False}
            )
            fig6.update_layout(paper_bgcolor="#1A1D27", plot_bgcolor="#1A1D27",
                               coloraxis_colorbar_title="Match %", yaxis={"categoryorder": "total ascending"},
                               height=max(400, len(dated) * 30), margin=dict(t=40, b=20, l=20, r=20),
                               xaxis_title="", yaxis_title="")
            fig6.add_vline(x=today_ts.timestamp() * 1000, line_dash="dash", line_color="#FF9800", annotation_text="Today")
            st.plotly_chart(fig6, use_container_width=True)
            urgent = dated[dated["Days Until"] <= 30].sort_values("Days Until")
            if not urgent.empty:
                st.markdown("### ⚠️ Due within 30 days")
                for _, row in urgent.iterrows():
                    days = int(row["Days Until"]); urgency = "🔴" if days <= 7 else "🟡"
                    dl_text, _ = deadline_label(row["Next Deadline"]); url = row["Grant URL"]
                    link = f"[{row['Grant Name']}]({url})" if url.startswith("http") else row["Grant Name"]
                    st.markdown(f"{urgency} **{link}** — {row['Funder']} — {score_pill_html(row['Score'])} — {dl_text}", unsafe_allow_html=True)

    # ── Tab 5: Monday.com ──
    with tab_monday:
        st.markdown("## 📌 Push Grants to Monday.com")
        st.markdown("Push your filtered grants to a Monday.com board as items — then track status, assign owners, and set reminders natively in Monday.")

        # API key: env var takes precedence, then user input
        default_key = os.environ.get("MONDAY_API_KEY", "")
        col_key, col_link = st.columns([4, 1])
        with col_key:
            api_key_input = st.text_input(
                "Monday.com API Key", value=default_key, type="password",
                placeholder="Paste your Monday.com API token…",
                help="Set MONDAY_API_KEY as an environment variable to avoid re-entering."
            )
        with col_link:
            st.markdown("<br>", unsafe_allow_html=True)
            st.caption("[Get API key ↗](https://monday.com/developers/v2#authentication-section)")

        if api_key_input:
            try:
                with st.spinner("Connecting to Monday.com…"):
                    boards = get_monday_boards(api_key_input)
                if not boards:
                    st.warning("No boards found in your Monday.com account.")
                else:
                    board_options = {b["name"]: b["id"] for b in boards}
                    selected_board = st.selectbox("Select target board", list(board_options.keys()))
                    board_id = board_options[selected_board]

                    st.info(f"**{len(f)} grant(s)** from the current filter will be pushed to **{selected_board}**. Each grant becomes a Monday.com item with a detailed comment containing score, deadline, funder, and description.")

                    if st.button("🚀 Push All Filtered Grants to Monday.com", type="primary", use_container_width=True):
                        success = 0; errors = []
                        prog = st.progress(0, text="Starting…")
                        for i, (_, row) in enumerate(f.iterrows()):
                            try:
                                push_grant_to_monday(api_key_input, board_id, row)
                                success += 1
                            except Exception as e:
                                errors.append(f"{row['Grant Name']}: {e}")
                            prog.progress((i + 1) / len(f), text=f"Pushed {i + 1} / {len(f)}…")
                        prog.empty()
                        if success:
                            st.success(f"✅ Successfully pushed **{success}** grant(s) to **{selected_board}**!")
                        if errors:
                            with st.expander(f"⚠️ {len(errors)} error(s)"):
                                for e in errors: st.text(e)
            except Exception as e:
                st.error(f"Monday.com connection failed: {e}")
        else:
            st.info("Enter your Monday.com API key above to connect.")
            st.markdown("""
**Why Monday.com for tracking?**
- Native status columns with color-coded labels (Researching → Applied → Awarded…)
- Team assignments, @mentions, and comments on each grant
- Deadline reminders and automation recipes
- Mobile app for on-the-go updates
- Dashboard views for pipeline overview

**What gets pushed:**
Each grant becomes a Monday.com item with its name as the title and a comment containing match score, funder, deadline, status, URLs, and description.
""")

    # ── Tab 6: Raw Table ──
    with tab_table:
        disp_cols = ["Rank", "Score", "Grant Name", "Funder", "Status", "Next Deadline",
                     "Funding Cycle", "Grant URL", "Website URL"]
        disp = f[[c for c in disp_cols if c in f.columns]].copy()
        disp["Score"] = disp["Score"].apply(lambda x: f"{x:.1f}%")
        disp["Next Deadline"] = f["_dl_date"].apply(lambda d: d.isoformat() if d else "Rolling / TBD")
        st.dataframe(disp, use_container_width=True, hide_index=True, column_config={
            "Rank":        st.column_config.NumberColumn("Rank"),
            "Grant URL":   st.column_config.LinkColumn("Grant URL",   display_text="🔗 Link"),
            "Website URL": st.column_config.LinkColumn("Website URL", display_text="🌐 Link"),
            "Score":       st.column_config.TextColumn("Match %"),
        })
        st.download_button(
            "⬇️ Download filtered data as CSV",
            data=f.to_csv(index=False).encode("utf-8"),
            file_name=f"grants_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )


def demo_data():
    today = date.today()
    rows = [
        [1, 92, "Climate Resilience Fund", "Bezos Earth Fund",
         (pd.Timestamp(today) + pd.Timedelta(days=25)).strftime("%Y-%m-%d"),
         "Active", "Annual", "https://example.com/1", "https://bezos.com",
         "Supports innovative approaches to climate resilience in coastal communities.\n\nFunds projects that demonstrate measurable impact on community adaptation to changing climate conditions. Priority given to Indigenous-led initiatives and frontline communities."],
        [2, 85, "Green Infrastructure Grant", "Patagonia Environmental",
         (pd.Timestamp(today) + pd.Timedelta(days=60)).strftime("%Y-%m-%d"),
         "Researching", "Biannual", "https://example.com/2", "https://patagonia.com",
         "Funding for urban green infrastructure projects including green roofs, rain gardens, and urban tree canopy expansion. Focus on equity and underserved communities."],
        [3, 78, "Community Health Initiative", "Robert Wood Johnson",
         (pd.Timestamp(today) + pd.Timedelta(days=90)).strftime("%Y-%m-%d"),
         "Applied", "Rolling", "https://example.com/3", "https://rwjf.org",
         "Improving health outcomes in rural communities through preventive care and mental health services."],
        [4, 65, "Watershed Restoration", "Gordon & Betty Moore",
         (pd.Timestamp(today) - pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
         "Invited", "Annual", "https://example.com/4", "https://moore.org",
         "Protecting critical watershed ecosystems through strategic land conservation and restoration."],
        [5, 88, "Biodiversity Conservation", "Wilburforce Foundation",
         (pd.Timestamp(today) + pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
         "Awarded", "Annual", "https://example.com/7", "https://wilburforce.org",
         "Protecting endangered species and critical habitat across the Rocky Mountain region."],
    ]
    return normalize_df(pd.DataFrame(rows, columns=EXPECTED_COLS))


if __name__ == "__main__":
    main()
