from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


DEFAULT_OUTPUT = Path("tests/benchmarks/odi_unseen_paraphrases_v1.yaml")


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def pair(seed_id: str, family: str, prompts: tuple[str, str], expected: dict[str, Any]) -> None:
        for suffix, prompt in zip(("a", "b"), prompts, strict=True):
            cases.append(
                {
                    "id": f"unseen-{seed_id}-{suffix}",
                    "family": family,
                    "planner_mode": "production_live",
                    "turns": [{"prompt": prompt, "expected": deepcopy(expected)}],
                }
            )

    supported = {"mode": "analysis", "status": "supported", "evidence": "required"}

    direct = [
        ("direct-kohli-runs-aus", ("Kohli's ODI run tally versus Australia?", "Against Australia, how many runs has Virat Kohli made?"), "batter", "runs_scored", {"batter": "Virat Kohli", "opposition": "Australia"}),
        ("direct-rohit-pp-sr", ("How quickly does Rohit score in the first ten overs?", "Rohit Sharma powerplay strike rate, please."), "batter", "batting_strike_rate", {"batter": "Rohit Sharma", "phase": "powerplay"}),
        ("direct-babar-spin-dot", ("What share of Babar's balls against spin are dots?", "Babar Azam dot-ball percentage when facing spin?"), "batter", "batter_dot_ball_percentage", {"batter": "Babar Azam", "bowling_style": "spin"}),
        ("direct-klaasen-death-boundary", ("Klaasen's boundary percentage at the death?", "How often does Heinrich Klaasen find the rope in death overs?"), "batter", "boundary_percentage", {"batter": "Heinrich Klaasen", "phase": "death"}),
        ("direct-buttler-middle-false", ("Jos Buttler false-shot rate through the middle overs?", "In the middle phase, what is Buttler's false-shot percentage?"), "batter", "false_shot_percentage", {"batter": "Jos Buttler", "phase": "middle"}),
        ("direct-bumrah-death-econ", ("How expensive is Bumrah from over 41 onwards?", "Give me Jasprit Bumrah's death-over economy."), "bowler", "economy_rate", {"bowler": "Jasprit Bumrah", "phase": "death"}),
        ("direct-starc-pp-wickets", ("Starc wickets inside the opening ten overs?", "How many powerplay wickets has Mitchell Starc taken?"), "bowler", "wickets_taken", {"bowler": "Mitchell Starc", "phase": "powerplay"}),
        ("direct-rashid-left-dot", ("Rashid Khan dot-ball rate to left-handers?", "Against left-handed batters, what percentage of Rashid's balls are dots?"), "bowler", "bowler_dot_ball_percentage", {"bowler": "Rashid Khan", "batter_hand": "LHB"}),
        ("direct-malinga-yorker-share", ("What fraction of Malinga's legal deliveries are yorkers?", "Lasith Malinga yorker percentage in ODIs?"), "bowler", "yorker_percentage", {"bowler": "Lasith Malinga"}),
        ("direct-ashwin-right-econ", ("Ashwin economy to right-handed batters?", "What does Ravichandran Ashwin concede per over against right-handers?"), "bowler", "economy_rate", {"bowler": "Ravichandran Ashwin", "batter_hand": "RHB"}),
    ]
    for seed_id, prompts, entity, metric, filters in direct:
        pair(seed_id, "direct", prompts, {**supported, "plan": {"operation": "aggregate", "entity": entity, "metric": metric, "filters": filters}})

    rankings = [
        ("rank-death-econ", ("Ten most economical death bowlers, at least 120 legal balls.", "With a 120-ball cutoff, rank the best ten death-over economies."), "bowler", "economy_rate", {"phase": "death"}, "asc", 10, {"legal_balls": 120}),
        ("rank-pp-wickets", ("Who are the top five powerplay wicket takers?", "List five bowlers with the most wickets in overs 1 to 10."), "bowler", "wickets_taken", {"phase": "powerplay"}, "desc", 5, {}),
        ("rank-middle-dots", ("Rank the best eight middle-over dot-ball bowlers, minimum 180 legal balls.", "Which eight bowlers lead dot-ball percentage in overs 11-40 with 180+ legal balls?"), "bowler", "bowler_dot_ball_percentage", {"phase": "middle"}, "desc", 8, {"legal_balls": 180}),
        ("rank-yorker-count", ("Which six bowlers have delivered the most yorkers?", "Top six by yorker volume, not yorker rate."), "bowler", "yorker_count", {}, "desc", 6, {}),
        ("rank-yorker-rate", ("Who leads yorker percentage with at least 150 legal balls?", "Highest yorker rate among bowlers with 150+ legal deliveries?"), "bowler", "yorker_percentage", {}, "desc", 10, {"legal_balls": 150}),
        ("rank-worst-econ", ("Show the five worst economy rates, minimum 200 legal balls.", "Which five qualified bowlers concede the most per over after 200 balls?"), "bowler", "economy_rate", {}, "desc", 5, {"legal_balls": 200}),
        ("rank-spin-sr", ("Top seven batters by strike rate versus spin, 100 balls minimum.", "Against spin, who are the seven fastest scorers with 100+ balls?"), "batter", "batting_strike_rate", {"bowling_style": "spin"}, "desc", 7, {"balls": 100}),
        ("rank-pace-boundary", ("Who has the best boundary percentage against pace after 120 balls?", "Rank batters by boundary rate versus pace, minimum sample 120."), "batter", "boundary_percentage", {"bowling_style": "pace"}, "desc", 10, {"balls": 120}),
        ("rank-pp-runs", ("Leading five run scorers in the powerplay?", "Who owns the five largest run totals in overs 1-10?"), "batter", "runs_scored", {"phase": "powerplay"}, "desc", 5, {}),
        ("rank-death-sr", ("Fastest six death-over batters with at least 90 balls?", "Give six highest strike rates after over 40, 90-ball floor."), "batter", "batting_strike_rate", {"phase": "death"}, "desc", 6, {"balls": 90}),
        ("rank-2019-runs", ("Top ten ODI run scorers in 2019?", "Who made the most runs during 2019?"), "batter", "runs_scored", {"years": [2019]}, "desc", 10, {}),
        ("rank-lords-wickets", ("Five leading wicket takers at Lord's?", "At Lord's in London, rank the top five bowlers by wickets."), "bowler", "wickets_taken", {"venue": "Lord's, London"}, "desc", 5, {}),
    ]
    for seed_id, prompts, entity, metric, filters, direction, limit, sample in rankings:
        group = "batter" if entity == "batter" else "bowler"
        expected_plan: dict[str, Any] = {"operation": "aggregate", "entity": entity, "metric": metric, "group_by": [group], "filters": filters, "sort": {"by": metric, "direction": direction}, "limit": limit}
        if sample:
            expected_plan["minimum_sample"] = sample
            expected_plan["minimum_sample_explicit"] = True
        pair(seed_id, "ranking", prompts, {**supported, "plan": expected_plan})

    breakdowns = [
        ("break-kohli-line-runs", ("Map Kohli's run output across bowling lines.", "Which line does Virat Kohli score the most runs from?"), "batter", "runs_scored", "line", {"batter": "Virat Kohli"}),
        ("break-rohit-length-dots", ("Break Rohit's dot-ball rate down by length.", "For Rohit Sharma, which lengths produce his dot balls?"), "batter", "batter_dot_ball_percentage", "length", {"batter": "Rohit Sharma"}),
        ("break-babar-style-sr", ("Babar strike rate for every bowling style?", "Split Babar Azam's scoring rate by bowler type."), "batter", "batting_strike_rate", "bowling_style", {"batter": "Babar Azam"}),
        ("break-buttler-shot-runs", ("Jos Buttler run totals for each shot type?", "Which shots account for Buttler's runs?"), "batter", "runs_scored", "shot_type", {"batter": "Jos Buttler"}),
        ("break-klaasen-zone-boundary", ("Klaasen boundary percentage by field zone?", "Where does Heinrich Klaasen find boundaries most often by zone?"), "batter", "boundary_percentage", "field_zone", {"batter": "Heinrich Klaasen"}),
        ("break-bumrah-length-wickets", ("Bumrah wickets grouped by delivery length?", "Which lengths bring Jasprit Bumrah his wickets?"), "bowler", "wickets_taken", "length", {"bowler": "Jasprit Bumrah"}),
        ("break-starc-line-dots", ("Starc dot-ball percentage across each line?", "Which bowling line creates Mitchell Starc's dots?"), "bowler", "bowler_dot_ball_percentage", "line", {"bowler": "Mitchell Starc"}),
        ("break-rashid-phase-econ", ("Rashid Khan economy in each innings phase?", "How does Rashid's economy move from powerplay to middle to death?"), "bowler", "economy_rate", "phase", {"bowler": "Rashid Khan"}),
        ("break-boult-hand-wickets", ("Boult wickets split by batter handedness?", "Does Trent Boult take more wickets against lefties or righties?"), "bowler", "wickets_taken", "batter_hand", {"bowler": "Trent Boult"}),
        ("break-warner-year-sr", ("David Warner strike rate year by year?", "Show Warner's annual batting strike-rate breakdown."), "batter", "batting_strike_rate", "year", {"batter": "David Warner"}),
    ]
    for seed_id, prompts, entity, metric, dimension, filters in breakdowns:
        pair(seed_id, "breakdown", prompts, {**supported, "plan": {"operation": "aggregate", "entity": entity, "metric": metric, "group_by": [dimension], "filters": filters}})

    matchups = [
        ("match-kohli-starc", ("Kohli versus Starc head-to-head numbers?", "How has Mitchell Starc done when bowling to Virat Kohli?"), "batter", "batting_strike_rate", {"batter": "Virat Kohli", "bowler": "Mitchell Starc"}),
        ("match-smith-bumrah", ("Smith's scoring record off Bumrah?", "Jasprit Bumrah against Steven Smith: show the matchup."), "batter", "batting_strike_rate", {"batter": "Steven Smith", "bowler": "Jasprit Bumrah"}),
        ("match-maxwell-ashwin", ("How many runs has Maxwell taken from Ashwin?", "Maxwell v Ravichandran Ashwin run tally?"), "batter", "runs_scored", {"batter": "Glenn Maxwell", "bowler": "Ravichandran Ashwin"}),
        ("match-warner-dismissers", ("Which bowler gets David Warner out most?", "Warner's most frequent ODI dismissor?"), "bowler", "dismissals", {"batter": "David Warner"}),
        ("match-klaasen-dots", ("Who controls Klaasen best by dot-ball percentage, minimum 60 legal balls?", "Against Heinrich Klaasen, rank bowlers on dot rate with 60+ balls."), "bowler", "bowler_dot_ball_percentage", {"batter": "Heinrich Klaasen"}),
        ("match-miller-false", ("Which bowler induces Miller's highest false-shot percentage after 60 balls?", "David Miller's toughest bowler by false-shot rate, 60-ball minimum?"), "bowler", "false_shot_percentage", {"batter": "David Miller"}),
        ("match-rashid-boundary", ("Which batter has the best boundary rate off Rashid Khan with 60 balls faced?", "Against Rashid, who finds boundaries most often after 60 deliveries?"), "batter", "boundary_percentage", {"bowler": "Rashid Khan"}),
        ("match-kohli-pace", ("Which pace bowler has the highest boundary rate conceded to Kohli, minimum 60 balls?", "Kohli versus pace: rank opposing bowlers by boundary percentage with a 60-ball floor."), "bowler", "boundary_percentage", {"batter": "Virat Kohli", "bowling_style": "pace"}),
    ]
    for seed_id, prompts, entity, metric, filters in matchups:
        plan: dict[str, Any] = {"operation": "matchup" if "bowler" in filters and "batter" in filters else "aggregate", "entity": entity, "metric": metric, "filters": filters}
        if not ("bowler" in filters and "batter" in filters):
            plan["group_by"] = [entity]
        if "60" in prompts[0]:
            plan["minimum_sample"] = {"legal_balls": 60} if metric == "bowler_dot_ball_percentage" else {"balls": 60}
            plan["minimum_sample_explicit"] = True
        pair(seed_id, "matchup", prompts, {**supported, "plan": plan})

    comparisons = [
        ("compare-kohli-rohit", ("Put Kohli and Rohit side by side as ODI batters.", "Compare Virat Kohli with Rohit Sharma across their core batting numbers."), "batter", ["Virat Kohli", "Rohit Sharma"], ["runs_scored", "batting_strike_rate", "batting_average", "batter_dot_ball_percentage", "boundary_percentage"], {}),
        ("compare-babar-smith", ("Babar versus Steven Smith as batters?", "Compare Babar Azam and Steven Smith's ODI batting records."), "batter", ["Babar Azam", "Steven Smith"], ["runs_scored", "batting_strike_rate", "batting_average", "batter_dot_ball_percentage", "boundary_percentage"], {}),
        ("compare-buttler-klaasen-spin", ("Against spin, contrast Buttler and Klaasen.", "Compare Jos Buttler with Heinrich Klaasen when facing spin bowling."), "batter", ["Jos Buttler", "Heinrich Klaasen"], ["batting_strike_rate", "runs_scored", "boundary_percentage"], {"bowling_style": "spin"}),
        ("compare-rohit-warner-pp", ("Rohit or Warner in the powerplay—compare them.", "Side-by-side powerplay batting for Rohit Sharma and David Warner."), "batter", ["Rohit Sharma", "David Warner"], ["runs_scored", "batting_strike_rate", "boundary_percentage"], {"phase": "powerplay"}),
        ("compare-bumrah-starc", ("Compare Bumrah and Starc as ODI bowlers.", "Jasprit Bumrah versus Mitchell Starc across their main bowling metrics."), "bowler", ["Jasprit Bumrah", "Mitchell Starc"], ["wickets_taken", "economy_rate", "bowling_strike_rate", "bowler_dot_ball_percentage"], {}),
        ("compare-bumrah-starc-death", ("At the death, compare Bumrah with Starc.", "Death-over bowling comparison: Jasprit Bumrah and Mitchell Starc."), "bowler", ["Jasprit Bumrah", "Mitchell Starc"], ["economy_rate", "wickets_taken", "bowler_dot_ball_percentage"], {"phase": "death"}),
        ("compare-rashid-ashwin", ("Rashid Khan or Ashwin—compare their ODI bowling.", "Put Rashid Khan and Ravichandran Ashwin side by side as spin bowlers."), "bowler", ["Rashid Khan", "Ravichandran Ashwin"], ["wickets_taken", "economy_rate", "bowler_dot_ball_percentage"], {"bowling_style": "spin"}),
        ("compare-rabada-shaheen-pp", ("Contrast Rabada and Shaheen in the opening ten overs.", "Powerplay comparison for Kagiso Rabada versus Shaheen Shah Afridi."), "bowler", ["Kagiso Rabada", "Shaheen Shah Afridi"], ["wickets_taken", "economy_rate", "bowler_dot_ball_percentage"], {"phase": "powerplay"}),
    ]
    for seed_id, prompts, entity, players, metrics, extra_filters in comparisons:
        filters = {**extra_filters, "compare_players": players, "comparison_metrics": metrics}
        pair(seed_id, "comparison", prompts, {**supported, "plan": {"operation": "player_compare", "entity": entity, "filters": filters}})

    splits = [
        ("split-bumrah-phase-econ", ("How different is Bumrah's economy in powerplay versus death?", "Compare Jasprit Bumrah's powerplay and death-over economy."), "bowler", "economy_rate", "phase", ["powerplay", "death"], {"bowler": "Jasprit Bumrah"}),
        ("split-starc-hand-econ", ("Starc economy to left-handers versus right-handers?", "Compare Mitchell Starc's economy by batter hand."), "bowler", "economy_rate", "batter_hand", ["LHB", "RHB"], {"bowler": "Mitchell Starc"}),
        ("split-kohli-phase-sr", ("Kohli strike rate in powerplay compared with death overs?", "Compare Virat Kohli's scoring rate at the start and the death."), "batter", "batting_strike_rate", "phase", ["powerplay", "death"], {"batter": "Virat Kohli"}),
        ("split-klaasen-spin-type", ("Klaasen against wrist spin versus finger spin?", "Compare Heinrich Klaasen's strike rate across wrist and finger spin."), "batter", "batting_strike_rate", "bowling_style_group", ["wrist_spin", "finger_spin"], {"batter": "Heinrich Klaasen"}),
        ("split-boult-hand-dots", ("Boult dot rate to lefties compared with righties?", "Compare Trent Boult's dot-ball percentage by batter handedness."), "bowler", "bowler_dot_ball_percentage", "batter_hand", ["LHB", "RHB"], {"bowler": "Trent Boult"}),
        ("split-miller-phase-boundary", ("Miller boundary percentage: powerplay or death?", "Compare David Miller's boundary rate in powerplay and death overs."), "batter", "boundary_percentage", "phase", ["powerplay", "death"], {"batter": "David Miller"}),
        ("split-team-phase-runrate", ("Which team changes run rate most from powerplay to death?", "Rank teams by the gap between powerplay and death-over run rate."), "team", "run_rate", "phase", ["powerplay", "death"], {}),
    ]
    for seed_id, prompts, entity, metric, split_by, values, filters in splits:
        pair(seed_id, "split", prompts, {**supported, "plan": {"operation": "split_compare", "entity": entity, "metric": metric, "split_by": split_by, "compare_values": values, "filters": filters}})

    trends = [
        ("trend-kohli-sr", ("Trace Kohli's batting strike rate by year.", "How has Virat Kohli's scoring rate moved season by season?"), "batter", "batting_strike_rate", {"batter": "Virat Kohli"}),
        ("trend-rohit-runs", ("Rohit Sharma runs year over year?", "Give me Rohit's annual ODI run totals."), "batter", "runs_scored", {"batter": "Rohit Sharma"}),
        ("trend-bumrah-econ", ("Bumrah economy trend by year.", "How has Jasprit Bumrah's economy changed season to season?"), "bowler", "economy_rate", {"bowler": "Jasprit Bumrah"}),
        ("trend-starc-death", ("Starc death-over economy year by year since 2018.", "From 2018 onward, chart Mitchell Starc's annual economy at the death."), "bowler", "economy_rate", {"bowler": "Mitchell Starc", "phase": "death", "years": [2018], "year_mode": "after"}),
        ("trend-rashid-wickets", ("Rashid Khan wickets by year.", "Show Rashid's annual ODI wicket trend."), "bowler", "wickets_taken", {"bowler": "Rashid Khan"}),
    ]
    for seed_id, prompts, entity, metric, filters in trends:
        pair(seed_id, "trend", prompts, {**supported, "plan": {"operation": "aggregate", "entity": entity, "metric": metric, "group_by": ["year"], "filters": filters}})

    contexts = [
        ("context-kohli-phase", "What is Virat Kohli's batting strike rate?", ("Now only at the death.", "What about in the powerplay instead?"), "batter", "batting_strike_rate", ({"batter": "Virat Kohli", "phase": "death"}, {"batter": "Virat Kohli", "phase": "powerplay"})),
        ("context-bumrah-phase", "What is Jasprit Bumrah's economy rate?", ("Limit that to the powerplay.", "And at the death?"), "bowler", "economy_rate", ({"bowler": "Jasprit Bumrah", "phase": "powerplay"}, {"bowler": "Jasprit Bumrah", "phase": "death"})),
        ("context-kohli-starc", "How has Virat Kohli scored against Mitchell Starc?", ("Only in the middle overs.", "Now show the death overs."), "batter", "batting_strike_rate", ({"batter": "Virat Kohli", "bowler": "Mitchell Starc", "phase": "middle"}, {"batter": "Virat Kohli", "bowler": "Mitchell Starc", "phase": "death"})),
        ("context-comparison", "Compare Rohit Sharma and David Warner as batters.", ("Use just the powerplay.", "Switch that comparison to death overs."), "batter", "runs_scored", ({"phase": "powerplay", "compare_players": ["Rohit Sharma", "David Warner"]}, {"phase": "death", "compare_players": ["Rohit Sharma", "David Warner"]})),
        ("context-trend", "Show Jasprit Bumrah's economy year by year.", ("Restrict it to death overs.", "Use powerplay overs instead."), "bowler", "economy_rate", ({"bowler": "Jasprit Bumrah", "phase": "death"}, {"bowler": "Jasprit Bumrah", "phase": "powerplay"})),
    ]
    for seed_id, first_prompt, followups, entity, metric, filters_pair in contexts:
        for suffix, followup, filters in zip(("a", "b"), followups, filters_pair, strict=True):
            operation = "matchup" if "bowler" in filters and "batter" in filters else "aggregate"
            if seed_id == "context-comparison":
                operation = "player_compare"
            group_by = ["year"] if seed_id == "context-trend" else []
            expected_plan: dict[str, Any] = {"operation": operation, "entity": entity, "metric": metric, "filters": filters}
            if group_by:
                expected_plan["group_by"] = group_by
            cases.append({"id": f"unseen-{seed_id}-{suffix}", "family": "context", "planner_mode": "production_live", "turns": [{"prompt": first_prompt, "expected": {"mode": "analysis", "status": "supported", "evidence": "required"}}, {"prompt": followup, "expected": {**supported, "plan": expected_plan}}]})

    behavior_seeds = [
        ("ambiguous-bumrah-sr", ("What's Bumrah's strike rate?", "Give me Jasprit Bumrah's SR."), {"mode": "clarification", "clarification_labels": ["Batting strike rate", "Bowling strike rate"]}),
        ("ambiguous-best", ("Who has the best numbers?", "Which player has the strongest statistics?"), {"mode": "clarification", "clarification_labels": ["Runs scored", "Batting strike rate", "Wickets taken", "Economy rate"]}),
        ("ambiguous-player", ("How good is Sharma?", "Show me Khan's record."), {"mode": "clarification"}),
        ("missing-catches", ("Who took the most catches in the 2019 World Cup?", "Leading ODI catcher in 2019?"), {"mode": "analysis", "status": "insufficient_evidence", "failure_state": "data_limitation"}),
        ("unsupported-team-econ", ("Which national side has the best bowling economy?", "Rank teams by economy rate against India."), {"mode": "analysis", "status": "unsupported", "failure_state": "unsupported_capability"}),
        ("unsupported-prediction", ("Who will win India's next ODI?", "Predict the next World Cup champion from this data."), {"mode": "analysis", "status": "unsupported", "failure_state": "unsupported_capability"}),
        ("unsupported-weather", ("How did rain affect Kohli's strike rate?", "What is Bumrah's economy in humid weather?"), {"mode": "analysis", "status": "unsupported", "failure_state": "unsupported_capability"}),
        ("missing-captain", ("Who captained India most often in 2012?", "Which captain won the most ODIs in 2015?"), {"mode": "analysis", "status": "insufficient_evidence", "failure_state": "data_limitation"}),
        ("unsupported-salary", ("Which ODI player offers the best value for salary?", "Rank players by runs per million dollars."), {"mode": "analysis", "status": "unsupported", "failure_state": "unsupported_capability"}),
        ("ambiguous-comparison", ("Compare Kohli and Bumrah.", "Who is better, Rohit or Starc?"), {"mode": "clarification"}),
    ]
    for seed_id, prompts, expected in behavior_seeds:
        pair(seed_id, "behavior", prompts, expected)

    if len(cases) != 150:
        raise AssertionError(f"Expected 150 cases, built {len(cases)}")
    return cases


def build_benchmark() -> dict[str, Any]:
    return {
        "version": 1,
        "name": "ODI unseen production paraphrase benchmark",
        "frozen_at": "2026-09-01",
        "design": "75 independently specified cricket meanings, each expressed through two previously unused phrasings",
        "cases": build_cases(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the frozen ODI unseen paraphrase benchmark.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(build_benchmark(), sort_keys=False, width=120), encoding="utf-8")
    print(f"Wrote 150 frozen cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
