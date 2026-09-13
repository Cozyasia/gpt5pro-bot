import json,argparse,time
from pathlib import Path
from .component import build,expression,IDENTITIES
from .validate import validate

def run(out):
 out=Path(out);summary=json.loads((out/'summary.json').read_text())
 if not summary['jaw_pass']:raise ValueError('jaw admission required before expressions')
 rows=[];start=time.monotonic()
 for name,params in IDENTITIES.items():
  t=build(**params)
  for opening in (0.,1.):
   for mode in ('smile','compression','protrusion','asymmetry'):
    for value in (.25,.5,.75,1.):
     r=validate(t,expression(t,opening,**{mode:value}));r.update(identity=name,opening=opening,mode=mode,coefficient=value);rows.append(r)
     (out/'expression-results.json').write_text(json.dumps(rows,indent=2))
     if not r['pass']:
      (out/'expression-summary.json').write_text(json.dumps(dict(passed=False,first_failure=r,cases=len(rows)),indent=2));print('FIRST FAILURE',name,opening,mode,value,r['intersections'],flush=True);return
  print(name,'expressions pass',flush=True)
 (out/'expression-summary.json').write_text(json.dumps(dict(passed=True,cases=len(rows),seconds=time.monotonic()-start),indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
