"""Deterministic reading and database-backed name validation, shared with models."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from backend.app.multiformat.plans import ScopePlan, UnderstandingPlan
from backend.app.multiformat.service import DeliveryFilter, _rows

# The user's product vocabulary defines franchise/other leagues as all domestic T20.
FRANCHISE_GROUP = {"format": "T20 domestic"}
COMPETITIONS = [
    (r"\bIPL\b|indian premier league", "IPL", "Indian Premier League"),
    (r"\bWPL\b|women'?s premier league", "WPL", "Women's Premier League"),
    (r"\bWBBL\b|women'?s big bash", "WBBL", "Women's Big Bash League"),
    (r"(?<!women's )\bBBL\b|(?<!women's )\bbig bash", "BBL", "Big Bash League"),
    (r"\bCPL\b|caribbean premier league", "CPL", "Caribbean Premier League"),
    (r"\bPSL\b|pakistan super league", "PSL", "Pakistan Super League"),
    (r"\bSA20\b", "SA20", "SA20"),
    (r"\bILT20\b|international league t20", "ILT20", "International League T20"),
    (r"\bMLC\b|major league cricket", "MLC", "Major League Cricket"),
    (r"\b(?:T20|Vitality) Blast\b", "T20 Blast", "%Blast%"),
    (r"county championship", "County Championship", "%County Championship%"),
    (r"sheffield shield", "Sheffield Shield", "%Sheffield Shield%"),
]
STOP = set(
    "what whats how who which is are was the in of for and against did does do show me give his her their to a an at on by with vs versus batting bowling record stats statistics numbers strike rate average economy economical runs wickets line length short full balls ball since from career best most highest lowest leading top data limits formats compare comparison powerplay death middle overs venue score scored has have many hit taken women womens men mens hundred test tests t20 t20i ipl bbl psl cpl wpl wbbl sa20 county championship blast fast medium pace spin left right arm leg off stump innings batter batters batsman batsmen bowler bowlers player players keeper keepers wicketkeeper fielder fielders captain finisher opener openers".split()
)
STOP.update(
    "or than more better often does each do cricket takers minimum outside international internationals format per".split()
)
STOP.update(
    "scoring scorers spinner spinners seamer seamers franchise franchises league leagues deliveries international internationals".split()
)


def words(s):
    return re.findall(r"[a-z]+", re.sub(r"['’]s\b", "", s.lower()))


class NameIndex:
    def __init__(self, service):
        self.service = service
        self._scope_work = {}
        with service._connect() as conn:
            self.players = {
                r["player_id"]: r
                for r in _rows(conn, "SELECT * FROM analytics.players")
            }
            self.aliases = _rows(
                conn, "SELECT name, player_id FROM analytics.player_names"
            )
            self.work = {
                r["id"]: r
                for r in _rows(
                    conn,
                    """
                SELECT id, sum(bat) AS bat, sum(bowl) AS bowl FROM (
                SELECT batter_id AS id, count(*) AS bat, 0 AS bowl FROM analytics.deliveries GROUP BY 1
                UNION ALL SELECT bowler_id, 0, count(*) FROM analytics.deliveries GROUP BY 1) GROUP BY id
            """,
                )
            }
            columns = {
                r[0] for r in conn.execute("DESCRIBE analytics.deliveries").fetchall()
            }
            self.teams = (
                [
                    r[0]
                    for r in conn.execute(
                        "SELECT DISTINCT batting_team FROM analytics.deliveries WHERE batting_team IS NOT NULL"
                    ).fetchall()
                ]
                if "batting_team" in columns
                else []
            )
            self.competitions = _rows(
                conn,
                "SELECT DISTINCT competition,format,gender FROM analytics.coverage WHERE competition IS NOT NULL AND format NOT IN ('ODI','Test','T20I') ORDER BY competition, format, gender",
            )
        self.by_alias = {}
        self.surnames = {}
        for row in self.aliases:
            key = tuple(words(row["name"]))
            if not key or (len(key) == 1 and key[0] in STOP):
                continue
            self.by_alias.setdefault(key, set()).add(row["player_id"])
            if len(key) > 1 and len(key[0]) > 3 and key[0] not in STOP:
                self.by_alias.setdefault((key[0],), set()).add(row["player_id"])
        for pid, p in self.players.items():
            key = words(p["name"])
            if key and key[-1] not in STOP and len(key[-1]) >= 3:
                self.by_alias.setdefault((key[-1],), set()).add(pid)
                if len(key) > 1:
                    self.surnames.setdefault(key[-1], set()).add(pid)

    def spot(self, question):
        tokens = words(question)
        raw_tokens = re.findall(
            r"[A-Za-z]+", re.sub(r"['’]s\b", "", question, flags=re.I)
        )
        hits = []
        for size in (4, 3, 2, 1):
            for i in range(len(tokens) - size + 1):
                gram = tuple(tokens[i : i + size])
                if any(
                    j in {k for h in hits for k in range(h[0], h[1])}
                    for j in range(i, i + size)
                ):
                    continue
                if size == 1 and (gram[0] in STOP or len(gram[0]) < 3):
                    continue
                ids = self.by_alias.get(gram, set())
                if not ids and size >= 2 and not any(t in STOP for t in gram):
                    # Full names may be stored as initials. Every given initial
                    # must agree; popularity alone never resolves a surname.
                    surname = gram[-1]
                    ids = {
                        pid
                        for pid, p in self.players.items()
                        if words(p["name"])[-1:] == [surname]
                        and "".join(
                            t if len(t) <= 3 else t[0] for t in words(p["name"])[:-1]
                        ).startswith("".join(t[0] for t in gram[:-1]))
                    }
                if ids:
                    hits.append((i, i + size, " ".join(gram), ids))
        # Process unmatched spans even when a different participant matched.
        # Otherwise a typo in a head-to-head silently becomes one career.
        occupied = {k for h in hits for k in range(h[0], h[1])}
        for i in range(len(tokens) - 1):
            if i not in occupied and i + 1 not in occupied:
                a, b = tokens[i : i + 2]
                if a in STOP or b in STOP:
                    continue
                ranked = []
                for pid, p in self.players.items():
                    nw = words(p["name"])
                    if (
                        len(nw) > 1
                        and nw[0][0] == a[0]
                        and min(len(b), len(nw[-1])) >= 4
                    ):
                        score = SequenceMatcher(None, b, nw[-1]).ratio()
                        if score >= 0.84:
                            ranked.append((score, pid))
                if ranked:
                    best = max(s for s, _ in ranked)
                    hits.append(
                        (i, i + 2, a + " " + b, {pid for s, pid in ranked if s == best})
                    )
                    occupied.update((i, i + 1))
        for i, token in enumerate(tokens):
            if (
                i in occupied
                or token in STOP
                or len(token) < 6
                or not raw_tokens[i][0].isupper()
            ):
                continue
            ranked = []
            for pid, player in self.players.items():
                surname = words(player["name"])[-1]
                if len(surname) < 6:
                    continue
                score = SequenceMatcher(None, token, surname).ratio()
                if score >= 0.84:
                    ranked.append((score, pid))
            if ranked:
                hits.append(
                    (
                        i,
                        i + 1,
                        raw_tokens[i],
                        {pid for _, pid in ranked},
                    )
                )
        return sorted(hits)

    def resolve(self, name):
        hits = self.spot(name)
        ids = set().union(*(h[3] for h in hits)) if hits else set()
        return [self.players[pid] for pid in sorted(ids)]

    def choose(self, name, scopes=()):
        candidates = self.resolve(name)
        if len(candidates) <= 1:
            return candidates
        # Identity resolution uses the requested scope and its observed sample,
        # never the question metric. Ambiguous peers require clarification.
        selected = []
        scoped_work = None
        if scopes:
            key = (
                tuple(s.model_dump_json() for s in scopes),
                tuple(p["player_id"] for p in candidates),
            )
            if key not in self._scope_work:
                conditions, params = [], [p["player_id"] for p in candidates]
                for scope in scopes:
                    where, values = delivery_filter(UnderstandingPlan(), scope).sql()
                    conditions.append("(" + where + ")")
                    params.extend(values)
                with self.service._connect() as conn:
                    rows = _rows(
                        conn,
                        f"""SELECT p.player_id,count(*) AS n
                        FROM analytics.players p JOIN analytics.deliveries d
                          ON d.batter_id=p.player_id OR d.bowler_id=p.player_id
                        WHERE p.player_id IN ({','.join('?' for _ in candidates)})
                          AND ({' OR '.join(conditions)}) GROUP BY p.player_id""",
                        params,
                    )
                self._scope_work[key] = {r["player_id"]: r["n"] for r in rows}
            scoped_work = self._scope_work[key]
        for p in candidates:
            work = self.work.get(p["player_id"], {})
            count = (
                scoped_work.get(p["player_id"], 0)
                if scoped_work is not None
                else work.get("bat", 0) + work.get("bowl", 0)
            )
            selected.append((count, p))
        name_tokens = words(name)
        if len(name_tokens) == 1:
            surname_ids = self.surnames.get(name_tokens[0], set())
            exact_surnames = [
                (count, p)
                for count, p in selected
                if count and p["player_id"] in surname_ids
            ]
            if exact_surnames:
                # A known surname outranks a derived given-name alias in the
                # same scope. If that surname has no sample, the given-name
                # candidates remain available (e.g. a player known by a first name).
                selected = exact_surnames
        selected.sort(key=lambda x: -x[0])
        if (
            selected
            and selected[0][0] > 0
            and (len(selected) == 1 or selected[0][0] >= 3 * max(selected[1][0], 1))
        ):
            return [selected[0][1]]
        return candidates


# "at" phrases that name a phase, position or moment rather than a ground.
NOT_A_VENUE = re.compile(
    r"\bat\s+(?:the\s+)?(?:death|start|end|top|crease|close|finish|"
    r"(?:no\.?|number)\s*\d+|\d+(?:st|nd|rd|th)?\s+(?:wicket|down|position))\b"
)


def _venues_by_initials(needle, venues, matches=None):
    """'MCG' -> Melbourne Cricket Ground: an all-letters short name that spells
    the initials of a ground's name (before any comma)."""
    letters = re.sub(r"[^a-z]", "", needle.lower())
    if not 2 <= len(letters) <= 5 or " " in needle.strip():
        return []
    out = []
    for venue in venues:
        head = venue.split(",")[0]
        initials = "".join(
            w[0] for w in re.findall(r"[A-Za-z][A-Za-z']*", head)
        ).lower()
        if initials == letters:
            out.append(venue)
    if len(out) > 1 and matches:
        # Several grounds share the initials (Melbourne/Malahide Cricket Ground):
        # take the clearly dominant one in this scope, otherwise none (the
        # question is then reported as an unresolved venue, not guessed).
        out.sort(key=lambda v: -matches.get(v, 0))
        top, second = matches.get(out[0], 0), matches.get(out[1], 0)
        return [out[0]] if top >= 3 * max(second, 1) else []
    return out


