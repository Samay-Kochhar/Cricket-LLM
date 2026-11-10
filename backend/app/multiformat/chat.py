"""Chat answers for formats beyond ODIs (Tests, T20Is, IPL and other leagues).

``MultiFormatChat.reply`` returns ``None`` for any question that does not name
a non-ODI format or competition, so ODI questions keep their existing path and
answers. For the others it answers from the multi-format database and always
states the data's limits: how much of the selected deliveries carry line and
length, and the stored limitation statement for each format involved.

Supported question shapes (deterministic, no model call):
- player numbers in a scope: "Kohli's IPL batting", "Bumrah Test bowling 2024"
- line/length breakdowns: "Kohli against short balls in the IPL", "Bumrah's line in Tests"
- rankings: "best strike rate in the IPL", "most wickets in BBL 2024"
- what data exists: "what line and length data do you have for Tests?"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from backend.app.multiformat.service import DeliveryFilter, MultiFormatService

# Order matters: specific competitions before generic formats.
_SCOPES: tuple[tuple[re.Pattern[str], str, DeliveryFilter], ...] = (
    (re.compile(r"\bIPL\b|indian premier league", re.I), "the IPL", DeliveryFilter(competition="Indian Premier League")),
    (re.compile(r"\bWPL\b|women'?s premier league", re.I), "the WPL", DeliveryFilter(competition="Women's Premier League")),
    (re.compile(r"\bWBBL\b|women'?s big bash", re.I), "the WBBL", DeliveryFilter(competition="Women's Big Bash League")),
    (re.compile(r"\bBBL\b|big bash", re.I), "the BBL", DeliveryFilter(competition="Big Bash League")),
    (re.compile(r"\bCPL\b|caribbean premier league", re.I), "the CPL", DeliveryFilter(competition="Caribbean Premier League")),
    (re.compile(r"\bPSL\b|pakistan super league", re.I), "the PSL", DeliveryFilter(competition="Pakistan Super League")),
    (re.compile(r"\bSA20\b", re.I), "SA20", DeliveryFilter(competition="SA20")),
    (re.compile(r"\bILT20\b|international league t20", re.I), "the ILT20", DeliveryFilter(competition="International League T20")),
    (re.compile(r"\bMLC\b|major league cricket", re.I), "Major League Cricket", DeliveryFilter(competition="Major League Cricket")),
    (re.compile(r"\bT20 Blast\b|\bVitality Blast\b", re.I), "the T20 Blast", DeliveryFilter(competition="%Blast%")),
    (re.compile(r"\bthe hundred\b", re.I), "The Hundred", DeliveryFilter(format="The Hundred")),
    (re.compile(r"\bT20 ?Is?\b|\bT20 internationals?\b|\bT20 world cup\b", re.I), "T20Is", DeliveryFilter(format="T20I")),
    (re.compile(r"\bT20s?\b|\btwenty20\b", re.I), "T20 cricket", DeliveryFilter(formats=("T20I", "T20 domestic"))),
    (re.compile(r"\bTests?\b|\btest (?:cricket|matches|match|career)\b"), "Tests", DeliveryFilter(format="Test")),
    (re.compile(r"\bfirst[- ]class\b|\bcounty championship\b|\bsheffield shield\b", re.I), "first-class cricket",
     DeliveryFilter(format="First-class domestic")),
)
_ODI = re.compile(r"\bODIs?\b|\bone[- ]day international", re.I)
_WOMEN = re.compile(r"\bwomen'?s?\b|\bwomen\b", re.I)
_YEAR = re.compile(r"\b(?:in |during )?((?:19|20)\d{2})\b")
_SINCE = re.compile(r"\b(?:since|from|after) ((?:19|20)\d{2})\b", re.I)
_BOWLING = re.compile(r"\bbowl\w*|\bwickets?\b|\beconomy\b|\bbowler\b|\bconced", re.I)
_LINE = re.compile(r"\bline\b|outside off|on the stumps|down leg|wide outside", re.I)
_LENGTH = re.compile(r"\blengths?\b|yorkers?|full toss|\bfull\b|\bshort\b|bouncers?|half volley|good length", re.I)
_DATA_QUESTION = re.compile(r"\b(data|coverage|available|availability|have|record(?:ed)?|limit\w*)\b", re.I)
_RANKING = re.compile(r"\b(best|highest|most|top|lowest|leading|fewest)\b", re.I)
_STOP = {
    "what", "whats", "how", "who", "which", "is", "are", "was", "the", "in", "of", "for", "and", "against", "did",
    "does", "do", "show", "me", "give", "his", "her", "their", "to", "a", "an", "at", "on", "by", "with", "vs",
    "versus", "batting", "bowling", "record", "stats", "statistics", "numbers", "strike", "rate", "average",
    "economy", "runs", "wickets", "line", "length", "short", "full", "balls", "ball", "since", "from", "career",
}

LENGTH_LABELS = {
    "YORKER": "Yorker", "FULL_TOSS": "Full toss", "FULL": "Full", "GOOD_LENGTH": "Good length",
    "SHORT_OF_A_GOOD_LENGTH": "Short of a good length", "SHORT": "Short",
}
LINE_LABELS = {
    "OUTSIDE_OFFSTUMP": "Outside off", "ON_THE_STUMPS": "On the stumps", "WIDE_OUTSIDE_OFFSTUMP": "Wide outside off",
    "DOWN_LEG": "Down leg", "WIDE_DOWN_LEG": "Wide down leg",
}


@dataclass(frozen=True, slots=True)
class Scope:
    label: str
    flt: DeliveryFilter
    gender_stated: bool = False  # "women's", WPL/WBBL; otherwise men's unless a named player says otherwise


def detect_scope(message: str) -> Scope | None:
    """The non-ODI scope a question names, or None (ODI questions keep their path)."""
    if _ODI.search(message):
        return None
    for pattern, label, flt in _SCOPES:
        if pattern.search(message):
            gender = "female" if _WOMEN.search(message) or label in {"the WPL", "the WBBL"} else "male"
            flt = replace(flt, gender=gender)
            since = _SINCE.search(message)
            year = _YEAR.search(message)
            if since:
                flt = replace(flt, year_from=int(since.group(1)))
                label = f"{label} since {since.group(1)}"
            elif year:
                flt = replace(flt, year_from=int(year.group(1)), year_to=int(year.group(1)))
                label = f"{label} in {year.group(1)}"
            if gender == "female" and "women" not in label.lower() and label not in {"the WPL", "the WBBL"}:
                label = f"women's {label}"
            return Scope(label=label, flt=flt, gender_stated=gender == "female")
    return None


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return f"{value:,}"


@dataclass(slots=True)
class MultiFormatAnswer:
    message: str
    suggestions: list[str]
    clarification: list[str] | None = None


class MultiFormatChat:
    def __init__(self, service: MultiFormatService) -> None:
        self.service = service

    # ----------------------------------------------------------------- routing
    def answer(self, message: str) -> MultiFormatAnswer | None:
        scope = detect_scope(message)
        if scope is None:
            return None
        role = "bowling" if _BOWLING.search(message) else "batting"
        if not scope.gender_stated:
            # A named player's own matches decide men's or women's cricket.
            player_scope = replace(scope, flt=replace(scope.flt, gender=None))
        else:
            player_scope = scope
        player = self._resolve_player(message, player_scope)
        if isinstance(player, dict):
            scope = player_scope
        if isinstance(player, list):
            names = ", ".join(p["name"] for p in player)
            return MultiFormatAnswer(
                message=f"More than one player matches that name in {scope.label}: {names}. Which one do you mean?",
                suggestions=[],
                clarification=[f"{message} ({p['name']})" for p in player],
            )
        dims = [d for d, rx in (("length", _LENGTH), ("line", _LINE)) if rx.search(message)]
        if player is None:
            if _RANKING.search(message) and not (dims and _DATA_QUESTION.search(message)):
                return self._ranking_answer(message, scope, role)
            return self._coverage_answer(scope)
        if dims:
            return self._line_length_answer(player, role, dims, scope)
        return self._stats_answer(player, role, scope)

    def _resolve_player(self, message: str, scope: Scope) -> dict[str, Any] | list[dict[str, Any]] | None:
        words = re.findall(r"[A-Za-z][A-Za-z'\-.]*", message)
        words = [re.sub(r"'s$", "", w) for w in words]
        ngrams: list[tuple[int, str]] = []
        for size in (4, 3, 2):
            for i in range(len(words) - size + 1):
                gram = words[i : i + size]
                if all(w.lower() not in _STOP for w in gram):
                    ngrams.append((size, " ".join(gram)))
        found = self.service.resolve_names([g for _, g in ngrams])
        for size, gram in ngrams:  # longest name first
            candidates = found.get(gram.lower())
            if candidates:
                return candidates[0]
        # A lone capitalised surname ("Kohli"): rank players with that surname in the scope.
        for word in words:
            if word[:1].isupper() and word.lower() not in _STOP and len(word) > 2 and not any(
                p.search(word) for p, _, _ in _SCOPES
            ):
                matches = self.service.players_by_surname(word, scope.flt)
                if not matches:
                    continue
                if len(matches) == 1 or matches[0]["matches"] >= 3 * matches[1]["matches"]:
                    return matches[0]
                return matches[:4]
        return None

    # ----------------------------------------------------------------- answers
    def _limitation_lines(self, scope: Scope) -> list[str]:
        no_years = replace(scope.flt, year_from=None, year_to=None)
        return [row["statement"] for row in self.service.limitations(no_years)]

    def _coverage_answer(self, scope: Scope) -> MultiFormatAnswer:
        lines = [f"What CricAtlas holds for {scope.label}:"]
        lines += [f"- {text}" for text in self._limitation_lines(scope)] or ["- No matches are recorded for this scope."]
        lines.append("Name a player to see their numbers, or ask for a ranking (e.g. best strike rate).")
        return MultiFormatAnswer("\n".join(lines), [f"Best strike rate in {scope.label}", f"Most wickets in {scope.label}"])

    def _stats_answer(self, player: dict[str, Any], role: str, scope: Scope) -> MultiFormatAnswer:
        rows = self.service.player_stats(player["player_id"], role, scope.flt)
        name = player["name"]
        if not rows:
            return MultiFormatAnswer(
                f"No {role} deliveries for {name} in {scope.label} in the CricAtlas data.", []
            )
        lines = [f"{name}, {role} in {scope.label}:"]
        for r in rows:
            span = f"{r['first_match']:%b %Y} to {r['last_match']:%b %Y}"
            if role == "batting":
                lines.append(
                    f"- {r['format']}: {_fmt(r['matches'])} matches, {_fmt(r['runs'])} runs off {_fmt(r['balls'])} balls, "
                    f"strike rate {_fmt(r['strike_rate'])}, average {_fmt(r['average'])} ({_fmt(r['dismissals'])} dismissals), "
                    f"{_fmt(r['fours'])} fours, {_fmt(r['sixes'])} sixes, dot balls {_fmt(r['dot_ball_pct'], 1)}% ({span})."
                )
            else:
                lines.append(
                    f"- {r['format']}: {_fmt(r['matches'])} matches, {_fmt(r['wickets'])} wickets from {_fmt(r['balls'])} balls, "
                    f"economy {_fmt(r['economy'])}, average {_fmt(r['average'])}, strike rate {_fmt(r['strike_rate'])}, "
                    f"dot balls {_fmt(r['dot_ball_pct'], 1)}% ({span})."
                )
        lines.append("Scores and results come from Cricsheet.")
        return MultiFormatAnswer(
            "\n".join(lines),
            [f"{name} {role} by length in {scope.label}", f"{name} {role} by line in {scope.label}"],
        )

    def _line_length_answer(self, player: dict[str, Any], role: str, dims: list[str], scope: Scope) -> MultiFormatAnswer:
        name = player["name"]
        lines: list[str] = []
        limitations: list[str] = []
        for dim in dims:
            result = self.service.line_length(player["player_id"], role, dim, scope.flt)
            labels = LENGTH_LABELS if dim == "length" else LINE_LABELS
            lines.append(f"{name}, {role} by {dim} in {scope.label}:")
            for r in result["rows"]:
                label = labels.get(r[dim], r[dim])
                if role == "batting":
                    lines.append(
                        f"- {label}: {_fmt(r['balls'])} balls, {_fmt(r['runs'])} runs, strike rate {_fmt(r['strike_rate'])}, "
                        f"{_fmt(r['dismissals'])} dismissals, dot balls {_fmt(r['dot_ball_pct'], 1)}%"
                    )
                else:
                    lines.append(
                        f"- {label}: {_fmt(r['balls'])} balls, {_fmt(r['wickets'])} wickets, economy {_fmt(r['economy'])}, "
                        f"dot balls {_fmt(r['dot_ball_pct'], 1)}%"
                    )
            lines.append(f"Data limit: {result['note']}")
            if not result["complete"]:
                limitations += [row["statement"] for row in result["limitations"]]
        for text in dict.fromkeys(limitations):
            lines.append(f"Coverage: {text}")
        other = "line" if dims == ["length"] else "length"
        return MultiFormatAnswer("\n".join(lines), [f"{name} {role} by {other} in {scope.label}", f"{name} {role} in {scope.label}"])

    def _ranking_answer(self, message: str, scope: Scope, role: str) -> MultiFormatAnswer:
        lowered = message.lower()
        if role == "bowling":
            metric = "economy" if "economy" in lowered else "average" if "average" in lowered else \
                "strike_rate" if "strike rate" in lowered else "wickets"
        else:
            metric = "strike_rate" if "strike rate" in lowered else "average" if "average" in lowered else "runs"
        rows = self.service.leaderboard(role, metric, scope.flt)
        nice = metric.replace("_", " ")
        if not rows:
            return MultiFormatAnswer(f"No {role} rankings are available for {scope.label}.", [])
        rate_note = " (minimum 60 balls)" if metric != "runs" and metric != "wickets" else ""
        who = "batters" if role == "batting" else "bowlers"
        lines = [f"Top {who} by {nice} in {scope.label}{rate_note}:"]
        for i, r in enumerate(rows, 1):
            if role == "batting":
                lines.append(
                    f"{i}. {r['name']}: {_fmt(r['runs'])} runs off {_fmt(r['balls'])} balls, strike rate {_fmt(r['strike_rate'])}, "
                    f"average {_fmt(r['average'])}"
                )
            else:
                lines.append(
                    f"{i}. {r['name']}: {_fmt(r['wickets'])} wickets from {_fmt(r['balls'])} balls, economy {_fmt(r['economy'])}, "
                    f"average {_fmt(r['average'])}"
                )
        lines.append("Scores and results come from Cricsheet.")
        return MultiFormatAnswer("\n".join(lines), [f"{rows[0]['name']} {role} by length in {scope.label}"])
