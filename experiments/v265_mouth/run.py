import json,argparse,time,resource
from pathlib import Path
from .component import build,jaw_only,IDENTITIES
from .validate import validate

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);rows=[];start=time.monotonic()
 for name,params in IDENTITIES.items():
  t=build(**params)
  for i in range(11):
   opening=i/10;r=validate(t,jaw_only(t,opening));r.update(identity=name,opening=opening);rows.append(r)
   (out/'results.json').write_text(json.dumps(rows,indent=2))
   print(name,opening,r['pass'],r['intersections'],flush=True)
   if not r['pass']:break
 summary=dict(cases=len(rows),neutral_pass=all(r['pass'] for r in rows if r['opening']==0),jaw_pass=len(rows)==110 and all(r['pass'] for r in rows),first_failure=next((r for r in rows if not r['pass']),None),seconds=time.monotonic()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,full_anatomy_admission=False)
 (out/'summary.json').write_text(json.dumps(summary,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
