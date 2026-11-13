"""Read-only ODI dismissal oracle and real application query-builder regression check.

PYTHONPATH=. python scripts/odi_dismissal_check.py --label before
Rerun with --label after --assert-correct after the application fix. Snapshots
are exclusive-create: an existing before snapshot is never overwritten.
No planner/model calls, answer keys, environment files, or network are used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket

import duckdb

from backend.app.cricket_analytics.schemas import CricketQueryPlan
from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.executors.matchup_executor import build_matchup_query

ROOT = Path(__file__).resolve().parents[1]
PLAYERS = ['MS Dhoni', 'V Kohli', 'RG Sharma', 'JE Root', 'KS Williamson', 'SPD Smith',
           'Babar Azam', 'AB de Villiers', 'RT Ponting', 'KC Sangakkara', 'Shakib Al Hasan', 'LRPL Taylor']
ODI_NAMES = dict(zip(PLAYERS, ['MS Dhoni','Virat Kohli','Rohit Sharma','Joe Root','Kane Williamson','Steven Smith',
                              'Babar Azam','AB de Villiers','Ricky Ponting','Kumar Sangakkara','Shakib Al Hasan','Ross Taylor']))
EXCLUDED = "('retired hurt','retired not out','retired not out (hurt)','not out')"
VALID = f"lower(coalesce(dismissal,'')) NOT IN {EXCLUDED} AND lower(out)='true'"


def rows(conn, sql, params=None):
    cur = conn.execute(sql, params or [])
    return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]


def snapshot():
    with duckdb.connect(str(ROOT / 'data/odi_analytics.duckdb'), read_only=True) as c:
        # ATTACH is read-only too; matching keys are date plus unordered teams.
        reference_path = str(ROOT / 'data/sources/tigzig/cricket_all_tables.duckdb').replace("'", "''")
        c.execute(f"ATTACH '{reference_path}' AS reference (READ_ONLY)")
        c.execute('''CREATE TEMP VIEW common_matches AS
          WITH a AS (SELECT DISTINCT p_match, try_cast(date AS DATE) AS day,
             least(trim(team_bat),trim(team_bowl)) AS t1,
             greatest(trim(team_bat),trim(team_bowl)) AS t2 FROM analytics.deliveries_v1),
          b AS (SELECT DISTINCT match_id, start_date AS day,
             least(trim(batting_team),trim(bowling_team)) AS t1,
             greatest(trim(batting_team),trim(bowling_team)) AS t2 FROM reference.ball_by_ball_odi_men)
          SELECT a.*, b.match_id FROM a JOIN b USING(day,t1,t2)''')
        alignment = rows(c, '''SELECT count(*) AS matched_keys, count(DISTINCT p_match) AS odi_matches,
          count(DISTINCT match_id) AS reference_matches FROM common_matches''')[0]
        # Detect ambiguous date/team keys instead of quietly double-counting.
        alignment['ambiguous_keys'] = rows(c, '''SELECT day,t1,t2,count(DISTINCT p_match) AS odi_matches,
          count(DISTINCT match_id) AS reference_matches FROM common_matches GROUP BY ALL
          HAVING count(DISTINCT p_match)>1 OR count(DISTINCT match_id)>1''')
        output = []
        for reference_name in PLAYERS:
            name = ODI_NAMES[reference_name]
            ids = [r['p_bat'] for r in rows(c, 'SELECT DISTINCT p_bat FROM analytics.deliveries_v1 WHERE bat=?', [name])]
            if not ids:
                raise ValueError(f'No player ID found: {name}')
            marks = ','.join('?' for _ in ids)
            expected = rows(c, f'''SELECT count(*) AS dismissals FROM analytics.deliveries_v1
              WHERE p_out IN ({marks}) AND {VALID}''', ids)[0]['dismissals']
            old = rows(c, "SELECT count(*) AS n FROM analytics.deliveries_v1 WHERE bat=? AND lower(out)='true'", [name])[0]['n']
            totals = rows(c, '''SELECT sum(try_cast(batruns AS INTEGER)) FILTER(WHERE try_cast(ballfaced AS INTEGER)=1) AS runs,
              count(*) FILTER(WHERE try_cast(ballfaced AS INTEGER)=1) AS balls FROM analytics.deliveries_v1 WHERE bat=?''', [name])[0]
            paths = {}
            for path, operation, builder in [('aggregate', 'aggregate', build_aggregate_query), ('matchup', 'matchup', build_matchup_query)]:
                plan = CricketQueryPlan(operation=operation,entity='batter',metric='batting_average', filters={'batter':name}, limit=1000)
                built = builder(plan)
                query = built.query if hasattr(built, 'query') else built
                result = rows(c, query.sql, query.params)
                paths[path] = {'rows':result,'sql_sha256':hashlib.sha256(query.sql.encode()).hexdigest(),
                               'dismissals_correct':len(result)==1 and result[0].get('dismissals')==expected}
            common_odi = rows(c, f'''SELECT p_match,count(*) AS dismissals FROM analytics.deliveries_v1
              WHERE p_out IN ({marks}) AND {VALID}
              AND p_match IN (SELECT p_match FROM common_matches) GROUP BY p_match''', ids)
            common_ref = rows(c, f'''SELECT match_id,count(*) AS dismissals FROM reference.ball_by_ball_odi_men
              WHERE player_dismissed=? AND lower(coalesce(wicket_type,'')) NOT IN {EXCLUDED}
              AND nullif(trim(wicket_type),'') IS NOT NULL
              AND match_id IN (SELECT match_id FROM common_matches) GROUP BY match_id''', [reference_name])
            amap = {r['p_match']:r['dismissals'] for r in common_odi}
            bmap = {r['match_id']:r['dismissals'] for r in common_ref}
            differences = [dict(r,odi_dismissals=amap.get(r['p_match'],0),reference_dismissals=bmap.get(r['match_id'],0))
                           for r in rows(c,'SELECT DISTINCT p_match,match_id,day,t1,t2 FROM common_matches')
                           if amap.get(r['p_match'],0)!=bmap.get(r['match_id'],0)]
            examples = rows(c, '''SELECT date,p_match,bat,p_bat,p_out,dismissal FROM analytics.deliveries_v1
              WHERE bat=? AND lower(out)='true' AND p_out<>p_bat ORDER BY date LIMIT 5''', [name])
            output.append({'player':reference_name,'odi_name':name,'player_ids':ids,'old_striker_out':old,'expected_dismissals':expected,
                           **totals,'expected_average':totals['runs']/expected if expected else None,
                           'app_paths':paths,'common_matches':{'odi_dismissals':sum(amap.values()),
                           'reference_dismissals':sum(bmap.values()),'differences':differences},
                           'partner_dismissal_examples':examples})
    return {'captured_at':datetime.now(timezone.utc).isoformat(),'oracle':'p_out identifies dismissed batter; exclude retired hurt, retired not out (including retired not out (hurt)), not out; out=true',
            'alignment':alignment,'players':output,
            'failing_app_checks':sum(not p['dismissals_correct'] for r in output for p in r['app_paths'].values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', default='before', choices=['before','after'])
    parser.add_argument('--assert-correct', action='store_true')
    parser.add_argument('--check-only', action='store_true', help='Return a red/green exit code without writing snapshots')
    args = parser.parse_args()
    def blocked(*args, **kwargs):
        raise RuntimeError('Network is disabled for the ODI dismissal check')
    socket.socket.connect = blocked
    socket.create_connection = blocked
    result = snapshot()
    if args.check_only:
        print(f"Failing real app checks: {result['failing_app_checks']}/24")
        return int(bool(result['failing_app_checks']))
    directory = ROOT / 'tests/evals/results/odi_nonstriker'
    directory.mkdir(parents=True,exist_ok=True)
    target = directory / f'{args.label}.json'
    with target.open('x') as f:
        json.dump(result,f,indent=2,default=str); f.write('\n')
    lines = ['# ODI dismissal check', '', 'Both databases opened read-only. Real app aggregate and matchup builders executed, without model calls.', '',
             f"Common matches: {result['alignment']['odi_matches']}; ambiguous date/team keys: {len(result['alignment']['ambiguous_keys'])}.", '',
             '| Player | Old striker outs | Correct p_out | App aggregate | App matchup | Common ODI / reference |',
             '|---|---:|---:|---:|---:|---:|']
    for r in result['players']:
        app = [r['app_paths'][p]['rows'][0]['dismissals'] for p in ['aggregate','matchup']]
        common = r['common_matches']
        lines.append(f"| {r['player']} | {r['old_striker_out']} | {r['expected_dismissals']} | {app[0]} | {app[1]} | {common['odi_dismissals']} / {common['reference_dismissals']} |")
    lines += ['', f"Failing real app checks: {result['failing_app_checks']}/24.", '',
              'Full JSON includes date/team alignment differences, runs, balls, expected averages, generated SQL hashes, and partner-dismissal examples. Common-source differences are reported rather than treated as automatic correctness failures.']
    with (directory / f'{args.label}.md').open('x') as f:
        f.write('\n'.join(lines)+'\n')
    print('\n'.join(lines))
    return 1 if args.assert_correct and result['failing_app_checks'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
