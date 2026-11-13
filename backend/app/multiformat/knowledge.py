"""Versioned cricket vocabulary supplied to every model reading."""

import json

from backend.app.multiformat.plans import UnderstandingPlan
from backend.app.multiformat.understanding import COMPETITIONS, FRANCHISE_GROUP

RULES = """Read the question into a plan, never calculate statistics or generate SQL.
In this product franchise/other leagues means every domestic T20 league: use format T20 domestic, not a handpicked competition list.
Keep every qualifier. Put requested unsupported concepts in unsupported; never simplify the question.
Names are user text or canonical database names; resolve ambiguous identities only in validation.
Batting against bowling/short balls means role batting. Bowler wickets, economy, pitches and yorkers
mean bowling; unqualified strike rate/dots for an established specialist bowler mean bowling.
Comparison keeps all subjects; matchup player order is batter then bowler, except 'X dismissed Y'
which keeps original order X,Y and role bowling. Partnership keeps unordered pair of players.
Style codes: left fast LF/LFM, left medium LM/LMF, right fast RF/RFM, right medium RM/RMF,
leg spin LB/LBG, off spin OB, left orthodox SLA, left wrist LWS.
bowler_kind is 'pace bowler' or 'spin bowler'; bowler_arm is Left or Right.
T20 powerplay overs1-6, middle7-15, death16-20. ODI1-10/11-40/41-50.
Hundred uses balls1-25/26-75/76-100. First-class has no limited-over phase.
Years '2022 and 2024' is a union; '2022 to 2024' is inclusive range; 'since2022' lower bound.
Gender defaults male for rankings/coverage; use gender=null for named-player questions unless
the question explicitly states men/women or names a gender-specific competition.
Minimum balls defaults60 for rankings, explicit minimum replaces it. Highest/lowest controls sorting;
economy, bowling average, bowling strike rate normally sort ascending; other rankings descending.
Use dimensions line/length for breakdowns; an explicit category additionally filters lines/lengths.
Lengths: YORKER,FULL_TOSS,FULL,GOOD_LENGTH,SHORT_OF_A_GOOD_LENGTH,SHORT.
Lines: OUTSIDE_OFFSTUMP,ON_THE_STUMPS,WIDE_OUTSIDE_OFFSTUMP,DOWN_LEG,WIDE_DOWN_LEG.
Metric identifiers: balls,runs,wickets,average,strike_rate,economy,dot_ball_pct,fours,sixes.
Length/line frequency means metrics=['balls'], intent stats, with the requested dimension.
Outside-off balls includes OUTSIDE_OFFSTUMP and WIDE_OUTSIDE_OFFSTUMP; 'wide outside off' only the latter.
Venue summaries use intent venue; player leaderboards at a venue use intent ranking with venue filter.
Venue must be a literal DB alias or pipe-separated aliases from the database candidates.
Partnership min runs is a stand threshold, not a player sample minimum.
Coverage questions can omit scopes for all formats. Exact competition names are required except
%Blast%, %County Championship%, %Sheffield Shield% which include sponsor eras.
Unsupported: predictions, fielding/catches, shot/control analysis, opening-position partnership,
relative dates, rankings across multiple metrics/groups. Do not invent fields or sources.
"""

# These are teaching examples, independent of the evaluation questions.
EXAMPLES = [
    (
        "A Batter batting in Tests",
        {
            "intent": "stats",
            "role": "batting",
            "players": ["A Batter"],
            "scopes": [{"label": "Tests", "format": "Test"}],
        },
    ),
    ("A Bowler Test economy", {"role": "bowling", "metrics": ["economy"]}),
    (
        "A Batter against left-arm fast in PSL",
        {"role": "batting", "bowler_styles": ["LF", "LFM"]},
    ),
    (
        "A Batter against left-arm medium",
        {"role": "batting", "bowler_styles": ["LM", "LMF"]},
    ),
    ("A Batter vs leg spin", {"role": "batting", "bowler_styles": ["LB", "LBG"]}),
    ("A Batter against off spin", {"role": "batting", "bowler_styles": ["OB"]}),
    ("A Bowler dot percentage", {"role": "bowling", "metrics": ["dot_ball_pct"]}),
    (
        "Highest BBL batting average minimum 350 balls",
        {"intent": "ranking", "metrics": ["average"], "min_balls": 350},
    ),
    (
        "Lowest CPL economy",
        {
            "intent": "ranking",
            "role": "bowling",
            "metrics": ["economy"],
            "descending": False,
        },
    ),
    (
        "WPL most wickets",
        {
            "intent": "ranking",
            "role": "bowling",
            "metrics": ["wickets"],
            "scopes": [
                {
                    "label": "WPL",
                    "competition": "Women's Premier League",
                    "gender": "female",
                }
            ],
        },
    ),
    (
        "Women's Hundred runs",
        {
            "scopes": [
                {"label": "The Hundred", "format": "The Hundred", "gender": "female"}
            ]
        },
    ),
    ("BBL runs in 2021 and 2023", {"years": [2021, 2023]}),
    ("BBL runs from 2021 to 2023", {"year_from": 2021, "year_to": 2023}),
    ("CPL record since 2021", {"year_from": 2021}),
    ("A Batter powerplay batting in T20Is", {"role": "batting", "phase": "powerplay"}),
    (
        "A Bowler middle overs ODI economy",
        {"role": "bowling", "phase": "middle", "metrics": ["economy"]},
    ),
    (
        "Death overs in The Hundred",
        {
            "phase": "death",
            "scopes": [{"label": "The Hundred", "format": "The Hundred"}],
        },
    ),
    ("Overs 12-17 in CPL", {"over_from": 12, "over_to": 17}),
    (
        "A Batter vs B Bowler",
        {"intent": "matchup", "players": ["A Batter", "B Bowler"]},
    ),
    (
        "A Bowler dismissed B Batter",
        {"intent": "matchup", "players": ["A Bowler", "B Batter"]},
    ),
    (
        "Compare A Batter and B Batter",
        {"intent": "comparison", "players": ["A Batter", "B Batter"]},
    ),
    (
        "A Batter Tests versus T20Is",
        {
            "intent": "comparison",
            "scopes": [
                {"label": "Tests", "format": "Test"},
                {"label": "T20Is", "format": "T20I"},
            ],
        },
    ),
    (
        "A Batter and B Batter 75-run partnerships",
        {
            "intent": "partnership",
            "players": ["A Batter", "B Batter"],
            "partnership_min_runs": 75,
        },
    ),
    (
        "Which formats have line data?",
        {"intent": "coverage", "dimensions": ["line"], "scopes": []},
    ),
    (
        "A Bowler yorkers in BBL",
        {"role": "bowling", "dimensions": ["length"], "lengths": ["YORKER"]},
    ),
    (
        "Forecast next season wickets",
        {"unsupported": ["future performance prediction"]},
    ),
]


def knowledge_pack(database_competitions=()):
    return (
        RULES
        + "\nCompetitions: "
        + json.dumps(COMPETITIONS)
        + "\nOther database competitions (use their exact names): "
        + json.dumps(list(database_competitions))
        + "\nFranchise leagues: "
        + json.dumps(FRANCHISE_GROUP)
        + "\nPartial worked readings (other fields retain their defaults): "
        + json.dumps(EXAMPLES)
        + "\nFull output schema: "
        + json.dumps(UnderstandingPlan.model_json_schema())
    )
