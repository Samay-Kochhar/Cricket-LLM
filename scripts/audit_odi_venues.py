"""Reproduce #52's full raw inventory and row/distinct-match union proof.

Run from the repository root: python -m scripts.audit_odi_venues
Only reads the local data; writes review artifacts under docs/.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb

from backend.app.domain.venues import REGISTRY, resolve_venue, venue_filter


def audit(db: Path, source: Path, destination: Path) -> dict:
    metadata = {v['id']: v for v in REGISTRY}
    with duckdb.connect(str(db), read_only=True) as conn:
        inventory = conn.execute('''SELECT ground, count(*), count(DISTINCT p_match)
            FROM analytics.deliveries_v1 GROUP BY ground ORDER BY ground''').fetchall()
        csv_inventory = conn.execute('''SELECT ground, count(*), count(DISTINCT p_match)
            FROM read_csv_auto(?, null_padding=true) GROUP BY ground ORDER BY ground''', [str(source)]).fetchall()
        csv_names = {r[0] for r in csv_inventory}
        db_names = {r[0] for r in inventory}
        if csv_names != db_names:
            raise ValueError(f'CSV/database venue mismatch: {csv_names ^ db_names}')
        if csv_inventory != inventory:
            raise ValueError('CSV/database per-venue delivery or distinct-match counts differ')
        unknown = [name for name in db_names if resolve_venue(name).id not in metadata]
        if unknown:
            raise ValueError(f'Inventory requires review: {unknown}')
        groups = {}
        for name, rows, matches in inventory:
            venue = resolve_venue(name)
            groups.setdefault(venue.id, []).append((name, rows, matches))
        proof = []
        output = []
        for venue_id, raw in sorted(groups.items()):
            venue = resolve_venue(venue_id)
            where, params = venue_filter([venue_id, *(name for name, _, _ in raw)])
            union_rows, union_matches = conn.execute(f'''SELECT count(*), count(DISTINCT p_match)
                FROM analytics.deliveries_v1 WHERE {where}''', params).fetchone()
            assert union_rows == sum(n for _, n, _ in raw)
            # An independent distinct union, not a sum of per-alias matches.
            expected_matches = conn.execute('''SELECT count(DISTINCT p_match)
                FROM analytics.deliveries_v1 WHERE ground IN (SELECT unnest(?))''', [[n for n, _, _ in raw]]).fetchone()[0]
            assert union_matches == expected_matches
            item = dict(venue_id=venue_id, display_name=venue.display_name,
                        legacy_ids=metadata[venue_id].get('legacy_ids', []),
                        raw_names=[name for name, _, _ in raw], deliveries=union_rows,
                        distinct_matches=union_matches, sum_raw_distinct_matches=sum(m for _, _, m in raw))
            proof.append(item)
            for name, rows, matches in raw:
                output.append(dict(raw_name=name, venue_id=venue_id, display_name=venue.display_name,
                    raw_deliveries=rows, raw_distinct_matches=matches,
                    combined_deliveries=union_rows, combined_distinct_matches=union_matches,
                    status=metadata[venue_id]['status'], verified_on=metadata[venue_id]['verified_on'],
                    verification_scope=metadata[venue_id].get('verification_scope', ''),
                    identity_status=metadata[venue_id].get('identity_status',
                        'resolved' if metadata[venue_id]['status'] == 'verified' else 'provisional'),
                    lifecycle=metadata[venue_id].get('lifecycle', 'not_assessed'),
                    researched_on=metadata[venue_id].get('researched_on', ''),
                    legacy_ids=' | '.join(metadata[venue_id].get('legacy_ids', [])),
                    sources=' | '.join(metadata[venue_id]['sources']), notes=metadata[venue_id]['notes']))
        summary = dict(observed_raw_names=len(inventory), physical_ground_ids=len(groups),
            total_deliveries=sum(n for _, n, _ in inventory),
            mapped_deliveries=sum(p['deliveries'] for p in proof),
            verified_identities=sum(metadata[v]['status'] == 'verified' for v in groups),
            verified_current_listings=sum(metadata[v].get('verification_scope') == 'official_current_listing' for v in groups),
            verified_archive_names=sum(metadata[v].get('verification_scope') == 'statistical_archive_name' for v in groups),
            corroborated_current_names=sum(metadata[v].get('verification_scope') == 'corroborated_current_listing' for v in groups),
            verified_historical_names=sum(metadata[v].get('verification_scope') == 'verified_historical_name' for v in groups),
            retained_separate_identities=sum(metadata[v]['status'] != 'verified' for v in groups),
            csv_inventory_matches_database=True,
            csv_delivery_and_match_counts_match_database=True, groups=proof)
        assert summary['total_deliveries'] == summary['mapped_deliveries']
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / 'issue-52-venue-inventory.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(output, key=lambda r: r['raw_name']))
    (destination / 'issue-52-venue-count-proof.json').write_text(json.dumps(summary, indent=2)+'\n')
    return {key: value for key, value in summary.items() if key != 'groups'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path('data/odi_analytics.duckdb'))
    parser.add_argument('--csv', type=Path, default=Path('data/odi_bbb-25.csv'))
    parser.add_argument('--output', type=Path, default=Path('docs'))
    args = parser.parse_args()
    print(json.dumps(audit(args.db, args.csv, args.output), indent=2))
