import sqlite3
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Airtel Telecom Analytics", layout="wide")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DB_ZIP = PROJECT_ROOT / "data" / "airtel.db.zip"
DEPLOY_DB_PATH = PROJECT_ROOT / "data" / "airtel.db"

if (DEPLOY_DB_ZIP.exists()
        and (not DEPLOY_DB_PATH.exists() or DEPLOY_DB_PATH.stat().st_size == 0)):
    try:
        with zipfile.ZipFile(DEPLOY_DB_ZIP, "r") as archive:
            with archive.open("airtel.db", "r") as source:
                with DEPLOY_DB_PATH.open("wb") as target:
                    shutil.copyfileobj(source, target)
    except (zipfile.BadZipFile, KeyError, OSError):
        pass

DB_PATH = next(
    (path for path in (
        PROJECT_ROOT / "airtel.db",
        PROJECT_ROOT / "data" / "raw" / "airtel.db",
        PROJECT_ROOT / "data" / "airtel.db",
        PROJECT_ROOT / "notebook" / "airtel.db",
    ) if path.exists() and path.stat().st_size > 0),
    PROJECT_ROOT / "data" / "raw" / "airtel.db",
)

# Enter the validated T7 result from your analysis notebook. Do not guess.
T7_P_VALUE = None        # e.g. a float
T7_RESULT = None         # one short sentence describing the association
T7_ALPHA = 0.05

RED, DARK_RED, PINK, GREY, BLUE = (
    "#E40000", "#9B0000", "#F7A8B0", "#8A8F98", "#0072CE",
)
PIE_COLORS = [RED, BLUE, DARK_RED, "#4C9BDD", PINK, GREY]

# CHANGE THIS to match your database (table and column names).
# Everything below reads only these two views-as-CTEs.
BASE = """
WITH s AS (
    SELECT customer_id AS subscriber_id,
           connection_type,
           region,
           circle_name AS circle,
           is_churned AS churned
    FROM customer_features
    WHERE (:conn = 'All' OR connection_type = :conn)
      AND (:region = 'All' OR region = :region)
),
t AS (
    SELECT complaint_id AS ticket_id,
           customer_id AS subscriber_id,
           category,
           CASE WHEN is_resolved = 1 THEN 'closed' ELSE 'open' END AS status,
           complaint_date AS created_date
    FROM complaints
)
"""


@st.cache_data
def q(sql, params=None):
    with sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True) as con:
        return pd.read_sql_query(sql, con, params=params or {})


def card(title, value, note):
    st.markdown(
        f'<div class="card"><div class="ct">{title}</div>'
        f'<div class="cv">{value}</div><div class="cn">{note}</div></div>',
        unsafe_allow_html=True,
    )


def chart_selector(chart_id, default, options):
    return st.selectbox(
        "Chart type",
        options,
        index=options.index(default),
        key=f"chart_type_{chart_id}",
        label_visibility="collapsed",
    )


