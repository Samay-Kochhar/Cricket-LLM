"""Map AUCB fixtures onto Cricsheet matches.

Team names differ between the feeds ("India Men" vs "India", renamed
franchises), so a fixture is matched by date plus the overlap of player
surnames: the share of the fixture's batters and bowlers whose surname appears
in the Cricsheet playing XIs. A fixture is mapped only when the best candidate
is clear (overlap >= 0.6 and either at least 0.25 ahead of the runner-up, or
the only candidate played on the fixture's own date, which separates the
same two teams meeting on consecutive days), and each
Cricsheet match takes at most one fixture.

ESPNcricinfo-style fixtures (src 'espn') need no name matching: Cricsheet's
match IDs are ESPNcricinfo match IDs, so they map on equal IDs.
"""

SURNAME_SQL = (
    "NULLIF(regexp_extract(lower(strip_accents({col})), '([a-z]+)[^a-z]*$', 1), '')"
)

MATCH_MAPPING_SQL = f"""
CREATE OR REPLACE TEMP TABLE src_surnames AS
SELECT DISTINCT src, fixture_id, s AS surname
FROM (
  SELECT src, fixture_id, {SURNAME_SQL.format(col='batter')} AS s FROM enrich.balls WHERE src <> 'espn'
  UNION ALL
  SELECT src, fixture_id, {SURNAME_SQL.format(col='bowler')} AS s FROM enrich.balls WHERE src <> 'espn'
)
WHERE s IS NOT NULL;

CREATE OR REPLACE TEMP TABLE src_fixtures AS
SELECT src, fixture_id, any_value(src_format) AS src_format, min(match_date) AS match_date,
       any_value(src_competition) AS src_competition
FROM enrich.balls WHERE src <> 'espn' GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE cs_surnames AS
SELECT DISTINCT p.match_id, {SURNAME_SQL.format(col='p.player_name')} AS surname
FROM cs.players p JOIN cs.matches m USING (match_id)
WHERE m.gender = 'male';

CREATE OR REPLACE TEMP TABLE map_candidates AS
WITH cand AS (
  SELECT f.src, f.fixture_id, m.match_id,
         CASE WHEN f.match_date BETWEEN m.start_date AND m.end_date THEN 0 ELSE 1 END AS date_dist
  FROM src_fixtures f
  JOIN cs.matches m
    ON m.gender = 'male'
   AND f.match_date BETWEEN m.start_date - INTERVAL 1 DAY AND m.end_date + INTERVAL 1 DAY
   AND (
        (f.src_format IN ('Test', 'First Class Domestic') AND m.match_type IN ('Test', 'MDM'))
     OR (f.src_format IN ('ODI', 'One Day Domestic') AND m.match_type IN ('ODI', 'ODM'))
     OR (f.src_format IN ('T20 International', 'T20 Domestic', 'Domestic The Hundred') AND m.match_type IN ('T20', 'IT20'))
   )
),
sizes AS (SELECT src, fixture_id, count(*) AS n_src FROM src_surnames GROUP BY ALL)
SELECT c.src, c.fixture_id, c.match_id, any_value(c.date_dist) AS date_dist,
       count(cs.surname)::DOUBLE / any_value(sz.n_src) AS overlap
FROM cand c
JOIN sizes sz USING (src, fixture_id)
JOIN src_surnames s USING (src, fixture_id)
LEFT JOIN cs_surnames cs ON cs.match_id = c.match_id AND cs.surname = s.surname
GROUP BY ALL
UNION ALL
SELECT DISTINCT 'espn', b.fixture_id, b.fixture_id, 0, 1.0
FROM enrich.balls b JOIN cs.matches m ON m.match_id = b.fixture_id
WHERE b.src = 'espn';

CREATE OR REPLACE TABLE enrich.match_map AS
WITH ranked AS (
  SELECT *,
         row_number() OVER w AS rk,
         lead(overlap) OVER w AS runner_up,
         lead(date_dist) OVER w AS runner_up_date_dist
  FROM map_candidates
  WINDOW w AS (PARTITION BY src, fixture_id ORDER BY overlap DESC, date_dist, match_id)
),
best AS (
  SELECT src, fixture_id, match_id, overlap, COALESCE(runner_up, 0) AS runner_up, date_dist
  FROM ranked
  WHERE rk = 1 AND overlap >= 0.6
    AND (overlap - COALESCE(runner_up, 0) >= 0.25 OR runner_up_date_dist > date_dist)
)
SELECT * FROM best
QUALIFY row_number() OVER (PARTITION BY match_id ORDER BY overlap DESC, src, fixture_id) = 1;
"""
