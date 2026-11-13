"""Honest self-checks for the database rules.

The rules answer only when every part of the question is accounted for. After
the deterministic reader produces a plan, each word of the question must be one
of: a named player the reader found, a competition/format/venue/team the plan
uses, a year or number the plan uses, a metric or qualifier word the reader
actually interprets, or a meaning-neutral function word. Anything left over
("opening", "chases", "slow", "new ball", "in an innings") is a qualifier the
rules would silently drop, so the question is handed off instead of answering
a simpler question. A refusal by the rules ("I can't answer the X part yet")
hands off too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from backend.app.multiformat.plans import UnderstandingPlan
from backend.app.multiformat.understanding import words

# Words that carry no cricket filter of their own.
FUNCTION_WORDS = set(
    """
    a about all an and any are as at be been being but by can could did do does doing done each
    ever for from get give had has have he her his how i in into is it its let list me my of on
    or our please show tell than that the their them there these they this those to us was we
    were what whats which who whom whose with would you your find see many much times made make
    makes hit hits percentage percent history ever takers taker perform performs performed
    performance year years usually typically generally normally mostly tend tends regularly
    """.split()
)

# Words the rules interpret (scopes, roles, metrics, ranking, phases, bowling
# types, line/length, partnerships, coverage). Derived from the reader's own
# patterns in understanding.py; a word belongs here only if the reader acts on it.
INTERPRETED_WORDS = set(
    """
    test tests odi odis t twenty international internationals one day hundred cricket format formats
    women womens woman female men mens male league leagues franchise franchises domestic first class
    county championship sheffield shield blast vitality ipl bbl psl cpl wpl wbbl sa ilt mlc
    major premier big bash caribbean pakistan super indian except other excluding
    batting bat bats batted batter batters batsman batsmen bowling bowl bowls bowled bowler bowlers
    runs run scored score scores scoring scorer scorers wickets wicket strike rate rates average averages
    economy economical econ dot dots ball balls deliveries delivery faced face faces facing played play
    plays playing sixes fours dismissed dismiss dismisses dismissing got gets out taken take took
    conceded concede conceding career record records stats stat statistics numbers figures overall total
    best highest most top lowest leading fewest fastest quickest slowest worst minimum min least
    compare comparison compared versus vs v against better more often frequent frequently
    powerplay power play middle death final overs over first last
    left right arm fast medium pace pacer pacers seam seamer seamers spin spinner spinners leg off
    orthodox legspin legspinner legspinners offspin offspinner offspinners
    line length lengths short full toss yorker yorkers bouncer bouncers good stump stumps outside wide
    down pitch pitched pitches pitching where profile breakdown by each
    venue venues ground grounds stadium partnership partnerships stand stands pair together
    data coverage covered available availability limits limit far back go
    since between after during season seasons edition player players handle handles handled handling
    cope deal fare fared does
    """.split()
)

NUMBER_WORDS = set(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split()
)


@dataclass(frozen=True, slots=True)
class HandOff:
    reason: str
    leftovers: tuple[str, ...] = ()


def _plan_numbers(plan: UnderstandingPlan) -> set[str]:
    values = [*plan.years, plan.year_from, plan.year_to, plan.min_balls, plan.limit,
              plan.over_from, plan.over_to, plan.partnership_min_runs]
    numbers = {str(v) for v in values if v is not None}
    if plan.year_from is not None:
        numbers.add(str(plan.year_from - 1))  # "after 2019" is stored as 2020
    if plan.over_from is not None and plan.over_to is not None:
        numbers.add(str(plan.over_to - plan.over_from + 1))  # "last 2 overs" is stored as overs 19-20
    return numbers


def _scope_words(plan: UnderstandingPlan) -> set[str]:
    out: set[str] = set()
    for scope in plan.scopes:
        for text in [scope.label, scope.competition or "", *scope.competitions,
                     *scope.excluded_competitions, scope.format or "", *scope.formats]:
            out.update(words(text.replace("%", " ")))
    return out


def _venue_words(plan: UnderstandingPlan, question_words: list[str]) -> set[str]:
    if not plan.venue:
        return set()
    from backend.app.domain.venues import resolve_venue

    out: set[str] = set()
    for name in plan.venue.split("|"):
        venue = resolve_venue(name)
        for text in [name, venue.display_name, *venue.aliases, *venue.search_aliases]:
            out.update(words(text))
    # Initials ("MCG", "SCG") and nicknames resolved by the reader.
    if "at" in question_words:
        tail = question_words[question_words.index("at") + 1:]
        for word in tail[:4]:
            if word not in FUNCTION_WORDS and word not in INTERPRETED_WORDS:
                out.add(word)
                break
    return out


def _player_words(names, player_id: str) -> set[str]:
    player = names.players.get(player_id) or {}
    found = set(words(str(player.get("name") or "")) + words(str(player.get("unique_name") or "")))
    found.update(w for gram, ids in names.by_alias.items() if player_id in ids for w in gram)
    return found


def unmatched_words(question: str, plan: UnderstandingPlan, names) -> list[str]:
    """Question words that no part of the plan accounts for, in question order."""
    tokens = words(question)
    consumed: set[int] = set()
    for start, end, *rest in names.spot(question):
        consumed.update(range(start, end))
        # A misspelled neighbour of a found name ("Jasprit Bumra") belongs to
        # that player when it closely matches one of the player's recorded names.
        ids = rest[1] if len(rest) > 1 else set()
        known_words = {w for pid in ids for w in _player_words(names, pid)}
        for i in (start - 1, end):
            if 0 <= i < len(tokens) and len(tokens[i]) >= 3 and any(
                SequenceMatcher(None, tokens[i], w).ratio() >= 0.8 for w in known_words
            ):
                consumed.add(i)
    for player in plan.players:
        player_words = set(words(player))
        consumed.update(i for i, t in enumerate(tokens) if t in player_words)
    known = FUNCTION_WORDS | INTERPRETED_WORDS | _scope_words(plan) | _venue_words(plan, tokens)
    if plan.opponent:
        known |= set(words(plan.opponent))
    if plan.over_from or plan.over_to:
        known |= NUMBER_WORDS
    if plan.intent == "venue":
        known |= {"innings", "inning"}  # venue summaries report first/second-innings scores
    leftovers = [t for i, t in enumerate(tokens) if i not in consumed and t not in known]
    numbers = _plan_numbers(plan)
    for number in re.findall(r"\b\d+\b", question):
        if number not in numbers and not re.search(rf"\bt{number}\b|\bsa{number}\b|\bilt{number}\b", question.lower()):
            leftovers.append(number)
    return list(dict.fromkeys(leftovers))


def rules_hand_off(question: str, plan: UnderstandingPlan, response, names, message: str = "") -> HandOff | None:
    """Why the rules should not answer this question themselves, or None when they may."""
    status = getattr(getattr(response, "status", None), "value", None)
    if status == "unsupported":
        stated = re.search(r"I can't answer the (.+?) part yet", message or "")
        refused = stated[1] if stated else "; ".join(dict.fromkeys(plan.unsupported)) or "a part of the question"
        return HandOff("the database rules could not answer the " + refused + " part")
    # A collection of individually familiar words can still request a
    # condition/grouping that the plan cannot represent.
    q = question.lower()
    for pattern, reason in [
        (r"\b(?:after|before)\s+(?:the\s+)?(?:powerplay|power play|middle overs|death overs)\b",
         "a condition relative to a phase"),
        (r"\b(?:first|last)\s+(?:legal\s+)?(?:ball|delivery)\b",
         "a specific delivery position"),
        (r"\b(?:by|per|each)\s+(?:year|season|edition)\b|\b(?:year|season)[ -]by[ -](?:year|season)\b",
         "a breakdown by year or season"),
    ]:
        if re.search(pattern, q) and plan.intent != "coverage":
            return HandOff("the database rules do not handle " + reason)
    leftovers = unmatched_words(question, plan, names)
    if leftovers:
        return HandOff(
            "the database rules do not handle the words " + ", ".join(f"“{w}”" for w in leftovers),
            tuple(leftovers),
        )
    return None