def xy_chart(data, chart_type, x_col, y_col, color, hovertemplate,
             custom_cols=(), text=None, horizontal_hovertemplate=None,
             pie_hovertemplate=None):
    required_cols = [y_col] if chart_type == "Histogram" else [x_col, y_col]
    plot_data = data.dropna(subset=required_cols)
    if plot_data.empty:
        return go.Figure()
    if chart_type in ("Pie Chart", "Donut Chart") and not plot_data[y_col].gt(0).any():
        return go.Figure()
    if text is not None:
        text = pd.Series(text, index=data.index).loc[plot_data.index].tolist()

    customdata = plot_data[list(custom_cols)].to_numpy() if custom_cols else None
    hover = (
        horizontal_hovertemplate
        if chart_type == "Horizontal Bar Chart" and horizontal_hovertemplate
        else hovertemplate
    )
    if chart_type == "Histogram":
        fig = go.Figure(go.Histogram(
            x=plot_data[y_col],
            marker_color=color,
            name=y_col,
            hovertemplate=f"{y_col}: %{{x}}<br>Records: %{{y}}<extra></extra>",
        ))
    elif chart_type in ("Pie Chart", "Donut Chart"):
        fig = go.Figure(go.Pie(
            labels=plot_data[x_col],
            values=plot_data[y_col],
            customdata=customdata,
            hole=0.55 if chart_type == "Donut Chart" else 0,
            marker=dict(colors=[
                PIE_COLORS[index % len(PIE_COLORS)]
                for index in range(len(plot_data))
            ]),
            hovertemplate=(
                pie_hovertemplate
                or f"%{{label}}<br>{y_col}: %{{value}}<extra></extra>"
            ),
        ))
    elif chart_type == "Horizontal Bar Chart":
        fig = go.Figure(go.Bar(
            x=plot_data[y_col], y=plot_data[x_col], orientation="h",
            marker_color=color, text=text,
            textposition="auto" if text is not None else None,
            customdata=customdata, hovertemplate=hover,
        ))
        fig.update_yaxes(autorange="reversed")
    elif chart_type == "Line Chart":
        fig = go.Figure(go.Scatter(
            x=plot_data[x_col], y=plot_data[y_col],
            mode="lines+markers+text" if text is not None else "lines+markers",
            line=dict(color=color, width=3), text=text,
            textposition="top center" if text is not None else None,
            customdata=customdata,
            hovertemplate=hover,
        ))
    elif chart_type == "Area Chart":
        fig = go.Figure(go.Scatter(
            x=plot_data[x_col], y=plot_data[y_col],
            mode="lines+markers+text" if text is not None else "lines+markers",
            fill="tozeroy", line=dict(color=color, width=2),
            text=text, textposition="top center" if text is not None else None,
            customdata=customdata, hovertemplate=hover,
        ))
    elif chart_type == "Scatter Plot":
        fig = go.Figure(go.Scatter(
            x=plot_data[x_col], y=plot_data[y_col], mode="markers",
            marker=dict(color=color, size=10), text=text, customdata=customdata,
            hovertemplate=hover,
        ))
    else:
        fig = go.Figure(go.Bar(
            x=plot_data[x_col], y=plot_data[y_col], marker_color=color,
            text=text, textposition="auto" if text is not None else None,
            customdata=customdata, hovertemplate=hover,
        ))
    return fig


def status_chart(data, chart_type):
    fig = go.Figure()
    colors = [("o", "Open", RED), ("c", "Closed", PINK)]
    if chart_type == "Histogram":
        for column, label, color in colors:
            fig.add_trace(go.Histogram(
                x=data[column], name=label, marker_color=color,
                hovertemplate=f"{label} complaints: %{{x}}<br>Circles: %{{y}}<extra></extra>",
            ))
        fig.update_layout(barmode="overlay")
        return fig

    for index, (column, label, color) in enumerate(colors):
        if chart_type in ("Line Chart", "Area Chart", "Scatter Plot"):
            mode = "markers" if chart_type == "Scatter Plot" else "lines+markers"
            trace = go.Scatter(
                x=data["circle"], y=data[column], name=label, mode=mode,
                marker=dict(color=color),
                line=dict(color=color, width=2),
                fill=("tozeroy" if index == 0 else "tonexty")
                if chart_type == "Area Chart" else None,
                hovertemplate=f"%{{x}}<br>{label}: %{{y}}<extra></extra>",
            )
        else:
            horizontal = chart_type == "Horizontal Bar Chart"
            trace = go.Bar(
                x=data[column] if horizontal else data["circle"],
                y=data["circle"] if horizontal else data[column],
                name=label, orientation="h" if horizontal else "v",
                marker_color=color,
                text=[f"{label} {value:,}" for value in data[column]],
                hovertemplate=f"%{{y}}<br>{label}: %{{x}}<extra></extra>"
                if horizontal else f"%{{x}}<br>{label}: %{{y}}<extra></extra>",
            )
        fig.add_trace(trace)

    if chart_type in ("Bar Chart", "Horizontal Bar Chart"):
        fig.update_layout(barmode="stack")
    if chart_type == "Horizontal Bar Chart":
        fig.update_yaxes(autorange="reversed")
    return fig


def show(fig, title, height, x="", y="", show_legend=False):
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#1F2227")),
        height=height, margin=dict(l=10, r=30, t=40, b=10),
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(color="#1F2227", size=12),
        showlegend=(
            show_legend
            or len(fig.data) > 1
            or any(trace.type == "pie" for trace in fig.data)
        ),
    )
    fig.update_xaxes(title=x, automargin=True, gridcolor="#EEE")
    fig.update_yaxes(title=y, automargin=True, gridcolor="#EEE")
    st.plotly_chart(fig, width="stretch", theme=None,
                    config={"displayModeBar": False})


