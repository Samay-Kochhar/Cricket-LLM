"""AI investigation for questions the database rules cannot fully answer.

Path: database rules first (fast, fixed definitions). When the rules refuse or
leave part of the question unaccounted for, the whole question goes to a
capable Gemini model that may run several read-only SQL queries over the
multi-format database (and the ODI database, attached as ``odi``), guided by a
knowledge pack of tables, coverage and cricket definitions. Its answer is
accepted only if every number in its text appears in a query result; tables are
copied straight from query results. If no checked answer is produced, the
question is saved as a specific case in a local backlog.

Guardrails (all enforced in code, not only in the prompt):
- read-only DuckDB connection with file access disabled and settings locked;
- exactly one SELECT/WITH statement per call, no write/DDL/PRAGMA/ATTACH/COPY,
  no file-reading functions, no source-identifying columns;
- row limit (oversized results are refused, so the model must aggregate),
  per-query time limit, and a maximum number of queries and model turns.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

import duckdb

from backend.app.domain.evidence_models import (
    EvidenceNote,
    EvidenceStatus,
    InsufficientEvidenceBlock,
    QueryInterpretation,
    QueryResponse,
    TableBlock,
)

PRICES_PER_MILLION = {  # (input, output incl. thinking), US dollars
    "gemini-3.1-pro-preview": (2.0, 12.0),
}
SOURCE_WORDS = re.compile(r"(?i)cricsheet|aucb|espn|tigzig|cricinfo")
HIDDEN_COLUMNS = (
    "score_source", "ll_source", "shot_source", "length_aucb", "line_aucb", "shot_aucb",
    "length_espn", "line_espn", "shot_espn", "feed_align_score", "feed_filled_from_commentary",
    "cricinfo_id", "batting_hand_source", "bowling_style_source", "ll_from_espn_pct",
    "ll_from_aucb_pct", "score_sources", "cricsheet_match_type",
)
_FORBIDDEN_WORDS = re.compile(
    r"\b(insert|update|delete|merge|create|drop|alter|attach|detach|copy|export|import|install|load|"
    r"pragma|set|reset|call|checkpoint|vacuum|begin|commit|rollback|grant|revoke|truncate|use|summarize|describe)\b",
    re.I,
)
_FILE_FUNCTIONS = re.compile(
    r"\b(read_\w+|glob|sniff_csv|parquet_\w+|query|query_table|getenv|current_setting|duckdb_\w+)\s*\(",
    re.I,
)
_HIDDEN = re.compile(r"\b(" + "|".join(HIDDEN_COLUMNS) + r"|source_fixture_map)\b", re.I)
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])-?\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9_])")


class SqlRejected(ValueError):
    """A query broke a guardrail; the reason is shown to the model."""


# ---------------------------------------------------------------- SQL tool
def _strip_literals(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def check_sql(sql: str, conn: duckdb.DuckDBPyConnection | None = None) -> str:
    """Return the query if it is one read-only SELECT/WITH statement, else raise SqlRejected."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise SqlRejected("empty query")
    bare = _strip_literals(text)
    if ";" in bare:
        raise SqlRejected("only one statement per call is allowed")
    if not re.match(r"(?is)^\s*(select|with)\b", bare):
        raise SqlRejected("only SELECT or WITH queries are allowed")
    word = _FORBIDDEN_WORDS.search(bare)
    if word:
        raise SqlRejected(f"'{word.group(1).upper()}' is not allowed: the database is read-only")
    func = _FILE_FUNCTIONS.search(bare)
    if func:
        raise SqlRejected(f"function {func.group(1)}() is not allowed")
    hidden = _HIDDEN.search(bare)
    if hidden:
        raise SqlRejected(f"column/table {hidden.group(1)} is not available; use line, length and shot")
    if conn is not None:
        statements = conn.extract_statements(text)
        if len(statements) != 1:
            raise SqlRejected("only one statement per call is allowed")
        if statements[0].type != duckdb.StatementType.SELECT:
            raise SqlRejected("only SELECT or WITH queries are allowed")
    return text


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if value != value else round(value, 6)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value)
    return text if len(text) <= 200 else text[:200] + "…"


@dataclass
class QueryResult:
    sql: str
    purpose: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0

    def for_model(self, index: int) -> dict[str, Any]:
        if self.error:
            return {"query": index, "error": self.error}
        return {"query": index, "columns": self.columns, "rows": self.rows, "row_count": len(self.rows)}


def _quoted(path: Path) -> str:
    return Path(path).resolve().as_posix().replace("'", "''")


