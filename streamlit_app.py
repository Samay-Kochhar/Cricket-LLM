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
SERVICE_BUNDLE_VERSION = 3
PLAYER_EXPLORER_BUNDLE_VERSION = 1


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
def initialize_services(service_bundle_version: int = SERVICE_BUNDLE_VERSION) -> dict[str, Any]:
    del service_bundle_version
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


@st.cache_resource(show_spinner=False)
def initialize_player_explorer_services(
    service_bundle_version: int = PLAYER_EXPLORER_BUNDLE_VERSION,
) -> dict[str, Any]:
    del service_bundle_version
    from scripts.bootstrap_data import ensure_database

    ensure_database(
        root=ROOT,
        csv_path=CSV_PATH,
        db_path=DB_PATH,
        source_url=os.getenv("CRICATLAS_DATA_URL"),
        expected_sha256=os.getenv("CRICATLAS_DATA_SHA256"),
        archive_member=os.getenv("CRICATLAS_DATA_ARCHIVE_MEMBER"),
    )

    from backend.app.db.repository import AnalyticsRepository

    repository = AnalyticsRepository(DB_PATH)
    return {
        "repository": repository,
        "player_names": tuple(repository.list_player_names()),
    }


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
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})


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
        st.dataframe(rows, use_container_width=True, hide_index=True)

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


def apply_ranking_controls(message_index: int, widget_prefix: str) -> None:
    """Commit a submitted ranking before Streamlit renders either answer."""
    from backend.app.cricket_analytics.ranking_controls import controlled_plan
    from backend.app.cricket_analytics.schemas import CricketQueryPlan

    message = st.session_state.messages[message_index]
    reply_data = message["reply"]
    try:
        plan = CricketQueryPlan.model_validate(reply_data["query_response"]["ranking_plan"])
        next_plan = controlled_plan(
            plan,
            unit=st.session_state[f"{widget_prefix}-unit"],
            minimum=st.session_state[f"{widget_prefix}-minimum"],
            sort_by=st.session_state[f"{widget_prefix}-sort"],
            direction=st.session_state[f"{widget_prefix}-direction"],
        )
        services = initialize_services(SERVICE_BUNDLE_VERSION)
        question = reply_data["query_response"]["interpretation"]["original_question"]
        response = services["semantic_service"].answer_ranking_plan(question, next_plan)
        if response.status.value != "supported":
            message["ranking_error"] = (
                response.insufficiencies[0].detail
                if response.insufficiencies
                else "No ranking matched these controls."
            )
            return
        updated = dict(reply_data)
        updated["query_response"] = response.model_dump(mode="json")
        updated["message"] = response.summaries[0].body
        message["reply"] = updated
        message["content"] = updated["message"]
        message.pop("ranking_error", None)
        message["ranking_controls_revision"] = message.get("ranking_controls_revision", 0) + 1
    except ValueError as exc:
        message["ranking_error"] = str(exc)
    except Exception:
        LOGGER.exception("CricAtlas ranking control failed")
        message["ranking_error"] = "The ranking could not be updated. Try a different sample or sort."


def reset_ranking_controls(message_index: int) -> None:
    message = st.session_state.messages[message_index]
    base = message.get("base_reply")
    if base:
        message["reply"] = base
        message["content"] = base["message"]
        message.pop("ranking_error", None)
        message["ranking_controls_revision"] = message.get("ranking_controls_revision", 0) + 1


