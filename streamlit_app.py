from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "odi_bbb-25.csv"
DB_PATH = DATA_DIR / "odi_analytics.duckdb"
LOGGER = logging.getLogger("cricatlas.streamlit")

SECRET_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_DEFAULT_MODEL",
    "GEMINI_COMPLEX_MODEL",
    "CRICATLAS_DATA_URL",
    "CRICATLAS_DATA_SHA256",
    "CRICATLAS_DATA_ARCHIVE_MEMBER",
)


def apply_cloud_secrets() -> None:
    try:
        secrets = st.secrets
        for key in SECRET_KEYS:
            value = secrets.get(key)
            if value:
                os.environ[key] = str(value)
    except FileNotFoundError:
        pass

    os.environ.setdefault("APP_ENV", "production")
    os.environ.setdefault("DUCKDB_PATH", str(DB_PATH))
    os.environ.setdefault("USE_SEMANTIC_ANALYTICS_V2", "true")
    os.environ.setdefault("SEMANTIC_V2_DEV_FALLBACK", "false")


@st.cache_resource(show_spinner=False)
def initialize_services() -> dict[str, Any]:
    from scripts.bootstrap_data import ensure_database

    ensure_database(
        root=ROOT,
        csv_path=CSV_PATH,
        db_path=DB_PATH,
        source_url=os.getenv("CRICATLAS_DATA_URL"),
        expected_sha256=os.getenv("CRICATLAS_DATA_SHA256"),
        archive_member=os.getenv("CRICATLAS_DATA_ARCHIVE_MEMBER"),
    )

    from backend.app.bootstrap import get_services

    get_services.cache_clear()
    return get_services()


