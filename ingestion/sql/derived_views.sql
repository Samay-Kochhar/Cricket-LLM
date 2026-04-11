CREATE OR REPLACE VIEW analytics.player_year_batting AS
SELECT
  bat AS player_name,
  TRY_CAST(year AS INTEGER) AS year,
  COUNT(*) AS balls_faced,
  SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
  SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 4 THEN 1 ELSE 0 END) AS fours,
  SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 6 THEN 1 ELSE 0 END) AS sixes,
  AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
FROM analytics.deliveries_v1
GROUP BY 1, 2;

CREATE OR REPLACE VIEW analytics.player_year_bowling AS
SELECT
  bowl AS player_name,
  TRY_CAST(year AS INTEGER) AS year,
  COUNT(*) AS deliveries,
  SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
  SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS wickets_on_ball
FROM analytics.deliveries_v1
GROUP BY 1, 2;

CREATE OR REPLACE VIEW analytics.player_lookup AS
SELECT DISTINCT
  bat AS player_name,
  regexp_replace(lower(bat), '[^a-z0-9]+', '', 'g') AS normalized_name,
  'batter' AS player_role
FROM analytics.deliveries_v1
UNION
SELECT DISTINCT
  bowl AS player_name,
  regexp_replace(lower(bowl), '[^a-z0-9]+', '', 'g') AS normalized_name,
  'bowler' AS player_role
FROM analytics.deliveries_v1;