class ReadOnlyDatabase:
    """One locked, read-only connection; every query passes check_sql first."""

    def __init__(
        self,
        multiformat_db: Path,
        odi_db: Path | None = None,
        *,
        max_rows: int = 200,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds
        # A private in-memory instance attaches both files read-only, so the
        # locked settings below never leak into the app's own connections
        # (DuckDB shares one instance per file within a process).
        self.conn = duckdb.connect(":memory:")
        self.conn.execute(f"ATTACH '{_quoted(multiformat_db)}' AS cricket (READ_ONLY)")
        self.conn.execute("USE cricket")
        if odi_db is not None and Path(odi_db).exists():
            self.conn.execute(f"ATTACH '{_quoted(odi_db)}' AS odi (READ_ONLY)")
        self.conn.execute("SET enable_external_access = false")
        self.conn.execute("SET lock_configuration = true")
        self._lock = threading.Lock()

    def run(self, sql: str, purpose: str = "") -> QueryResult:
        started = time.perf_counter()
        result = QueryResult(sql=(sql or "").strip(), purpose=purpose)
        with self._lock:
            try:
                text = check_sql(sql, self.conn)
                timer = threading.Timer(self.timeout_seconds, self.conn.interrupt)
                timer.start()
                try:
                    cursor = self.conn.execute(text)
                    rows = cursor.fetchmany(self.max_rows + 1)
                    columns = [d[0] for d in cursor.description]
                finally:
                    timer.cancel()
                if len(rows) > self.max_rows:
                    raise SqlRejected(
                        f"the result has more than {self.max_rows} rows; aggregate further or add LIMIT"
                    )
                if any(_HIDDEN.search(column) for column in columns):
                    raise SqlRejected("source-identifying columns are not available; select explicit analytics columns")
                result.columns = columns
                result.rows = [[_cell(v) for v in row] for row in rows]
            except SqlRejected as exc:
                result.error = f"rejected: {exc}"
            except duckdb.InterruptException:
                result.error = f"rejected: the query took longer than {self.timeout_seconds:.0f} seconds"
            except duckdb.Error as exc:
                result.error = "database error: " + str(exc).splitlines()[0][:300]
        result.seconds = round(time.perf_counter() - started, 3)
        return result

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------------- provenance
def _decimals(token: str) -> int:
    return len(token.split(".", 1)[1]) if "." in token else 0


def _result_numbers(results: list[QueryResult]) -> list[float]:
    values: list[float] = []
    for result in results:
        if result.error:
            continue
        for row in result.rows:
            for value in row:
                if isinstance(value, bool) or value is None:
                    continue
                if isinstance(value, (int, float)):
                    values.append(float(value))
                elif isinstance(value, str):
                    # Dates and labels such as "2023-05-01" or "overs 1-6".
                    values.extend(float(n) for n in re.findall(r"\d+(?:\.\d+)?", value))
    return values


def unsupported_numbers(text: str, results: list[QueryResult], question: str = "") -> list[str]:
    """Numbers in ``text`` that no successful query result supports.

    A number written with d decimals matches a result value that rounds to it
    (134.86 matches 134.857). Whole numbers match exactly or as a rounded rate.
    Percentages may come from a result fraction (0.452 → 45.2%).
    """
    values = _result_numbers(results)
    missing: list[str] = []
    for match in NUMBER.finditer(text or ""):
        token = match.group()
        number = float(token.replace(",", ""))
        places = _decimals(token)
        percentage = (text[match.end():].lstrip()).startswith("%")
        if any(round(v, places) == number or (percentage and round(100 * v, places) == number) for v in values):
            continue
        missing.append(token)
    return list(dict.fromkeys(missing))


# ---------------------------------------------------------------- backlog
class UnansweredBacklog:
    """Local, gitignored JSONL of questions we could not answer, for later improvement."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def add(self, question: str, reason: str, tried: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        record = {
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "question": question,
            "reason": reason,
            "tried": tried,
            **extra,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        return record


# ---------------------------------------------------------------- model client
class ToolModel(Protocol):
    model: str

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return the raw generateContent JSON (or {"error": ...})."""


class GeminiToolModel:
    """generateContent with function calling; every response is cached by request hash.

    The cache makes evaluation replayable offline and means a question is paid
    for once. Failed calls are cached too after two retries.
    """

    def __init__(
        self,
        api_key: str | None,
        model: str,
        cache_dir: Path,
        *,
        offline: bool = False,
        timeout_seconds: float = 180.0,
        api_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.timeout_seconds = timeout_seconds
        self.api_base_url = api_base_url
        self.paid_calls = 0

    def cache_path(self, payload: dict[str, Any]) -> Path:
        key = sha256((self.model + "\n" + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
        return self.cache_dir / self.model / f"{key}.json"

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = self.cache_path(payload)
        if path.exists():
            return json.loads(path.read_text())
        if self.offline:
            return {"error": "missing offline capture"}
        if not self.api_key:
            return {"error": "not_configured"}
        import httpx

        record: dict[str, Any] = {}
        for attempt in range(3):
            try:
                self.paid_calls += 1
                response = httpx.post(
                    f"{self.api_base_url}/models/{self.model}:generateContent",
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                response.raise_for_status()
                record = response.json()
                break
            except httpx.HTTPStatusError as exc:
                record = {"error": f"http_{exc.response.status_code}"}
                break
            except (httpx.HTTPError, ValueError) as exc:
                record = {"error": "request_failed: " + type(exc).__name__}
                if attempt < 2:
                    time.sleep(5)
                    continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record))
        temp.replace(path)
        return record


# ---------------------------------------------------------------- investigation
RUN_SQL = {
    "name": "run_sql",
    "description": "Run ONE read-only DuckDB SELECT/WITH query. Returns columns and rows (max 200 rows).",
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "A single SELECT or WITH query."},
            "purpose": {"type": "string", "description": "One plain-English line: what this query checks."},
        },
        "required": ["sql", "purpose"],
    },
}
SUBMIT = {
    "name": "submit_answer",
    "description": (
        "Finish. outcome=answered with a checked answer; clarify when the question is genuinely ambiguous; "
        "cannot_answer when the data cannot support a correct answer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": ["answered", "clarify", "cannot_answer"]},
            "showing": {"type": "string", "description": "Interpretation line, e.g. 'Showing: opening stands · men's BBL · 2011–2026 · by runs'."},
            "answer": {"type": "string", "description": "Short plain-English answer. Every number must appear in a query result."},
            "tables": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "integer", "description": "1-based number of the query whose rows to show."},
                        "title": {"type": "string"},
                        "columns": {"type": "array", "items": {"type": "string"}},
                        "max_rows": {"type": "integer"},
                    },
                    "required": ["query", "title"],
                },
            },
            "definitions": {"type": "string", "description": "How the main metric was calculated, in plain words."},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "clarification_question": {"type": "string"},
            "clarification_options": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string", "description": "For cannot_answer: why, in plain words."},
        },
        "required": ["outcome"],
    },
}


