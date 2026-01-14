def extract_match_row(path: Path, data: dict) -> dict:
    """
    Extract one row for the `matches` table from a single IPL JSON file.
    `path` is used to derive match_id from the filename.
    """
    info = data["info"]
    
    # match_id from filename, e.g. '1082646.json' -> 1082646
    match_id = int(path.stem)
    
    teams = info["teams"]
    team1, team2 = teams[0], teams[1]
    
    # outcome block can have runs or wickets
    outcome = info.get("outcome", {})
    winner = outcome.get("winner")
    by = outcome.get("by", {})
    result_margin = None
    result_margin_type = None
    if "runs" in by:
        result_margin = by["runs"]
        result_margin_type = "runs"
    elif "wickets" in by:
        result_margin = by["wickets"]
        result_margin_type = "wickets"
    
    officials = info.get("officials", {})
    
    row = {
        "match_id": match_id,
        "season": str(info.get("season", "")),
        "match_date": info["dates"][0],
        "city": info.get("city"),
        "venue": info.get("venue"),
        "event_name": info.get("event", {}).get("name"),
        "match_number": info.get("event", {}).get("match_number"),
        "team1": team1,
        "team2": team2,
        "toss_winner": info["toss"]["winner"],
        "toss_decision": info["toss"]["decision"],
        "winner": winner,
        "result_margin": result_margin,
        "result_margin_type": result_margin_type,
        "balls_per_over": info.get("balls_per_over"),
        "overs_scheduled": info.get("overs"),
        "match_type": info.get("match_type"),
        "gender": info.get("gender"),
        "team_type": info.get("team_type"),
        # lists below: we store them as Python lists for now
        "player_of_match": info.get("player_of_match", []),
        "umpires": officials.get("umpires", []),
        "tv_umpires": officials.get("tv_umpires", []),
        "reserve_umpires": officials.get("reserve_umpires", []),
        "match_referees": officials.get("match_referees", []),
        "players_team1": info["players"][team1],
        "players_team2": info["players"][team2],
    }
    return row

def extract_delivery_rows(path: Path, data: dict) -> list[dict]:
    """
    Extract all delivery rows for this match JSON,
    matching the `deliveries` table schema.
    """
    info = data["info"]
    match_id = int(path.stem)
    rows = []

    for innings_idx, innings in enumerate(data["innings"]):
        innings_number = innings_idx + 1
        batting_team = innings["team"]
        bowling_team = get_bowling_team(info, batting_team)

        # absolute ball counter (legal balls) for this innings
        ball_number_abs = 0

        for over in innings["overs"]:
            over_number = over["over"]     # 0-based over index

            deliveries = over["deliveries"]
            for ball_idx, delivery in enumerate(deliveries):
                ball_in_over = ball_idx + 1

                # In Cricsheet/modern JSON, each 'delivery' is a legal ball,
                # even if there are wides/no-balls (extras are stored but ball still counts).
                ball_number_abs += 1

                phase = classify_phase(innings, over_number, ball_number_abs)

                runs = delivery["runs"]
                runs_batter = runs["batter"]
                runs_extras_total = runs["extras"]
                runs_total = runs["total"]

                extras_obj = delivery.get("extras", {})
                extras_wides = extras_obj.get("wides", 0)
                extras_noballs = extras_obj.get("noballs", 0)
                extras_byes = extras_obj.get("byes", 0)
                extras_legbyes = extras_obj.get("legbyes", 0)

                runs_conceded_bowler = runs_batter + extras_wides + extras_noballs

                is_boundary_4 = (runs_batter == 4)
                is_boundary_6 = (runs_batter == 6)
                is_dot_bowler = (runs_conceded_bowler == 0)
                is_dot_batter = (runs_batter == 0)

                # Dismissal info
                dismissal_kind = None
                dismissal_player_out = None
                dismissal_bowler_credit = None
                fielder_1 = None

                if "wickets" in delivery and delivery["wickets"]:
                    w = delivery["wickets"][0]
                    dismissal_kind = w.get("kind")
                    dismissal_player_out = w.get("player_out")

                    fielders = w.get("fielders", [])
                    if fielders:
                        # Some JSONs store as list of dicts with 'name'
                        fielder = fielders[0]
                        if isinstance(fielder, dict):
                            fielder_1 = fielder.get("name")
                        else:
                            # sometimes might just be a string
                            fielder_1 = str(fielder)

                    # credit wicket to bowler for standard types
                    bowler_credit_kinds = {"bowled", "lbw", "caught", "stumped", "hit wicket", "caught and bowled"}
                    dismissal_bowler_credit = dismissal_kind in bowler_credit_kinds

                row = {
                    "match_id": match_id,
                    "innings_number": innings_number,
                    "batting_team": batting_team,
                    "bowling_team": bowling_team,
                    "over_number": over_number,
                    "ball_in_over": ball_in_over,
                    "ball_number_absolute": ball_number_abs,
                    "phase": phase,
                    "batter": delivery["batter"],
                    "bowler": delivery["bowler"],
                    "non_striker": delivery["non_striker"],
                    "runs_batter": runs_batter,
                    "runs_extras_total": runs_extras_total,
                    "runs_total": runs_total,
                    "extras_wides": extras_wides,
                    "extras_noballs": extras_noballs,
                    "extras_byes": extras_byes,
                    "extras_legbyes": extras_legbyes,
                    "runs_conceded_bowler": runs_conceded_bowler,
                    "is_legal_delivery": True,  # treating each listed delivery as legal ball
                    "is_boundary_4": is_boundary_4,
                    "is_boundary_6": is_boundary_6,
                    "is_dot_ball_bowler_view": is_dot_bowler,
                    "is_dot_ball_batter_view": is_dot_batter,
                    "dismissal_kind": dismissal_kind,
                    "dismissal_player_out": dismissal_player_out,
                    "dismissal_bowler_credit": dismissal_bowler_credit,
                    "fielder_1": fielder_1,
                }

                rows.append(row)

    return rows
