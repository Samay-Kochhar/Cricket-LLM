"""SQL for the published multi-format database (data/cricket_all.duckdb).

Truth model, decided from measured comparisons (docs/data-sources.md):

- Scores, wickets, results: Cricsheet. Where Cricsheet and the
  ESPNcricinfo-style ODI data disagree on a first-innings total, Cricsheet
  matches the official target in 143 of 157 cases, ESPN in 0.
- Matches Cricsheet does not hold (withheld Afghanistan games, the newest
  fixtures, some tours and domestic games) are scored from ESPNcricinfo (ODIs)
  or the AUCB feed, and marked by ``score_source``.
- Line/length: per delivery, ESPNcricinfo where it has a value (ODIs, 2014+),
  otherwise AUCB. On 239k shared ODI balls ESPN's length is the more
  consistent with independently recorded shots; both raw values are kept.
- Player attributes: ESPNcricinfo styles/handedness first, then the AUCB feed
  (odata batter hand; AUCB bowling type with the hand-coding inversion
  corrected per fixture).
"""

# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------
PLAYERS_SQL = """
CREATE OR REPLACE TEMP TABLE people AS
SELECT * FROM read_csv('{people}', all_varchar = true, header = true);

CREATE OR REPLACE TEMP TABLE cricinfo_key AS
SELECT DISTINCT identifier, k AS cricinfo_id FROM (
  SELECT identifier, key_cricinfo AS k FROM people UNION ALL
  SELECT identifier, key_cricinfo_2 FROM people UNION ALL
  SELECT identifier, key_cricinfo_3 FROM people
) WHERE k IS NOT NULL;

-- Accepted ball pairs with the Cricsheet delivery they describe.
CREATE OR REPLACE TEMP TABLE aligned AS
SELECT a.*, b.batter AS s_batter, b.bowler AS s_bowler, b.batter_src_id, b.bowler_src_id,
       b.batter_hand_src, b.bowling_type_raw, b.bowling_hand_raw, b.match_date,
       d.batter_id, d.bowler_id
FROM enrich.ball_alignment a
JOIN enrich.balls b USING (src, fixture_id, innings, seq)
JOIN cs.deliveries d USING (match_id, innings_no, innings_delivery_seq);

-- Source player key -> Cricsheet identifier, by majority over aligned balls.
CREATE OR REPLACE TEMP TABLE xref AS
WITH obs AS (
  SELECT CASE WHEN src = 'espn' THEN 'espn' ELSE 'aucb' END AS fam,
         COALESCE(batter_src_id, 'name:' || s_batter) AS src_key, batter_id AS cs_id
  FROM aligned WHERE batter_id IS NOT NULL AND (batter_src_id IS NOT NULL OR s_batter IS NOT NULL)
  UNION ALL
  SELECT CASE WHEN src = 'espn' THEN 'espn' ELSE 'aucb' END,
         COALESCE(bowler_src_id, 'name:' || s_bowler), bowler_id
  FROM aligned WHERE bowler_id IS NOT NULL AND (bowler_src_id IS NOT NULL OR s_bowler IS NOT NULL)
  UNION ALL
  SELECT 'aucb', 'name:' || s_batter, batter_id FROM aligned WHERE batter_id IS NOT NULL AND s_batter IS NOT NULL AND batter_src_id IS NOT NULL
  UNION ALL
  SELECT 'aucb', 'name:' || s_bowler, bowler_id FROM aligned WHERE bowler_id IS NOT NULL AND s_bowler IS NOT NULL AND bowler_src_id IS NOT NULL
),
counts AS (SELECT fam, src_key, cs_id, count(*) AS n FROM obs GROUP BY ALL)
SELECT fam, src_key, arg_max(cs_id, n) AS cs_id, max(n)::DOUBLE / sum(n) AS purity, sum(n) AS n
FROM counts GROUP BY ALL
HAVING max(n)::DOUBLE / sum(n) >= 0.8;

-- ESPNcricinfo attributes per Cricinfo player id.
CREATE OR REPLACE TEMP TABLE espn_bat AS
SELECT p_bat AS cricinfo_id, mode(bat_hand) AS bat_hand
FROM espn_db.analytics.deliveries_v1 WHERE bat_hand IN ('RHB', 'LHB') GROUP BY 1;
CREATE OR REPLACE TEMP TABLE espn_bowl AS
SELECT p_bowl AS cricinfo_id, mode(bowl_style) AS bowl_style
FROM espn_db.analytics.deliveries_v1 WHERE bowl_style NOT IN ('-', '') GROUP BY 1;

-- Cricsheet id -> Cricinfo id: the register first, then aligned observation.
CREATE OR REPLACE TEMP TABLE cs_cricinfo AS
SELECT identifier AS cs_id, cricinfo_id FROM cricinfo_key
UNION
SELECT cs_id, src_key FROM xref WHERE fam = 'espn' AND src_key NOT LIKE 'name:%';

CREATE OR REPLACE TEMP TABLE espn_attr AS
SELECT c.cs_id, mode(b.bat_hand) AS bat_hand, mode(w.bowl_style) AS bowl_style
FROM cs_cricinfo c
LEFT JOIN espn_bat b USING (cricinfo_id)
LEFT JOIN espn_bowl w USING (cricinfo_id)
GROUP BY 1;

-- Bowler hand from an ESPN style code: left-arm pace (LF/LFM/LMF/LM), SLA, LWS.
CREATE OR REPLACE MACRO style_hand(style) AS
  CASE WHEN style IS NULL THEN NULL
       WHEN regexp_matches(split_part(style, '/', 1), '^(L[FM]|LMF|SLA|LWS)') THEN 'Left'
       ELSE 'Right' END;

-- AUCB hand coding is inverted on every fixture up to 2023-02-26 and correct
-- from 2023-02-28 (measured: 1,927 and 2,154 fixtures, no exceptions).
-- Orientation per fixture is read from bowlers whose hand ESPN knows; fixtures
-- without such bowlers use the switch date.
CREATE OR REPLACE TEMP TABLE fixture_hand_orientation AS
WITH known AS (
  SELECT a.src, a.fixture_id, any_value(a.match_date) AS d,
         avg((a.bowling_hand_raw = style_hand(e.bowl_style))::INT) AS agree, count(*) AS n
  FROM aligned a JOIN espn_attr e ON e.cs_id = a.bowler_id
  WHERE a.src = 'aucb' AND a.bowling_hand_raw IN ('Left', 'Right') AND e.bowl_style IS NOT NULL
  GROUP BY ALL
)
SELECT src, fixture_id,
       CASE WHEN n >= 30 AND agree >= 0.75 THEN FALSE
            WHEN n >= 30 AND agree <= 0.25 THEN TRUE
            ELSE d <= DATE '2023-02-26' END AS inverted
FROM (
  SELECT f.src, f.fixture_id, min(b.match_date) AS d, any_value(k.agree) AS agree, COALESCE(any_value(k.n), 0) AS n
  FROM (SELECT DISTINCT src, fixture_id FROM enrich.balls WHERE src = 'aucb') f
  JOIN enrich.balls b USING (src, fixture_id)
  LEFT JOIN known k USING (src, fixture_id)
  GROUP BY ALL
);

CREATE OR REPLACE TEMP TABLE aucb_attr AS
WITH bowl AS (
  SELECT a.bowler_id AS cs_id,
         -- odata's hand field is unreliable and has no orientation signal: unused.
         CASE WHEN a.src <> 'aucb' THEN NULL
              WHEN o.inverted THEN CASE a.bowling_hand_raw WHEN 'Left' THEN 'Right' WHEN 'Right' THEN 'Left' END
              ELSE a.bowling_hand_raw END AS hand,
         CASE WHEN a.bowling_type_raw IN ('Fast', 'FastSeam', 'Fast Seam', 'Fast Medium', 'Medium Fast', 'Medium') THEN 'pace'
              WHEN a.bowling_type_raw IN ('OffSpin', 'Off Spin') THEN 'off spin'
              WHEN a.bowling_type_raw = 'Orthodox' THEN 'orthodox'
              WHEN a.bowling_type_raw IN ('LegSpin', 'Leg Spin', 'Leg break') THEN 'leg spin'
              WHEN a.bowling_type_raw = 'Unorthodox' THEN 'wrist spin' END AS kind
  FROM aligned a LEFT JOIN fixture_hand_orientation o USING (src, fixture_id)
  WHERE a.src IN ('aucb', 'odata') AND a.bowler_id IS NOT NULL
)
SELECT cs_id,
       mode(hand) FILTER (hand IS NOT NULL) AS hand,
       mode(kind) FILTER (kind IS NOT NULL) AS kind,
       NULL AS bat_hand
FROM bowl GROUP BY 1
UNION ALL
SELECT batter_id, NULL, NULL,
       mode(CASE batter_hand_src WHEN 'Right' THEN 'RHB' WHEN 'Left' THEN 'LHB' END)
         FILTER (batter_hand_src IN ('Right', 'Left'))
FROM aligned WHERE src IN ('aucb', 'odata') AND batter_id IS NOT NULL GROUP BY 1;

CREATE OR REPLACE TABLE out.analytics.players AS
WITH a AS (
  SELECT cs_id, any_value(hand) FILTER (hand IS NOT NULL) AS hand,
         any_value(kind) FILTER (kind IS NOT NULL) AS kind,
         any_value(bat_hand) FILTER (bat_hand IS NOT NULL) AS bat_hand
  FROM aucb_attr GROUP BY 1
),
base AS (
  SELECT p.identifier AS player_id, p.name, p.unique_name,
         (SELECT min(cricinfo_id) FROM cricinfo_key k WHERE k.identifier = p.identifier) AS cricinfo_id,
         e.bat_hand AS espn_bat_hand, e.bowl_style AS espn_bowl_style,
         a.bat_hand AS aucb_bat_hand, a.hand AS aucb_bowl_hand, a.kind AS aucb_bowl_kind
  FROM people p
  LEFT JOIN espn_attr e ON e.cs_id = p.identifier
  LEFT JOIN a ON a.cs_id = p.identifier
)
SELECT player_id, name, unique_name, cricinfo_id,
       COALESCE(espn_bat_hand, aucb_bat_hand) AS batting_hand,
       CASE WHEN espn_bat_hand IS NOT NULL THEN 'espn' WHEN aucb_bat_hand IS NOT NULL THEN 'aucb' END AS batting_hand_source,
       espn_bowl_style AS bowling_style_code,
       COALESCE(style_hand(espn_bowl_style), aucb_bowl_hand) AS bowling_arm,
       CASE
         WHEN espn_bowl_style IS NOT NULL THEN
           CASE WHEN regexp_matches(split_part(espn_bowl_style, '/', 1), '^R(F|FM|MF|M|SM)?$') THEN 'Right-arm pace'
                WHEN regexp_matches(split_part(espn_bowl_style, '/', 1), '^L(F|FM|MF|M)$') THEN 'Left-arm pace'
                WHEN split_part(espn_bowl_style, '/', 1) = 'OB' THEN 'Right-arm off spin'
                WHEN split_part(espn_bowl_style, '/', 1) IN ('LB', 'LBG') THEN 'Right-arm leg spin'
                WHEN split_part(espn_bowl_style, '/', 1) = 'SLA' THEN 'Left-arm orthodox'
                WHEN split_part(espn_bowl_style, '/', 1) = 'LWS' THEN 'Left-arm wrist spin'
           END
         WHEN aucb_bowl_kind = 'pace' AND aucb_bowl_hand IS NOT NULL THEN aucb_bowl_hand || '-arm pace'
         WHEN aucb_bowl_kind = 'off spin' THEN COALESCE(aucb_bowl_hand, 'Right') || '-arm off spin'
         WHEN aucb_bowl_kind = 'leg spin' THEN 'Right-arm leg spin'
         WHEN aucb_bowl_kind = 'orthodox' THEN 'Left-arm orthodox'
         WHEN aucb_bowl_kind = 'wrist spin' THEN 'Left-arm wrist spin'
       END AS bowling_style_group,
       CASE WHEN espn_bowl_style IS NOT NULL THEN 'espn' WHEN aucb_bowl_kind IS NOT NULL THEN 'aucb' END AS bowling_style_source
FROM base;
"""

