# Multi-format data: sources, decisions and evidence

CricAtlas expands from ODI-only to every format with one database,
`data/cricket_all.duckdb`, built by:

```bash
conda activate odi-analyst-workbench
python -m ingestion.app.multiformat.build            # every step, ~5 minutes
python -m ingestion.app.multiformat.build --steps publish validate
```

Generated companions: [data-coverage.md](data-coverage.md) (what exists, and the
limitation statements to give users) and [data-validation.md](data-validation.md)
(every check from the last build).

## Inputs

All inputs live in `data/sources/` (git-ignored).

| Source | File | What it brings | Formats and dates |
|---|---|---|---|
| Cricsheet | `cricsheet/all_json.zip`, `people.csv`, `names.csv` from cricsheet.org | Scores, wickets, results, player register with ESPNcricinfo IDs | Every format, men's and women's, internationals and leagues (IPL, BBL, CPL, PSL, SA20, The Hundred, Blast, county, Shield and more), 2001 onwards |
| AUCB feed, new export | `aucb_bbb.csv` | Line, length, shot, footwork, bat contact, bowling variation, over/round the wicket, wagon angle | Men's Test, ODI, T20I, T20 leagues, The Hundred, 2019 to Nov 2026 |
| AUCB feed, old export | `odata_full.csv` | Same feed, plus batter handedness; fixtures the new export lacks (county, Shield, One-Day Cup, older leagues) | Men's, 2012 to Jan 2025 |
| TigZig (cross-check only) | `tigzig/cricket_all_tables.duckdb` | Independent copy of Cricsheet internationals + IPL | Used only to verify the Cricsheet parse |
| ESPNcricinfo-style ODI data | `data/odi_analytics.duckdb` (existing CricAtlas data) | Line, length, shot, control, wagon wheel, bowling style, batting hand | Men's ODIs 2005 to Feb 2025, line/length from 2014 |

TigZig (tigzig.com/apis/database) republishes Cricsheet: internationals plus
the IPL, without the other leagues, refreshed twice daily. Cricsheet is
therefore read directly so that BBL, CPL, The Hundred and the rest are included,
and TigZig's database (`data/sources/tigzig/cricket_all_tables.duckdb`, from
`https://api.tigzig.com/cricket/v1/download/cricket_all_tables.duckdb.zip`)
serves as an independent cross-check. Every innings it shares with CricAtlas
(24,062 innings) has identical runs and ball counts, and all 11,252 of its
matches are present. The validation step repeats this whenever the file is
there. The venue-name cleanup credited to TigZig was Cricsheet's own
(Nov 2026); TigZig only picked it up.

Cricsheet withholds matches involving Afghanistan. Those ODIs come from the
ESPNcricinfo-style data or the AUCB feed instead.

## Which source is trusted for what

### Scores and results: Cricsheet

- On the 157 ODI first innings where Cricsheet and the ESPNcricinfo-style data
  disagree, Cricsheet's total equals the official target minus one in 143
  cases; ESPN's does in 0.
- Over the whole build, Cricsheet's first-innings total + 1 equals the
  recorded target in 99.7% of 15,747 limited-overs matches (no DLS).
- AUCB innings totals match Cricsheet exactly on about 95% of innings and are
  almost always lower when they differ. AUCB is therefore never used for a
  score when Cricsheet has the match.

Matches that Cricsheet lacks are scored from ESPN (355 ODIs, mostly
Afghanistan) or the AUCB feed (about 210 matches). Each match records its
`score_source`, and AUCB-only matches carry a `quality_note`.

### Line and length: ESPNcricinfo where present, else AUCB

The two are independent taggings of the same deliveries. On 239k shared ODI
balls their length labels agree about 60% of the time, mostly differing by one
band, and their line labels about 62%. Neither is ground truth, so they were
tested against signals neither tagger controls:

| Check | AUCB | ESPN |
|---|---|---|
| Other source says pull/hook: called short or back of a length | 86% | 90% |
| Other source says cut: called short-ish | 48% | 67% |
| Other source says drive: called full | 24% | 43% |
| Umpire-called wides tagged wide or down leg | 49% | 59% |
| Legal balls wrongly tagged wide | 1.1% | 4.0% |
| LBWs tagged down leg or wide (should be ~0) | 0.5% | 0.3% |

