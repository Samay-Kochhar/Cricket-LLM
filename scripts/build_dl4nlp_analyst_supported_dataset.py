from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from backend.app.bootstrap import get_services
from backend.app.cricket_analytics.ontology import METRICS
from scripts.build_dl4nlp_eval_dataset import Candidate, aggregate, compare, materialize_case, matchup


DEFAULT_OUTPUT = Path("tests/evals/dl4nlp_cricket_analyst_supported_100.yaml")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a realistic, answerable 100-question analyst benchmark.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output YAML path.")
    args = parser.parse_args()

    repository = get_services()["repository"]
    selected: list[dict[str, Any]] = []
    skipped: list[str] = []
    seen_questions: set[str] = set()

    for candidate in analyst_candidates():
        normalized_question = candidate.question.lower().strip()
        if normalized_question in seen_questions:
            continue
        seen_questions.add(normalized_question)
        try:
            case = materialize_case(candidate, repository)
        except Exception as exc:
            skipped.append(f"{candidate.case_id}: {exc}")
            continue
        if case["answer_key"]["row_count"] <= 0:
            skipped.append(f"{candidate.case_id}: empty answer")
            continue
        case["expected_status"] = "supported"
        selected.append(case)
        if len(selected) == 100:
            break

    if len(selected) != 100:
        raise SystemExit(f"Expected 100 non-empty supported cases, built {len(selected)}. First skips: {skipped[:10]}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(selected, sort_keys=False, allow_unicode=False, width=110),
        encoding="utf-8",
    )
    print(f"Wrote {len(selected)} realistic supported analyst cases to {output_path}")
    if skipped:
        print(f"Skipped {len(skipped)} candidate cases while building non-empty gold answers.")
    return 0


def split_compare(
    case_id: str,
    category: str,
    question: str,
    *,
    entity: str,
    metric: str,
    split_by: str,
    compare_values: list[str],
    filters: dict[str, Any] | None = None,
    limit: int = 10,
) -> Candidate:
    return Candidate(
        case_id,
        category,
        question,
        {
            "operation": "split_compare",
            "entity": entity,
            "metric": metric,
            "group_by": [entity],
            "filters": filters or {},
            "split_by": split_by,
            "compare_values": compare_values,
            "sort": {"by": metric, "direction": METRICS[metric].default_sort},
            "limit": limit,
        },
    )


