# Issue #52: ODI venue identity audit

Researched **2026-10-21 through 2026-10-22**. The final 15 records now have
explicit, source-backed physical-ground and display-name decisions. The earlier
9-unresolved/6-archive-only count conflated identity with sponsorship certification.

- **194 raw values → 166 identities**; no identity merges in this last round.
- **1,364,851 deliveries → 1,364,851** with distinct-match unions checked.
- **162 official naming listings**, **3 corroborated naming decisions**, and
  **1 verified former venue name (Kinrara)**. No unresolved physical-site assignments
  remain in the observed inventory, including Mulpani's exact upper oval.
- Criterion 2 now has one evidenced display name per ground: current attested
  names where available, and the established last-used cricket name for the former
  Kinrara venue. The issue did not require an official current sponsorship
  certificate for every entry. Three names rely on corroborated evidence rather
  than a modern operator naming declaration; that provenance remains explicit.

See [all 15 decisions](issue-52-final-venue-decisions.md), the
[machine-readable receipts](issue-52-venue-resolution-2026-10-22.json), and the
[African source report](issue-52-african-venue-evidence.md).

The [complete raw inventory](issue-52-venue-inventory.csv) contains permanent IDs,
display labels, row and distinct-match counts, verification scope, dates, sources,
notes and retired IDs. The [union proof](issue-52-venue-count-proof.json) records
all 166 groups. The [research ledger](issue-52-venue-research.json) records naming
findings, source URLs, exact unsuccessful searches, limitations and the resolved
Mulpani match and per-match ICC Academy receipts. Verification dates are actual review
dates, distinct from publication dates. Reproduce count artifacts with:

```sh
python -m scripts.audit_odi_venues
```

The audit independently groups the raw CSV and delivery view by venue and rejects
any delivery-count or distinct-match-count discrepancy, even if names agree.

The audit uses DuckDB `null_padding=true` for the CSV's short trailing tracking
columns. It does not skip rows or modify the source CSV or database.

## Identity corrections and compatibility

The eleven issue-listed groups remain covered: Motera/Narendra Modi;
Kotla/Arun Jaitley; Beausejour/Sammy; Mangaung/Chevrolet/Goodyear/OUTsurance;
Chinnaswamy Bangalore/Bengaluru; St George's Port Elizabeth/Gqeberha;
Chittagong Divisional/Zahur Ahmed Chowdhury across city spellings; Sharjah;
Zayed; Rose Bowl/Utilita Bowl; and Wellington regional stadium names.

This completion round consolidates the following five groups, plus the Academy
group documented below:

