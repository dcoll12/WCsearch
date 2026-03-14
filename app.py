import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import json
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials

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
</style>""", unsafe_allow_html=True)

SHEET_ID = "1ixKVIO7xeyuGL9n4Afnz10lJ0-Pyxlsm"
EXPECTED_COLS = ["Rank","Score","Grant Name","Grant ID","Funder","Next Deadline","Status","Is Custom","Rolling","Funding Cycle","Grant URL","Description","Locations"]
STATUS_COLORS = {
    "Active": ("#1B5E20","#66BB6A"), "Invited": ("#0D47A1","#42A5F5"),
    "Applied": ("#E65100","#FFA726"), "Awarded": ("#4A148C","#CE93D8"),
    "Declined": ("#B71C1C","#EF9A9A"), "Researching": ("#1A237E","#90CAF9"),
    "Not a fit": ("#37474F","#78909C"), "": ("#37474F","#78909C"),
}

@st.cache_data(ttl=300, show_spinner=False)
def load_from_public_csv(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    return pd.read_csv(url)

def load_from_service_account(sheet_id, creds_json):
    scopes = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(creds)
    return pd.DataFrame(gc.open_by_key(sheet_id).get_worksheet(0).get_all_records())

def normalize_df(df):
    for col in EXPECTED_COLS:
        if col not in df.columns:
            df[col] = ""
    df["Score"] = pd.to_numeric(df["Score"], errors="coerce").fillna(0)
    df["Rank"]  = pd.to_numeric(df["Rank"],  errors="coerce").fillna(0)
    mx = df["Score"].max()
    df["Score"] = ((df["Score"] / mx * 100) if mx > 100 else df["Score"]).round(1)

    # Parse dates then store as plain Python date objects to avoid pandas dtype issues
    parsed = pd.to_datetime(df["Next Deadline"], errors="coerce", utc=True)
    df["Next Deadline"] = parsed.dt.tz_convert(None)
    df["_dl_date"] = df["Next Deadline"].apply(lambda x: x.date() if pd.notna(x) else None)

    for col in ("Is Custom","Rolling"):
        df[col] = df[col].astype(str).str.strip().str.lower().isin(["true","yes","1","x","✓"])
    for col in ("Grant Name","Funder","Status","Locations","Description","Grant ID"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["Grant URL"] = df["Grant URL"].fillna("").astype(str).str.strip()
    return df

def match_color(s):
    return "#4CAF50" if s>=80 else "#8BC34A" if s>=60 else "#FF9800" if s>=40 else "#EF5350"

def deadline_label(dt):
    if pd.isna(dt): return "Rolling / TBD","rolling"
    days = (dt.date() - date.today()).days
    if days < 0:   return f"Closed ({dt.strftime('%b %d')})","urgent"
    if days <= 14: return f"{days}d left ({dt.strftime('%b %d')})","urgent"
    if days <= 60: return f"{days}d left ({dt.strftime('%b %d')})","soon"
    return dt.strftime("%b %d, %Y"),"upcoming"

def status_badge_html(s):
    bg,fg = STATUS_COLORS.get(s,("#37474F","#78909C"))
    return f'<span class="status-badge" style="background:{bg};color:{fg};">{s or "Unknown"}</span>'

def score_pill_html(score):
    c = match_color(score)
    return f'<span class="score-pill" style="background:{c}22;color:{c};border:1px solid {c}55;">{score:.0f}% match</span>'

def main():
    with st.sidebar:
        st.markdown("# 🌿 Grant Tracker\n---")
        st.markdown('<div class="sidebar-section">Data Source</div>', unsafe_allow_html=True)
        data_mode = st.radio("Connect via",["Public sheet (CSV)","Service account (private sheet)"],index=0)
        creds_json = None
        if data_mode == "Service account (private sheet)":
            uploaded = st.file_uploader("Service account key (.json)", type="json")
            if uploaded:
                try: creds_json = json.load(uploaded)
                except: st.error("Invalid JSON file.")
        if st.button("🔄 Refresh data", use_container_width=True):
            st.cache_data.clear(); st.rerun()
        st.markdown("---")
        st.markdown('<div class="sidebar-section">Filters</div>', unsafe_allow_html=True)

    with st.spinner("Loading grant data…"):
        try:
            raw = load_from_public_csv(SHEET_ID) if data_mode == "Public sheet (CSV)" else load_from_service_account(SHEET_ID, creds_json)
            df = normalize_df(raw.copy())
        except Exception as e:
            st.error(f"**Could not load data:** {e}\n\nMake sure the sheet is shared as 'Anyone with the link can view'.")
            df = demo_data()

    # ── Sidebar filters ──
    with st.sidebar:
        mn,mx2 = int(df["Score"].min()), int(df["Score"].max())
        score_range = st.slider("Match score %", mn, max(mx2,1), (mn, max(mx2,1)))
        selected_statuses = st.multiselect("Status", sorted(df["Status"].unique()), default=sorted(df["Status"].unique()))
        all_locs = sorted(set(l.strip() for ls in df["Locations"] for l in ls.split(",") if l.strip()))
        selected_locs = st.multiselect("Locations", all_locs, default=[])
        st.markdown('<div class="sidebar-section">Deadline</div>', unsafe_allow_html=True)
        deadline_filter = st.selectbox("Show deadlines",["All","Next 30 days","Next 90 days","Overdue","Rolling / TBD"])
        st.markdown('<div class="sidebar-section">Search</div>', unsafe_allow_html=True)
        search_query = st.text_input("Search grants", placeholder="Keyword, funder, location…")
        st.markdown('<div class="sidebar-section">Sort</div>', unsafe_allow_html=True)
        sort_by = st.selectbox("Sort by",["Score (high→low)","Score (low→high)","Deadline (soonest)","Rank","Funder A-Z"])

    # ── Filtering — all date comparisons use plain Python date objects ──
    f = df.copy()
    f = f[(f["Score"]>=score_range[0])&(f["Score"]<=score_range[1])]
    if selected_statuses: f = f[f["Status"].isin(selected_statuses)]
    if selected_locs:     f = f[f["Locations"].apply(lambda x: any(l in x for l in selected_locs))]

    today = date.today()  # plain Python date, no pandas dtype
    today_ts = pd.Timestamp(today)

    def gte(d,r): return d is not None and d >= r
    def lte(d,r): return d is not None and d <= r
    def lt(d,r):  return d is not None and d < r

    if deadline_filter == "Next 30 days":
        from datetime import timedelta
        cut = today + timedelta(days=30)
        f = f[f["_dl_date"].apply(lambda d: gte(d,today) and lte(d,cut))]
    elif deadline_filter == "Next 90 days":
        from datetime import timedelta
        cut = today + timedelta(days=90)
        f = f[f["_dl_date"].apply(lambda d: gte(d,today) and lte(d,cut))]
    elif deadline_filter == "Overdue":
        f = f[f["_dl_date"].apply(lambda d: lt(d,today))]
    elif deadline_filter == "Rolling / TBD":
        f = f[f["_dl_date"].isna() | f["Rolling"]]

    if search_query:
        q = search_query.lower()
        f = f[f["Grant Name"].str.lower().str.contains(q,na=False)|f["Funder"].str.lower().str.contains(q,na=False)|f["Description"].str.lower().str.contains(q,na=False)|f["Locations"].str.lower().str.contains(q,na=False)]

    sort_map = {"Score (high→low)":("Score",False),"Score (low→high)":("Score",True),"Deadline (soonest)":("Next Deadline",True),"Rank":("Rank",True),"Funder A-Z":("Funder",True)}
    col_s,asc_s = sort_map.get(sort_by,("Score",False))
    f = f.sort_values(col_s, ascending=asc_s, na_position="last")

    # ── Header ──
    st.markdown("# 🌿 Grant Research Dashboard")
    st.markdown(f"Showing **{len(f)}** of **{len(df)}** grants · Last refreshed: {datetime.now().strftime('%b %d, %Y %H:%M')}")
    st.markdown("---")

    # ── KPIs ──
    from datetime import timedelta
    c1,c2,c3,c4,c5 = st.columns(5)
    cut30 = today + timedelta(days=30)
    kpis = [
        (c1, str(len(df)), "Total Grants"),
        (c2, f"{df['Score'].mean():.0f}%", "Avg Match Score"),
        (c3, str(len(df[df["Score"]>=70])), "High Matches (≥70%)"),
        (c4, str(len(df[df["_dl_date"].apply(lambda d: gte(d,today) and lte(d,cut30))])), "Due in 30 Days"),
        (c5, str(len(df[df["Status"].str.lower()=="awarded"])), "Awarded"),
    ]
    for col,val,label in kpis:
        with col:
            st.markdown(f'<div class="metric-card"><h1>{val}</h1><p>{label}</p></div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    tab_list,tab_chart,tab_deadline,tab_table = st.tabs(["📋 Grant List","📊 Analytics","📅 Deadline Calendar","🗂 Raw Table"])

    # ── Tab 1: Grant List ──
    with tab_list:
        if f.empty:
            st.info("No grants match the current filters.")
        else:
            st.markdown(f"### {len(f)} Grants")
            for _,row in f.iterrows():
                score = row["Score"]; bar_color = match_color(score); url = row["Grant URL"]
                dl_text,dl_class = deadline_label(row["Next Deadline"])
                rolling_tag = ' <span style="color:#42A5F5;font-size:0.75rem;">↻ Rolling</span>' if row["Rolling"] else ""
                custom_tag  = ' <span style="color:#CE93D8;font-size:0.75rem;">★ Custom</span>'  if row["Is Custom"] else ""
                with st.expander(f"{'⭐ ' if score>=80 else ''}{row['Grant Name']} — {row['Funder']}", expanded=False):
                    c1,c2,c3 = st.columns([3,2,2])
                    with c1:
                        st.markdown(f"{score_pill_html(score)} {status_badge_html(row['Status'])}{rolling_tag}{custom_tag}", unsafe_allow_html=True)
                        st.markdown(f'<div class="match-bar-wrap"><div class="match-bar" style="width:{score}%;background:{bar_color};"></div></div>', unsafe_allow_html=True)
                        st.markdown(f"**Funder:** {row['Funder']}")
                        if row["Locations"]: st.markdown(f"**Locations:** {row['Locations']}")
                        if row["Funding Cycle"]: st.markdown(f"**Cycle:** {row['Funding Cycle']}")
                    with c2:
                        if row["Grant ID"]: st.markdown(f"**Grant ID:** `{row['Grant ID']}`")
                        st.markdown(f'**Deadline:** <span class="{dl_class}">{dl_text}</span>', unsafe_allow_html=True)
                        if url.startswith("http"): st.markdown(f"[🔗 View Grant]({url})")
                    with c3:
                        st.markdown(f"**Match Score:** `{score:.1f}%`")
                        if row["Rank"]: st.markdown(f"**Rank:** #{int(row['Rank'])}")
                    if row["Description"]:
                        st.markdown("---"); st.markdown(f"**Description:**"); st.markdown(row["Description"])

    # ── Tab 2: Analytics ──
    with tab_chart:
        if f.empty:
            st.info("No data to chart.")
        else:
            r1c1,r1c2 = st.columns(2)
            with r1c1:
                fig = px.histogram(f,x="Score",nbins=20,title="Match Score Distribution",color_discrete_sequence=["#4CAF50"],template="plotly_dark")
                fig.update_layout(paper_bgcolor="#1A1D27",plot_bgcolor="#1A1D27",bargap=0.05,xaxis_title="Match %",yaxis_title="# Grants",margin=dict(t=40,b=20,l=20,r=20))
                fig.add_vline(x=f["Score"].mean(),line_dash="dash",line_color="#FF9800",annotation_text=f"Avg {f['Score'].mean():.0f}%",annotation_position="top right")
                st.plotly_chart(fig,use_container_width=True)
            with r1c2:
                sc = f["Status"].value_counts().reset_index(); sc.columns=["Status","Count"]
                colors=[STATUS_COLORS.get(s,("#37474F","#78909C"))[1] for s in sc["Status"]]
                fig2 = go.Figure(go.Pie(labels=sc["Status"],values=sc["Count"],hole=0.55,marker_colors=colors,textinfo="label+percent"))
                fig2.update_layout(title="Grants by Status",paper_bgcolor="#1A1D27",plot_bgcolor="#1A1D27",font_color="#FAFAFA",showlegend=False,margin=dict(t=40,b=20,l=20,r=20),template="plotly_dark")
                st.plotly_chart(fig2,use_container_width=True)
            r2c1,r2c2 = st.columns(2)
            with r2c1:
                tf=(f[f["Funder"]!=""].groupby("Funder")["Score"].agg(["mean","count"]).reset_index().rename(columns={"mean":"Avg Score","count":"# Grants"}).sort_values("Avg Score",ascending=False).head(15))
                fig3=px.bar(tf,x="Avg Score",y="Funder",orientation="h",color="Avg Score",color_continuous_scale=["#EF5350","#FF9800","#4CAF50"],title="Top Funders by Avg Match Score",template="plotly_dark",hover_data={"# Grants":True},text="Avg Score")
                fig3.update_traces(texttemplate="%{text:.0f}%",textposition="outside")
                fig3.update_layout(paper_bgcolor="#1A1D27",plot_bgcolor="#1A1D27",coloraxis_showscale=False,yaxis={"categoryorder":"total ascending"},margin=dict(t=40,b=20,l=20,r=20),xaxis_title="Avg Match %",yaxis_title="")
                st.plotly_chart(fig3,use_container_width=True)
            with r2c2:
                sd=f[f["Next Deadline"].notna()].copy()
                if not sd.empty:
                    sd["Days Until"]=sd["_dl_date"].apply(lambda d:(d-today).days if d else None)
                    fig4=px.scatter(sd,x="Days Until",y="Score",color="Score",color_continuous_scale=["#EF5350","#FF9800","#4CAF50"],size="Score",hover_name="Grant Name",hover_data={"Funder":True,"Status":True,"Score":":.1f"},title="Match Score vs Days Until Deadline",template="plotly_dark",labels={"Days Until":"Days Until Deadline","Score":"Match %"})
                    fig4.update_layout(paper_bgcolor="#1A1D27",plot_bgcolor="#1A1D27",coloraxis_showscale=False,margin=dict(t=40,b=20,l=20,r=20))
                    fig4.add_vline(x=0,line_dash="dash",line_color="#EF5350",annotation_text="Today")
                    fig4.add_vline(x=30,line_dash="dot",line_color="#FF9800",annotation_text="30d")
                    st.plotly_chart(fig4,use_container_width=True)
            loc_df=pd.DataFrame([{"Location":l.strip(),"Score":row["Score"]} for _,row in f.iterrows() for l in row["Locations"].split(",") if l.strip()])
            if not loc_df.empty:
                la=loc_df.groupby("Location").agg(Count=("Score","count"),Avg_Score=("Score","mean")).reset_index().sort_values("Count",ascending=False).head(20)
                fig5=px.bar(la,x="Location",y="Count",color="Avg_Score",color_continuous_scale=["#EF5350","#FF9800","#4CAF50"],title="Grant Coverage by Location",template="plotly_dark",hover_data={"Avg_Score":":.1f"})
                fig5.update_layout(paper_bgcolor="#1A1D27",plot_bgcolor="#1A1D27",coloraxis_colorbar_title="Avg Match %",xaxis_tickangle=-35,margin=dict(t=40,b=80,l=20,r=20),xaxis_title="",yaxis_title="# Grants")
                st.plotly_chart(fig5,use_container_width=True)

    # ── Tab 3: Deadline Calendar ──
    with tab_deadline:
        dated=f[f["Next Deadline"].notna()].copy().sort_values("Next Deadline")
        if dated.empty:
            st.info("No dated deadlines in current filter set.")
        else:
            dated["Days Until"]=dated["_dl_date"].apply(lambda d:(d-today).days if d else None)
            dated["Label"]=dated.apply(lambda r:f"{r['Grant Name'][:40]} | {r['Score']:.0f}%",axis=1)
            today_str=today.isoformat()
            fig6=px.timeline(dated.assign(Start=today_str,Finish=dated["_dl_date"].apply(lambda d:d.isoformat() if d else today_str)),x_start="Start",x_end="Finish",y="Label",color="Score",color_continuous_scale=["#EF5350","#FF9800","#4CAF50"],title="Grant Deadline Timeline",template="plotly_dark",hover_name="Grant Name",hover_data={"Funder":True,"Status":True,"Score":":.0f","Start":False,"Finish":False})
            fig6.update_layout(paper_bgcolor="#1A1D27",plot_bgcolor="#1A1D27",coloraxis_colorbar_title="Match %",yaxis={"categoryorder":"total ascending"},height=max(400,len(dated)*30),margin=dict(t=40,b=20,l=20,r=20),xaxis_title="",yaxis_title="")
            fig6.add_vline(x=today_ts.timestamp()*1000,line_dash="dash",line_color="#FF9800",annotation_text="Today")
            st.plotly_chart(fig6,use_container_width=True)
            urgent=dated[dated["Days Until"]<=30].sort_values("Days Until")
            if not urgent.empty:
                st.markdown("### ⚠️ Due within 30 days")
                for _,row in urgent.iterrows():
                    days=int(row["Days Until"]); urgency="🔴" if days<=7 else "🟡"
                    dl_text,_=deadline_label(row["Next Deadline"]); url=row["Grant URL"]
                    link=f"[{row['Grant Name']}]({url})" if url.startswith("http") else row["Grant Name"]
                    st.markdown(f"{urgency} **{link}** — {row['Funder']} — {score_pill_html(row['Score'])} — {dl_text}",unsafe_allow_html=True)

    # ── Tab 4: Raw Table ──
    with tab_table:
        disp_cols=["Rank","Score","Grant Name","Funder","Status","Next Deadline","Locations","Rolling","Is Custom","Funding Cycle","Grant URL"]
        disp=f[[c for c in disp_cols if c in f.columns]].copy()
        disp["Score"]=disp["Score"].apply(lambda x:f"{x:.1f}%")
        disp["Next Deadline"]=f["_dl_date"].apply(lambda d:d.isoformat() if d else "Rolling / TBD")
        st.dataframe(disp,use_container_width=True,hide_index=True,column_config={"Grant URL":st.column_config.LinkColumn("Grant URL",display_text="🔗 Link"),"Score":st.column_config.TextColumn("Match %"),"Rolling":st.column_config.CheckboxColumn("Rolling"),"Is Custom":st.column_config.CheckboxColumn("Custom")})
        st.download_button("⬇️ Download filtered data as CSV",data=f.to_csv(index=False).encode("utf-8"),file_name=f"grants_{datetime.now().strftime('%Y%m%d')}.csv",mime="text/csv")

def demo_data():
    today=date.today(); rows=[
        [1,92,"Climate Resilience Fund","G001","Bezos Earth Fund",(pd.Timestamp(today)+pd.Timedelta(days=25)).strftime("%Y-%m-%d"),"Active",False,False,"Annual","https://example.com/1","Supports innovative approaches to climate resilience.","California, Oregon"],
        [2,85,"Green Infrastructure Grant","G002","Patagonia Environmental",(pd.Timestamp(today)+pd.Timedelta(days=60)).strftime("%Y-%m-%d"),"Researching",True,False,"Biannual","https://example.com/2","Funding for urban green infrastructure projects.","Nationwide"],
        [3,78,"Community Health Initiative","G003","Robert Wood Johnson",(pd.Timestamp(today)+pd.Timedelta(days=90)).strftime("%Y-%m-%d"),"Applied",False,True,"Rolling","https://example.com/3","Improving health outcomes in rural communities.","Texas, New Mexico"],
        [4,65,"Watershed Restoration","G004","Gordon & Betty Moore",(pd.Timestamp(today)-pd.Timedelta(days=5)).strftime("%Y-%m-%d"),"Invited",False,False,"Annual","https://example.com/4","Protecting critical watershed ecosystems.","Pacific Northwest"],
        [5,88,"Biodiversity Conservation","G007","Wilburforce Foundation",(pd.Timestamp(today)+pd.Timedelta(days=10)).strftime("%Y-%m-%d"),"Active",True,False,"Annual","https://example.com/7","Protecting endangered species and critical habitat.","Rocky Mountains"],
    ]
    return normalize_df(pd.DataFrame(rows,columns=EXPECTED_COLS))

if __name__=="__main__":
    main()