def render_chart(chart: Any) -> None:
    points = [point for point in chart.series if isinstance(point, dict)]
    labels = [str(point.get("label", "")) for point in points]
    values = [float(point.get("value", 0) or 0) for point in points]
    if not points:
        return

    figure = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color="#F28F3B",
            hovertemplate="%{y}: %{x}<extra></extra>",
        )
    )
    figure.update_layout(
        title=chart.title,
        height=max(280, 46 * len(points)),
        margin=dict(l=16, r=16, t=52, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#F3EDE4",
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def render_query_response(response: Any) -> None:
    status_label = response.status.value.replace("_", " ").title()
    st.markdown(f"<span class='status-pill'>{status_label}</span>", unsafe_allow_html=True)

    for summary in response.summaries:
        with st.container(border=True):
            st.markdown(f"#### {summary.title}")
            st.markdown(summary.body)

    for insufficiency in response.insufficiencies:
        st.warning(f"**{insufficiency.title}**\n\n{insufficiency.detail}")
        if insufficiency.suggestions:
            st.markdown("\n".join(f"- {item}" for item in insufficiency.suggestions))

    for table in response.tables:
        st.markdown(f"#### {table.title}")
        rows = [dict(zip(table.columns, row, strict=False)) for row in table.rows]
        st.dataframe(rows, width="stretch", hide_index=True)

    for chart in response.charts:
        render_chart(chart)

    if response.metric_references or response.evidence_notes or response.citations:
        with st.expander("Evidence, definitions and limitations"):
            for metric in response.metric_references:
                unit = f" ({metric.unit})" if metric.unit else ""
                st.markdown(f"**{metric.label}{unit}:** `{metric.formula}`")
            for note in response.evidence_notes:
                if not note.title.startswith("Semantic trace"):
                    st.markdown(f"**{note.title}:** {note.detail}")
            for citation in response.citations:
                st.markdown(f"- [{citation.label}]({citation.locator}) — {citation.source_type.value}")


def render_reply(reply_data: dict[str, Any]) -> None:
    from backend.app.services.chat_service import ChatReply

    reply = ChatReply.model_validate(reply_data)
    display_message = reply.message.split("\n\n", maxsplit=1)[0] if reply.query_response else reply.message
    st.markdown(display_message)
    if reply.resolution_note:
        st.caption(reply.resolution_note)
    if reply.query_response:
        render_query_response(reply.query_response)
    clarification_options = getattr(reply, "clarification_options", [])
    if clarification_options:
        st.info("Try one of these clarified versions: " + " · ".join(item.label for item in clarification_options))
    if reply.suggestions:
        st.caption("Continue with: " + " · ".join(reply.suggestions[:3]))


def render_page() -> None:
    st.set_page_config(
        page_title="CricAtlas — Evidence-first cricket analysis",
        page_icon="🏏",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .stApp {
          background:
            radial-gradient(circle at top left, rgba(242,143,59,.16), transparent 30%),
            radial-gradient(circle at top right, rgba(124,226,180,.12), transparent 25%),
            linear-gradient(180deg, #091015 0%, #11181e 100%);
        }
        [data-testid="stSidebar"] { background: rgba(17,25,32,.96); }
        [data-testid="stChatMessage"] {
          border: 1px solid rgba(255,255,255,.08);
          border-radius: 22px;
          background: rgba(18,25,32,.82);
          padding: .6rem 1rem;
          margin-bottom: .8rem;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
          border-color: rgba(255,255,255,.09);
          background: rgba(18,25,32,.72);
          border-radius: 22px;
        }
        .atlas-kicker { color:#FFB268; letter-spacing:.16em; text-transform:uppercase; font-weight:700; font-size:.72rem; }
        .atlas-title { font-size:clamp(2.4rem,4vw,4rem); line-height:.98; letter-spacing:-.05em; margin:.4rem 0 1rem; max-width:14ch; }
        .explorer-title { max-width:18ch; }
        .atlas-copy { color:#A7B2BB; max-width:760px; font-size:1.05rem; line-height:1.7; }
        .status-pill { display:inline-block; color:#7CE2B4; background:rgba(124,226,180,.12); border:1px solid rgba(124,226,180,.28); border-radius:999px; padding:.25rem .7rem; font-size:.72rem; text-transform:uppercase; letter-spacing:.1em; margin:.2rem 0 .8rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    apply_cloud_secrets()

    with st.sidebar:
        st.markdown("### CricAtlas")
        st.caption("ODI-first · evidence-first")
        st.markdown("Database statistics remain the source of truth. Gemini assists with interpretation and explanation.")
        view = st.radio("Navigate", ["Ask Atlas", "Player Explorer"], label_visibility="collapsed")
        if view == "Ask Atlas":
            if st.button("New analysis", width="stretch"):
                st.session_state.messages = []
                st.session_state.history = []
                st.session_state.conversation_state = None
                st.rerun()
        st.divider()
        st.caption("Private testing deployment")
        st.caption("Chat and Player Explorer are hosted here. Compare and venue explorers remain in the Docker edition.")

    if view == "Player Explorer":
        try:
            with st.spinner("Preparing the ODI player database…"):
                services = initialize_services()
            from streamlit_player_explorer import render_player_explorer

            render_player_explorer(services)
        except Exception:
            LOGGER.exception("CricAtlas Streamlit player explorer failed to initialize")
            st.error("CricAtlas could not prepare the Player Explorer. Check the private app logs for details.")
        return

    st.markdown("<div class='atlas-kicker'>◆ Cricket intelligence workbench</div>", unsafe_allow_html=True)
    st.markdown("<h1 class='atlas-title'>Ask cricket questions.<br>Inspect the evidence.</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='atlas-copy'>Database-backed ODI analysis with question-specific tables, Plotly charts, metric definitions and explicit limitations.</p>",
        unsafe_allow_html=True,
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "history" not in st.session_state:
        st.session_state.history = []
    if "conversation_state" not in st.session_state:
        st.session_state.conversation_state = None

    if not st.session_state.messages:
        examples = (
            "How many ODI runs has Virat Kohli scored in this database?",
            "Compare Rohit Sharma and Virat Kohli's batting strike rate.",
            "Show Jasprit Bumrah's bowling economy by phase.",
        )
        columns = st.columns(len(examples))
        for index, example in enumerate(examples):
            if columns[index].button(example, key=f"example-{index}", width="stretch"):
                st.session_state.pending_prompt = example
                st.rerun()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant" and message.get("reply"):
                render_reply(message["reply"])
            else:
                st.markdown(message["content"])

    prompt = st.chat_input("Ask about a player, matchup, venue, phase or metric…")
    pending_prompt = st.session_state.pop("pending_prompt", None)
    question = prompt or pending_prompt
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    try:
        with st.spinner("Preparing the ODI evidence…"):
            services = initialize_services()
            from backend.app.services.chat_service import ChatHistoryTurn

            history = [ChatHistoryTurn.model_validate(turn) for turn in st.session_state.history]
            chat_service = services["chat_service"]
            if "conversation_state" in inspect.signature(chat_service.reply).parameters:
                from backend.app.services.chat_service import ConversationState

                state = (
                    ConversationState.model_validate(st.session_state.conversation_state)
                    if st.session_state.conversation_state
                    else None
                )
                reply = chat_service.reply(question, history, state)
            else:
                reply = chat_service.reply(question, history)
    except Exception:
        LOGGER.exception("CricAtlas Streamlit data service failed to initialize")
        st.error(
            "CricAtlas could not prepare its data service. Check the private app logs for details."
        )
        return

    reply_data = reply.model_dump(mode="json")
    st.session_state.messages.append({"role": "assistant", "content": reply.message, "reply": reply_data})
    st.session_state.history.extend(
        [
            {"role": "user", "content": question},
            {"role": "assistant", "content": reply.message},
        ]
    )
    conversation_state = getattr(reply, "conversation_state", None)
    st.session_state.conversation_state = (
        conversation_state.model_dump(mode="json") if conversation_state else None
    )
    st.rerun()


render_page()