def header(sentence):
    st.markdown(
        '<div class="hdr"><b>airtel</b> | Telecom Analytics: Customer Service'
        f'<span>{sentence}</span></div>', unsafe_allow_html=True)


st.markdown(f"""<style>
.stApp {{background:#F6F6F8;}}
header[data-testid="stHeader"] {{background:transparent;}}
.block-container {{padding:2.6rem 1.2rem 0;
                    }} div[data-testid="stVerticalBlock"] {{gap:0.5rem;}}
section[data-testid="stSidebar"] {{background:#212429;}}
section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] label p,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{color:white;}}
.hdr {{background:linear-gradient(100deg,{RED},{DARK_RED}); color:white;
       padding:8px 16px; border-radius:10px; font-size:1.25rem;}}
.hdr span {{display:block; font-size:0.8rem;}}
.card {{background:white; border-left:5px solid {RED}; border-radius:10px;
        padding:8px 14px; height:100px; margin-bottom:16px; box-shadow:0 1px 4px #0002;}}
.ct {{font-size:0.8rem; font-weight:600; color:#333;}}
.cv {{font-size:1.6rem; font-weight:700; color:{DARK_RED}; line-height:1.3;}}
.cn {{font-size:0.7rem; color:#555; line-height:1.25;}}
.chat-note {{background:white; border:1px solid #E2E2E6; border-radius:10px;
             padding:10px 14px; color:#555; margin-bottom:8px;}}
</style>""", unsafe_allow_html=True)

if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
    st.error("airtel.db is missing or empty. Copy the real database into the project root.")
    st.stop()

# ---------------- Filters ----------------
with st.sidebar:
    st.header("Filters")
    conns = q("SELECT DISTINCT connection_type AS v FROM customer_features "
              "WHERE connection_type IS NOT NULL ORDER BY 1")["v"].tolist()
    regions = q("SELECT DISTINCT region AS v FROM customer_features "
                "WHERE region IS NOT NULL ORDER BY 1")["v"].tolist()
    conn = st.selectbox("Connection type", ["All"] + conns)
    region = st.selectbox("Region", ["All"] + regions)
    st.caption("Cards marked FIXED ignore these filters.")

P = {"conn": conn, "region": region}
scope = f"{'All connection types' if conn == 'All' else conn}, " \
        f"{'all regions' if region == 'All' else region}"
SENTENCE = ("This dashboard helps Head of Customer Service prioritise service effort "
            "and understand ticket patterns and ticket-status relationships.")

header(SENTENCE)
overview, detail = st.tabs(["Overview", "Detail"])