@dataclass
class Investigation:
    outcome: str  # answered | clarify | not_answered
    question: str
    reason: str
    model: str
    showing: str = ""
    answer: str = ""
    tables: list[TableBlock] = field(default_factory=list)
    queries: list[QueryResult] = field(default_factory=list)
    used_queries: list[int] = field(default_factory=list)
    definitions: str = ""
    limitations: list[str] = field(default_factory=list)
    clarification_question: str = ""
    clarification_options: list[str] = field(default_factory=list)
    failure: str = ""
    model_calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    trace: list[str] = field(default_factory=list)

    @property
    def cost_usd(self) -> float | None:
        price = PRICES_PER_MILLION.get(self.model)
        if not price:
            return None
        return round((self.prompt_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000, 4)

    def tried(self) -> list[dict[str, Any]]:
        return [
            {"purpose": q.purpose, "sql": q.sql, "error": q.error, "rows": len(q.rows)}
            for q in self.queries
        ]


class Investigator:
    def __init__(
        self,
        model: ToolModel,
        database: ReadOnlyDatabase,
        knowledge: str,
        *,
        max_queries: int = 10,
        max_turns: int = 14,
        thinking_level: str | None = "high",
        backlog: UnansweredBacklog | None = None,
    ) -> None:
        self.model = model
        self.database = database
        self.knowledge = knowledge
        self.max_queries = max_queries
        self.max_turns = max_turns
        self.thinking_level = thinking_level
        self.backlog = backlog

    def _payload(self, contents: list[dict[str, Any]]) -> dict[str, Any]:
        config: dict[str, Any] = {"temperature": 1.0, "maxOutputTokens": 16384}
        if self.thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        return {
            "systemInstruction": {"parts": [{"text": self.knowledge}]},
            "contents": contents,
            "tools": [{"functionDeclarations": [RUN_SQL, SUBMIT]}],
            "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
            "generationConfig": config,
        }

    def investigate(self, question: str, reason: str) -> Investigation:
        result = Investigation(outcome="not_answered", question=question, reason=reason, model=self.model.model)
        contents: list[dict[str, Any]] = [{
            "role": "user",
            "parts": [{"text": (
                f"Question: {question}\n"
                f"Why the fixed database rules handed this over: {reason}.\n"
                "Investigate with run_sql, then call submit_answer."
            )}],
        }]
        repairs = 0
        for _ in range(self.max_turns):
            result.model_calls += 1
            try:
                response = self.model.call(self._payload(contents))
            except Exception as exc:
                # Transport/client failures must still produce a saved case.
                result.failure = "the AI model request failed (" + type(exc).__name__ + ")"
                break
            usage = response.get("usageMetadata") or {}
            result.prompt_tokens += int(usage.get("promptTokenCount") or 0)
            result.output_tokens += int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
            if response.get("error"):
                result.failure = f"the AI model was unavailable ({response['error']})"
                break
            candidates = response.get("candidates") or []
            parts = ((candidates[0] if candidates else {}).get("content") or {}).get("parts") or []
            calls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            if not calls:
                contents.append({"role": "user", "parts": [{"text": "Call run_sql or submit_answer."}]})
                continue
            replies = []
            finished = False
            for call in calls:
                name, args = call.get("name"), call.get("args") or {}
                if name == "run_sql":
                    if len(result.queries) >= self.max_queries:
                        reply = {"error": f"query limit ({self.max_queries}) reached; call submit_answer now"}
                    else:
                        query = self.database.run(str(args.get("sql", "")), str(args.get("purpose", "")))
                        result.queries.append(query)
                        result.trace.append(f"query {len(result.queries)}: {query.error or f'{len(query.rows)} rows'}")
                        reply = query.for_model(len(result.queries))
                elif name == "submit_answer":
                    try:
                        problem = self._accept(result, args)
                    except (TypeError, ValueError, AttributeError, KeyError) as exc:
                        problem = "malformed answer fields: " + type(exc).__name__
                    if problem is None:
                        finished = True
                        reply = {"accepted": True}
                    else:
                        repairs += 1
                        result.trace.append("answer rejected: " + problem)
                        reply = {"rejected": problem}
                        if repairs > 2:
                            result.failure = "the AI answer failed the number check: " + problem
                            finished = True
                else:
                    reply = {"error": f"unknown tool {name}"}
                function_response = {"name": name or "unknown", "response": reply}
                if call.get("id"):
                    function_response["id"] = call["id"]
                replies.append({"functionResponse": function_response})
            if finished:
                break
            contents.append({"role": "user", "parts": replies})
        else:
            result.failure = result.failure or f"no checked answer within {self.max_turns} model turns"
        if result.outcome == "not_answered" and not result.failure:
            result.failure = "no checked answer was produced"
        if result.outcome == "not_answered" and self.backlog is not None:
            self.backlog.add(
                question, result.failure, result.tried(), handed_off_because=reason,
                model=result.model, path="AI investigation",
            )
        return result

    def _accept(self, result: Investigation, args: dict[str, Any]) -> str | None:
        """Validate a submission. Returns a problem to send back, or None when accepted."""
        outcome = args.get("outcome")
        if outcome == "clarify":
            question = str(args.get("clarification_question") or "").strip()
            if not question:
                return "clarify needs clarification_question"
            result.outcome = "clarify"
            result.clarification_question = question
            result.clarification_options = [str(o) for o in args.get("clarification_options") or []][:5]
            return None
        if outcome == "cannot_answer":
            result.failure = str(args.get("reason") or "the AI could not find a reliable way to answer")
            return None
        if outcome != "answered":
            return "outcome must be answered, clarify or cannot_answer"
        good = [i for i, q in enumerate(result.queries, 1) if not q.error and q.rows]
        if not good:
            return "an answer needs at least one successful query with rows"
        tables, used = [], []
        for spec in args.get("tables") or []:
            index = int(spec.get("query") or 0)
            if index not in good:
                return f"table refers to query {index}, which has no successful rows"
            query = result.queries[index - 1]
            columns = [c for c in (spec.get("columns") or query.columns)]
            unknown = [c for c in columns if c not in query.columns]
            if unknown:
                return f"query {index} has no column(s) {unknown}"
            positions = [query.columns.index(c) for c in columns]
            limit = max(1, min(int(spec.get("max_rows") or 25), 50))
            tables.append(TableBlock(
                title=_safe(str(spec.get("title") or f"Query {index}")),
                columns=columns,
                rows=[[row[p] for p in positions] for row in query.rows[:limit]],
            ))
            used.append(index)
        if not tables:
            return "include at least one table copied from a query result"
        showing = _safe(str(args.get("showing") or "").strip())
        answer = _safe(str(args.get("answer") or "").strip())
        limitations = [_safe(str(x)) for x in args.get("limitations") or []]
        definitions = _safe(str(args.get("definitions") or ""))
        text = "\n".join([showing, answer, definitions, *limitations, *(t.title for t in tables)])
        missing = unsupported_numbers(text, result.queries, result.question)
        if missing:
            return (
                "these numbers do not appear in any query result: " + ", ".join(missing)
                + ". Run a query that returns them, or remove them."
            )
        result.outcome = "answered"
        result.showing = showing if showing.lower().startswith("showing:") else "Showing: " + showing
        result.answer, result.tables, result.used_queries = answer, tables, used
        result.limitations, result.definitions = limitations, definitions
        return None


def _safe(text: str) -> str:
    return SOURCE_WORDS.sub("the recorded data", text)


# ---------------------------------------------------------------- presentation
PATH_TITLE = "How this was answered"
RULES_PATH = (
    "Database rules — CricAtlas's fixed, tested database rules matched every part of this question "
    "(players, competition, dates, conditions, metric and grouping)."
)


def _afghan_note() -> EvidenceNote:
    from backend.app.multiformat.answers import AFGHAN_NOTE

    return EvidenceNote(title="Afghanistan coverage", detail=AFGHAN_NOTE)


def _text(headline: str, summary: str, tables: list[TableBlock], notes: list[EvidenceNote]) -> str:
    text = headline + ("\n" + summary.strip() if summary.strip() else "")
    for t in tables:
        text += "\n\n" + t.title + "\n| " + " | ".join(t.columns) + " |\n| " + " | ".join("---" for _ in t.columns) + " |"
        for row in t.rows:
            text += "\n| " + " | ".join("-" if v is None else str(v) for v in row) + " |"
    return text + "\n\nEvidence & limitations\n" + "\n".join(n.title + ": " + n.detail for n in notes)


def render_investigation(result: Investigation) -> tuple[str, QueryResponse]:
    """The checked AI answer in the same shape as a rules answer."""
    notes = [
        EvidenceNote(
            title=PATH_TITLE,
            detail=(
                f"AI investigation — {result.reason}, so an AI model ({result.model}) investigated the whole "
                f"question with {len(result.queries)} read-only database "
                f"quer{'y' if len(result.queries) == 1 else 'ies'}. Every number in this answer was checked "
                "against the query results; tables are copied directly from them."
            ),
        )
    ]
    if result.definitions:
        notes.append(EvidenceNote(title="Definitions", detail=result.definitions))
    for limitation in result.limitations:
        notes.append(EvidenceNote(title="Limitation", detail=limitation))
    for index in range(1, len(result.queries) + 1):
        query = result.queries[index - 1]
        if query.error:
            continue
        notes.append(EvidenceNote(
            title=f"SQL query {index}" + (f" — {_safe(query.purpose)}" if query.purpose else ""),
            detail="\n```sql\n" + query.sql + "\n```",
        ))
    notes.append(_afghan_note())
    response = QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(
            original_question=result.question, query_class="ai_investigation",
            filters={"path": "ai_investigation", "model": result.model},
        ),
        tables=result.tables,
        evidence_notes=notes,
    )
    return _text(result.showing, result.answer, result.tables, notes), response


