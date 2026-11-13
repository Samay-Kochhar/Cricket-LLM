"""Independent SQL oracle. No planner, service, filter builder or production aggregate imports."""
from pathlib import Path
import json,yaml,duckdb,math,collections
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--capture',type=Path,required=True)
parser.add_argument('--split',choices=['dev','holdout'],required=True,help='holdout: final test only, run once after fixes are frozen (2026-11-13)')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]; OUT=args.capture.resolve().parent
c=duckdb.connect(str(ROOT/'data/cricket_all.duckdb'),read_only=True)
c.execute("ATTACH '"+str(ROOT/'data/sources/tigzig/cricket_all_tables.duckdb')+"' AS tig (READ_ONLY)")
qs=json.loads(args.capture.read_text())
gold={r['id']:r['plan'] for r in yaml.safe_load((ROOT/'tests/evals/multiformat_gold_plans.yaml').read_text()) if r['split']==args.split}
if len(qs)!=len(gold) or {r['id'] for r in qs}!=set(gold) or any(r.get('split')!=args.split for r in qs):
 raise SystemExit('Capture must contain exactly the locked dev IDs; refusing other splits')
NON_DISMISSALS="('retired hurt','retired not out','not out','retired not out (hurt)','retired_hurt','retired_not_out','not_out','retired-not-out')"
def sqlrows(sql,params=()):
 cur=c.execute(sql,params); return [dict(zip([d[0] for d in cur.description],r)) for r in cur.fetchall()]
def lit(x): return "'"+str(x).replace("'","''")+"'"
def identity(name):
 r=c.execute('SELECT DISTINCT player_id FROM analytics.player_names WHERE lower(name)=lower(?)',[name]).fetchall()
 if not r:r=c.execute('SELECT player_id FROM analytics.players WHERE lower(name)=lower(?)',[name]).fetchall()
 if len(r)>1: r=c.execute('SELECT player_id FROM analytics.players WHERE lower(unique_name)=lower(?)',[name]).fetchall()
 if len(r)!=1: raise ValueError((name,r))
 return r[0][0]
def where(p,s):
 clauses=['TRUE']
 for col in ['format','gender','competition']:
  if s.get(col): clauses.append(f"{col} {'ILIKE' if '%' in s[col] else '='} {lit(s[col])}")
 for col,key in [('format','formats'),('competition','competitions'),('competition','excluded_competitions'),('year','years'),('bowler_style_code','bowler_styles'),('line','lines'),('length','lengths')]:
  a=(s if key in ['formats','competitions','excluded_competitions'] else p).get(key)
  if a: clauses.append(f"{col} {'NOT IN' if key=='excluded_competitions' else 'IN'} ({','.join(map(lit,a))})")
 if p.get('year_from'):clauses.append(f"year>={p['year_from']}")
 if p.get('year_to'):clauses.append(f"year<={p['year_to']}")
 if p.get('venue'):clauses.append('venue ILIKE '+lit('%'+p['venue']+'%'))
 if p.get('phase'):
  # Independently specified scheduled over boundaries, with Hundred five-ball sets.
  ph=p['phase']; bounds={'powerplay':(0,6),'middle':(6,15),'death':(15,20)}[ph]
  clauses.append(f'over_no>={bounds[0]} AND over_no<{bounds[1]}')
 return ' AND '.join(clauses)
VENUE_ROWS=json.loads((ROOT/'backend/app/domain/data/odi_venues.json').read_text())
VENUE_CANON={alias:row['display_name'] for row in VENUE_ROWS for alias in row['aliases'] if len(row['aliases'])>1}
venue_case="CASE venue "+' '.join('WHEN '+lit(a)+' THEN '+lit(b) for a,b in VENUE_CANON.items())+" ELSE venue END"
def equal(a,b):
 if a is None or b is None:return a is b
 if isinstance(a,(int,float)) and isinstance(b,(int,float)):return abs(a-b)<0.015
 return str(a)==str(b)