def _venue_head(name):
    return re.sub(r"^the\s+", "", name.split(",")[0].strip().lower())


def _venues_via_registry(needle, venues, matches=None):
    """A nickname the verified venue registry knows ('the Gabba', 'Chepauk')
    mapped to this database's spelling by the ground's main name."""
    from backend.app.domain.venues import VENUES

    pattern = re.compile(r"(?<!\w)" + re.escape(needle.lower()) + r"(?!\w)")
    grounds = []  # one list of this database's names per physical ground
    for venue in VENUES:
        names = (*venue.aliases, *venue.search_aliases)
        if any(pattern.search(n.lower()) for n in names):
            heads = {_venue_head(n) for n in venue.aliases}
            hit = [v for v in venues if _venue_head(v) in heads]
            if hit:
                grounds.append(hit)
    if len(grounds) > 1 and matches:
        # Different grounds share the nickname: keep a clearly dominant one.
        grounds.sort(key=lambda g: -sum(matches.get(v, 0) for v in g))
        top = sum(matches.get(v, 0) for v in grounds[0])
        second = sum(matches.get(v, 0) for v in grounds[1])
        return grounds[0] if top >= 3 * max(second, 1) else []
    return grounds[0] if len(grounds) == 1 else []


def _same_ground_names(found, venues):
    """Add this database's other names for the same physical ground
    (Feroz Shah Kotla / Arun Jaitley Stadium) per the verified registry."""
    from backend.app.domain.venues import VENUES

    if not found:
        return found
    found_heads = {_venue_head(v) for v in found}
    heads = set(found_heads)
    for venue in VENUES:
        alias_heads = {_venue_head(n) for n in venue.aliases}
        if alias_heads & found_heads:
            heads |= alias_heads
    return sorted({*found, *(v for v in venues if _venue_head(v) in heads)})