- **Castle Avenue / Clontarf Cricket Club Ground**: [Cricket Ireland explicitly
  identifies the same venue](https://cricketireland.ie/international/venues-and-facilities/international-grounds/clontarf/).
- **Westvliet, The Hague / Voorburg**: KNCB's current club address places Voorburg
  CC at Westvliet, Groene Zoom 20, Den Haag; its 2012 almanac identifies the 2010
  World Cricket League site as Westvliet, Voorburg. Duivesteijn is not merged.
- **Maple Leaf North-West, Toronto / King City**: [ICC locates the precise North-West
  facility in King City just outside Toronto](https://www.icc-cricket.com/news/road-to-2023-cricket-world-cup-continues-in-canada).
  Other Maple Leaf ovals and Toronto Cricket Club remain separate.
- **Narayanganj Osmani / Khan Shaheb Osman Ali, Fatullah**: [Cricket Ireland's ground
  history](https://www.cricketarchive.com/CricketIreland/Grounds/237.html) explicitly
  dates these names to the same main cricket stadium. The National Sports Council
  currently lists **Shaheed Ria Gope Stadium, Fatullah**. Neither the outer cricket
  ground nor the separate Osmani football stadium is merged.
- **Khulna Divisional / Sheikh Abu Naser**: the explicit statistical ground history,
  BCB's activities report and current government project records support
  **Khulna Divisional Stadium**. Khulna District Stadium is a different site.

Surviving IDs retain `legacy_ids` for every retired ID: `odi-ground-038`, `096`,
`069`, `106`, `151` and `162` (each with the `odi-ground-` prefix). Old names and IDs
continue to resolve and expand to one deduplicated alias predicate. Names are never
used as aggregation keys. All saved raw names remain aliases, including names
introduced during this research round before stronger current evidence appeared.

Newer labels include Ninja Stadium (Bellerive), Marvel Stadium (Docklands), Optus
Stadium (Perth), Imran Khan Stadium (Peshawar), Niranjan Shah Stadium (Rajkot),
Banks Homes Riverside, Seat Unique Stadium (Bristol), Ambassador Cruise Line Ground
(Chelmsford), The Kia Oval, Emirates Old Trafford, Cello Basin Reserve,
Sir John Davies Oval, University of Otago Oval, Schiebroekse Park (Hazelaarweg),
and Tin Kwong Road Recreation Ground (Mission Road). Each has explicit provenance
in the registry. Current names absent from raw data remain filterable aliases.

## Final identity and naming decisions

Criterion 1's observed inventory now has resolved physical-ground assignments.
The only raw Mulpani ODI is match **1368000**, **29 April 2023**, **Oman–UAE**.
The previous-day preview explicitly places that semifinal at **Upper Mulpani**,
quoting CAN's acting secretary. CAN’s current directory uses **Mulpani International Cricket Ground**. The proposed
Jayakumar Shah rename was suspended in July 2023; it is recorded as a suspended
proposal rather than promoted into an actual ground alias. Upper Mulpani and the
raw Mulpani name remain aliases. Lower Mulpani remains separate.

Criterion 2 has an evidenced canonical presentation for every record. Source
quality and lifecycle remain explicit, independently of physical identity. The three corroborated decisions are Reliance/IPCL Vadodara, Jaffery Nairobi,
and Mombasa Sports Club. Rajkot is supported by its municipal budgets; Greater
Noida by a GNIDA government tender; Mulpani by CAN’s current ground directory. Kinrara keeps its verified historical cricket name and
`former_cricket_venue` lifecycle after the documented 2022 departure. All other
records have official source listings. These are explicit provenance distinctions,
not remaining unknown-ground or duplicate-statistics problems.

Criteria 3–7 retain shared filters and aggregation for all registered aliases,
including the eleven issue-listed groups. Old IDs, raw names, old profile links and
conversation-state filters continue to resolve; no source deliveries are rewritten.
No new physical-ground merge was needed for these final 15 decisions.

The Mulpani check also exposed a proposed rename that was later suspended; the
current board directory takes precedence over initial rename coverage.

The problem in the earlier rounds was an overly narrow search strategy (including
exact current-year searches) and an overly strict interpretation of verification:
absence of a sponsor announcement was treated as absence of ground identity.
Operator facilities pages, board fixture histories, original match previews,
current government directories and corroborated event reports close those gaps.
A replacement stadium in the same city is never automatically a renamed ground.
See the full per-record source chain and limitations in the linked decision report.

## Validation and integration

`issue-52-validation.json` separates earlier mixed-working-tree runs from the
isolated index export used for integration. Earlier runs are historical receipts,
not evidence that the scoped commit includes the unrelated ranking controls.
The isolated tree preserves the original 24-legal-ball venue API. Identity tests
use qualifying fixtures and independently count distinct matches across aliases.

The scoped change includes the shared registry, canonical selectors and filters,
grouped profiles, chat/match metadata integration, audit artifacts and regressions.
It excludes the pre-existing chat and venue ranking controls. No source CSV or
DuckDB file is committed or modified. No production UI change is included.
The inventory writer uses LF line endings so its output passes whitespace checks.

Isolated integration verification: the full suite produced **1,552 passes** and
two environment-only launcher failures because the export lacked
`frontend/node_modules`. After `npm ci` from its lockfile, all four launcher
tests passed; no test failures remain. The isolated frontend production build
(including TypeScript), Python compilation and whitespace checks passed. Audit
artifacts reproduced byte for byte. Exact commands and scope are in the receipt.