def stat(w,role,pid,dim=None,cell=None,matchup=None):
 key='batter_id' if role=='batting' else 'bowler_id'; sel=w+f' AND {key}={lit(pid)}'
 if dim:sel+=f' AND {dim}={lit(cell)}'
 if matchup:sel+=f' AND bowler_id={lit(matchup)}'
 if role=='batting':
  r=sqlrows(f"SELECT sum(runs_batter) runs,count(*) FILTER(WHERE coalesce(wides,0)=0) balls,count(*) FILTER(WHERE runs_batter=4 AND NOT coalesce(non_boundary,false)) fours,count(*) FILTER(WHERE runs_batter=6 AND NOT coalesce(non_boundary,false)) sixes,count(*) FILTER(WHERE runs_batter=0 AND coalesce(wides,0)=0) dot_balls FROM analytics.deliveries WHERE {sel}")[0]
  if dim or matchup or 'bowler_style_code' in w:
   ds=sel+' AND is_wicket AND player_out_id=batter_id'
  else: ds=w+f' AND player_out_id={lit(pid)} AND is_wicket'
  r['dismissals']=c.execute(f"SELECT count(*) FROM analytics.deliveries WHERE {ds} AND lower(trim(coalesce(wicket_kind,''))) NOT IN {NON_DISMISSALS}").fetchone()[0]
  den=r['dismissals'];runs=r['runs'] or 0;balls=r['balls']; r.update(strike_rate=round(100*runs/balls,2) if balls else None,average=round(runs/den,2) if den else None,dot_ball_pct=round(100*r['dot_balls']/balls,1) if balls else None)
 else:
  r=sqlrows(f"SELECT sum(runs_batter+coalesce(wides,0)+coalesce(noballs,0)) runs_conceded,count(*) FILTER(WHERE is_legal) balls,count(*) FILTER(WHERE is_bowler_wicket) wickets,count(*) FILTER(WHERE is_legal AND runs_total=0) dot_balls FROM analytics.deliveries WHERE {sel}")[0]
  runs=r['runs_conceded'] or 0;balls=r['balls'];wk=r['wickets'];r.update(economy=round(6*runs/balls,2) if balls else None,strike_rate=round(balls/wk,2) if wk else None,average=round(runs/wk,2) if wk else None,dot_ball_pct=round(100*r['dot_balls']/balls,1) if balls else None)
 metadata_sel=sel
 if role=='batting' and not (dim or matchup or 'bowler_style_code' in w):
  metadata_sel=f"{w} AND (batter_id={lit(pid)} OR (is_wicket AND player_out_id={lit(pid)} AND player_out_id<>batter_id))"
 meta=sqlrows(f"SELECT min(match_date) first_match,max(match_date) last_match,count(*) delivery_rows,count(DISTINCT match_id) matches FROM analytics.deliveries WHERE {metadata_sel}")[0]
 # Delivery volume counts raw faced/bowled events; career dates and matches
 # also include legitimate dismissal-only non-striker appearances.
 meta['delivery_rows']=c.execute(f"SELECT count(*) FROM analytics.deliveries WHERE {sel}").fetchone()[0]
 r.update(meta)
 if matchup:
  r['bowler_wickets']=c.execute(f"SELECT count(*) FROM analytics.deliveries WHERE {sel} AND is_bowler_wicket AND player_out_id={lit(pid)}").fetchone()[0]
 if dim:
  den=c.execute(f"SELECT count(*) FROM analytics.deliveries WHERE {w} AND {key}={lit(pid)} AND {dim} IS NOT NULL").fetchone()[0]
  r['delivery_pct']=round(100*r['delivery_rows']/den,2) if den else None
 if role=='bowling':
  r['boundaries']=c.execute(f"SELECT count(*) FROM analytics.deliveries WHERE {sel} AND runs_batter IN (4,6) AND NOT coalesce(non_boundary,false)").fetchone()[0]
 return r