def analyst_candidates() -> list[Candidate]:
    cases: list[Candidate] = []

    cases.extend(
        [
            aggregate("analyst-single-kohli-runs", "single_metric", "How many ODI runs has Virat Kohli scored in this database?", entity="batter", metric="runs_scored", group_by=["batter"], filters={"batter": "Virat Kohli"}, limit=1),
            aggregate("analyst-single-rohit-boundary", "single_metric", "What percentage of Rohit Sharma's recorded balls become boundaries?", entity="batter", metric="boundary_percentage", group_by=["batter"], filters={"batter": "Rohit Sharma"}, limit=1),
            aggregate("analyst-single-babar-dot", "single_metric", "What is Babar Azam's dot-ball percentage as a batter?", entity="batter", metric="batter_dot_ball_percentage", group_by=["batter"], filters={"batter": "Babar Azam"}, limit=1),
            aggregate("analyst-single-klaasen-spin-sr", "single_metric", "What is Heinrich Klaasen's batting strike rate against spin?", entity="batter", metric="batting_strike_rate", group_by=["batter"], filters={"batter": "Heinrich Klaasen", "bowling_style": "spin"}, limit=1),
            aggregate("analyst-single-buttler-death-runs", "single_metric", "How many runs has Jos Buttler scored in the death overs?", entity="batter", metric="runs_scored", group_by=["batter"], filters={"batter": "Jos Buttler", "phase": "death"}, limit=1),
            aggregate("analyst-single-warner-powerplay-sr", "single_metric", "What is David Warner's powerplay batting strike rate?", entity="batter", metric="batting_strike_rate", group_by=["batter"], filters={"batter": "David Warner", "phase": "powerplay"}, limit=1),
            aggregate("analyst-single-maxwell-pace-boundary", "single_metric", "What is Glenn Maxwell's boundary percentage against pace?", entity="batter", metric="boundary_percentage", group_by=["batter"], filters={"batter": "Glenn Maxwell", "bowling_style": "pace"}, limit=1),
            aggregate("analyst-single-miller-short-sr", "single_metric", "What is David Miller's strike rate against short balls?", entity="batter", metric="batting_strike_rate", group_by=["batter"], filters={"batter": "David Miller", "length": "SHORT"}, limit=1),
            aggregate("analyst-single-bumrah-wickets", "single_metric", "How many bowler-credit wickets has Jasprit Bumrah taken?", entity="bowler", metric="wickets_taken", group_by=["bowler"], filters={"bowler": "Jasprit Bumrah"}, limit=1),
            aggregate("analyst-single-starc-death-economy", "single_metric", "What is Mitchell Starc's economy rate at the death?", entity="bowler", metric="economy_rate", group_by=["bowler"], filters={"bowler": "Mitchell Starc", "phase": "death"}, limit=1),
            aggregate("analyst-single-malinga-yorker", "single_metric", "What percentage of Lasith Malinga's legal balls are yorkers?", entity="bowler", metric="yorker_percentage", group_by=["bowler"], filters={"bowler": "Lasith Malinga"}, limit=1),
            aggregate("analyst-single-rashid-middle-dots", "single_metric", "What is Rashid Khan's dot-ball percentage in the middle overs?", entity="bowler", metric="bowler_dot_ball_percentage", group_by=["bowler"], filters={"bowler": "Rashid Khan", "phase": "middle"}, limit=1),
            aggregate("analyst-single-southee-left-economy", "single_metric", "What is Tim Southee's economy rate against left-hand batters?", entity="bowler", metric="economy_rate", group_by=["bowler"], filters={"bowler": "Tim Southee", "batter_hand": "LHB"}, limit=1),
            aggregate("analyst-single-boult-powerplay-wickets", "single_metric", "How many wickets has Trent Boult taken in the powerplay?", entity="bowler", metric="wickets_taken", group_by=["bowler"], filters={"bowler": "Trent Boult", "phase": "powerplay"}, limit=1),
            aggregate("analyst-single-rabada-pace-dots", "single_metric", "What is Kagiso Rabada's overall dot-ball percentage?", entity="bowler", metric="bowler_dot_ball_percentage", group_by=["bowler"], filters={"bowler": "Kagiso Rabada"}, limit=1),
        ]
    )

    leaderboard_cases = [
        ("analyst-lb-death-economy", "Which bowlers are most economical in the death overs?", "bowler", "economy_rate", ["bowler"], {"phase": "death"}, None),
        ("analyst-lb-powerplay-wickets", "Who takes the most wickets in the powerplay?", "bowler", "wickets_taken", ["bowler"], {"phase": "powerplay"}, None),
        ("analyst-lb-middle-dots", "Which bowler creates the highest dot-ball percentage in middle overs?", "bowler", "bowler_dot_ball_percentage", ["bowler"], {"phase": "middle"}, None),
        ("analyst-lb-yorker-volume", "Which bowlers deliver the most yorkers?", "bowler", "yorker_count", ["bowler"], {}, None),
        ("analyst-lb-left-arm-pace-wickets", "Among left-arm pace bowlers, who has taken the most wickets?", "bowler", "wickets_taken", ["bowler"], {"bowling_style": "left_arm_pace"}, None),
        ("analyst-lb-spin-economy", "Which spin bowler has the lowest economy rate?", "bowler", "economy_rate", ["bowler"], {"bowling_style": "spin"}, None),
        ("analyst-lb-pace-dots", "Which pace bowler has the highest dot-ball percentage?", "bowler", "bowler_dot_ball_percentage", ["bowler"], {"bowling_style": "pace"}, None),
        ("analyst-lb-2023-runs", "Which batters scored the most ODI runs in 2023?", "batter", "runs_scored", ["batter"], {"years": [2023]}, None),
        ("analyst-lb-since-2022-boundary", "Since 2022, which batter has the highest boundary percentage?", "batter", "boundary_percentage", ["batter"], {"years": [2022], "year_mode": "after"}, None),
        ("analyst-lb-spin-sr", "Who scores fastest against spin bowling?", "batter", "batting_strike_rate", ["batter"], {"bowling_style": "spin"}, None),
        ("analyst-lb-pace-runs", "Who has made the most runs against pace?", "batter", "runs_scored", ["batter"], {"bowling_style": "pace"}, None),
        ("analyst-lb-death-batter-sr", "Which batter scores fastest in the death overs?", "batter", "batting_strike_rate", ["batter"], {"phase": "death"}, None),
        ("analyst-lb-powerplay-boundary", "Which batter has the highest boundary percentage in the powerplay?", "batter", "boundary_percentage", ["batter"], {"phase": "powerplay"}, None),
        ("analyst-lb-lords-wickets", "Which bowler has taken the most wickets at Lord's?", "bowler", "wickets_taken", ["bowler"], {"venue": "Lord's, London"}, None),
        ("analyst-lb-mcg-runs", "Which batter has scored the most runs at the Melbourne Cricket Ground?", "batter", "runs_scored", ["batter"], {"venue": "Melbourne Cricket Ground"}, None),
        ("analyst-lb-chinnaswamy-boundary", "At Chinnaswamy, which batter has the highest boundary percentage?", "batter", "boundary_percentage", ["batter"], {"venue": "M Chinnaswamy Stadium, Bangalore"}, None),
        ("analyst-lb-team-run-rate", "Which batting team has the highest run rate?", "team", "run_rate", ["team"], {}, None),
        ("analyst-lb-venue-boundary", "Which venue has the highest boundary percentage?", "venue", "boundary_percentage", ["venue"], {}, None),
    ]
    for case_id, question, entity, metric, group_by, filters, direction in leaderboard_cases:
        cases.append(aggregate(case_id, "leaderboard", question, entity=entity, metric=metric, group_by=group_by, filters=filters, sort_direction=direction))

    breakdown_cases = [
        ("analyst-bd-kohli-style", "Break down Virat Kohli's strike rate by bowling style.", "batter", "batting_strike_rate", ["bowling_style"], {"batter": "Virat Kohli"}),
        ("analyst-bd-kohli-length", "Which length has kept Virat Kohli quietest by dot-ball percentage?", "batter", "batter_dot_ball_percentage", ["length"], {"batter": "Virat Kohli"}, "desc"),
        ("analyst-bd-kohli-shot", "Which shot type has produced the most runs for Virat Kohli?", "batter", "runs_scored", ["shot_type"], {"batter": "Virat Kohli"}),
        ("analyst-bd-kohli-zone", "Where has Virat Kohli scored most of his runs by field zone?", "batter", "runs_scored", ["field_zone"], {"batter": "Virat Kohli"}),
        ("analyst-bd-rohit-phase", "Show Rohit Sharma's run scoring by innings phase.", "batter", "runs_scored", ["phase"], {"batter": "Rohit Sharma"}),
        ("analyst-bd-rohit-style-boundary", "Against which bowling style does Rohit Sharma hit boundaries most often?", "batter", "boundary_percentage", ["bowling_style"], {"batter": "Rohit Sharma"}),
        ("analyst-bd-babar-line-false", "Which line causes the highest false-shot percentage for Babar Azam?", "batter", "false_shot_percentage", ["line"], {"batter": "Babar Azam"}),
        ("analyst-bd-babar-length-runs", "Which length has Babar Azam scored the most runs from?", "batter", "runs_scored", ["length"], {"batter": "Babar Azam"}),
        ("analyst-bd-buttler-zone-boundary", "Which field zone gives Jos Buttler the highest boundary percentage?", "batter", "boundary_percentage", ["field_zone"], {"batter": "Jos Buttler"}),
        ("analyst-bd-buttler-shot-runs", "Which shot type is most productive for Jos Buttler?", "batter", "runs_scored", ["shot_type"], {"batter": "Jos Buttler"}),
        ("analyst-bd-klaasen-spin-lines", "Against Heinrich Klaasen, which line has the highest dot-ball percentage?", "batter", "batter_dot_ball_percentage", ["line"], {"batter": "Heinrich Klaasen"}),
        ("analyst-bd-klaasen-style-runs", "Which bowling style has Heinrich Klaasen scored the most runs against?", "batter", "runs_scored", ["bowling_style"], {"batter": "Heinrich Klaasen"}),
        ("analyst-bd-miller-length-dismiss", "Which length dismisses David Miller most often?", "batter", "dismissals", ["length"], {"batter": "David Miller"}),
        ("analyst-bd-maxwell-style-sr", "Which bowling style does Glenn Maxwell score fastest against?", "batter", "batting_strike_rate", ["bowling_style"], {"batter": "Glenn Maxwell"}),
        ("analyst-bd-bumrah-phase-economy", "How does Jasprit Bumrah's economy rate vary by phase?", "bowler", "economy_rate", ["phase"], {"bowler": "Jasprit Bumrah"}),
        ("analyst-bd-bumrah-length-wickets", "Which length has given Jasprit Bumrah the most wickets?", "bowler", "wickets_taken", ["length"], {"bowler": "Jasprit Bumrah"}),
        ("analyst-bd-starc-line-dots", "Which line gives Mitchell Starc the highest dot-ball percentage?", "bowler", "bowler_dot_ball_percentage", ["line"], {"bowler": "Mitchell Starc"}),
        ("analyst-bd-malinga-length-yorker", "What share of Lasith Malinga's balls are yorkers by phase?", "bowler", "yorker_percentage", ["phase"], {"bowler": "Lasith Malinga"}),
        ("analyst-bd-rashid-hand-economy", "How does Rashid Khan's economy differ by batter hand?", "bowler", "economy_rate", ["batter_hand"], {"bowler": "Rashid Khan"}),
        ("analyst-bd-boult-phase-wickets", "Where does Trent Boult take wickets by phase?", "bowler", "wickets_taken", ["phase"], {"bowler": "Trent Boult"}),
    ]
    for item in breakdown_cases:
        case_id, question, entity, metric, group_by, filters, *direction = item
        cases.append(aggregate(case_id, "breakdown", question, entity=entity, metric=metric, group_by=group_by, filters=filters, sort_direction=direction[0] if direction else None))

    cases.extend(
        [
            split_compare("analyst-split-batter-after20", "split_compare", "Which batter improves their strike rate the most after facing 20 balls?", entity="batter", metric="batting_strike_rate", split_by="balls_faced_window", compare_values=["after_20_balls", "first_20_balls"]),
            split_compare("analyst-split-batter-wrist-finger", "split_compare", "Which batter has the biggest strike-rate gap between wrist spin and finger spin?", entity="batter", metric="batting_strike_rate", split_by="bowling_style_group", compare_values=["wrist_spin", "finger_spin"]),
            split_compare("analyst-split-bowler-power-death", "split_compare", "Which bowler has the biggest economy-rate difference between powerplay and death overs?", entity="bowler", metric="economy_rate", split_by="phase", compare_values=["powerplay", "death"]),
            split_compare("analyst-split-bowler-left-right", "split_compare", "Which bowler is most different against left-handers and right-handers by economy?", entity="bowler", metric="economy_rate", split_by="batter_hand", compare_values=["LHB", "RHB"]),
            split_compare("analyst-split-team-middle-death", "split_compare", "Which team accelerates most from middle overs to death overs?", entity="team", metric="run_rate", split_by="phase", compare_values=["death", "middle"]),
            split_compare("analyst-split-batter-power-death-boundary", "split_compare", "Which batter increases boundary percentage most from powerplay to death overs?", entity="batter", metric="boundary_percentage", split_by="phase", compare_values=["death", "powerplay"]),
            split_compare("analyst-split-bowler-dot-hands", "split_compare", "Which bowler's dot-ball percentage changes most by batter hand?", entity="bowler", metric="bowler_dot_ball_percentage", split_by="batter_hand", compare_values=["LHB", "RHB"]),
            split_compare("analyst-split-batter-overs15-20", "split_compare", "Which batter scores fastest between overs 15 and 20 compared with before over 15?", entity="batter", metric="batting_strike_rate", split_by="over_range", compare_values=["overs_15_to_20", "before_over_15"], filters={"over_range": [15, 20]}),
        ]
    )

    cases.extend(
        [
            compare("analyst-compare-kohli-smith", "player_comparison", "Compare Virat Kohli and Steven Smith as ODI batters.", entity="batter", players=["Virat Kohli", "Steven Smith"], metrics=["runs_scored", "batting_strike_rate", "batting_average", "boundary_percentage"]),
            compare("analyst-compare-rohit-warner-powerplay", "player_comparison", "Compare Rohit Sharma and David Warner in the powerplay.", entity="batter", players=["Rohit Sharma", "David Warner"], metrics=["runs_scored", "batting_strike_rate", "boundary_percentage"], filters={"phase": "powerplay"}),
            compare("analyst-compare-buttler-klaasen-spin", "player_comparison", "Compare Jos Buttler and Heinrich Klaasen against spin.", entity="batter", players=["Jos Buttler", "Heinrich Klaasen"], metrics=["batting_strike_rate", "runs_scored", "boundary_percentage"], filters={"bowling_style": "spin"}),
            compare("analyst-compare-babar-kohli-pace", "player_comparison", "Compare Babar Azam and Virat Kohli against pace bowling.", entity="batter", players=["Babar Azam", "Virat Kohli"], metrics=["runs_scored", "batting_strike_rate", "batter_dot_ball_percentage"], filters={"bowling_style": "pace"}),
            compare("analyst-compare-bumrah-starc", "player_comparison", "Compare Jasprit Bumrah and Mitchell Starc as ODI bowlers.", entity="bowler", players=["Jasprit Bumrah", "Mitchell Starc"], metrics=["wickets_taken", "economy_rate", "bowling_strike_rate", "bowler_dot_ball_percentage"]),
            compare("analyst-compare-bumrah-starc-death", "player_comparison", "Compare Jasprit Bumrah and Mitchell Starc in death overs.", entity="bowler", players=["Jasprit Bumrah", "Mitchell Starc"], metrics=["economy_rate", "wickets_taken", "bowler_dot_ball_percentage"], filters={"phase": "death"}),
            compare("analyst-compare-malinga-boult-powerplay", "player_comparison", "Compare Lasith Malinga and Trent Boult in the powerplay.", entity="bowler", players=["Lasith Malinga", "Trent Boult"], metrics=["wickets_taken", "economy_rate", "bowler_dot_ball_percentage"], filters={"phase": "powerplay"}),
            compare("analyst-compare-rashid-ashwin-spin", "player_comparison", "Compare Rashid Khan and Ravichandran Ashwin as spin bowlers.", entity="bowler", players=["Rashid Khan", "Ravichandran Ashwin"], metrics=["wickets_taken", "economy_rate", "bowler_dot_ball_percentage"], filters={"bowling_style": "spin"}),
        ]
    )

    cases.extend(
        [
            matchup("analyst-matchup-smith-bumrah", "matchup", "How has Steven Smith scored against Jasprit Bumrah?", entity="matchup", metric="batting_strike_rate", group_by=[], filters={"batter": "Steven Smith", "bowler": "Jasprit Bumrah"}, limit=1),
            matchup("analyst-matchup-maxwell-ashwin", "matchup", "How many runs has Glenn Maxwell made against Ravichandran Ashwin?", entity="matchup", metric="runs_scored", group_by=[], filters={"batter": "Glenn Maxwell", "bowler": "Ravichandran Ashwin"}, limit=1),
            matchup("analyst-matchup-kohli-starc", "matchup", "What is Virat Kohli's strike rate against Mitchell Starc?", entity="matchup", metric="batting_strike_rate", group_by=[], filters={"batter": "Virat Kohli", "bowler": "Mitchell Starc"}, limit=1),
            matchup("analyst-matchup-warner-dismissers", "matchup", "Which bowler has dismissed David Warner most often?", entity="bowler", metric="wickets_taken", group_by=["bowler"], filters={"batter": "David Warner"}),
            matchup("analyst-matchup-klaasen-dot", "matchup", "Which bowler has the highest dot-ball percentage against Heinrich Klaasen?", entity="bowler", metric="bowler_dot_ball_percentage", group_by=["bowler"], filters={"batter": "Heinrich Klaasen"}),
            matchup("analyst-matchup-miller-false", "matchup", "Which bowler induces the highest false-shot percentage against David Miller?", entity="bowler", metric="false_shot_percentage", group_by=["bowler"], filters={"batter": "David Miller"}),
            matchup("analyst-matchup-bumrah-batters", "matchup", "Against which batters has Jasprit Bumrah taken the most wickets?", entity="batter", metric="wickets_taken", group_by=["batter"], filters={"bowler": "Jasprit Bumrah"}),
            matchup("analyst-matchup-rashid-boundary", "matchup", "Which batter has the highest boundary percentage against Rashid Khan?", entity="batter", metric="boundary_percentage", group_by=["batter"], filters={"bowler": "Rashid Khan"}),
            matchup("analyst-matchup-kohli-pace-boundary", "matchup", "Which pace bowler has conceded boundaries most often to Virat Kohli?", entity="bowler", metric="boundary_percentage", group_by=["bowler"], filters={"batter": "Virat Kohli", "bowling_style": "pace"}),
            matchup("analyst-matchup-maxwell-spin-dots", "matchup", "Which spin bowling style creates the most dot balls against Glenn Maxwell?", entity="bowling_style", metric="bowler_dot_ball_percentage", group_by=["bowling_style"], filters={"batter": "Glenn Maxwell", "bowling_style": "spin"}),
        ]
    )

    extra_cases = [
        aggregate("analyst-extra-ab-spin-sr", "single_metric", "How quickly has AB de Villiers scored against spin?", entity="batter", metric="batting_strike_rate", group_by=["batter"], filters={"batter": "AB de Villiers", "bowling_style": "spin"}, limit=1),
        aggregate("analyst-extra-smith-middle-runs", "single_metric", "How many runs has Steven Smith scored in the middle overs?", entity="batter", metric="runs_scored", group_by=["batter"], filters={"batter": "Steven Smith", "phase": "middle"}, limit=1),
        aggregate("analyst-extra-shaheen-powerplay-economy", "single_metric", "What is Shaheen Shah Afridi's powerplay economy rate?", entity="bowler", metric="economy_rate", group_by=["bowler"], filters={"bowler": "Shaheen Shah Afridi", "phase": "powerplay"}, limit=1),
        aggregate("analyst-extra-ashwin-right-hand-dots", "single_metric", "What is Ravichandran Ashwin's dot-ball percentage against right-hand batters?", entity="bowler", metric="bowler_dot_ball_percentage", group_by=["bowler"], filters={"bowler": "Ravichandran Ashwin", "batter_hand": "RHB"}, limit=1),
        aggregate("analyst-extra-lb-lowest-batter-dots", "leaderboard", "Which batter has the lowest dot-ball percentage overall?", entity="batter", metric="batter_dot_ball_percentage", group_by=["batter"], sort_direction="asc"),
        aggregate("analyst-extra-lb-highest-false-batter", "leaderboard", "Which batter has the highest false-shot percentage?", entity="batter", metric="false_shot_percentage", group_by=["batter"]),
        aggregate("analyst-extra-lb-lowest-bowling-sr", "leaderboard", "Which bowler has the best bowling strike rate?", entity="bowler", metric="bowling_strike_rate", group_by=["bowler"]),
        aggregate("analyst-extra-lb-false-shots-bowler", "leaderboard", "Which bowler induces the highest false-shot percentage?", entity="bowler", metric="false_shot_percentage", group_by=["bowler"]),
        aggregate("analyst-extra-lb-good-length-runs", "leaderboard", "Which batter has scored the most runs against good-length balls?", entity="batter", metric="runs_scored", group_by=["batter"], filters={"length": "GOOD_LENGTH"}),
        aggregate("analyst-extra-lb-short-ball-sr", "leaderboard", "Which batter has the highest strike rate against short balls?", entity="batter", metric="batting_strike_rate", group_by=["batter"], filters={"length": "SHORT"}),
        aggregate("analyst-extra-lb-yorker-economy", "leaderboard", "Which bowler has the lowest economy rate when bowling yorkers?", entity="bowler", metric="economy_rate", group_by=["bowler"], filters={"length": "YORKER"}),
        aggregate("analyst-extra-lb-full-wickets", "leaderboard", "Which bowler takes the most wickets with full balls?", entity="bowler", metric="wickets_taken", group_by=["bowler"], filters={"length": "FULL"}),
        aggregate("analyst-extra-warner-style-boundary", "breakdown", "Break down David Warner's boundary percentage by bowling style.", entity="batter", metric="boundary_percentage", group_by=["bowling_style"], filters={"batter": "David Warner"}),
        aggregate("analyst-extra-smith-shot-runs", "breakdown", "Which shots bring Steven Smith the most runs?", entity="batter", metric="runs_scored", group_by=["shot_type"], filters={"batter": "Steven Smith"}),
        aggregate("analyst-extra-ab-zone-runs", "breakdown", "Which scoring zones did AB de Villiers use most for runs?", entity="batter", metric="runs_scored", group_by=["field_zone"], filters={"batter": "AB de Villiers"}),
        aggregate("analyst-extra-warner-line-dots", "breakdown", "Which line creates the most dot balls against David Warner?", entity="batter", metric="batter_dot_ball_percentage", group_by=["line"], filters={"batter": "David Warner"}),
        aggregate("analyst-extra-rabada-length-wickets", "breakdown", "Which length has produced Kagiso Rabada's wickets?", entity="bowler", metric="wickets_taken", group_by=["length"], filters={"bowler": "Kagiso Rabada"}),
        aggregate("analyst-extra-shaheen-line-dots", "breakdown", "Which line gives Shaheen Shah Afridi his highest dot-ball percentage?", entity="bowler", metric="bowler_dot_ball_percentage", group_by=["line"], filters={"bowler": "Shaheen Shah Afridi"}),
        aggregate("analyst-extra-ashwin-phase-economy", "breakdown", "How does Ravichandran Ashwin's economy rate vary by phase?", entity="bowler", metric="economy_rate", group_by=["phase"], filters={"bowler": "Ravichandran Ashwin"}),
        aggregate("analyst-extra-southee-hand-wickets", "breakdown", "Against which batting hand has Tim Southee taken more wickets?", entity="bowler", metric="wickets_taken", group_by=["batter_hand"], filters={"bowler": "Tim Southee"}),
        split_compare("analyst-extra-split-batter-left-right", "split_compare", "Which batter has the biggest strike-rate difference against left-hand and right-hand bowlers?", entity="batter", metric="batting_strike_rate", split_by="batter_hand", compare_values=["LHB", "RHB"]),
        split_compare("analyst-extra-split-team-power-death", "split_compare", "Which team changes run rate most between powerplay and death overs?", entity="team", metric="run_rate", split_by="phase", compare_values=["death", "powerplay"]),
        compare("analyst-extra-compare-maxwell-miller-death", "player_comparison", "Compare Glenn Maxwell and David Miller in death overs.", entity="batter", players=["Glenn Maxwell", "David Miller"], metrics=["runs_scored", "batting_strike_rate", "boundary_percentage"], filters={"phase": "death"}),
        compare("analyst-extra-compare-rabada-shaheen-powerplay", "player_comparison", "Compare Kagiso Rabada and Shaheen Shah Afridi in the powerplay.", entity="bowler", players=["Kagiso Rabada", "Shaheen Shah Afridi"], metrics=["wickets_taken", "economy_rate", "bowler_dot_ball_percentage"], filters={"phase": "powerplay"}),
        matchup("analyst-extra-matchup-kohli-rashid", "matchup", "What is Virat Kohli's scoring record against Rashid Khan?", entity="matchup", metric="runs_scored", group_by=[], filters={"batter": "Virat Kohli", "bowler": "Rashid Khan"}, limit=1),
        matchup("analyst-extra-matchup-babar-starc", "matchup", "What is Babar Azam's strike rate against Mitchell Starc?", entity="matchup", metric="batting_strike_rate", group_by=[], filters={"batter": "Babar Azam", "bowler": "Mitchell Starc"}, limit=1),
        matchup("analyst-extra-matchup-rohit-boult", "matchup", "How often has Trent Boult dismissed Rohit Sharma?", entity="matchup", metric="wickets_taken", group_by=[], filters={"batter": "Rohit Sharma", "bowler": "Trent Boult"}, limit=1),
        matchup("analyst-extra-matchup-buttler-bowlers", "matchup", "Which bowler has conceded the most runs to Jos Buttler?", entity="bowler", metric="runs_scored", group_by=["bowler"], filters={"batter": "Jos Buttler"}),
    ]
    cases.extend(extra_cases)

    return cases


if __name__ == "__main__":
    raise SystemExit(main())