def render_unanswered(question: str, reason: str, tried: list[str], query_class: str = "not_answered") -> tuple[str, QueryResponse]:
    """A plain 'we could not answer' reply that says why and what was tried."""
    detail = f"I couldn't produce a checked answer to this question. Why: {reason}."
    if tried:
        detail += " What was tried: " + "; ".join(tried) + "."
    detail += " It has been saved as a case to improve."
    notes = [
        EvidenceNote(title=PATH_TITLE, detail="Not answered — " + reason + ". Saved to the improvement backlog."),
        _afghan_note(),
    ]
    response = QueryResponse(
        status=EvidenceStatus.unsupported,
        failure_state="unsupported_capability",
        interpretation=QueryInterpretation(original_question=question, query_class=query_class,
                                           filters={"path": "not_answered"}),
        evidence_notes=notes,
        insufficiencies=[InsufficientEvidenceBlock(title="Not answered", detail=detail)],
    )
    return _text("Not answered", detail, [], notes), response


__all__ = [
    "GeminiToolModel",
    "Investigation",
    "Investigator",
    "QueryResult",
    "ReadOnlyDatabase",
    "SqlRejected",
    "UnansweredBacklog",
    "check_sql",
    "render_investigation",
    "render_unanswered",
    "unsupported_numbers",
]