# Resolve only the selected split aliases, never holdout targets.
aliases={name:identity(name) for p in gold.values() for name in p['players']}
(OUT/'gold_alias_validation.json').write_text(json.dumps(aliases,indent=2))
captures={}
model=qs[0].get('planner')
if model and model!='deterministic':
 for path in (ROOT/'tests/evals/results/multiformat/planner-cache'/model).glob('*.json'):
  record=json.loads(path.read_text())
  captures[record['question']]=record
reports=[]
for q in qs:
 p=gold[q['id']]; ap=q.get('plan') or {}; resp=q.get('query_response') or {}; tables=resp.get('tables',[])
 w=where(p,(p['scopes'] or [{}])[0]); failures=[]; checks=0; diffs=[]; oracle=[]
 for field in ['intent','role','years','year_from','year_to','phase','bowler_styles','dimensions','lengths','lines','partnership_min_runs','metrics']:
  if ap.get(field)!=p.get(field):diffs.append({'field':field,'gold':p.get(field),'actual':ap.get(field)})
 # Check each visible row against GOLD filters, including individual player targets.
 for ti,t in enumerate(tables):
  rs=[dict(zip(t['columns'],r)) for r in t['rows']]
  if not rs:continue
  if 'runs' in t['columns'] or 'runs_conceded' in t['columns']:
   for r in rs:
    pid=r.get('player_id')
    if not pid:
     names=p['players'];name=names[min(ti,len(names)-1)] if names else None
     if not name:continue
     pid=aliases[name]
    dim=next((d for d in ['line','length'] if d in r),None)
    role=p['role']; target=None
    if p['intent']=='matchup':
     role='batting'; a,b=[aliases[n] for n in p['players']]
     pid,target=(b,a) if q['id']=='mu-05' else (a,b)
    expected=stat(w,role,pid,dim,r.get(dim),target)
    for key,value in expected.items():
     if key in r:
      checks+=1
      if not equal(value,r[key]):failures.append(f"{t['title']} {r.get('name',r.get(dim,''))} {key}: got {r[key]}, expected {value}")
    if p['intent']=='ranking' and r.get('balls',0)<p['min_balls']:failures.append('minimum sample violated')
    oracle.append({'target':pid,'group':r.get(dim) if dim else None,**expected})
  elif 'venue' in t['columns']:
   expected=sqlrows(f"WITH inn AS (SELECT {venue_case} venue,match_id,innings_no,sum(runs_total) runs,count(*) FILTER(WHERE is_legal) balls FROM analytics.deliveries WHERE {w} AND NOT coalesce(is_super_over,false) GROUP BY ALL) SELECT venue,count(DISTINCT match_id) matches,round(avg(runs) FILTER(WHERE innings_no=1),2) avg_first_innings_runs,round(avg(runs) FILTER(WHERE innings_no=2),2) avg_second_innings_runs,round(6.0*sum(runs)/nullif(sum(balls),0),2) run_rate FROM inn GROUP BY venue")
   by={r['venue']:r for r in expected}
   for r in rs:
    if r['venue'] not in by: failures.append('venue outside requested scope: '+r['venue']);continue
    for k,v in by[r['venue']].items():
     checks+=1
     if not equal(v,r[k]):failures.append(f'venue {k}: {r[k]} vs {v}')
   checks+=1
   if [r['venue'] for r in rs]!=[r['venue'] for r in sorted(expected,key=lambda r: (-(r['avg_first_innings_runs'] or 0),r['venue']))]:failures.append('venue membership/order differs from independent SQL')
   oracle.extend(expected)
  elif 'partnership_runs' in t['columns']:
   # Python segmentation independently from ordered delivery stream, retaining repeat pair stands.
   balls=sqlrows(f'SELECT match_id,innings_no,batter_id,non_striker_id,runs_total FROM analytics.deliveries WHERE {w} ORDER BY match_id,innings_no,innings_delivery_seq')
   stands=[];prev=None
   for b in balls:
    if b['non_striker_id'] is None or b['batter_id'] is None:prev=None;continue
    pair=tuple(sorted([b['batter_id'],b['non_striker_id']]));key=(b['match_id'],b['innings_no'],pair)
    if key!=prev:stands.append([pair,0]);prev=key
    stands[-1][1]+=b['runs_total']
   totals=collections.defaultdict(list)
   for pair,runs in stands:totals[pair].append(runs)
   name_ids={r['name']:r['player_id'] for r in sqlrows('SELECT player_id,name FROM analytics.players')}
   target_ids={aliases[n] for n in p['players']}
   candidates=[(pair,values) for pair,values in totals.items() if target_ids.issubset(pair) and any(n>=(p['partnership_min_runs'] or 0) for n in values)]
   expected_pairs=[pair for pair,values in sorted(candidates,key=lambda x:(-sum(x[1]),-max(x[1])))[:p['limit']]]
   actual_pairs=[tuple(sorted([name_ids[r['batter_1']],name_ids[r['batter_2']]])) for r in rs]
   checks+=1
   if actual_pairs!=expected_pairs:failures.append('partnership membership/order differs from independent Python oracle')
   for r in rs:
    pair=tuple(sorted([name_ids[r['batter_1']],name_ids[r['batter_2']]])); values=totals[pair]
    if p['players'] and not set(aliases[n] for n in p['players']).issubset(pair):failures.append('partnership targets differ from gold')
    expected={'stands':len(values),'partnership_runs':sum(values),'best_stand':max(values),'fifty_plus_stands':sum(n>=50 for n in values),'hundred_plus_stands':sum(n>=100 for n in values),'qualifying_stands':sum(n>=(p['partnership_min_runs'] or 0) for n in values)}
    for k,v in expected.items():
     checks+=1
     if not equal(v,r[k]):failures.append(f'partnership {k}: {r[k]} vs {v}')
    oracle.append(expected)
  elif 'with_line' in t['columns']:
   for r in rs:
    cw=w+f" AND format={lit(r['format'])} AND gender={lit(r['gender'])}"
    if 'year' in r:cw+=f" AND year={r['year']} AND competition={lit(r['competition'])}"
    ex=sqlrows(f"SELECT count(DISTINCT match_id) matches,round(100.0*count(line)/count(*),1) line_pct,round(100.0*count(length)/count(*),1) length_pct,count(*) deliveries,count(line) with_line,count(length) with_length,min(match_date) first_match,max(match_date) last_match,min(match_date) FILTER(WHERE line IS NOT NULL) first_line,min(match_date) FILTER(WHERE length IS NOT NULL) first_length FROM analytics.deliveries WHERE {cw}")[0]
    for k,v in ex.items():
     checks+=1
     if not equal(v,r[k]):failures.append(f'coverage {k}: {r[k]} vs {v}')
    oracle.append(ex)
 # Independently verify complete leaderboard membership and order, not only emitted values.
 if (p['intent']=='ranking' or (p['intent']=='venue' and p['players'])) and not p['dimensions']:
  metric=p['metrics'][0];role=p['role'];key='batter_id' if role=='batting' else 'bowler_id'
  if role=='batting':
   bases=f"SELECT batter_id player_id,sum(runs_batter) runs,count(*) FILTER(WHERE coalesce(wides,0)=0) balls FROM analytics.deliveries WHERE {w} GROUP BY 1"
   outs=f"SELECT player_out_id player_id,count(*) dismissals FROM analytics.deliveries WHERE {w} AND is_wicket AND lower(trim(coalesce(wicket_kind,''))) NOT IN {NON_DISMISSALS} GROUP BY 1"
   expr={'runs':'runs','strike_rate':'round(100.0*runs/nullif(balls,0),2)','average':'round(1.0*runs/nullif(dismissals,0),2)'}[metric]
   query=f"WITH b AS ({bases}),o AS ({outs}) SELECT b.player_id,balls,{expr} AS stat_value FROM b LEFT JOIN o USING(player_id)"
  else:
   expr={'wickets':'wickets','economy':'round(6.0*runs/nullif(balls,0),2)','strike_rate':'round(1.0*balls/nullif(wickets,0),2)'}[metric]
   query=f"WITH b AS (SELECT bowler_id player_id,sum(runs_batter+coalesce(wides,0)+coalesce(noballs,0)) runs,count(*) FILTER(WHERE is_legal) balls,count(*) FILTER(WHERE is_bowler_wicket) wickets FROM analytics.deliveries WHERE {w} GROUP BY 1) SELECT player_id,balls,{expr} AS stat_value FROM b"
  direction='ASC' if p['descending']==False or (role=='bowling' and metric in ['economy','strike_rate','average']) else 'DESC'
  ranked=sqlrows(f"WITH calculated AS ({query}) SELECT x.player_id FROM calculated x JOIN analytics.players p USING(player_id) WHERE balls>={p['min_balls']} AND stat_value IS NOT NULL ORDER BY stat_value {direction},p.name LIMIT {p['limit']}")
  actual=[dict(zip(t['columns'],r))['player_id'] for t in tables for r in t['rows'] if 'player_id' in t['columns']]
  checks+=1
  if actual!=[r['player_id'] for r in ranked]:failures.append('leaderboard membership/order differs from independent SQL')
 if p['dimensions'] and p['players'] and not p['lengths']:
  for dim in p['dimensions']:
   pid=aliases[p['players'][0]];key='batter_id' if p['role']=='batting' else 'bowler_id'
   expected_groups={r[0] for r in c.execute(f"SELECT DISTINCT {dim} FROM analytics.deliveries WHERE {w} AND {key}={lit(pid)} AND {dim} IS NOT NULL").fetchall()}
   actual_groups={dict(zip(t['columns'],r))[dim] for t in tables if dim in t['columns'] for r in t['rows']}
   if expected_groups!=actual_groups:failures.append(f'missing {dim} groups: {expected_groups-actual_groups}')
 # Cross-check 2 matched innings per dev case with TigZig, whole-innings aligned samples.
 sample=sqlrows(f"SELECT DISTINCT match_id,innings_no FROM analytics.deliveries d WHERE {w} AND try_cast(match_id AS BIGINT) IN (SELECT DISTINCT match_id FROM tig.ball_by_ball) ORDER BY match_id,innings_no LIMIT 2")
 aligned=[]
 for s in sample:
  aa=c.execute('SELECT count(*),sum(runs_batter),sum(runs_total),count(*) FILTER(WHERE is_legal) FROM analytics.deliveries WHERE match_id=? AND innings_no=?',[s['match_id'],s['innings_no']]).fetchone()
  bb=c.execute('SELECT count(*),sum(runs_off_bat),sum(runs_off_bat+extras),count(*) FILTER(WHERE coalesce(wides,0)=0 AND coalesce(noballs,0)=0) FROM tig.ball_by_ball WHERE match_id=? AND innings=?',[int(s['match_id']),s['innings_no']]).fetchone()
  aligned.append({**s,'analytics':aa,'tigzig':bb,'equal':aa==bb})
 notes=resp.get('evidence_notes',[])
 if not notes or notes[-1]['title']!='Afghanistan coverage':failures.append('general Afghanistan evidence note absent/not last')
 if any(s in (q.get('answer') or '').lower() for s in ['cricsheet','tigzig','aucb','espn']):failures.append('source provenance leaked')
 if not tables and q['id'] not in ['lim-01']:failures.append('missing requested result')
 # Answer rubric: all qualifiers mandatory. Reading issues that still expose requested metrics are PARTIAL.
 grade='FAIL' if failures else 'PASS'

 reports.append({'id':q['id'],'grade':grade,'reading_diffs':diffs,'numeric_checks':checks,'failures':failures,'oracle':oracle,'tigzig_aligned':aligned})
 print(q['id'],grade,checks,len(failures),flush=True)
 (OUT/'independent_checks.json').write_text(json.dumps(reports,indent=2,default=str))

