"""SQL that normalizes the line/length sources into one enrichment-ball table.

Three sources carry line, length and shot data:

- ``aucb`` (aucb_bbb.csv) and ``odata`` (odata_full.csv): the AUCB feed, all
  formats, 2012-2026.
- ``espn``: the ESPNcricinfo-style ODI data already behind CricAtlas
  (data/odi_analytics.duckdb), ODIs 2005-2025 with line/length from 2014.

Both files (``aucb_bbb.csv`` and ``odata_full.csv``) come from the same AUCB
feed and share fixture IDs. ``aucb`` is the newer, structured export and wins
for every fixture it contains. ``odata`` contributes only fixtures that
``aucb`` lacks, plus batter handedness and names that ``aucb`` left blank.

Verified source quirks corrected here (see docs/data-sources.md):
- aucb ``scoreValue`` is runs off the bat; the delivery total is
  ``scoreValue + extras``. The ``runs`` column is inconsistent and unused.
- aucb ``bowlingHandId`` is inverted before ~March 2023, and odata's
  ``bowlerHand`` disagrees too, so neither is used as truth. Bowler hand and
  style come from the player attribute table instead.
- aucb leaves ~78k batter/bowler names blank (mostly 2019-2022 India players);
  they are recovered from odata on the same ball.
- aucb encodes "no value" as the string 'Null' (and '0' for footwork).
- odata ``is_wicket`` omits run outs; dismissals come from ``dismissalType``.
- odata has 1,389 placeholder fixtures with no date, and some rows carry
  umpire-decision text as a player name ("OUT after REFERRAL",
  "OUT changed by umpire"); both are dropped/blanked.
- Older odata fixtures (2012-2018 internationals and leagues) number overs
  from 0 rather than 1; the alignment step detects the offset per innings.
"""

AUCB_RAW = "data/build/raw_aucb_bbb.parquet"
ODATA_RAW = "data/build/raw_odata_full.parquet"


def _null(expr: str) -> str:
    return f"NULLIF(NULLIF(NULLIF(TRIM({expr}), ''), 'Null'), 'None')"


def _player(expr: str) -> str:
    """Player name with odata's umpire-decision artefacts blanked out."""
    return (
        f"CASE WHEN regexp_matches({expr}, '(REFERRAL|changed by umpire)') THEN NULL "
        f"ELSE {_null(expr)} END"
    )