# ---------------- Overview ----------------
with overview:
    fixed = q("""SELECT COUNT(*) AS n, MIN(complaint_date) AS d1,
                        MAX(complaint_date) AS d2 FROM complaints""").iloc[0]
    opn = q(BASE + """
        SELECT COALESCE(SUM(t.status = 'open'), 0) AS n_open, COUNT(*) AS n,
               ROUND(100.0 * SUM(t.status = 'open') / NULLIF(COUNT(*), 0), 1) AS pct
        FROM t JOIN s USING (subscriber_id)""", P).iloc[0]

    c1, c2, c3 = st.columns(3)
    with c1:
        card("Total tickets (FIXED)", f"{int(fixed.n):,}",
             f"Ticket records, {fixed.d1} to {fixed.d2}. Ignores filters.")
    with c2:
        if T7_P_VALUE is None:
            card("T7 two-tailed test (FIXED)", "Not entered",
                 "Add the validated p-value and result in app.py. Ignores filters.")
        else:
            verdict = ("Evidence of an association" if T7_P_VALUE < T7_ALPHA
                       else "No evidence of an association")
            card("T7 two-tailed test (FIXED)", f"p = {T7_P_VALUE:.3g}",
                 f"{verdict} (α = {T7_ALPHA}). {T7_RESULT or ''} Not causation. Ignores filters.")
    with c3:
        share = "n/a" if pd.isna(opn.pct) else f"{opn.pct:.1f}%"
        card("Open tickets", f"{int(opn.n_open):,} ({share})",
             f"Open ÷ all {int(opn.n):,} tickets. {scope}.")

    churn = q(BASE + """,
        h AS (
            SELECT s.subscriber_id, s.churned, COUNT(t.ticket_id) AS n,
                   COALESCE(SUM(t.status = 'open'), 0) AS o,
                   COALESCE(SUM(t.status = 'closed'), 0) AS c
            FROM s LEFT JOIN t USING (subscriber_id)
            GROUP BY s.subscriber_id, s.churned
        ),
        g AS (
            SELECT CASE WHEN n = 0 THEN 'never'
                        WHEN c = n THEN 'all closed'
                        WHEN o = 1 THEN 'one open'
                        ELSE 'outside groups' END AS grp, churned
            FROM h
        )
        SELECT grp, COUNT(*) AS total, SUM(churned) AS lost,
               CASE WHEN COUNT(*) >= 100
                    THEN ROUND(100.0 * SUM(churned) / COUNT(*), 1) END AS rate,
               (SELECT ROUND(100.0 * AVG(churned), 1) FROM s) AS ref
        FROM g GROUP BY grp
        ORDER BY CASE grp WHEN 'never' THEN 1 WHEN 'all closed' THEN 2
                          WHEN 'one open' THEN 3 ELSE 4 END""", P)

    closure = q(BASE + """
        SELECT t.category, COUNT(*) AS total, SUM(t.status = 'closed') AS closed,
               CASE WHEN COUNT(*) >= 100
                    THEN ROUND(100.0 * SUM(t.status = 'closed') / COUNT(*), 1) END AS share
        FROM t JOIN s USING (subscriber_id)
        GROUP BY t.category ORDER BY share""", P)

    rate = q(BASE + """,
        k AS (SELECT subscriber_id, COUNT(*) AS n FROM t GROUP BY subscriber_id)
        SELECT s.circle, COUNT(*) AS subs, COALESCE(SUM(k.n), 0) AS tickets,
               CASE WHEN COUNT(*) >= 100
                    THEN ROUND(100.0 * COALESCE(SUM(k.n), 0) / COUNT(*), 1) END AS per100
        FROM s LEFT JOIN k USING (subscriber_id)
        GROUP BY s.circle ORDER BY per100 DESC LIMIT 5""", P)

    left, right = st.columns([1.2, 1])
    with left:
        main = churn[churn.grp != "outside groups"]
        if main.empty:
            st.info("No subscribers for this selection.")
        else:
            history_types = [
                "Bar Chart", "Horizontal Bar Chart", "Line Chart",
                "Area Chart", "Scatter Plot",
            ]
            chart_type = chart_selector(
                "overview_complaint_history", "Bar Chart", history_types,
            )
            text = [
                f"{'' if pd.isna(r.rate) else f'{r.rate:.1f}%<br>'}"
                f"{int(r.lost):,} of {int(r.total):,} left"
                for r in main.itertuples()
            ]
            fig = xy_chart(
                main, chart_type, "grp", "rate", RED,
                "%{x}<br>Left: %{y:.1f}%<br>%{customdata[0]:,} of %{customdata[1]:,} customers"
                "<extra></extra>",
                custom_cols=("lost", "total"), text=text,
                horizontal_hovertemplate=(
                    "%{y}<br>Left: %{x:.1f}%<br>"
                    "%{customdata[0]:,} of %{customdata[1]:,} customers<extra></extra>"
                ),
            )
            ref = main.ref.iloc[0]
            if chart_type == "Horizontal Bar Chart":
                fig.add_vline(
                    x=ref, line_dash="dash", line_color="#222",
                    annotation_text=f"Selection average {ref:.1f}%",
                    annotation_position="top",
                )
            else:
                fig.add_hline(y=ref, line_dash="dash", line_color="#222",
                              annotation_text=f"Dashed line: selection average {ref:.1f}%",
                              annotation_position="top left")
                fig.update_yaxes(
                    range=[0, max(main.rate.max(), ref) * 1.2
                           if main.rate.notna().any() else 100]
                )
            if chart_type == "Horizontal Bar Chart":
                x_axis, y_axis = "Subscribers who left (%)", "Complaint history"
            else:
                x_axis, y_axis = "Complaint history", "Subscribers who left (%)"
            show(fig, f"Does ticket history relate to leaving? ({scope})", 340,
                 x_axis, y_axis)
        other = churn[churn.grp == "outside groups"]
        if not other.empty:
            st.caption(f"{int(other.total.iloc[0]):,} subscribers fit none of the three groups "
                       "(2+ open or another status); they are in the average only.")
        st.caption("Rates are hidden for groups under 100. Association, not causation.")
    with right:
        for df, label, name, val, num, den, title, axis in [
            (closure, "category", "category", "share", "closed", "total",
             "lowest closure share", "Closed ÷ tickets (%)"),
            (rate, "circle", "circle", "per100", "tickets", "subs",
             "highest ticket rate", "Tickets per 100 subscribers"),
        ]:
            chart_type = chart_selector(
                f"overview_{val}",
                "Horizontal Bar Chart",
                [
                    "Horizontal Bar Chart", "Bar Chart", "Line Chart",
                    "Area Chart", "Scatter Plot", "Histogram",
                ],
            )
            ranked = df.dropna(subset=[val])
            head = (f"{ranked[label].iloc[0]} has the {title}" if not ranked.empty
                    else f"No {name} has 100+ records to rank")
            unit = "closed" if val == "share" else "tickets"
            base = "tickets" if val == "share" else "subscribers"
            text = [
                f"{'' if pd.isna(v) else f'{v:.1f} | '}{int(a):,} {unit} / {int(b):,} {base}"
                for v, a, b in zip(df[val], df[num], df[den])
            ]
            percent_suffix = "%" if val == "share" else ""
            fig = xy_chart(
                df, chart_type, label, val,
                DARK_RED if val == "share" else GREY,
                f"%{{y}}<br>Value: %{{x:.1f}}{percent_suffix}<br>"
                f"%{{customdata[0]:,}} {unit} / %{{customdata[1]:,}} {base}<extra></extra>",
                custom_cols=(num, den), text=text,
                horizontal_hovertemplate=(
                    f"%{{y}}<br>Value: %{{x:.1f}}{percent_suffix}<br>"
                    f"%{{customdata[0]:,}} {unit} / %{{customdata[1]:,}} {base}<extra></extra>"
                ),
                pie_hovertemplate=(
                    f"%{{label}}<br>Value: %{{value:.1f}}{percent_suffix}<br>"
                    f"%{{customdata[0]:,}} {unit}<br>"
                    f"%{{customdata[1]:,}} {base}<extra></extra>"
                ),
            )
            show(
                fig, head, 195, axis,
                "Number of groups" if chart_type == "Histogram" else "",
            )