# Plan scoring is separate from final rendered tables. Requested metrics are a subset.
def scope_equivalent(g,a,p):
 g={k:v for k,v in g.items() if k!='label' and v not in (None,[])}
 a={k:v for k,v in a.items() if k!='label' and v not in (None,[])}
 if g.get('gender')!=a.get('gender') and p['players'] and ('gender' not in g or 'gender' not in a):
  ids=[aliases[n] for n in p['players']]
  w=where(p,{k:v for k,v in g.items() if k!='gender'})
  genders={r[0] for r in c.execute(f"SELECT DISTINCT gender FROM analytics.deliveries WHERE {w} AND (batter_id IN ({','.join(map(lit,ids))}) OR bowler_id IN ({','.join(map(lit,ids))}))").fetchall()}
  explicit=g.get('gender') or a.get('gender')
  if genders=={explicit}:g.pop('gender',None);a.pop('gender',None)
 if g==a:return True
 # Competition membership can imply a redundant format (e.g. CPL), or a
 # gender-scoped Hundred format can imply its explicit competition name.
 # Never use this to erase a gender qualifier or arbitrary player filters.
 if g.get('gender')!=a.get('gender'):return False
 gg={tuple(r.values()) for r in sqlrows('SELECT DISTINCT format,gender,competition FROM analytics.coverage WHERE '+where({},g))}
 aa={tuple(r.values()) for r in sqlrows('SELECT DISTINCT format,gender,competition FROM analytics.coverage WHERE '+where({},a))}
 return bool(gg) and gg==aa
