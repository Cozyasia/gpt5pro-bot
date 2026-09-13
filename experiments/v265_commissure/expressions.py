"""Expression tests execute only after sealed standalone jaw qualification."""
import json,argparse
import numpy as np
from pathlib import Path
from experiments.v265_mouth.component import build,expression,jaw_only,IDENTITIES
from experiments.v265_mouth.validate import validate
from .candidates import deform_d,anchor_weights
from .audit import metrics,wall

def articulated_expression(t,opening=0.,**modes):
 """Transport neutral soft displacement in the same local jaw frames as skin.

 Compression acts on intrinsic lip coordinates, never on jaw opening itself.
 Dental deltas remain zero; neutral geometry and jaw trajectories are unchanged.
 """
 delta=expression(t,0.,**modes)-t['vertices']
 a=np.deg2rad(22)*opening;c,s=np.cos(a),np.sin(a)
 rotation=np.array([[1,0,0],[0,c,-s],[0,s,c]])
 weights=anchor_weights(t)[:,None]
 return deform_d(t,opening)+(1-weights)*delta+weights*(delta@rotation.T)

def run(out):
 out=Path(out)
 if not json.loads((out/'qualification.json').read_text())['passed']:raise ValueError('sealed jaw qualification required')
 envelope=json.loads((out/'envelope.json').read_text())['envelope']
 rows=[]
 for name,p in IDENTITIES.items():
  t=build(**p)
  for opening in (0.,1.):
   for mode in ('smile','compression','protrusion','asymmetry'):
    for value in (.25,.5,.75,1.):
     v=articulated_expression(t,opening,**{mode:value})
     c=validate(t,v);m=metrics(v,t['vertices'],t['triangles']);w=wall(t,v)
     strain=(m['edge_min']>=envelope['edge_min'] and m['edge_max']<=envelope['edge_max'] and m['area_min']>=envelope['area_min'] and m['area_max']<=envelope['area_max'] and m['local_concentration']<=envelope['concentration_max'])
     r=dict(strain_pass=strain,identity=name,opening=opening,mode=mode,coefficient=value,contact=c,geometry=m,wall=w);rows.append(r)
     (out/'expression-results.json').write_text(json.dumps(rows,separators=(',',':')))
     if not c['pass'] or not strain or w['global']['metres']<=.001:
      (out/'expression-summary.json').write_text(json.dumps(dict(passed=False,first_failure=r,classification='CONTACT/SEPARATION' if not c['pass'] or w['global']['metres']<=.001 else 'STRAIN'),indent=2));print('EXPRESSION FAIL',name,opening,mode,value,flush=True);return
  print('expression',name,'done',flush=True)
 (out/'expression-summary.json').write_text(json.dumps(dict(passed=True,cases=len(rows),scope='standalone engineering; uses frozen jaw envelope conservatively',full_admission=False),indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