ENRICHMENT_SQL = f"""
ATTACH IF NOT EXISTS '{{espn}}' AS espn_db (READ_ONLY);
CREATE OR REPLACE TEMP VIEW aucb_raw AS SELECT * FROM read_parquet('{{aucb}}');
CREATE OR REPLACE TEMP VIEW odata_raw AS
SELECT DISTINCT * EXCLUDE (column00) FROM read_parquet('{{odata}}') WHERE matchDate IS NOT NULL;

-- odata row per (fixture, innings, over, ball, commentary): used to recover
-- names that aucb left blank, and to carry batter handedness.
CREATE OR REPLACE TEMP TABLE odata_names AS
SELECT fixtureId, inns, "over", ball, commentary,
       any_value({_player('batsman')}) AS batsman,
       any_value({_player('bowler')}) AS bowler,
       any_value(batsmanHand) AS batsman_hand
FROM odata_raw
GROUP BY ALL;

CREATE OR REPLACE TABLE enrich.balls AS
WITH a AS (
  SELECT
    'aucb' AS src,
    a.fixtureId AS fixture_id,
    a.competition AS src_competition,
    a.format AS src_format,
    TRY_CAST(a.matchDate AS DATE) AS match_date,
    TRY_CAST(a.inningNumber AS INTEGER) AS innings,
    TRY_CAST(a.overNumber AS INTEGER) AS over_1b,
    TRY_CAST(a.ballNumber AS INTEGER) AS ball_no,
    TRY_CAST(a.ballDateTime AS TIMESTAMP) AS ball_ts,
    TRY_CAST(a.event_seq AS INTEGER) AS event_seq,
    regexp_replace(a.battingTeam, ' (Men|Women)$', '') AS batting_team,
    regexp_replace(a.bowlingTeam, ' (Men|Women)$', '') AS bowling_team,
    COALESCE({_null('a.battingPlayer')}, o.batsman) AS batter,
    COALESCE({_null('a.bowlingPlayer')}, o.bowler) AS bowler,
    {_null('a.nonStrikerPlayer')} AS non_striker,
    CAST(TRY_CAST(a.battingPlayerId AS DOUBLE) AS BIGINT)::VARCHAR AS batter_src_id,
    CAST(TRY_CAST(a.bowlingPlayerId AS DOUBLE) AS BIGINT)::VARCHAR AS bowler_src_id,
    TRY_CAST(a.scoreValue AS INTEGER) AS runs_bat,
    TRY_CAST(a.extras AS INTEGER) AS extras,
    a.isWide = 'True' AS is_wide,
    a.isNoBall = 'True' AS is_noball,
    a.isByes = 'True' AS is_bye,
    a.isLegByes = 'True' AS is_legbye,
    (a.isWicket = 'True' OR a.bat_out = 'True' OR a.dismissalType IS NOT NULL) AS is_wicket,
    a.dismissalType AS dismissal_type,
    {_null('a.dismissedPlayer')} AS dismissed,
    {_null('a.lengthTypeId')} AS length,
    {_null('a.lineTypeId')} AS line,
    {_null('a.battingShotTypeId')} AS shot,
    NULLIF({_null('a.battingFeetId')}, '0') AS footwork,
    {_null('a.battingConnectionId')} AS connection,
    TRY_CAST(a.control AS INTEGER) AS control_raw,
    {_null('a.bowlingDetailId')} AS bowling_detail,
    {_null('a.bowlingTypeId')} AS bowling_type_raw,
    {_null('a.bowlingFromId')} AS bowling_from,
    {_null('a.bowlingHandId')} AS bowling_hand_raw,
    TRY_CAST(a.shotAngle AS DOUBLE) AS shot_angle,
    TRY_CAST(a.shotMagnitude AS DOUBLE) AS shot_magnitude,
    {_null('a.fieldingPosition')} AS fielding_position,
    a.isAirControlled = 'True' AS air_controlled,
    a.isAirNotControlled = 'True' AS air_not_controlled,
    o.batsman_hand AS batter_hand_src,
    a.commentary,
    TRY_CAST(a.runsWide AS INTEGER) AS wide_runs,
    TRY_CAST(a.noBallsCount AS INTEGER) AS noball_runs,
    TRY_CAST(a.runsByes AS INTEGER) AS bye_runs,
    TRY_CAST(a.runsLegByes AS INTEGER) AS legbye_runs,
    a.tossWinner AS toss_winner, a.tossDecision AS toss_decision, a.matchWinner AS match_winner,
    a.winType AS win_type, a.winMargin AS win_margin, a.ground AS ground
  FROM aucb_raw a
  LEFT JOIN odata_names o
    ON o.fixtureId = a.fixtureId AND o.inns = a.inningNumber AND o."over" = a.overNumber
   AND o.ball = a.ballNumber AND o.commentary = a.commentary
),
-- Shot and variation vocabularies of odata-only fixtures are mapped onto the
-- aucb codes by majority vote over the ~1M balls present in both files.
overlap AS (
  SELECT o.shot_type, o.foot, o.variation, a.battingShotTypeId AS a_shot, a.bowlingDetailId AS a_detail
  FROM odata_raw o JOIN aucb_raw a
    ON a.fixtureId = o.fixtureId AND a.inningNumber = o.inns AND a.overNumber = o."over"
   AND a.ballNumber = o.ball AND a.commentary = o.commentary
),
shot_map AS (
  SELECT shot_type, foot, arg_max(a_shot, n) AS shot, max(n) / sum(n) AS purity
  FROM (SELECT shot_type, foot, a_shot, count(*) AS n FROM overlap WHERE a_shot IS NOT NULL AND a_shot <> 'Null' GROUP BY ALL)
  GROUP BY ALL HAVING max(n) / sum(n) >= 0.8
),
detail_map AS (
  SELECT variation, arg_max(a_detail, n) AS detail
  FROM (SELECT variation, a_detail, count(*) AS n FROM overlap WHERE a_detail IS NOT NULL AND a_detail <> 'Null' GROUP BY ALL)
  GROUP BY ALL HAVING max(n) / sum(n) >= 0.8
),
o AS (
  SELECT
    'odata' AS src,
    o.fixtureId AS fixture_id,
    o.competition AS src_competition,
    o.format AS src_format,
    TRY_CAST(o.matchDate AS DATE) AS match_date,
    TRY_CAST(o.inns AS INTEGER) AS innings,
    TRY_CAST(o."over" AS INTEGER) AS over_1b,
    TRY_CAST(o.ball AS INTEGER) AS ball_no,
    TRY_CAST(o."timestamp" AS TIMESTAMP) AS ball_ts,
    NULL::INTEGER AS event_seq,
    o.battingTeam AS batting_team,
    o.bowlingTeam AS bowling_team,
    {_player('o.batsman')} AS batter,
    {_player('o.bowler')} AS bowler,
    NULL AS non_striker,
    NULL AS batter_src_id,
    NULL AS bowler_src_id,
    CAST(TRY_CAST(o.runs_scored AS DOUBLE) AS INTEGER) AS runs_bat,
    TRY_CAST(o.extras AS INTEGER) AS extras,
    regexp_matches(o.commentary, '^(OUT! [^.]*\\. )?Wide ') AS is_wide,
    regexp_matches(o.commentary, '^(OUT! [^.]*\\. )?No ball ') AS is_noball,
    NULL::BOOLEAN AS is_bye,
    NULL::BOOLEAN AS is_legbye,
    o.dismissalType IS NOT NULL AS is_wicket,
    o.dismissalType AS dismissal_type,
    o.dismissedPlayer AS dismissed,
    CASE o.length WHEN 'length ball' THEN 'LengthBall' WHEN 'back of a length' THEN 'BackOfALength'
      WHEN 'half volley' THEN 'HalfVolley' WHEN 'short' THEN 'Short' WHEN 'full toss' THEN 'FullToss'
      WHEN 'yorker' THEN 'Yorker' WHEN 'bouncer' THEN 'HalfTracker' END AS length,
    CASE o.line WHEN 'outside off' THEN 'OutsideOff' WHEN 'off' THEN 'OffStump' WHEN 'middle' THEN 'MiddleStump'
      WHEN 'leg' THEN 'LegStump' WHEN 'down leg' THEN 'DownLeg' WHEN 'wide outside off' THEN 'Wide' END AS line,
    sm.shot AS shot,
    CASE o.foot WHEN 'front foot' THEN 'FrontFoot' WHEN 'back foot' THEN 'BackFoot' WHEN 'down the track' THEN 'DownTheTrack'
      WHEN 'no foot movement' THEN 'NoMovement' WHEN 'backing away' THEN 'BacksAway' WHEN 'in front' THEN 'MovesInfront'
      WHEN 'ducked' THEN 'Ducked' WHEN 'deep in crease' THEN 'DeepInCrease' END AS footwork,
    NULL AS connection,
    NULL::INTEGER AS control_raw,
    dm.detail AS bowling_detail,
    o.bowlerType AS bowling_type_raw,
    NULL AS bowling_from,
    o.bowlerHand AS bowling_hand_raw,
    TRY_CAST(o.shot_angle AS DOUBLE) AS shot_angle,
    TRY_CAST(o.shot_magnitude AS DOUBLE) AS shot_magnitude,
    o.fielding_position AS fielding_position,
    NULL::BOOLEAN AS air_controlled,
    NULL::BOOLEAN AS air_not_controlled,
    o.batsmanHand AS batter_hand_src,
    o.commentary,
    CASE WHEN regexp_matches(o.commentary, '^(OUT! [^.]*\\. )?Wide ') THEN TRY_CAST(o.extras AS INTEGER) END AS wide_runs,
    CASE WHEN regexp_matches(o.commentary, '^(OUT! [^.]*\\. )?No ball ') THEN 1 END AS noball_runs,
    NULL::INTEGER AS bye_runs,
    NULL::INTEGER AS legbye_runs,
    NULL AS toss_winner, NULL AS toss_decision, NULL AS match_winner, NULL AS win_type, NULL AS win_margin,
    o.ground AS ground
  FROM odata_raw o
  LEFT JOIN shot_map sm ON sm.shot_type IS NOT DISTINCT FROM o.shot_type AND sm.foot IS NOT DISTINCT FROM o.foot
  LEFT JOIN detail_map dm ON dm.variation IS NOT DISTINCT FROM o.variation
  WHERE o.fixtureId NOT IN (SELECT DISTINCT fixtureId FROM aucb_raw)
),
-- ESPNcricinfo-style ODI rows. ``ball`` is the delivery number within the
-- over (wides included); extras columns hold runs. Line/length/shot codes stay
-- in ESPN's own vocabulary here and are mapped to the canonical one at publish.
e AS (
  SELECT
    'espn' AS src,
    e.p_match AS fixture_id,
    e.competition AS src_competition,
    'ODI' AS src_format,
    TRY_CAST(e."date" AS DATE) AS match_date,
    TRY_CAST(e.inns AS INTEGER) AS innings,
    TRY_CAST(e."over" AS INTEGER) AS over_1b,
    TRY_CAST(e.ball AS INTEGER) AS ball_no,
    NULL::TIMESTAMP AS ball_ts,
    NULL::INTEGER AS event_seq,
    e.team_bat AS batting_team,
    e.team_bowl AS bowling_team,
    e.bat AS batter,
    e.bowl AS bowler,
    NULL AS non_striker,
    e.p_bat AS batter_src_id,
    e.p_bowl AS bowler_src_id,
    TRY_CAST(e.batruns AS INTEGER) AS runs_bat,
    TRY_CAST(e.score AS INTEGER) - TRY_CAST(e.batruns AS INTEGER) AS extras,
    COALESCE(TRY_CAST(e.wide AS INTEGER), 0) > 0 AS is_wide,
    COALESCE(TRY_CAST(e.noball AS INTEGER), 0) > 0 AS is_noball,
    COALESCE(TRY_CAST(e.byes AS INTEGER), 0) > 0 AS is_bye,
    COALESCE(TRY_CAST(e.legbyes AS INTEGER), 0) > 0 AS is_legbye,
    lower(CAST(e."out" AS VARCHAR)) = 'true' AS is_wicket,
    NULLIF(e.dismissal, '') AS dismissal_type,
    NULL AS dismissed,
    NULLIF(e.length, '') AS length,
    NULLIF(e.line, '') AS line,
    NULLIF(e.shot, '') AS shot,
    NULL AS footwork,
    NULL AS connection,
    TRY_CAST(TRY_CAST(e.control AS DOUBLE) AS INTEGER) AS control_raw,
    NULL AS bowling_detail,
    NULLIF(e.bowl_style, '') AS bowling_type_raw,
    NULL AS bowling_from,
    NULL AS bowling_hand_raw,
    NULL::DOUBLE AS shot_angle,
    NULL::DOUBLE AS shot_magnitude,
    NULL AS fielding_position,
    NULL::BOOLEAN AS air_controlled,
    NULL::BOOLEAN AS air_not_controlled,
    e.bat_hand AS batter_hand_src,
    NULL AS commentary,
    TRY_CAST(e.wagonX AS INTEGER) AS wagon_x,
    TRY_CAST(e.wagonY AS INTEGER) AS wagon_y,
    TRY_CAST(e.wagonZone AS INTEGER) AS wagon_zone,
    NULLIF(TRY_CAST(e.wide AS INTEGER), 0) AS wide_runs,
    NULLIF(TRY_CAST(e.noball AS INTEGER), 0) AS noball_runs,
    NULLIF(TRY_CAST(e.byes AS INTEGER), 0) AS bye_runs,
    NULLIF(TRY_CAST(e.legbyes AS INTEGER), 0) AS legbye_runs,
    e.p_out AS player_out_src_id,
    e.toss AS toss_winner, NULL AS toss_decision, e.winner AS match_winner, NULL AS win_type, NULL AS win_margin,
    e.ground AS ground, e.country AS country
  FROM espn_db.analytics.deliveries_v1 e
)
SELECT *,
  row_number() OVER (
    PARTITION BY src, fixture_id, innings
    ORDER BY over_1b, ball_no, ball_ts NULLS LAST, event_seq NULLS LAST, commentary
  ) AS seq
FROM (SELECT * FROM a UNION ALL BY NAME SELECT * FROM o UNION ALL BY NAME SELECT * FROM e);
"""