for item,q in zip(reports,qs):
 p=gold[q['id']];a=q.get('plan') or {};diff=[]
 venue_rank=p['intent']=='venue' and bool(p['players']) and a.get('intent')=='ranking'
 ignored={'metrics','players','scopes','venue','min_balls','limit','descending','unsupported'}
 for key,val in p.items():
  if key in ignored:continue
  # An explicit interval identical to the selected T20 phase is redundant,
  # not a changed reading. Independently specified one-based over bounds.
  bounds={'powerplay':(1,6),'middle':(7,15),'death':(16,20)}.get(p.get('phase'))
  if key in {'over_from','over_to'} and p.get('over_from') is None and p.get('over_to') is None and bounds and a.get('phase')==p.get('phase') and (a.get('over_from'),a.get('over_to'))==bounds:continue
  if key=='intent' and venue_rank:continue
  if val!=a.get(key):diff.append({'field':key,'gold':val,'actual':a.get(key)})
 if p['intent'] not in ['coverage','partnership','venue'] and not set(p['metrics']).issubset(a.get('metrics',[])):
  diff.append({'field':'metrics','gold':p['metrics'],'actual':a.get('metrics')})
 allowed_metrics=({'balls','runs','average','strike_rate','dot_ball_pct','fours','sixes'} if a.get('role')=='batting' else {'balls','wickets','average','strike_rate','economy','dot_ball_pct'})
 invalid_metrics=sorted(set(a.get('metrics',[]))-allowed_metrics) if a.get('intent') not in ['coverage','partnership','venue','matchup'] else []
 if invalid_metrics:diff.append({'field':'invalid_role_metrics','actual':invalid_metrics})
 # canonical names from explicit aliases and validation trace; unresolved strings remain wrong.
 mapping={}
 for change in q.get('validation_changes') or []:
  if ' → ' in change:
   old,new=change.split(' → ',1);mapping[old]=new
 actual=[]
 for name in a.get('players',[]):
  try:actual.append(identity(mapping.get(name,name)))
  except ValueError:actual.append('UNRESOLVED:'+name)
 if actual!=[aliases[n] for n in p['players']]:diff.append({'field':'players','gold':p['players'],'actual':a.get('players')})
 if len(p['scopes'])!=len(a.get('scopes',[])) or any(not scope_equivalent(g,s,p) for g,s in zip(p['scopes'],a.get('scopes',[]))):diff.append({'field':'scopes','gold':p['scopes'],'actual':a.get('scopes')})
 if bool(p['venue'])!=bool(a.get('venue')) or (p['venue'] and VENUE_CANON.get(p['venue'],p['venue']).lower() != VENUE_CANON.get(a.get('venue'),a.get('venue') or '').lower() and p['venue'].lower() not in (a.get('venue') or '').lower()):diff.append({'field':'venue','gold':p['venue'],'actual':a.get('venue')})
 if p['intent']=='ranking' or venue_rank:
  for key in ['min_balls','limit']:
   if p[key]!=a.get(key):diff.append({'field':key,'gold':p[key],'actual':a.get(key)})
 if (p['intent']=='ranking' or venue_rank) and a.get('descending') is not None and (p.get('descending') is False)!=(a.get('descending') is False):
  diff.append({'field':'descending','gold':p.get('descending'),'actual':a.get('descending')})
 if bool(p['unsupported'])!=bool(a.get('unsupported')):diff.append({'field':'unsupported','gold':p['unsupported'],'actual':a.get('unsupported')})
 item['reading_diffs']=diff;item['A_plan']='FAIL' if diff else 'PASS'
 changes=q.get('validation_changes') or []
 raw_ids=[]
 for name in a.get('players',[]):
  try:raw_ids.append(identity(name))
  except ValueError:raw_ids.append('UNRESOLVED:'+name)
 target_ids=[aliases[n] for n in p['players']]
 classification='no_change'
 if changes:
  classification=('neutral_canonicalization' if raw_ids==actual else 'helpful' if actual==target_ids else 'harmful' if raw_ids==target_ids else 'changed_but_incorrect')
 status=(q.get('query_response') or {}).get('status')
 if not changes and status=='unsupported':
  classification='correct_rejection' if p['unsupported'] else 'helpful_rejection_of_invalid_metrics' if invalid_metrics else 'rejected_requested_result'
 item['B_validation']={'classification':classification,'trace':changes,'scope_role_reinterpretation':False}
 model_error=any(str(x).startswith('model reading unavailable:') for x in a.get('unsupported',[]))
 capture=captures.get(q['question'],{})
 response=capture.get('response',{})
 capture_failure=capture.get('error') or response.get('error_kind') or ('truncated' if response.get('finish_reason')=='MAX_TOKENS' else None)
 if model_error or capture_failure:
  item['grade']='FAIL';item['A_plan']='FAIL'
  item['B_validation']['classification']='model_capture_failure'
  item['failures'].append('model capture failed: '+str(capture_failure or a.get('unsupported')))
 item['capture_failure']=capture_failure
 item['C_numeric']=item['grade']
 if a.get('unsupported') and not p['unsupported']:item['grade']='FAIL'
 if diff:item['grade']='FAIL'
