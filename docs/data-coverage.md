# CricAtlas data coverage and limitations

Generated on 2026-11-10. The multi-format database (`data/cricket_all.duckdb`) holds 23,805 matches and 12,039,901 deliveries.

- Latest Cricsheet match: 03 Nov 2026
- Latest AUCB (line/length) match: 07 Nov 2026
- Latest ESPNcricinfo-style ODI: 12 Feb 2025

## What to tell users

Each statement below is also stored in `analytics.data_limitations` so the app can quote it.

- **T20 domestic (male)**: Ball-by-ball men's T20 domestic data covers 6,987 matches from 18 Apr 2008 to 03 Nov 2026. Length is available from 2019 to 18 Jul 2026, on 49.3% of deliveries in that period. Line is available from 2020 to 18 Jul 2026, on 33.4% of deliveries in that period.
- **T20I (male)**: Ball-by-ball men's T20I data covers 3,747 matches from 17 Feb 2005 to 01 Nov 2026. Length is available from 2019 to 01 Nov 2026, on 34.4% of deliveries in that period. Line is available from 2019 to 01 Nov 2026, on 29.7% of deliveries in that period.
- **ODI (male)**: Ball-by-ball men's ODI data covers 2,985 matches from 27 Jun 2002 to 07 Nov 2026. Length is available from 2014 to 07 Nov 2026, on 73.1% of deliveries in that period. Line is available from 2014 to 07 Nov 2026, on 73.1% of deliveries in that period.
- **First-class domestic (male)**: Ball-by-ball men's First-class domestic data covers 2,242 matches from 27 Oct 2012 to 31 Oct 2026. Length is available from 2020 to 06 Dec 2024, on 80.0% of deliveries in that period. Line exists only sparsely (Mar 2019 to Sep 2021); treat it as unavailable.
- **List A domestic (male)**: Ball-by-ball men's List A domestic data covers 1,282 matches from 26 Jul 2014 to 24 Oct 2026. Length is available from 2019 to 03 Dec 2024, on 63.2% of deliveries in that period. Line is not recorded for men's List A domestic in any source.
- **Test (male)**: Ball-by-ball men's Test data covers 914 matches from 19 Dec 2001 to 05 Nov 2026. Length is available from 2018 to 05 Nov 2026, on 91.1% of deliveries in that period. Line is available from 2018 to 05 Nov 2026, on 91.1% of deliveries in that period.
- **List A (other international) (male)**: Ball-by-ball men's List A (other international) data covers 476 matches from 28 May 2010 to 31 Oct 2026. Length exists for only one match day (27 Oct 2024); treat it as unavailable. Line exists for only one match day (27 Oct 2024); treat it as unavailable.
- **T20 (other international) (male)**: Ball-by-ball men's T20 (other international) data covers 240 matches from 04 Jun 2010 to 26 May 2024. Line and length are not recorded for men's T20 (other international) in any source.
- **The Hundred (male)**: Ball-by-ball men's The Hundred data covers 201 matches from 22 Jul 2021 to 16 Aug 2026. Length is available from 2021 to 16 Aug 2026, on 99.9% of deliveries in that period. Line is available from 2021 to 16 Aug 2026, on 99.9% of deliveries in that period.
- **Multi-day (other international) (male)**: Ball-by-ball men's Multi-day (other international) data covers 17 matches from 05 Dec 2006 to 29 Nov 2017. Line and length are not recorded for men's Multi-day (other international) in any source.
- **T20I (female)**: Ball-by-ball women's T20I data covers 2,200 matches from 18 Jun 2009 to 25 Oct 2026. Line and length are not recorded for women's T20I in any source.
- **T20 domestic (female)**: Ball-by-ball women's T20 domestic data covers 1,245 matches from 18 Dec 2015 to 02 Nov 2026. Line and length are not recorded for women's T20 domestic in any source.
- **ODI (female)**: Ball-by-ball women's ODI data covers 620 matches from 22 Jan 2007 to 28 Oct 2026. Line and length are not recorded for women's ODI in any source.
- **List A domestic (female)**: Ball-by-ball women's List A domestic data covers 327 matches from 29 Aug 2020 to 19 Sep 2026. Line and length are not recorded for women's List A domestic in any source.
- **The Hundred (female)**: Ball-by-ball women's The Hundred data covers 188 matches from 21 Jul 2021 to 16 Aug 2026. Line and length are not recorded for women's The Hundred in any source.
- **T20 (other international) (female)**: Ball-by-ball women's T20 (other international) data covers 80 matches from 23 Jul 2013 to 27 Nov 2017. Line and length are not recorded for women's T20 (other international) in any source.
- **List A (other international) (female)**: Ball-by-ball women's List A (other international) data covers 30 matches from 15 Jul 2016 to 27 Nov 2021. Line and length are not recorded for women's List A (other international) in any source.
- **Test (female)**: Ball-by-ball women's Test data covers 24 matches from 22 Feb 2003 to 10 Jul 2026. Line and length are not recorded for women's Test in any source.

