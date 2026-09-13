"""Calibrate on independent construction parameters, test on sealed parameters.

This qualifies the standalone component only; face attachment is a separate gate.
"""
import json,argparse
from pathlib import Path
import numpy as np
from experiments.v265_mouth.component import build
from experiments.v265_mouth.validate import validate
from .candidates import deform_d
from .audit import metrics,wall

def sample(rng,i):
 p=dict(width=rng.uniform(.018,.031),upper=rng.uniform(.0015,.0045),lower=rng.uniform(.0018,.005),philtrum=rng.uniform(.009,.020),jaw=rng.uniform(.030,.050),asymmetry=rng.uniform(-.08,.08))
 t=build(**p)
 # Additional asymmetric lower-face transition; old positive identities unchanged.
 if i%4==0:
  q=t['loops'][0];x=t['vertices'][q,0];y=t['vertices'][q,1];t['vertices'][q,1]+=np.maximum(y,0)*.08*x/(p['width']+.010)
 return t,p

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);base=json.loads((out/'summary.json').read_text())
 if not base['contact_pass']:raise ValueError('D contact failure')
 rng=np.random.default_rng(2651301);cal=[]
 for i in range(24):
  t,p=sample(rng,i)
  for o in np.linspace(0,1,21):cal.append(metrics(deform_d(t,float(o)),t['vertices'],t['triangles']))
 # Fixed20% engineering margin, after repaired mechanics, NOT human tissue bounds.
 envelope=dict(edge_min=min(r['edge_min'] for r in cal)*.8,edge_max=max(r['edge_max'] for r in cal)*1.2,area_min=min(r['area_min'] for r in cal)*.8,area_max=max(r['area_max'] for r in cal)*1.2,concentration_max=max(r['local_concentration'] for r in cal)*1.2)
 (out/'envelope.json').write_text(json.dumps(dict(seed=2651301,identities=24,states=len(cal),envelope=envelope,margin=.2,status='standalone synthetic engineering only'),indent=2))
 rng=np.random.default_rng(2651302);rows=[]
 for i in range(12):
  t,p=sample(rng,i)
  for o in np.linspace(0,1,11):
   v=deform_d(t,float(o));m=metrics(v,t['vertices'],t['triangles']);ct=validate(t,v);w=wall(t,v)
   strain=(envelope['edge_min']<=m['edge_min'] and m['edge_max']<=envelope['edge_max'] and envelope['area_min']<=m['area_min'] and m['area_max']<=envelope['area_max'] and m['local_concentration']<=envelope['concentration_max'])
   ok=ct['pass'] and strain and w['global']['metres']>.001
   rows.append(dict(identity=i,params=p,opening=float(o),geometry=m,contact_pass=ct['pass'],contacts=ct['intersections'],wall=w,strain_pass=strain,passed=ok))
   (out/'sealed-results.json').write_text(json.dumps(rows,separators=(',',':')))
   if not ok:
    (out/'qualification.json').write_text(json.dumps(dict(passed=False,first_failure=rows[-1]),indent=2));print('SEALED FAIL',i,o,flush=True);return
  print('sealed',i,'pass',flush=True)
 (out/'qualification.json').write_text(json.dumps(dict(passed=True,identities=12,states=len(rows),calibration_seed=2651301,sealed_seed=2651302,scope='standalone mouth only',attachment_pass=False),indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