def render_ranking_controls(reply_data: dict[str, Any], message_index: int) -> bool:
    from backend.app.cricket_analytics.ranking_controls import ranking_options
    from backend.app.cricket_analytics.metric_registry import get_metric
    from backend.app.cricket_analytics.schemas import CricketQueryPlan

    raw_plan = reply_data["query_response"].get("ranking_plan")
    if not raw_plan:
        return True
    message = st.session_state.messages[message_index]
    message.setdefault("base_reply", reply_data)
    try:
        plan = CricketQueryPlan.model_validate(raw_plan)
        units, sorts = ranking_options(plan)
    except ValueError as exc:
        st.error(str(exc))
        return False
    sample = plan.minimum_sample
    active_unit = next(
        (unit for unit in units if sample and getattr(sample, unit) is not None),
        next(iter(units)),
    )
    active_minimum = getattr(sample, active_unit) if sample else None
    active_sort = plan.sort.by if plan.sort and plan.sort.by in sorts else plan.metric
    active_direction = (
        plan.sort.direction
        if plan.sort
        else get_metric(plan.metric, entity=plan.entity, filters=plan.filters).default_sort
    )
    threshold_label = (
        "minimum " + " and ".join(
            f"{getattr(sample, unit)} {label.lower()}"
            for unit, label in units.items()
            if getattr(sample, unit) is not None
        )
        if sample and active_minimum is not None
        else "no minimum"
    )
    base_plan = message["base_reply"]["query_response"]["ranking_plan"]
    is_default = not plan.minimum_sample_explicit and raw_plan.get("sort") == base_plan.get("sort")
    st.caption(
        f"Active ranking{' (default)' if is_default else ''}: "
        f"{threshold_label} · "
        f"{sorts[active_sort]} {'ascending' if active_direction == 'asc' else 'descending'}"
    )
    revision = message.get("ranking_controls_revision", 0)
    widget_prefix = f"ranking-controls-{message_index}-{revision}"
    with st.form(key=f"ranking-controls-{message_index}-{revision}", border=False):
        unit_col, minimum_col, sort_col, direction_col, apply, reset = st.columns(
            [1.5, 1.1, 2, 1.4, 0.8, 0.8], gap="small", vertical_alignment="bottom",
        )
        with unit_col:
            st.selectbox(
                "Minimum sample unit", list(units), index=list(units).index(active_unit),
                format_func=units.get, label_visibility="collapsed",
                key=f"{widget_prefix}-unit",
            )
        with minimum_col:
            st.number_input(
                "Minimum sample (0 = no minimum)", min_value=0, max_value=1_000_000,
                value=active_minimum if active_minimum is not None else 0, step=1,
                label_visibility="collapsed",
                key=f"{widget_prefix}-minimum",
            )
        with sort_col:
            st.selectbox(
                "Sort column", list(sorts), index=list(sorts).index(active_sort),
                format_func=sorts.get, label_visibility="collapsed",
                key=f"{widget_prefix}-sort",
            )
        with direction_col:
            st.selectbox(
                "Sort direction", ["desc", "asc"],
                index=["desc", "asc"].index(active_direction),
                format_func=lambda value: "Descending" if value == "desc" else "Ascending",
                label_visibility="collapsed",
                key=f"{widget_prefix}-direction",
            )
        apply.form_submit_button(
            "Apply", use_container_width=True,
            on_click=apply_ranking_controls, args=(message_index, widget_prefix),
        )
        reset.form_submit_button(
            "Reset", use_container_width=True,
            on_click=reset_ranking_controls, args=(message_index,),
        )
    if message.get("ranking_error"):
        st.error(message["ranking_error"])
        return False
    return True