(OUT/'independent_checks.json').write_text(json.dumps(reports,indent=2,default=str))
(OUT/'plan_comparison.json').write_text(json.dumps([{k:r[k] for k in ['id','A_plan','reading_diffs','B_validation','C_numeric','grade']} for r in reports],indent=2))
counts=collections.Counter(r['grade'] for r in reports)
summary={'questions':len(reports),'overall':dict(counts),'A_plan':dict(collections.Counter(r['A_plan'] for r in reports)),'B_validation':dict(collections.Counter(r['B_validation']['classification'] for r in reports)),'C_numeric':dict(collections.Counter(r['C_numeric'] for r in reports)),'numeric_checks':sum(r['numeric_checks'] for r in reports),'tigzig_matched_innings':sum(len(r['tigzig_aligned']) for r in reports),'tigzig_mismatches':sum(not s['equal'] for r in reports for s in r['tigzig_aligned'])}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
lines=['# Independent dev grading','',json.dumps(summary,indent=2),'','Only the locked dev split was scored. No application planner, filter builder or aggregate is imported. Obstructing the field counts as a dismissal. Numeric correctness never excuses a plan error. Gender equivalence requires a single resolved identity with only the specified gender in the gold scope. Validation traces resolve names only; scope and role are not reinterpreted. Equivalent phase bounds and competition-implied format restrictions are normalized independently. Extra metrics incompatible with the role fail A, even when the requested metrics are present.','']
for r in reports:
 lines += [f"## {r['id']} — {r['grade']}",f"A: {r['A_plan']}; B: {r['B_validation']['classification']}; C: {r['C_numeric']}; {r['numeric_checks']} independent checks.",json.dumps(r['reading_diffs'],ensure_ascii=False)]+r['failures']+['']