On length, ESPN is clearly more consistent. AUCB files 62% of balls under one
broad "length ball" band, while ESPN separates good length from full. On line,
the two are mixed. So each delivery takes ESPN's line and length where ESPN has
them (ODIs, 2014 to Feb 2025) and AUCB's otherwise, and `ll_source` names which
source was used. Both raw sets stay on every delivery (`length_espn`,
`line_espn`, `shot_espn`, `length_aucb`, `line_aucb`, `shot_aucb`), so an
analysis can stay within one tagger.

**Caveat:** ODI line/length mixes ESPN (to Feb 2025) and AUCB (after, and in
gaps). The two taggers draw the good-length/full boundary differently. When
comparing periods or formats like for like, filter on `ll_source`.

The canonical vocabulary is the one the CricAtlas ODI analytics already uses
(`GOOD_LENGTH`, `OUTSIDE_OFFSTUMP`, ...). AUCB codes map onto it, and AUCB's
stump-level line (off, middle, leg) stays in `line_aucb`.

### In control

ESPN `control` is used where present. AUCB has no equivalent flag, because its
`control` column marks well-timed contact. An in-control flag is built from
AUCB's contact type, checked against ESPN on shared balls:

- **Clean contact** (well timed, middled, played, left): ESPN says in control 96–98% of the time.
- **Misses, edges, pad hits:** 5–27%.
- **Ambiguous contact** (mis-timed, play and miss down leg, padded): ESPN is
  about 50/50, so these stay NULL.

### Player attributes

- **Batting hand and bowling style:** ESPN where the player appears in its data,
  linked through Cricsheet's register of ESPNcricinfo IDs.
- **Otherwise, batting hand:** odata's batsman hand. It never contradicted
  ESPN on shared balls.
- **Otherwise, bowling type:** AUCB's bowling type.
- **Bowling arm:** AUCB's hand field is inverted on every fixture up to
  26 Feb 2023 and correct on every fixture from 28 Feb 2023. Measured against
  ESPN bowling styles, all 1,927 earlier fixtures were inverted and all 2,154
  later ones were correct, with no exceptions. (An early check reporting
  inverted fixtures into 2024 wrongly treated ESPN's "LB" (leg break) as
  left-arm.) Orientation is still decided per fixture from bowlers whose arm
  ESPN knows, with the date as the fallback. The validation step re-checks
  this on every build. odata's hand field contradicts both and is not used.

### Competition names

Sources rename the same league with each sponsor, and the AUCB and ESPN feeds
add the year. `matches.competition` holds one name per competition, and
`matches.event_name` keeps the source's own name. Examples:

- **T20 Blast:** NatWest T20 Blast, Vitality Blast and Vitality Blast Men.
- **County Championship:** the LV= and Specsavers eras.
- **One-Day Cup (England):** Royal London One-Day Cup and One-Day Cup.
- **One-Day Cup (Australia):** the Marsh names.
- **CSA T20 Challenge:** MiWAY and Ram Slam.
- **Super Smash:** HRV Cup.
- **ICC Men's T20 World Cup:** ICC World Twenty20.
- **ICC Cricket World Cup:** ICC World Cup, and "World Cup 2023" from ESPN.

A year or " - Men" suffix is dropped only when what remains is a known
competition, so bilateral series and one-off tours keep their year. The
validation step fails if a league name is still split by a sponsor or a year.

## How the AUCB balls were matched to Cricsheet deliveries

1. **Normalize.** The two AUCB exports merge into one table, keeping the new
   export wherever both have a fixture. The following are corrected:
   - `scoreValue` is runs off the bat; total = `scoreValue + extras`.
   - `'Null'` and `'0'` placeholders are blanked.
   - About 78k blank batter/bowler names are recovered from the old export on
     the same ball.
   - Umpire-decision text stored as a player name is removed.
   - The 1,389 dateless placeholder fixtures are dropped.
2. **Commentary fill.** About 20k rows had blank structured fields but intact
   commentary. Names, runs, length, line and footwork are parsed from the text.
   When the parser gives a value, it disagrees with the structured field on
   0.00% of runs, 0.07% of lengths, 0.08% of lines and 0.24% of footwork
   (measured on 165k rows that have both). Such rows are flagged
   `feed_filled_from_commentary`.
3. **Candidate matches.** For each fixture, find Cricsheet matches of the same
   format family within a day whose playing XIs contain at least 60% of the
   fixture's player surnames. Team names are not used: they differ between
   feeds. AUCB dates West Indies and USA evening games one day late (UTC).
4. **Ball alignment.** Each over is aligned with a small sequence alignment
   scoring bowler, batter, runs, extras, wide/no-ball and wicket. A bowler
   mismatch is never accepted. The over-number offset is chosen per innings,
   because old odata fixtures count overs from 0.