def render_reply(reply_data: dict[str, Any], message_index: int | None = None) -> None:
    from backend.app.services.chat_service import ChatReply

    reply = ChatReply.model_validate(reply_data)
    display_message = reply.message.split("\n\n", maxsplit=1)[0] if reply.query_response else reply.message
    headline = st.empty()
    headline.markdown(display_message)
    if reply.resolution_note:
        st.caption(reply.resolution_note)
    if reply.query_response:
        if (
            message_index is not None
            and reply.query_response.ranking_plan
            and not render_ranking_controls(reply_data, message_index)
        ):
            headline.empty()
            return
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

    # The hosted computer starts without large data files. Fetch our prepared
    # records before either chat or an explorer creates its database services.
    from scripts.bootstrap_multiformat import ensure_multiformat_database

    multiformat_path = Path(os.getenv("MULTIFORMAT_DUCKDB_PATH") or DATA_DIR / "cricket_all.duckdb")
    if not multiformat_path.is_file():
        try:
            with st.spinner("Downloading cricket records for all formats. This is needed only on the first start…"):
                ensure_multiformat_database(multiformat_path)
        except Exception:
            LOGGER.exception("Could not download the all-format cricket records")
            st.error("The website could not download the cricket records for all formats. Please reload to try again.")
            st.stop()

    with st.sidebar:
        st.markdown("### CricAtlas")
        st.caption("All formats · evidence-first")
        st.markdown("Database statistics remain the source of truth. Gemini assists with interpretation and explanation.")
        view = st.radio(
            "Navigate",
            ["Ask Atlas", "Player Explorer", "Compare", "Matchups", "Venue Explorer"],
            label_visibility="collapsed",
        )
        if view == "Ask Atlas":
            if st.button("New analysis", width="stretch"):
                st.session_state.messages = []
                st.session_state.history = []
                st.session_state.conversation_state = None
                st.rerun()
        st.divider()
        st.caption("Private testing deployment")
        st.caption(
            "Chat and the four explorers cover Tests, ODIs, T20Is, the IPL and other leagues, The Hundred "
            "and domestic cricket, men's and women's, using the shared CricAtlas analytics engine."
        )

    if view in {"Player Explorer", "Compare", "Matchups", "Venue Explorer"}:
        from streamlit_format_explorer import ExplorerScope, default_db_path, render_other_format_view, render_scope_selector

        multiformat_db = default_db_path(ROOT)
        try:
            scope = render_scope_selector(multiformat_db)
        except Exception:
            LOGGER.exception("CricAtlas Streamlit format selector failed")
            st.error("CricAtlas could not list the other formats, so men's ODIs are shown.")
            scope = ExplorerScope()
        if not scope.original_odi:
            try:
                with st.spinner("Preparing the player database…"):
                    render_other_format_view(view, multiformat_db, scope)
            except Exception:
                LOGGER.exception("CricAtlas Streamlit %s failed for %s", view, scope.key)
                st.error(f"CricAtlas could not prepare {view}. Check the private app logs for details.")
            return
        try:
            with st.spinner("Preparing the player database…"):
                services = (
                    initialize_player_explorer_services(PLAYER_EXPLORER_BUNDLE_VERSION)
                    if view in {"Player Explorer", "Compare", "Venue Explorer"}
                    else initialize_services(SERVICE_BUNDLE_VERSION)
                )
            if view == "Player Explorer":
                from streamlit_player_explorer import render_player_explorer

                render_player_explorer(services)
            elif view == "Compare":
                from streamlit_compare_explorer import render_compare_explorer

                render_compare_explorer(services)
            elif view == "Matchups":
                from streamlit_matchup_explorer import render_matchup_explorer

                render_matchup_explorer(services)
            else:
                from streamlit_venue_explorer import render_venue_explorer

                render_venue_explorer(services)
        except Exception:
            LOGGER.exception("CricAtlas Streamlit %s failed to initialize", view)
            st.error(f"CricAtlas could not prepare {view}. Check the private app logs for details.")
        return

    st.markdown("<div class='atlas-kicker'>◆ Cricket intelligence workbench</div>", unsafe_allow_html=True)
    st.markdown("<h1 class='atlas-title'>Ask cricket questions.<br>Inspect the evidence.</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='atlas-copy'>Database-backed analysis of Tests, ODIs, T20Is, leagues and domestic cricket, men's and women's, with question-specific tables, Plotly charts, metric definitions and explicit limitations.</p>",
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

    for message_index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            if message["role"] == "assistant" and message.get("reply"):
                render_reply(message["reply"], message_index)
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
        with st.spinner("Preparing the evidence…"):
            services = initialize_services(SERVICE_BUNDLE_VERSION)
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
    st.session_state.messages.append(
        {"role": "assistant", "content": reply.message, "reply": reply_data, "base_reply": reply_data}
    )
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


if __name__ == "__main__":
    render_page()