(OUT/'grading.md').write_text('\n'.join(lines))
print(json.dumps(summary))

# Actual captured token accounting, including thinking. No estimated calls are
# substituted for missing captures; HTTP failures without usage stay unknown.
if captures:
 rates={'gemini-4-argon':(2.0,10.0),'gemini-3.1-pro-preview':(2.0,12.0),'gemini-3.8-flash':(.75,3.75)}
 input_rate,output_rate=rates[model]
 usage=[]
 for q in qs:
  rec=captures.get(q['question'])
  if not rec:continue
  r=rec.get('response',{})
  inp=r.get('prompt_token_count');out=r.get('output_token_count');thought=r.get('thoughts_token_count')
  total=r.get('total_token_count')
  # Omitted thinking metadata on non-thinking responses represents zero.
  thinking=thought or 0
  known=inp is not None and out is not None
  cost=(inp*input_rate+(out+thinking)*output_rate)/1e6 if known else None
  usage.append({'id':q['id'],'model':model,'input_tokens':inp,'output_tokens':out,
   'thoughts_tokens':thought,'total_tokens':total,'billable_output_tokens':out+thinking if out is not None else None,
   'estimated_usd':cost,'max_output_budget_usd':4096*output_rate/1e6,
   'input_plus_max_output_budget_usd':(inp*input_rate+4096*output_rate)/1e6 if inp is not None else None,
   'finish_reason':r.get('finish_reason'),'error':rec.get('error') or r.get('error_kind')})
 usage_summary={'model':model,'date':'2026-11-12','captured_calls':len(usage),'missing_calls':len(qs)-len(usage),
  'errors':sum(bool(r['error']) for r in usage),'truncated':sum(r['finish_reason']=='MAX_TOKENS' for r in usage),
  'unknown_usage_calls':sum(r['estimated_usd'] is None for r in usage),
  'tokens':{k:sum(r[k] or 0 for r in usage) for k in ['input_tokens','output_tokens','thoughts_tokens','total_tokens']},
  'estimated_known_usd':sum(r['estimated_usd'] or 0 for r in usage),
  'mean_known_usd_per_usage_reported_response':sum(r['estimated_usd'] or 0 for r in usage)/max(1,sum(r['estimated_usd'] is not None for r in usage)),
  'all_calls_output_cap_usd':len(usage)*4096*output_rate/1e6,
  'mean_known_usd_per_captured_question':sum(r['estimated_usd'] or 0 for r in usage)/len(usage),
  'known_input_plus_max_output_budget_usd':sum(r['input_plus_max_output_budget_usd'] or 0 for r in usage),
  'rates_usd_per_million':{'input':input_rate,'output_including_thinking':output_rate},
  'source':'https://aistudio.google.com/docs/pricing',
  'notes':['Standard paid tier estimate; actual invoice may apply implicit input-cache discounts not recorded by this client.',
   'HTTP errors with absent usage have unknown charge, not an asserted zero cost.',
   '4096-token output cap includes thinking; max budget adds actual recorded input. Unknown-usage calls are excluded from known budget.',
   'Argon changes to $4/$20 per million on December 1, 2026; Flash changes to $1.50/$7.50 on January 1, 2027.']}
 (OUT/'usage.json').write_text(json.dumps({'summary':usage_summary,'questions':usage},indent=2))
 with (OUT/'grading.md').open('a') as f:
  f.write('\n\n## Captured usage and estimated cost\n\n'+json.dumps(usage_summary,indent=2)+'\n')
 print(json.dumps(usage_summary))