5. **Choose and accept.** The candidate with the highest precision (share of
   the fixture's balls aligned) wins. It is accepted at 80% or more, and only
   when at least 0.2 ahead of the runner-up. This picked the correct game in
   every back-to-back series fixture that date matching alone got wrong.

Results are in [data-validation.md](data-validation.md). In summary:

- **Matches attached:** all 7,378 source matches.
- **Precision:** median 100%, 1st percentile 98%.
- **Same runs off the bat:** 99.99% of attached balls.
- **Same bowler surname** (read from commentary): 99%. The remainder are
  spelling variants.

## Exclusions and notes

- **Excluded:** 5 ESPN-only ODIs whose source rows are corrupt (an over with
  up to 210 deliveries). They are listed in `analytics.excluded_matches`.
- **Noted, not excluded:** matches whose source innings have a few more legal
  balls than the format allows (likely unflagged wides). They carry a
  `quality_note`.
- **Dropped:** odata fragments of 1–2 balls.

## Database layout (`analytics` schema)

| Table / view | Contents |
|---|---|
| `deliveries` | One row per delivery, every format and gender. Includes match context, Cricsheet player IDs, batter hand, bowler style, canonical and raw line/length/shot, `ll_source`, `score_source` |
| `matches` | One row per match, with `score_source` and `quality_note` |
| `players` | Cricsheet register plus ESPNcricinfo ID, batting hand, bowling style code/group/arm and their sources |
| `coverage`, `coverage_by_year`, `coverage_summary` | What exists per competition, year and format |
| `data_limitations` | User-facing statements of what is and is not available per format |
| `validation_checks` | The last build's checks |
| `excluded_matches`, `source_fixture_map` | Audit trail |
| `deliveries_test_men`, `deliveries_odi_men`, `deliveries_t20i_men`, `deliveries_ipl`, `deliveries_t20_leagues_men`, women's equivalents, `deliveries_with_line_length` | Convenience views |

Conventions: `over_no` starts at 0; `legal_ball_in_over` counts legal balls
including this one. `is_wicket` excludes retired hurt and retired not out.
`is_bowler_wicket` excludes run outs, retirements and obstruction.

## Access: `/api/v2/data`

The backend serves the multi-format database read-only, next to the unchanged
ODI chat endpoints (`backend/app/api/routes/multiformat.py`; path from
`MULTIFORMAT_DUCKDB_PATH`, default `data/cricket_all.duckdb`):

| Endpoint | Returns |
|---|---|
| `GET /api/v2/data/coverage` | Formats, date ranges, line/length availability and every limitation statement |
| `GET /api/v2/data/competitions?format=&gender=` | Per-competition coverage |
| `GET /api/v2/data/players/search?q=` | Players with Cricsheet IDs, hand and style |
| `GET /api/v2/data/players/{id}/stats?role=batting\|bowling&format=&gender=&competition=&year_from=&year_to=` | Career numbers per format |
| `GET /api/v2/data/players/{id}/line-length?role=&dimension=length\|line&...` | Breakdown by length or line, the share of deliveries it rests on, and the limitation statements for the formats involved |

Every line/length response states its coverage, e.g. "Length is recorded for
3,242 of 7,127 deliveries (45.5%): T20 domestic 45.5% (Mar 2019 to May 2026).
Figures describe only those deliveries." When nothing is recorded, it returns
the format's limitation statement instead, e.g. "Line and length are not
recorded for women's T20I in any source."

### In the chat

`/api/chat` answers questions that name a non-ODI format or competition (IPL,
WPL, BBL, WBBL, CPL, PSL, SA20, ILT20, MLC, T20 Blast, The Hundred, T20I,
T20, Test, first-class) from this database (`backend/app/multiformat/chat.py`).
It handles:

- **Player numbers:** "MS Dhoni IPL 2023 runs".
- **Line/length breakdowns:** "How does Kohli bat against short balls in the IPL?"
- **Rankings** (rates need 60 balls, per CONTEXT.md): "best strike rate in the IPL".
- **Coverage questions:** "What line and length data do you have for women's T20Is?"

Every line/length answer ends with its data limit, and the format's
limitation statement when coverage is partial or absent. A question with no
such scope, or one that says ODI, takes the unchanged ODI path. The
`unsupported-test-cricket` and `unsupported-ipl` answer keys in
`tests/evals/dl4nlp_cricket_analyst_realistic_100.yaml` (and its generator)
now expect answers. The `/api/query`, workbench and explorer endpoints remain
ODI.