# --------------------------------------------------------------------------
# Delivery backbone: Cricsheet, then matches Cricsheet does not hold.
# --------------------------------------------------------------------------
BACKBONE_SQL = """
-- Matches outside Cricsheet. ESPN-only ODIs first; AUCB/odata fixtures that
-- aligned onto one of them are folded in there, the rest stand alone.
CREATE OR REPLACE TEMP TABLE espn_only AS
SELECT DISTINCT fixture_id FROM enrich.balls
WHERE src = 'espn' AND fixture_id NOT IN (SELECT match_id FROM cs.matches)
  -- an ESPN ODI missing >10% of an innings that AUCB holds in full gives way to AUCB
  AND fixture_id NOT IN (SELECT espn_fixture FROM enrich.orphan_pairs WHERE espn_incomplete);

CREATE OR REPLACE TEMP TABLE feed_only AS
SELECT src, fixture_id
FROM (SELECT src, fixture_id, count(*) AS n FROM enrich.balls WHERE src IN ('aucb', 'odata') GROUP BY ALL)
WHERE n >= 30
  AND (src, fixture_id) NOT IN (SELECT (src, fixture_id) FROM enrich.fixture_match WHERE accepted)
  AND (src, fixture_id) NOT IN (SELECT DISTINCT (src, fixture_id) FROM enrich.orphan_alignment);

-- Resolve a source player to a Cricsheet identifier: aligned-observation
-- cross-reference first, then an unambiguous Cricsheet register name.
CREATE OR REPLACE TEMP TABLE register_names AS
SELECT name, any_value(identifier) AS identifier FROM read_csv('{names}', all_varchar = true, header = true)
GROUP BY name HAVING count(DISTINCT identifier) = 1;

-- Every source player key used by non-Cricsheet matches, resolved once:
-- aligned-observation cross-reference first, then the Cricsheet register of
-- ESPNcricinfo IDs, then an unambiguous Cricsheet register name.
CREATE OR REPLACE TEMP TABLE player_keys AS
SELECT DISTINCT fam, src_id, nm FROM (
  SELECT 'espn' AS fam, batter_src_id AS src_id, batter AS nm FROM enrich.balls
   WHERE src = 'espn' AND fixture_id IN (SELECT fixture_id FROM espn_only)
  UNION ALL SELECT 'espn', bowler_src_id, bowler FROM enrich.balls
   WHERE src = 'espn' AND fixture_id IN (SELECT fixture_id FROM espn_only)
  UNION ALL SELECT 'espn', player_out_src_id, NULL FROM enrich.balls
   WHERE src = 'espn' AND fixture_id IN (SELECT fixture_id FROM espn_only) AND is_wicket
  UNION ALL SELECT 'aucb', batter_src_id, batter FROM enrich.balls WHERE (src, fixture_id) IN (SELECT (src, fixture_id) FROM feed_only)
  UNION ALL SELECT 'aucb', bowler_src_id, bowler FROM enrich.balls WHERE (src, fixture_id) IN (SELECT (src, fixture_id) FROM feed_only)
  UNION ALL SELECT 'aucb', NULL, non_striker FROM enrich.balls WHERE (src, fixture_id) IN (SELECT (src, fixture_id) FROM feed_only)
  UNION ALL SELECT 'aucb', NULL, COALESCE(dismissed, batter) FROM enrich.balls
   WHERE (src, fixture_id) IN (SELECT (src, fixture_id) FROM feed_only) AND is_wicket
);
CREATE OR REPLACE TEMP TABLE player_resolved AS
SELECT k.fam, k.src_id, k.nm, COALESCE(x1.cs_id, c.cs_id, x2.cs_id, r.identifier) AS cs_id
FROM player_keys k
LEFT JOIN xref x1 ON x1.fam = k.fam AND x1.src_key = k.src_id
LEFT JOIN (SELECT cricinfo_id, min(cs_id) AS cs_id FROM cs_cricinfo GROUP BY 1) c
  ON k.fam = 'espn' AND c.cricinfo_id = k.src_id
LEFT JOIN xref x2 ON x2.fam = k.fam AND x2.src_key = 'name:' || k.nm
LEFT JOIN register_names r ON r.name = k.nm;

CREATE OR REPLACE TEMP TABLE espn_names AS
SELECT p_bat AS cricinfo_id, any_value(bat) AS name FROM espn_db.analytics.deliveries_v1 GROUP BY 1;

CREATE OR REPLACE TEMP TABLE backbone AS
SELECT
  d.match_id, 'cricsheet' AS score_source,
  d.innings_no, d.is_super_over, d.batting_team, d.bowling_team,
  d.over_no, d.delivery_in_over, d.legal_ball_in_over, d.innings_delivery_seq, d.is_legal,
  d.batter, d.batter_id, d.non_striker, d.non_striker_id, d.bowler, d.bowler_id,
  d.runs_batter, d.runs_extras, d.runs_total, d.non_boundary,
  d.wides, d.noballs, d.byes, d.legbyes, d.penalty,
  d.wicket_count > 0 AND COALESCE(d.wicket_kind NOT IN ('retired hurt', 'retired not out'), FALSE) AS is_wicket,
  d.wicket_kind, d.player_out, d.player_out_id, d.fielders, d.is_bowler_wicket,
  d.wicket2_kind, d.player_out2, d.review_by, d.review_decision,
  d.target_runs, d.target_overs, d.declared
FROM cs.deliveries d
UNION ALL BY NAME
SELECT
  b.fixture_id AS match_id, 'espn' AS score_source,
  b.innings AS innings_no, FALSE AS is_super_over, b.batting_team, b.bowling_team,
  b.over_1b - 1 AS over_no, b.ball_no AS delivery_in_over,
  sum(CASE WHEN NOT b.is_wide AND NOT b.is_noball THEN 1 ELSE 0 END)
    OVER (PARTITION BY b.fixture_id, b.innings, b.over_1b ORDER BY b.seq) AS legal_ball_in_over,
  b.seq AS innings_delivery_seq, NOT b.is_wide AND NOT b.is_noball AS is_legal,
  b.batter, pr_bat.cs_id AS batter_id,
  NULL AS non_striker, NULL AS non_striker_id,
  b.bowler, pr_bowl.cs_id AS bowler_id,
  b.runs_bat AS runs_batter, b.extras AS runs_extras, b.runs_bat + b.extras AS runs_total, FALSE AS non_boundary,
  b.wide_runs AS wides, b.noball_runs AS noballs, b.bye_runs AS byes, b.legbye_runs AS legbyes, NULL::INTEGER AS penalty,
  b.is_wicket, lower(b.dismissal_type) AS wicket_kind,
  CASE WHEN b.is_wicket THEN COALESCE(
    (SELECT n.name FROM espn_names n WHERE n.cricinfo_id = b.player_out_src_id), b.batter) END AS player_out,
  CASE WHEN b.is_wicket THEN pr_out.cs_id END AS player_out_id,
  NULL AS fielders,
  b.is_wicket AND lower(b.dismissal_type) IN ('bowled', 'caught', 'caught and bowled', 'lbw', 'stumped', 'hit wicket') AS is_bowler_wicket,
  NULL AS wicket2_kind, NULL AS player_out2, NULL AS review_by, NULL AS review_decision,
  NULL::INTEGER AS target_runs, NULL::FLOAT AS target_overs, FALSE AS declared
FROM enrich.balls b
LEFT JOIN player_resolved pr_bat ON pr_bat.fam = 'espn' AND pr_bat.src_id IS NOT DISTINCT FROM b.batter_src_id AND pr_bat.nm IS NOT DISTINCT FROM b.batter
LEFT JOIN player_resolved pr_bowl ON pr_bowl.fam = 'espn' AND pr_bowl.src_id IS NOT DISTINCT FROM b.bowler_src_id AND pr_bowl.nm IS NOT DISTINCT FROM b.bowler
LEFT JOIN player_resolved pr_out ON b.is_wicket AND pr_out.fam = 'espn' AND pr_out.src_id IS NOT DISTINCT FROM b.player_out_src_id AND pr_out.nm IS NOT DISTINCT FROM NULL
WHERE b.src = 'espn' AND b.fixture_id IN (SELECT fixture_id FROM espn_only)
UNION ALL BY NAME
SELECT
  b.src || '-' || b.fixture_id AS match_id, b.src AS score_source,
  b.innings AS innings_no, FALSE AS is_super_over, b.batting_team, b.bowling_team,
  b.over_1b - 1 AS over_no,
  row_number() OVER (PARTITION BY b.src, b.fixture_id, b.innings, b.over_1b ORDER BY b.seq) AS delivery_in_over,
  sum(CASE WHEN NOT COALESCE(b.is_wide, FALSE) AND NOT COALESCE(b.is_noball, FALSE) THEN 1 ELSE 0 END)
    OVER (PARTITION BY b.src, b.fixture_id, b.innings, b.over_1b ORDER BY b.seq) AS legal_ball_in_over,
  b.seq AS innings_delivery_seq, NOT COALESCE(b.is_wide, FALSE) AND NOT COALESCE(b.is_noball, FALSE) AS is_legal,
  b.batter, pr_bat.cs_id AS batter_id,
  b.non_striker, pr_ns.cs_id AS non_striker_id,
  b.bowler, pr_bowl.cs_id AS bowler_id,
  b.runs_bat AS runs_batter, b.extras AS runs_extras, b.runs_bat + b.extras AS runs_total, FALSE AS non_boundary,
  NULLIF(b.wide_runs, 0) AS wides, NULLIF(b.noball_runs, 0) AS noballs, NULLIF(b.bye_runs, 0) AS byes,
  NULLIF(b.legbye_runs, 0) AS legbyes, NULL::INTEGER AS penalty,
  b.is_wicket AND COALESCE(lower(b.dismissal_type) NOT LIKE 'retired%', TRUE) AS is_wicket,
  lower(regexp_replace(b.dismissal_type, ' \\(sub\\)$', '')) AS wicket_kind,
  CASE WHEN b.is_wicket THEN COALESCE(b.dismissed, b.batter) END AS player_out,
  CASE WHEN b.is_wicket THEN pr_out.cs_id END AS player_out_id,
  NULL AS fielders,
  b.is_wicket AND lower(regexp_replace(b.dismissal_type, ' \\(sub\\)$', '')) IN
    ('bowled', 'caught', 'caught and bowled', 'lbw', 'stumped', 'hit wicket') AS is_bowler_wicket,
  NULL AS wicket2_kind, NULL AS player_out2, NULL AS review_by, NULL AS review_decision,
  NULL::INTEGER AS target_runs, NULL::FLOAT AS target_overs, FALSE AS declared
FROM enrich.balls b
LEFT JOIN player_resolved pr_bat ON pr_bat.fam = 'aucb' AND pr_bat.src_id IS NOT DISTINCT FROM b.batter_src_id AND pr_bat.nm IS NOT DISTINCT FROM b.batter
LEFT JOIN player_resolved pr_bowl ON pr_bowl.fam = 'aucb' AND pr_bowl.src_id IS NOT DISTINCT FROM b.bowler_src_id AND pr_bowl.nm IS NOT DISTINCT FROM b.bowler
LEFT JOIN player_resolved pr_out ON b.is_wicket AND pr_out.fam = 'aucb' AND pr_out.src_id IS NOT DISTINCT FROM NULL AND pr_out.nm IS NOT DISTINCT FROM COALESCE(b.dismissed, b.batter)
LEFT JOIN player_resolved pr_ns ON pr_ns.fam = 'aucb' AND pr_ns.src_id IS NULL AND pr_ns.nm IS NOT DISTINCT FROM b.non_striker
WHERE (b.src, b.fixture_id) IN (SELECT (src, fixture_id) FROM feed_only);

-- Quality of matches that only one non-Cricsheet source holds. An over with
-- more than 15 deliveries means duplicated or corrupt rows: the match is
-- excluded and listed. An innings a few legal balls over the format maximum
-- (unflagged wides in the source) is kept and noted.
CREATE OR REPLACE TEMP TABLE single_source_quality AS
WITH overs AS (
  SELECT match_id, innings_no, over_no, count(*) AS n FROM backbone WHERE score_source <> 'cricsheet' GROUP BY ALL
),
fmt AS (
  SELECT DISTINCT b.match_id,
         CASE WHEN b.score_source = 'espn' THEN 'ODI' ELSE f.src_format END AS src_format
  FROM backbone b
  LEFT JOIN (SELECT src || '-' || fixture_id AS match_id, any_value(src_format) AS src_format
             FROM enrich.balls GROUP BY ALL) f USING (match_id)
  WHERE b.score_source <> 'cricsheet'
),
legal AS (
  SELECT b.match_id, b.innings_no, count(*) FILTER (b.is_legal) AS legal
  FROM backbone b WHERE b.score_source <> 'cricsheet' GROUP BY ALL
),
limits AS (
  SELECT l.match_id, max(l.legal - CASE f.src_format WHEN 'ODI' THEN 300 WHEN 'One Day Domestic' THEN 300
                                          WHEN 'Domestic The Hundred' THEN 100 WHEN 'T20 International' THEN 120
                                          WHEN 'T20 Domestic' THEN 120 END) AS excess
  FROM legal l JOIN fmt f USING (match_id) GROUP BY 1
)
SELECT f.match_id,
       (SELECT max(n) FROM overs o WHERE o.match_id = f.match_id) AS max_over_deliveries,
       l.excess,
       CASE WHEN (SELECT max(n) FROM overs o WHERE o.match_id = f.match_id) > 15
            THEN 'excluded: an over holds more than 15 deliveries (duplicated or corrupt source rows)'
            WHEN l.excess > 0
            THEN 'innings has ' || l.excess || ' legal ball(s) above the format maximum in the source (likely unflagged wides)'
       END AS quality_note
FROM fmt f LEFT JOIN limits l USING (match_id);

CREATE OR REPLACE TEMP TABLE excluded_matches AS
SELECT match_id, quality_note AS reason FROM single_source_quality WHERE quality_note LIKE 'excluded:%';
DELETE FROM backbone WHERE match_id IN (SELECT match_id FROM excluded_matches);

-- Which source row describes each backbone delivery.
CREATE OR REPLACE TEMP TABLE ll_link AS
SELECT a.match_id, a.innings_no, a.innings_delivery_seq, a.src, a.fixture_id, a.innings, a.seq, a.align_score
FROM enrich.ball_alignment a
UNION ALL
SELECT fixture_id, innings, seq, 'espn', fixture_id, innings, seq, NULL
FROM enrich.balls WHERE src = 'espn' AND fixture_id IN (SELECT fixture_id FROM espn_only)
UNION ALL
SELECT espn_fixture, espn_innings, espn_seq, src, fixture_id, innings, seq, align_score
FROM enrich.orphan_alignment
UNION ALL
SELECT b.src || '-' || b.fixture_id, b.innings, b.seq, b.src, b.fixture_id, b.innings, b.seq, NULL
FROM enrich.balls b WHERE (b.src, b.fixture_id) IN (SELECT (src, fixture_id) FROM feed_only);
"""