Line and length come only from the AUCB feed (2012-2026, men's) and the ESPNcricinfo-style
ODI data (2014-2025). No source records them for women's cricket, for most associate
matches, or for games older than these ranges. Analyses that need line or length must say
so when a player's matches fall outside the covered period.

## Summary by format

| Format | Gender | Matches | Ball-by-ball from | Ball-by-ball to | Length from | Length to | Length % in period | Line from | Line to | Line % in period |
|---|---|---|---|---|---|---|---|---|---|---|
| T20 domestic | male | 6,987 | 2008-04-18 | 2026-11-03 | 2019 | 2026-07-18 | 49.3 | 2020 | 2026-07-18 | 33.4 |
| T20I | male | 3,747 | 2005-02-17 | 2026-11-01 | 2019 | 2026-11-01 | 34.4 | 2019 | 2026-11-01 | 29.7 |
| ODI | male | 2,985 | 2002-06-27 | 2026-11-07 | 2014 | 2026-11-07 | 73.1 | 2014 | 2026-11-07 | 73.1 |
| First-class domestic | male | 2,242 | 2012-10-27 | 2026-10-31 | 2020 | 2024-12-06 | 80.0 | - | - | - |
| List A domestic | male | 1,282 | 2014-07-26 | 2026-10-24 | 2019 | 2024-12-03 | 63.2 | - | - | - |
| Test | male | 914 | 2001-12-19 | 2026-11-05 | 2018 | 2026-11-05 | 91.1 | 2018 | 2026-11-05 | 91.1 |
| List A (other international) | male | 476 | 2010-05-28 | 2026-10-31 | - | - | - | - | - | - |
| T20 (other international) | male | 240 | 2010-06-04 | 2024-05-26 | - | - | - | - | - | - |
| The Hundred | male | 201 | 2021-07-22 | 2026-08-16 | 2021 | 2026-08-16 | 99.9 | 2021 | 2026-08-16 | 99.9 |
| Multi-day (other international) | male | 17 | 2006-12-05 | 2017-11-29 | - | - | - | - | - | - |
| T20I | female | 2,200 | 2009-06-18 | 2026-10-25 | - | - | - | - | - | - |
| T20 domestic | female | 1,245 | 2015-12-18 | 2026-11-02 | - | - | - | - | - | - |
| ODI | female | 620 | 2007-01-22 | 2026-10-28 | - | - | - | - | - | - |
| List A domestic | female | 327 | 2020-08-29 | 2026-09-19 | - | - | - | - | - | - |
| The Hundred | female | 188 | 2021-07-21 | 2026-08-16 | - | - | - | - | - | - |
| T20 (other international) | female | 80 | 2013-07-23 | 2017-11-27 | - | - | - | - | - | - |
| List A (other international) | female | 30 | 2016-07-15 | 2021-11-27 | - | - | - | - | - | - |
| Test | female | 24 | 2003-02-22 | 2026-07-10 | - | - | - | - | - | - |

## Men's line/length coverage by year

### Test

| Year | Matches | Length % | Line % |
|---|---|---|---|
| 2012 | 42 | 0.0 | 0.0 |
| 2013 | 44 | 0.0 | 0.0 |
| 2014 | 41 | 0.0 | 0.0 |
| 2015 | 43 | 0.0 | 0.0 |
| 2016 | 47 | 0.0 | 0.0 |
| 2017 | 47 | 0.0 | 0.0 |
| 2018 | 47 | 38.4 | 38.4 |
| 2019 | 39 | 99.3 | 99.3 |
| 2020 | 22 | 100.0 | 99.9 |
| 2021 | 44 | 100.0 | 100.0 |
| 2022 | 43 | 100.0 | 100.0 |
| 2023 | 34 | 100.0 | 100.0 |
| 2024 | 53 | 100.0 | 100.0 |
| 2025 | 42 | 100.0 | 100.0 |
| 2026 | 27 | 97.4 | 97.3 |

### ODI

| Year | Matches | Length % | Line % |
|---|---|---|---|
| 2012 | 90 | 0.0 | 0.0 |
| 2013 | 135 | 0.0 | 0.0 |
| 2014 | 121 | 54.5 | 54.5 |
| 2015 | 145 | 87.8 | 87.7 |
| 2016 | 99 | 77.8 | 77.8 |
| 2017 | 128 | 72.3 | 72.2 |
| 2018 | 128 | 70.8 | 70.7 |
| 2019 | 149 | 80.1 | 80.1 |
| 2020 | 44 | 79.1 | 79.1 |
| 2021 | 71 | 75.4 | 75.4 |
| 2022 | 161 | 61.0 | 61.0 |
| 2023 | 218 | 88.5 | 88.5 |
| 2024 | 103 | 76.9 | 76.9 |
| 2025 | 114 | 67.6 | 67.6 |
| 2026 | 122 | 53.5 | 53.4 |

### T20I

| Year | Matches | Length % | Line % |
|---|---|---|---|
| 2012 | 72 | 0.0 | 0.0 |
| 2013 | 42 | 0.0 | 0.0 |
| 2014 | 58 | 0.0 | 0.0 |
| 2015 | 45 | 0.0 | 0.0 |
| 2016 | 82 | 0.0 | 0.0 |
| 2017 | 53 | 0.0 | 0.0 |
| 2018 | 74 | 4.5 | 4.5 |
| 2019 | 216 | 51.0 | 27.0 |
| 2020 | 75 | 61.6 | 61.6 |
| 2021 | 297 | 43.9 | 43.9 |
| 2022 | 463 | 41.8 | 33.0 |
| 2023 | 353 | 25.4 | 20.1 |
| 2024 | 631 | 27.8 | 27.3 |
| 2025 | 546 | 35.0 | 29.5 |
| 2026 | 553 | 25.2 | 25.2 |

### T20 domestic

| Year | Matches | Length % | Line % |
|---|---|---|---|
| 2012 | 155 | 0.0 | 0.0 |
| 2013 | 181 | 0.0 | 0.0 |
| 2014 | 305 | 0.0 | 0.0 |
| 2015 | 304 | 0.0 | 0.0 |
| 2016 | 420 | 0.0 | 0.0 |
| 2017 | 364 | 0.0 | 0.0 |
| 2018 | 431 | 0.2 | 0.0 |
| 2019 | 727 | 30.9 | 15.5 |
| 2020 | 348 | 70.6 | 45.4 |
| 2021 | 594 | 47.6 | 27.6 |
| 2022 | 546 | 58.1 | 34.3 |
| 2023 | 560 | 52.9 | 29.3 |
| 2024 | 620 | 49.0 | 29.1 |
| 2025 | 635 | 51.3 | 30.2 |
| 2026 | 537 | 47.3 | 44.1 |

### First-class domestic

| Year | Matches | Length % | Line % |
|---|---|---|---|
| 2012 | 13 | 0.0 | 0.0 |
| 2013 | 20 | 0.0 | 0.0 |
| 2014 | 150 | 0.0 | 0.0 |
| 2015 | 165 | 0.0 | 0.0 |
| 2016 | 167 | 0.0 | 0.0 |
| 2017 | 144 | 0.0 | 0.0 |
| 2018 | 150 | 0.0 | 0.0 |
| 2019 | 161 | 7.1 | 0.0 |
| 2020 | 86 | 59.0 | 0.0 |
| 2021 | 171 | 78.2 | 0.0 |
| 2022 | 180 | 82.9 | 0.0 |
| 2023 | 181 | 85.8 | 0.0 |
| 2024 | 187 | 82.7 | 0.0 |
| 2025 | 265 | 0.0 | 0.0 |
| 2026 | 202 | 0.0 | 0.0 |

## Men's T20 leagues

| Competition | Format | Matches | First | Last | % deliveries with line/length | Line/length first | Line/length last |
|---|---|---|---|---|---|---|---|
| T20 Blast | T20 domestic | 1,570 | 2014-05-16 | 2026-07-18 | 60.9 | 2016-05-20 | 2026-07-18 |
| Indian Premier League | T20 domestic | 1,243 | 2008-04-18 | 2026-05-31 | 44.1 | 2015-04-22 | 2026-05-31 |
| Syed Mushtaq Ali Trophy | T20 domestic | 695 | 2016-01-02 | 2024-12-15 | 0.0 | - | - |
| Big Bash League | T20 domestic | 662 | 2011-12-16 | 2026-01-25 | 55.5 | 2012-12-23 | 2026-01-25 |
| Bangladesh Premier League | T20 domestic | 469 | 2012-02-11 | 2026-01-23 | 0.0 | - | - |
| Caribbean Premier League | T20 domestic | 445 | 2013-07-30 | 2026-09-20 | 51.4 | 2019-09-04 | 2025-09-21 |
| Pakistan Super League | T20 domestic | 357 | 2016-02-04 | 2026-05-03 | 0.0 | - | - |
| CSA T20 Challenge | T20 domestic | 314 | 2012-02-15 | 2024-10-27 | 0.0 | - | - |
| Super Smash | T20 domestic | 270 | 2013-01-20 | 2026-01-31 | 0.0 | - | - |
| The Hundred Men's Competition | The Hundred | 201 | 2021-07-22 | 2026-08-16 | 99.9 | 2021-07-22 | 2026-08-16 |
| Lanka Premier League | T20 domestic | 143 | 2020-11-26 | 2026-08-08 | 0.0 | - | - |
| International League T20 | T20 domestic | 134 | 2023-01-13 | 2026-01-04 | 0.0 | - | - |
| SA20 | T20 domestic | 130 | 2023-01-10 | 2026-01-25 | 0.0 | - | - |
| Major Clubs T20 Tournament | T20 domestic | 121 | 2024-05-12 | 2026-09-16 | 0.0 | - | - |
| Cricket Ireland Inter-Provincial Twenty20 Trophy | T20 domestic | 111 | 2016-05-27 | 2026-07-29 | 0.0 | - | - |
| Major League Cricket | T20 domestic | 109 | 2023-07-13 | 2026-07-18 | 79.6 | 2024-07-05 | 2026-07-18 |
| Nepal Premier League | T20 domestic | 76 | 2024-11-30 | 2026-11-03 | 0.0 | - | - |
| Mzansi Super League | T20 domestic | 56 | 2018-11-16 | 2019-12-16 | 0.0 | - | - |
| European T20 Premier League | T20 domestic | 31 | 2026-08-26 | 2026-09-20 | 0.0 | - | - |
