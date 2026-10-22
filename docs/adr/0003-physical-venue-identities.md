# Separate physical ODI ground identity from its display name

Issue: [#52](https://github.com/Samay-Kochhar/Cricket-LLM/issues/52). Decision date: 2026-10-21.

Use the checked-in `backend/app/domain/data/odi_venues.json` registry as the shared
source for physical-ground IDs, current display names, historical dataset aliases,
explicit search nicknames, evidence URLs, verification dates and audit decisions.
IDs are permanent: changing a sponsor changes the display name and adds an alias;
it does not create a new identity. Never regenerate or renumber existing IDs.
When research proves two previously separate records are one ground, retain one
ID and list the other under `legacy_ids`. Resolution of every retired ID must
redirect to the surviving identity, including old profile links and saved filters.

Raw CSV and DuckDB `ground` values remain unchanged. Existing URLs, old singular
`venue` filters and plural `venues` conversation-state filters continue to work.
Execution expands an identity to a deduplicated parameterized `IN` predicate.
This filters the original delivery relation once, without an alias join or
`UNION ALL`. Grouped venue statistics group by stable ID and project the current
name for display. Distinct matches are calculated on the combined deliveries,
never by summing per-name match counts. Match-fact metadata checks also compare
physical identities, while preserving the raw source metadata.

Repository venue options are deduplicated by this mapping. FastAPI profiles,
Streamlit Venue Explorer and Matchup selectors, comparison/chat filters, semantic
query builders and legacy repository analytics share the same registry. No new
selector styling, layouts, controls or leaderboard features are introduced.

A shared city, similar name, or shared complex is insufficient evidence to merge.
Uncertain records retain explicitly separate IDs and their original display labels;
the registry marks them `distinct_unverified`. This status does **not** assert that
their sponsorship is current. Previously unseen raw values receive deterministic,
separate fallback IDs; the audit command fails until they receive an explicit
registry decision. Runtime remains usable without silently assigning them to an
existing ground.

Record `verification_scope` independently of the resolution decision. An
`official_current_listing` is supported by a board, operator or government naming
record; `statistical_archive_name` verifies the historical/catalogued name only.
`unresolved_current_name` retains the raw label without certifying current naming.
`researched_on` and exact `research_queries` track unsuccessful research without
giving an unverified label a misleading `verified_on` date. A named complex with
multiple ovals (notably ICC Academy) still needs match-to-oval evidence; separate
provisional IDs are a compatibility precaution, not a finding of distinct sites.

To maintain the registry, verify identity and current presentation against the
operator, national board, ICC or official statistical archive. Record source URLs
and the actual verification date. Retain all old names; do not promote short search
nicknames to physical dataset aliases. For reused sponsor names, establish the
specific historical site before mapping (e.g. Lancaster Park versus the later
AMI-branded Rugby League Park). Run `python -m scripts.audit_odi_venues` after data
or mapping changes and review the inventory and union proof artifacts.
Run the identity and chat follow-up regressions when changing display names too:
new words in an official name can expose false matches in contextual language
(for example, `of` in University of Otago versus “regardless of the result”).

## Clarification after remaining-venue research, 2026-10-22

Do not conflate physical identity, name provenance, and operating status. An old
venue does not become an unidentified site just because no current sponsor
announcement exists. Establish the exact historic cricket ground first, then use
the best independently attested name. A closed venue retains its historical name
and a separate lifecycle field; its statistics never move to its successor ground.

Prefer board/operator/government naming evidence. Where direct pages are missing,
`corroborated_current_listing` records an archive identity supported by independent
contemporary reporting or fixtures; it is explicitly **not** an official current
sponsorship certificate. `verified_historical_name` records an established former
venue, with closure/retirement evidence and no invented active name.
`identity_status=resolved` describes only the physical-site decision. Retain the
source URLs, review date and limitations for each naming decision. Genuine
unallocated multi-oval records remain provisional until exact match evidence is
found. A canonical label based on corroboration does not silently satisfy a
stricter requirement for an official current listing.