# --------------------------------------------------------------------------
# Published tables
# --------------------------------------------------------------------------
FINAL_SQL = """
-- Canonical line/length use the ESPNcricinfo vocabulary already used by the
-- CricAtlas ODI analytics; AUCB codes map onto it (stump-level detail kept).
CREATE OR REPLACE MACRO aucb_length(x) AS CASE x
  WHEN 'Yorker' THEN 'YORKER' WHEN 'FullToss' THEN 'FULL_TOSS' WHEN 'Beamer' THEN 'FULL_TOSS'
  WHEN 'HalfVolley' THEN 'FULL' WHEN 'LengthBall' THEN 'GOOD_LENGTH'
  WHEN 'BackOfALength' THEN 'SHORT_OF_A_GOOD_LENGTH' WHEN 'Short' THEN 'SHORT' WHEN 'HalfTracker' THEN 'SHORT' END;
CREATE OR REPLACE MACRO aucb_line(x) AS CASE x
  WHEN 'OutsideOff' THEN 'OUTSIDE_OFFSTUMP' WHEN 'Wide' THEN 'WIDE_OUTSIDE_OFFSTUMP'
  WHEN 'OffStump' THEN 'ON_THE_STUMPS' WHEN 'MiddleStump' THEN 'ON_THE_STUMPS' WHEN 'LegStump' THEN 'ON_THE_STUMPS'
  WHEN 'DownLeg' THEN 'DOWN_LEG' WHEN 'WideDownLeg' THEN 'WIDE_DOWN_LEG' END;
CREATE OR REPLACE MACRO shot_family(x) AS CASE
  WHEN x IN ('COVER_DRIVE','ON_DRIVE','STRAIGHT_DRIVE','SQUARE_DRIVE','OFF_SIDE_DRIVE_ON_FRONT_FOOT','OFF_SIDE_DRIVE_ON_BACK_FOOT',
             'ON_SIDE_DRIVE_ON_FRONT_FOOT','ON_SIDE_DRIVE_ON_BACK_FOOT','VERTICAL_FORWARD_ATTACK','Drive') THEN 'drive'
  WHEN x IN ('DEFENDED','FORWARD_DEFENCE','BACK_DEFENCE','ForwardDefensive','BackwardDefensive','Dropped','Fended') THEN 'defence'
  WHEN x IN ('PULL','HOOK','PULL_HOOK_ON_BACK_FOOT','PULL_HOOK_ON_FRONT_FOOT','Pull','Hook') THEN 'pull/hook'
  WHEN x IN ('CUT_SHOT','CUT_SHOT_ON_BACK_FOOT','CUT_SHOT_ON_FRONT_FOOT','LATE_CUT','UPPER_CUT','Cut','LateCut','UpperCut') THEN 'cut'
  WHEN x IN ('SWEEP','SWEEP_SHOT','SLOG_SWEEP','PADDLE_SWEEP','Sweep','SlogSweep') THEN 'sweep'
  WHEN x IN ('REVERSE_SWEEP','REVERSE_SCOOP','REVERSE_PULL','ReverseSweep','ReverseScoop','SwitchHit') THEN 'reverse/switch'
  WHEN x IN ('FLICK','LEG_GLANCE','Flick','Glance','Worked') THEN 'flick/glance/work'
  WHEN x IN ('PUSH','PUSH_SHOT','STEERED','DAB','Pushed','Steer') THEN 'push/steer/dab'
  WHEN x IN ('SLOG_SHOT','Slog') THEN 'slog'
  WHEN x IN ('RAMP','PADDLE_AWAY','Scoop') THEN 'scoop/ramp'
  WHEN x IN ('LEFT_ALONE','Leave','ShouldersArms') THEN 'leave'
  WHEN x IN ('NO_SHOT','PADDED_AWAY','NoShot','Padded') THEN 'no shot'
END;
-- AUCB has no in-control flag; its contact type maps onto ESPN's control
-- (measured on shared balls). Ambiguous contacts stay NULL.
CREATE OR REPLACE MACRO aucb_in_control(conn) AS CASE
  WHEN conn IS NULL OR conn IN ('WellTimed','Played','Middled','Left','HitHard','ShouldersArms','NoShot') THEN TRUE
  WHEN conn IN ('Missed','HitPad','InsideEdge','OutsideEdge','ThickEdge','TopEdge','BottomEdge','Edged','LeadingEdge',
                'Gloved','HitBody','Spliced','BatPad','HitHelmet') THEN FALSE
END;

-- Team and venue names of non-Cricsheet matches mapped to Cricsheet's
-- spelling, learnt from matches present in both.
CREATE OR REPLACE TEMP TABLE team_xref AS
SELECT src_team, arg_max(cs_team, n) AS cs_team FROM (
  SELECT b.batting_team AS src_team, d.batting_team AS cs_team, count(*) AS n
  FROM enrich.ball_alignment a JOIN enrich.balls b USING (src, fixture_id, innings, seq)
  JOIN cs.deliveries d USING (match_id, innings_no, innings_delivery_seq)
  GROUP BY ALL
) GROUP BY 1 HAVING max(n)::DOUBLE / sum(n) >= 0.9;
CREATE OR REPLACE TEMP TABLE venue_xref AS
SELECT src_venue, arg_max(venue, n) AS venue, arg_max(city, n) AS city FROM (
  SELECT b.ground AS src_venue, m.venue, m.city, count(DISTINCT a.match_id) AS n
  FROM enrich.ball_alignment a JOIN enrich.balls b USING (src, fixture_id, innings, seq)
  JOIN cs.matches m ON m.match_id = a.match_id
  WHERE b.ground IS NOT NULL GROUP BY ALL
) GROUP BY 1 HAVING max(n)::DOUBLE / sum(n) >= 0.6;

-- Same ground under another spelling, checked by hand against Cricsheet's
-- standardised names (Cricsheet holds none of these grounds' source names).
CREATE OR REPLACE TEMP TABLE venue_alias (src_venue VARCHAR, venue VARCHAR);
INSERT INTO venue_alias VALUES
  ('Sharjah Cricket Association Stadium', 'Sharjah Cricket Stadium'),
  ('Sylhet Stadium', 'Sylhet International Cricket Stadium'),
  ('Khulna Divisional Stadium', 'Sheikh Abu Naser Stadium, Khulna'),
  ('Sportpark Westvliet, Voorburg', 'Sportpark Westvliet, The Hague'),
  ('Magheramason', 'Bready Cricket Club, Magheramason');

-- Otherwise a source name maps to the one Cricsheet venue sharing its text
-- before the first comma ("Kensington Oval, Bridgetown, Barbados").
CREATE OR REPLACE MACRO venue_name(v) AS COALESCE(
  (SELECT x.venue FROM venue_xref x WHERE x.src_venue = v),
  (SELECT a.venue FROM venue_alias a WHERE a.src_venue = v),
  (SELECT any_value(m.venue) FROM (SELECT DISTINCT venue FROM cs.matches) m
    WHERE split_part(m.venue, ',', 1) = split_part(v, ',', 1)
    HAVING count(*) = 1),
  v
);

CREATE OR REPLACE MACRO team_name(t) AS COALESCE((SELECT cs_team FROM team_xref WHERE src_team = t), t);

CREATE OR REPLACE TEMP TABLE extra_matches AS
WITH f AS (
  SELECT src, fixture_id, min(match_date) AS start_date, max(match_date) AS end_date,
         any_value(src_competition) AS competition, any_value(src_format) AS src_format,
         any_value(batting_team) FILTER (innings = 1) AS team1, any_value(bowling_team) FILTER (innings = 1) AS team2,
         any_value(ground) AS ground, any_value(country) AS country,
         any_value(toss_winner) AS toss_winner, any_value(toss_decision) AS toss_decision,
         any_value(match_winner) AS match_winner, any_value(win_type) AS win_type, any_value(win_margin) AS win_margin
  FROM enrich.balls
  WHERE (src = 'espn' AND fixture_id IN (SELECT fixture_id FROM espn_only))
     OR (src, fixture_id) IN (SELECT (src, fixture_id) FROM feed_only)
  GROUP BY ALL
)
SELECT
  CASE WHEN src = 'espn' THEN fixture_id ELSE src || '-' || fixture_id END AS match_id,
  src AS score_source,
  CASE src_format WHEN 'ODI' THEN 'ODI' WHEN 'Test' THEN 'Test' WHEN 'T20 International' THEN 'T20I'
       WHEN 'T20 Domestic' THEN 'T20 domestic' WHEN 'Domestic The Hundred' THEN 'The Hundred'
       WHEN 'First Class Domestic' THEN 'First-class domestic' WHEN 'One Day Domestic' THEN 'List A domestic' END AS format,
  'male' AS gender,
  CASE WHEN src_format IN ('ODI', 'Test', 'T20 International') THEN 'international' ELSE 'club' END AS team_type,
  competition, CAST(year(start_date) AS VARCHAR) AS season, start_date, end_date,
  venue_name(f.ground) AS venue,
  COALESCE(v.city, (SELECT any_value(m.city) FROM cs.matches m WHERE m.venue = venue_name(f.ground)), f.country) AS city,
  team_name(regexp_replace(team1, ' Men$', '')) AS team1, team_name(regexp_replace(team2, ' Men$', '')) AS team2,
  team_name(regexp_replace(toss_winner, ' Men$', '')) AS toss_winner, lower(toss_decision) AS toss_decision,
  team_name(regexp_replace(match_winner, ' Men$', '')) AS winner,
  CASE WHEN lower(win_type) LIKE '%run%' THEN TRY_CAST(win_margin AS INTEGER) END AS win_by_runs,
  CASE WHEN lower(win_type) LIKE '%wicket%' THEN TRY_CAST(win_margin AS INTEGER) END AS win_by_wickets
FROM f LEFT JOIN venue_xref v ON v.src_venue = f.ground;

CREATE OR REPLACE TABLE out.analytics.matches AS
SELECT match_id, 'cricsheet' AS score_source, format, gender, team_type, competition, season, start_date, end_date,
       venue, city, team1, team2, toss_winner, toss_decision, winner, win_by_runs, win_by_wickets, win_by_innings,
       result, method, eliminator, balls_per_over, scheduled_overs, player_of_match, event_match_number, event_stage,
       match_type AS cricsheet_match_type
FROM cs.matches
UNION ALL BY NAME
SELECT e.*, CASE WHEN e.format = 'The Hundred' THEN 5 ELSE 6 END AS balls_per_over,
       concat_ws('; ',
         CASE WHEN e.score_source IN ('aucb', 'odata')
              THEN 'scored from the AUCB feed only (not in Cricsheet); AUCB innings totals match the official record on about 95% of innings where both exist'
         END,
         q.quality_note) AS quality_note
FROM extra_matches e LEFT JOIN single_source_quality q USING (match_id)
WHERE e.match_id NOT IN (SELECT match_id FROM excluded_matches);
UPDATE out.analytics.matches SET quality_note = NULL WHERE quality_note = '';

-- Grounds Cricsheet never covered can still arrive under two spellings from
-- ESPN and AUCB ("X" and "X, City"): keep the fuller name for both.
CREATE OR REPLACE TEMP TABLE extra_venue_unify AS
WITH v AS (
  SELECT DISTINCT venue FROM out.analytics.matches
  WHERE score_source <> 'cricsheet' AND venue IS NOT NULL
    AND venue NOT IN (SELECT venue FROM cs.matches WHERE venue IS NOT NULL)
)
SELECT a.venue AS old_venue, arg_max(b.venue, length(b.venue)) AS new_venue
FROM v a JOIN v b ON split_part(a.venue, ',', 1) = split_part(b.venue, ',', 1)
GROUP BY 1;
UPDATE out.analytics.matches m SET venue = u.new_venue
FROM extra_venue_unify u
WHERE m.venue = u.old_venue AND m.score_source <> 'cricsheet' AND u.new_venue <> u.old_venue;

CREATE OR REPLACE TABLE out.analytics.excluded_matches AS
SELECT x.match_id, x.reason, e.score_source, e.format, e.competition, e.start_date, e.team1, e.team2
FROM excluded_matches x LEFT JOIN extra_matches e USING (match_id);

-- Staged as temp tables: one big CTE join made DuckDB spill badly.
CREATE OR REPLACE TEMP TABLE espn_ll AS

  SELECT l.match_id, l.innings_no, l.innings_delivery_seq, b.length, b.line, b.shot, b.control_raw,
         b.wagon_x, b.wagon_y, b.wagon_zone
  FROM ll_link l JOIN enrich.balls b USING (src, fixture_id, innings, seq) WHERE l.src = 'espn';
CREATE OR REPLACE TEMP TABLE feed_ll AS
  SELECT l.match_id, l.innings_no, l.innings_delivery_seq, l.src AS feed_src, l.align_score,
         b.length, b.line, b.shot, b.footwork, b.connection, b.bowling_detail, b.bowling_from,
         b.shot_angle, b.shot_magnitude, b.fielding_position, b.air_controlled, b.air_not_controlled,
         b.filled_from_commentary, b.commentary
  FROM ll_link l JOIN enrich.balls b USING (src, fixture_id, innings, seq) WHERE l.src IN ('aucb', 'odata');
CREATE OR REPLACE TEMP TABLE d AS
  SELECT bb.*, m.format, m.gender, m.team_type, m.competition, m.season, m.start_date AS match_date,
         year(m.start_date) AS year, m.venue, m.city
  FROM backbone bb JOIN out.analytics.matches m USING (match_id);

CREATE OR REPLACE TABLE out.analytics.deliveries AS
SELECT
  d.*,
  pb.batting_hand AS batter_hand,
  pw.bowling_style_code AS bowler_style_code,
  pw.bowling_style_group AS bowler_style_group,
  pw.bowling_arm AS bowler_arm,
  CASE WHEN pw.bowling_style_group LIKE '%pace' THEN 'pace bowler'
       WHEN pw.bowling_style_group LIKE '%spin' OR pw.bowling_style_group LIKE '%orthodox' THEN 'spin bowler' END AS bowler_kind,
  -- canonical line/length: ESPNcricinfo where it has a value, else AUCB feed
  CASE WHEN e.length IS NOT NULL OR e.line IS NOT NULL THEN 'espn'
       WHEN f.length IS NOT NULL OR f.line IS NOT NULL THEN f.feed_src END AS ll_source,
  CASE WHEN e.length IS NOT NULL OR e.line IS NOT NULL THEN e.length ELSE aucb_length(f.length) END AS length,
  CASE WHEN e.length IS NOT NULL OR e.line IS NOT NULL THEN e.line ELSE aucb_line(f.line) END AS line,
  CASE WHEN e.shot IS NOT NULL THEN e.shot ELSE f.shot END AS shot,
  CASE WHEN e.shot IS NOT NULL THEN 'espn' WHEN f.shot IS NOT NULL THEN f.feed_src END AS shot_source,
  shot_family(CASE WHEN e.shot IS NOT NULL THEN e.shot ELSE f.shot END) AS shot_family,
  CASE WHEN e.control_raw IS NOT NULL THEN e.control_raw = 1
       WHEN f.feed_src = 'aucb' AND (f.shot IS NOT NULL OR f.connection IS NOT NULL) THEN aucb_in_control(f.connection) END AS in_control,
  f.footwork, f.connection, f.bowling_detail AS bowling_variation, f.bowling_from,
  f.length AS length_aucb, f.line AS line_aucb, f.shot AS shot_aucb,
  e.length AS length_espn, e.line AS line_espn, e.shot AS shot_espn,
  e.wagon_x, e.wagon_y, e.wagon_zone, f.shot_angle, f.shot_magnitude, f.fielding_position,
  f.air_controlled, f.air_not_controlled,
  f.align_score AS feed_align_score, COALESCE(f.filled_from_commentary, FALSE) AS feed_filled_from_commentary,
  f.commentary
FROM d
LEFT JOIN espn_ll e USING (match_id, innings_no, innings_delivery_seq)
LEFT JOIN feed_ll f USING (match_id, innings_no, innings_delivery_seq)
LEFT JOIN out.analytics.players pb ON pb.player_id = d.batter_id
LEFT JOIN out.analytics.players pw ON pw.player_id = d.bowler_id;
"""