class DeterministicPlanner:
    def __init__(self, service):
        self.service = service
        self.names = NameIndex(service)

    def _specialism(self, name, scopes=()):
        """'bowler' when a player bowled at least 3x the balls he faced,
        'batter' when the reverse, else 'all-rounder' (or unknown)."""
        resolved = self.names.choose(name, scopes)
        if len(resolved) != 1:
            return "unknown"
        w = self.names.work.get(resolved[0]["player_id"], {})
        bat, bowl = w.get("bat", 0) or 0, w.get("bowl", 0) or 0
        if bowl >= 3 * max(bat, 1):
            return "bowler"
        if bat >= 3 * max(bowl, 1):
            return "batter"
        return "all-rounder"

    def read(self, question):
        q = question.lower().replace("’", "'")
        p = UnderstandingPlan()
        female = bool(re.search(r"women|\bWPL\b|\bWBBL\b", question, re.I))
        gender = "female" if female else "male"
        franchise = bool(re.search(r"franchise leagues?", q))
        if franchise:
            p.scopes = [
                ScopePlan(
                    label="domestic T20 leagues", format="T20 domestic", gender=gender
                )
            ]
            if re.search(r"(?:except|other than|excluding) (?:the )?ipl", q):
                p.scopes[0].excluded_competitions = ["Indian Premier League"]
        else:
            for pattern, label, competition in COMPETITIONS:
                if re.search(pattern, q, re.I):
                    p.scopes.append(
                        ScopePlan(label=label, competition=competition, gender=gender)
                    )
            if not p.scopes:
                for row in self.names.competitions:
                    if re.search(
                        r"(?<!\w)" + re.escape(row["competition"].lower()) + r"(?!\w)",
                        q,
                    ):
                        p.scopes.append(
                            ScopePlan(
                                label=row["competition"],
                                competition=row["competition"],
                                gender=row["gender"],
                            )
                        )
            if not p.scopes or re.search(r"compare|across|versus|\bvs\b", q):
                for pattern, label, fmt in [
                    (
                        r"\b(?:the |women's |men's )?hundred\b",
                        "The Hundred",
                        "The Hundred",
                    ),
                    (r"\bt20\s?is?\b|t20 internationals?", "T20Is", "T20I"),
                    (r"\btests?\b", "Tests", "Test"),
                    (r"\bodis?\b|one.day international", "ODIs", "ODI"),
                    (r"first.class", "first-class cricket", "First-class domestic"),
                ]:
                    if re.search(pattern, q):
                        p.scopes.append(
                            ScopePlan(label=label, format=fmt, gender=gender)
                        )
            if re.search(r"\bt20s?\b|twenty20", q) and (
                not p.scopes or any(s.format == "ODI" for s in p.scopes)
            ):
                p.scopes.append(
                    ScopePlan(
                        label="T20 cricket",
                        formats=["T20I", "T20 domestic"],
                        gender=gender,
                    )
                )
        coverage = bool(
            re.search(
                r"\bdata\b|coverage|\bcovered\b|which formats|limits|availability|available|how far back|go back to",
                q,
            )
        )
        if not p.scopes and not coverage:
            return None
        if len(p.scopes) == 1 and p.scopes[0].format == "ODI" and not coverage:
            return None
        p.intent = "coverage" if coverage else "stats"
        if coverage and not re.search(
            r"women|\bWPL\b|\bWBBL\b|\bmen'?s?\b", question, re.I
        ):
            for scope in p.scopes:
                if scope.competition is None and not scope.competitions:
                    scope.gender = None
        name_question = re.sub(
            r"\bat\s+.+?(?=\s+in\b|\s+since\b|$)", " ", question, flags=re.I
        )
        p.players = [h[2] for h in self.names.spot(name_question)]
        if p.players and not re.search(
            r"women|\bWPL\b|\bWBBL\b|\bmen'?s?\b", question, re.I
        ):
            for scope in p.scopes:
                scope.gender = None
        if (
            re.search(
                r"\b(?:best|highest|most|top|lowest|leading|fewest|fastest|quickest|slowest)\b",
                q,
            )
            and not coverage
        ):
            p.intent = "ranking"
        if re.search(r"partnership|\bstand(?:s)?\b|\bpair\b", q):
            p.intent = "partnership"
        if len(p.players) > 1:
            if p.intent == "partnership":
                pass
            elif re.search(r"compare|\bor\b|more|better", q):
                p.intent = "comparison"
            elif re.search(r"dismiss|got out|gets out", q):
                p.intent = "matchup"
            else:
                # "A vs B" is a head-to-head unless both are the same kind of
                # specialist: two batters (or two bowlers) are a comparison.
                kinds = [self._specialism(name, p.scopes) for name in p.players[:2]]
                same = kinds[0] == kinds[1] and kinds[0] in {"batter", "bowler"}
                p.intent = "comparison" if same else "matchup"
        if len(p.scopes) > 1 and p.players:
            p.intent = "comparison"
        # Role language nearest the subject takes precedence over the word
        # "bowling" in a batter's opponent/filter phrase.
        against_type = bool(
            re.search(
                r"(?:against|\bvs\b|versus|\bfac(?:e|es|ed|ing)\b|handl(?:e|es|ed|ing)|\bplay(?:s|ed|ing)?\b|cope with|deal with)"
                r".*(?:bowling|bowlers?|spinn|pace|seam|arm|short|length|full|yorkers?|bouncers?|deliver)",
                q,
            )
            or re.search(
                r"(?:short|short.pitched|full|spin|pace|seam|fast|medium|wrist|orthodox|quick)\W+(?:pitched\W+)?bowling",
                q,
            )
            and not re.search(
                r"\bbowl(?:s|ed)\b|\bbowler'?s\b|wickets?|econom|conced", q
            )
        )
        explicit_bat = bool(
            re.search(
                r"\bbat(?:ting|smen|ters?)?\b|with the bat|scor(?:e|ed|ing)|\bruns\b|\bsixes\b",
                q,
            )
        )
        explicit_bowl = bool(
            re.search(
                r"\bbowl(?:ing|er|ers|s)?\b|wickets?|econom|conced|pitch(?:es)?|dismissed",
                q,
            )
        )
        p.role = (
            "bowling"
            if explicit_bowl and not against_type and not explicit_bat
            else "batting"
        )
        if p.players and not explicit_bat and not explicit_bowl and not against_type:
            # Only a clear specialist bowler (or all named players being one)
            # turns an unqualified metric into a bowling question; all-rounders
            # default to batting, which the interpretation line states.
            if all(self._specialism(name, p.scopes) == "bowler" for name in p.players):
                p.role = "bowling"
        for pattern, metric in [
            (r"strike rates?", "strike_rate"),
            (r"averages?", "average"),
            (r"econom", "economy"),
            (r"\bruns?\b", "runs"),
            (r"wicket|dismissed", "wickets"),
            (r"dot", "dot_ball_pct"),
            (r"\bsixes\b", "sixes"),
            (r"\bfours\b", "fours"),
        ]:
            if re.search(pattern, q):
                p.metrics.append(metric)
        if not p.metrics and re.search(r"\b(?:fastest|quickest|slowest)\b", q):
            p.metrics = ["strike_rate"]
        if not p.metrics:
            p.metrics = (
                [
                    "wickets",
                    "balls",
                    "economy",
                    "average",
                    "strike_rate",
                    "dot_ball_pct",
                ]
                if p.role == "bowling"
                else [
                    "runs",
                    "balls",
                    "strike_rate",
                    "average",
                    "fours",
                    "sixes",
                    "dot_ball_pct",
                ]
            )
            if p.intent == "matchup":
                p.metrics = ["runs", "balls", "strike_rate", "wickets"]
            elif p.intent == "ranking":
                p.metrics = ["wickets" if p.role == "bowling" else "runs"]
        years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", q)]
        if years:
            if re.search(r"since|from|after", q) and len(years) == 1:
                p.year_from = years[0] + int(bool(re.search(r"after", q)))
            elif len(years) == 2 and re.search(r"between|\d{4}\s*(?:to|[-–])", q):
                p.year_from, p.year_to = min(years), max(years)
            else:
                p.years = sorted(set(years))
        sample = re.search(r"(?:minimum|min\.?|at least)\s*(\d+)\s*(?:legal )?balls", q)
        if sample:
            p.min_balls = int(sample[1])
        top = re.search(r"top\s+(\d+)", q)
        if top:
            p.limit = min(int(top[1]), 100)
        if re.search(r"lowest|fewest|worst|slowest", q):
            p.descending = False
        if re.search(r"highest", q):
            p.descending = True
        for phase, pattern in [
            ("powerplay", r"powerplay|power play"),
            ("middle", r"middle overs"),
            ("death", r"death|final overs"),
        ]:
            if re.search(pattern, q):
                p.phase = phase
        overs = re.search(r"overs?\s+(\d+)\s*[-–to]+\s*(\d+)", q)
        if overs:
            p.over_from, p.over_to = int(overs[1]), int(overs[2])
        relative_overs = re.search(r"\b(first|last|final)\s+(\d+|[a-z]+)\s+overs?\b", q)
        if relative_overs:
            number_words = dict(
                zip(
                    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(),
                    range(1, 21),
                )
            )
            n = (
                int(relative_overs[2])
                if relative_overs[2].isdigit()
                else number_words.get(relative_overs[2])
            )
            formats = set()
            for scope in p.scopes:
                formats.update(scope.formats)
                if scope.format:
                    formats.add(scope.format)
                if scope.competition:
                    formats.update(
                        r["format"]
                        for r in self.names.competitions
                        if r["competition"] == scope.competition
                    )
            scheduled = (
                20
                if formats
                and formats <= {"T20I", "T20 domestic", "T20 (other international)"}
                else (50 if formats == {"ODI"} else None)
            )
            if n and scheduled and n <= scheduled:
                p.over_from, p.over_to = (
                    (1, n)
                    if relative_overs[1] == "first"
                    else (scheduled - n + 1, scheduled)
                )
            else:
                p.unsupported.append("relative over window for this format")
        if re.search(r"left.arm fast", q):
            p.bowler_styles = ["LF", "LFM"]
        elif re.search(r"left.arm medium", q):
            p.bowler_styles = ["LM", "LMF"]
        elif re.search(r"leg.?spin", q):
            p.bowler_styles = ["LB", "LBG"]
        elif re.search(r"off.?spin", q):
            p.bowler_styles = ["OB"]
        elif re.search(r"left.arm spin|left.arm orthodox", q):
            p.bowler_styles = ["SLA"]
        elif re.search(r"pace|fast bowl|seam", q):
            p.bowler_kind = "pace bowler"
        elif re.search(r"\bspin(?:ners)?\b", q):
            p.bowler_kind = "spin bowler"
        if re.search(r"left.arm", q) and not p.bowler_styles:
            p.bowler_arm = "left"
        if re.search(r"right.arm", q) and not p.bowler_styles:
            p.bowler_arm = "right"
        for team in sorted(self.names.teams, key=len, reverse=True):
            if re.search(
                r"\b(?:against|vs|versus|v)\s+" + re.escape(team.lower()) + r"\b", q
            ):
                p.opponent = team
                break
        for dim, pattern in [
            ("line", r"\bline\b|outside off|off stump|down leg|on the stumps"),
            ("length", r"length|yorker|short|bouncer|full toss|\bfull\b"),
        ]:
            if re.search(pattern, q):
                p.dimensions.append(dim)
        if p.players and p.dimensions and re.search(r"most often|most frequent", q):
            p.intent = "stats"
            p.metrics = ["balls"]
        # "by length" asks for all categories; a named category is a filter.
        if not re.search(r"by length|each length|length profile|length.*most often", q):
            # A compound category is consumed first so its words ("short",
            # "good length") are not read again as separate categories.
            sogl = re.search(r"short.of.a.good.length", q)
            if sogl:
                p.lengths.append("SHORT_OF_A_GOOD_LENGTH")
            lq = re.sub(r"short.of.a.good.length", " ", q)
            for pat, val in [
                (r"yorker", "YORKER"),
                (r"full toss", "FULL_TOSS"),
                (r"good length", "GOOD_LENGTH"),
                (r"\bshort\b|bouncer", "SHORT"),
                (r"\bfull\b(?! toss)", "FULL"),
            ]:
                if re.search(pat, lq):
                    p.lengths.append(val)
            # "Short (pitched) bowling" means the short end of the length scale,
            # i.e. bouncers and back-of-a-length balls; "full" balls include
            # yorkers. A named sub-category on its own stays exact.
            if re.search(r"\bshort\b", lq) and not re.search(r"bouncer", q):
                p.lengths = list(dict.fromkeys([*p.lengths, "SHORT_OF_A_GOOD_LENGTH"]))
            if re.search(r"\bfull\b(?! toss)", lq) and not re.search(r"yorker", q):
                p.lengths = list(dict.fromkeys([*p.lengths, "YORKER"]))
        if re.search(r"outside off|off stump", q):
            p.lines = ["OUTSIDE_OFFSTUMP", "WIDE_OUTSIDE_OFFSTUMP"]
        if re.search(r"wide outside off", q):
            p.lines = ["WIDE_OUTSIDE_OFFSTUMP"]
        if re.search(r"down leg", q):
            p.lines = ["DOWN_LEG"]
        if re.search(r"on the stumps", q):
            p.lines = ["ON_THE_STUMPS"]
        venue_q = re.sub(NOT_A_VENUE, " ", q)
        if re.search(r"\bvenue\b|\bground\b|\bat\b", venue_q):
            # Read the venue vocabulary, without interpreting it in validation.
            with self.service._connect() as c:
                cols = {
                    r[0] for r in c.execute("DESCRIBE analytics.deliveries").fetchall()
                }
                scope_filter = (
                    delivery_filter(p, p.scopes[0]) if p.scopes else DeliveryFilter()
                )
                scope_where, scope_params = scope_filter.sql()
                venue_matches = (
                    dict(
                        c.execute(
                            f"SELECT venue, count(DISTINCT match_id) FROM analytics.deliveries d WHERE venue IS NOT NULL AND {scope_where} GROUP BY venue",
                            scope_params,
                        ).fetchall()
                    )
                    if "venue" in cols
                    else {}
                )
                venues = sorted(venue_matches)
            tail = re.search(
                r"\bat\s+(.+?)(?:\s+in\b|\s+since\b|\s+during\b|$)", venue_q
            )
            needle = (
                re.sub(r"^the\s+|[?.!,;:]+$", "", tail[1].strip()).strip()
                if tail
                else None
            )
            from backend.app.domain.venues import matching_venues, resolve_venue

            identities = {
                resolve_venue(v).id for v in matching_venues(question, venues)
            }
            found = [v for v in venues if resolve_venue(v).id in identities]
            if not found:
                found = [
                    v
                    for v in venues
                    if needle
                    and (
                        needle in v.lower()
                        or needle.replace("'", "") in v.lower().replace("'", "")
                    )
                ]
            if not found and needle:
                found = _venues_by_initials(needle, venues, venue_matches)
            if not found and needle:
                found = _venues_via_registry(needle, venues, venue_matches)
            found = _same_ground_names(found, venues)
            if found:
                p.venue = "|".join(sorted(found))
            elif needle:
                p.unsupported.append("unresolved venue " + needle)
            if not p.players and (p.intent != "ranking" or not p.venue):
                p.intent = "venue"
        if p.intent == "partnership":
            p.role = "batting"
            n = re.search(r"(\d+)[- ]run partnership", q)
            if n:
                p.partnership_min_runs = int(n[1])
            if re.search(
                r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)[- ]wicket\b",
                q,
            ):
                p.unsupported.append("partnership wicket position")
        if re.search(
            r"win probability|predict|forecast|wagon|fielding|catch(?:es)?|control|false shot|salar(?:y|ies)|wages?|weather|captaincy",
            q,
        ):
            p.unsupported.append(
                "requested prediction, shot, control, fielding, salary, weather or captaincy analysis"
            )
        if re.search(
            r"\b(?:last|past)\s+(?:\d+|two|three|five)\s+(?:years|seasons)|minimum\s+\d+\s+(?:innings|matches)|\bopening (?:pair|partnership)",
            q,
        ):
            p.unsupported.append(
                "relative date, innings/match minimum or opening-position qualifier"
            )
        if p.phase and any(
            s.format in {"Test", "First-class domestic"} for s in p.scopes
        ):
            p.unsupported.append("limited-overs phase in first-class cricket")
        if re.search(r"\bpitch(?:es|ing)?\b", q) and not re.search(r"short.pitched", q):
            # Where a ball pitches is its length; line is added only when asked.
            p.dimensions = list(dict.fromkeys([*p.dimensions, "length"]))
        if re.search(r"\bwhere\b.*\bbowl(?:s|ing)?\b", q) and not p.venue:
            p.dimensions = list(dict.fromkeys([*p.dimensions, "line", "length"]))
        if (
            len(p.players) == 1
            and len(p.scopes) < 2
            and re.search(r"\b(?:vs|versus|against|v)\b", q)
            and not (
                p.dimensions
                or p.bowler_styles
                or p.bowler_arm
                or p.bowler_kind
                or p.opponent
            )
        ):
            p.unsupported.append("unresolved comparison or matchup participant")
        return p


def delivery_filter(plan, scope):
    return DeliveryFilter(
        format=scope.format,
        formats=tuple(scope.formats),
        competition=scope.competition,
        competitions=tuple(scope.competitions),
        excluded_competitions=tuple(scope.excluded_competitions),
        gender=scope.gender,
        years=tuple(plan.years),
        year_from=plan.year_from,
        year_to=plan.year_to,
        phase=plan.phase,
        over_from=plan.over_from,
        over_to=plan.over_to,
        bowler_styles=tuple(plan.bowler_styles),
        bowler_arm=plan.bowler_arm,
        bowler_kind=plan.bowler_kind,
        lengths=tuple(plan.lengths),
        lines=tuple(plan.lines),
        opponent=plan.opponent,
        role=plan.role,
        venue=plan.venue,
    )