# ---------------- Detail ----------------
with detail:
    cats = q(BASE + """SELECT DISTINCT t.category AS v FROM t JOIN s USING (subscriber_id)
                       WHERE t.category IS NOT NULL ORDER BY 1""", P)["v"].tolist()
    if not cats:
        st.info("No tickets for this selection.")
        st.stop()

    c0, c1, c2, c3 = st.columns(4)
    with c0:
        cat = st.selectbox("Complaint category", cats)
    D = {**P, "cat": cat}
    k = q(BASE + """
        SELECT COUNT(*) AS n, SUM(t.status = 'open') AS o, SUM(t.status = 'closed') AS c,
               ROUND(100.0 * SUM(t.status = 'closed') / COUNT(*), 1) AS share
        FROM t JOIN s USING (subscriber_id) WHERE t.category = :cat""", D).iloc[0]
    with c1:
        card(f"{cat}: tickets", f"{int(k.n):,}", f"Ticket records. {scope}.")
    with c2:
        card(f"{cat}: closure", f"{k.share:.1f}%" if k.n >= 100 else f"{int(k.c)} of {int(k.n)}",
             f"{int(k.c):,} closed ÷ {int(k.n):,} tickets.")
    with c3:
        card(f"{cat}: open", f"{int(k.o):,}", f"Open tickets out of {int(k.n):,}.")

    trend = q(BASE + """
        SELECT strftime('%Y-%m', t.created_date) AS month, COUNT(*) AS n
        FROM t JOIN s USING (subscriber_id) WHERE t.category = :cat
        GROUP BY month ORDER BY month""", D)
    trend_types = [
        "Line Chart", "Bar Chart", "Area Chart", "Scatter Plot",
        "Pie Chart", "Donut Chart", "Histogram",
    ]
    trend_type = chart_selector("detail_monthly_trend", "Line Chart", trend_types)
    fig = xy_chart(
        trend, trend_type, "month", "n", RED,
        "%{x}<br>Tickets: %{y:,}<extra></extra>",
        text=trend.n,
    )
    if trend_type not in ("Pie Chart", "Donut Chart", "Histogram"):
        fig.update_xaxes(type="category")
    fig.update_yaxes(rangemode="tozero")
    if trend_type in ("Line Chart", "Area Chart", "Scatter Plot"):
        fig.update_traces(cliponaxis=False)
    if trend_type == "Histogram":
        trend_x_axis, trend_y_axis = "Tickets per month", "Number of months"
    else:
        trend_x_axis, trend_y_axis = "Month", "Tickets"
    show(
        fig, f"How have {cat} ticket counts changed by month?", 180,
        trend_x_axis, trend_y_axis,
    )

    leave = q(BASE + """,
        p AS (
            SELECT s.subscriber_id, s.churned, MAX(t.status = 'open') AS has_open
            FROM t JOIN s USING (subscriber_id) WHERE t.category = :cat
            GROUP BY s.subscriber_id, s.churned
        )
        SELECT CASE has_open WHEN 1 THEN 'Has open ticket' ELSE 'No open ticket' END AS grp,
               COUNT(*) AS total, SUM(churned) AS lost,
               CASE WHEN COUNT(*) >= 100
                    THEN ROUND(100.0 * SUM(churned) / COUNT(*), 1) END AS rate
        FROM p GROUP BY has_open ORDER BY has_open""", D)
    status = q(BASE + """
        SELECT s.circle, SUM(t.status = 'open') AS o, SUM(t.status = 'closed') AS c
        FROM t JOIN s USING (subscriber_id) WHERE t.category = :cat
        GROUP BY s.circle ORDER BY o DESC LIMIT 5""", D)

    left, right = st.columns(2)
    with left:
        leave_types = [
            "Bar Chart", "Horizontal Bar Chart", "Line Chart",
            "Area Chart", "Scatter Plot",
        ]
        leave_type = chart_selector(
            "detail_ticket_status_churn", "Bar Chart", leave_types,
        )
        leave_text = [
            f"{'' if pd.isna(r.rate) else f'{r.rate:.1f}%<br>'}"
            f"{int(r.lost):,} of {int(r.total):,} left"
            for r in leave.itertuples()
        ]
        fig = xy_chart(
            leave, leave_type, "grp", "rate", RED,
            "%{x}<br>Left: %{y:.1f}%<br>%{customdata[0]:,} of "
            "%{customdata[1]:,} customers<extra></extra>",
            custom_cols=("lost", "total"), text=leave_text,
            horizontal_hovertemplate=(
                "%{y}<br>Left: %{x:.1f}%<br>%{customdata[0]:,} of "
                "%{customdata[1]:,} customers<extra></extra>"
            ),
        )
        visible_groups = leave.loc[leave.rate.notna(), "grp"]
        fig.update_traces(marker_color=[
            RED if group == "Has open ticket" else GREY
            for group in visible_groups
        ])
        if leave_type == "Horizontal Bar Chart":
            leave_x_axis, leave_y_axis = "Left (%)", f"Subscribers with a {cat} ticket"
        else:
            leave_x_axis, leave_y_axis = f"Subscribers with a {cat} ticket", "Left (%)"
        show(fig, f"{cat}: is ticket status associated with leaving?", 200,
             leave_x_axis, leave_y_axis)
        st.caption("Association only. Rates are hidden for groups under 100.")
    with right:
        status_types = [
            "Horizontal Bar Chart", "Bar Chart", "Line Chart",
            "Area Chart", "Scatter Plot", "Histogram",
        ]
        status_type = chart_selector(
            "detail_circle_open_closed", "Horizontal Bar Chart", status_types,
        )
        fig = status_chart(status, status_type)
        if status_type == "Horizontal Bar Chart":
            status_x_axis, status_y_axis = "Tickets (Open | Closed)", "Circle"
        elif status_type == "Histogram":
            status_x_axis, status_y_axis = "Tickets per circle", "Number of circles"
        else:
            status_x_axis, status_y_axis = "Circle", "Tickets (Open | Closed)"
        show(
            fig, f"{cat}: circles with the most open tickets", 200,
            status_x_axis, status_y_axis,
        )
