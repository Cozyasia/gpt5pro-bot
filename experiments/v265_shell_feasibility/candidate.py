"""Candidate G only: frozen normal field, independently frozen shell contract."""
import json,argparse,hashlib
from pathlib import Path
import numpy as np
from .analyze import fields
from experiments.v265_lid_material.neutral import construct
from experiments.v265_retained.surface import build
from experiments.v265_retained.admission import validate
from experiments.v265_mouth.validate import clearance

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);contract=json.loads(Path(__file__).with_name('contract.json').read_text());base,rows=fields()
 rejected=[r for r in rows if not r['direction_feasible']]
 if rejected:
  result=dict(candidate='G',construction='NOT_RUN_AFTER_DIRECTION_GATE',direction_failures=len(rejected),witnesses=rejected,neutral_admitted=False,blink='NOT_RUN',seam='NOT_RUN',training='FORBIDDEN')
  (out/'candidate-g.json').write_text(json.dumps(result,indent=2));print({'direction_failures':len(rejected),'construction':'NOT_RUN'});return
 normals={r['vertex']:np.array(r['inward_normal']) for r in rows};t=construct(contract['construction_depth_m']);v=t['vertices'];tr=t['triangles'];n=base['vertices'];bt=base['triangles']
 for d in t['domains']:
  v[d['inner_vertices']]=n[d['outer_vertices']]+contract['construction_depth_m']*np.array([normals[i] for i in d['outer_vertices']])
 r=validate(t);distances=[];lookup={tuple(f):i for i,f in enumerate(tr)}
 for d in t['domains']:
  side=-1 if d['side']=='left' else 1;eye=np.flatnonzero((t['labels'][tr]=='eyeball').all(1)&(side*v[tr].mean(1)[:,0]>0));outer=np.array(d['outer_triangles']);inner=np.array([lookup[tuple(f)] for f in d['inner_triangles']]);old_eye=np.flatnonzero((base['labels'][bt]=='eyeball').all(1)&(side*n[bt].mean(1)[:,0]>0))
  wall=clearance(v,tr,outer,inner);entry=dict(side=d['side'],outer_to_inner=wall,exterior_to_globe=clearance(v,tr,eye,outer),inner_to_globe=clearance(v,tr,eye,inner),frozen_exterior_to_globe=clearance(n,bt,old_eye,outer),regions={})
  for name,mask in [('upper',n[bt[outer]].mean(1)[:,1]<-.026),('lower',n[bt[outer]].mean(1)[:,1]>=-.026)]:entry['regions'][name]=clearance(v,tr,outer[mask],inner[mask])
  distances.append(entry)
 r.update(candidate='G',contract=contract,distances=distances,exterior_deviation_m=float(abs(v[:len(n)]-n).max()),exterior_preserved=all(abs(d['exterior_to_globe']['metres']-d['frozen_exterior_to_globe']['metres'])<1e-15 for d in distances),wall_threshold_pass=all(d['outer_to_inner']['metres']>=contract['thickness_min_m'] for d in distances),inner_globe_pass=all(d['inner_to_globe']['metres']>=contract['inner_globe_min_m'] for d in distances))
 r['neutral_admitted']=r['structural_pass'] and r['exterior_preserved'] and r['wall_threshold_pass'] and r['inner_globe_pass'];r['blink']='NOT_RUN';r['seam']='NOT_RUN';r['training']='FORBIDDEN';r['thickness_note']='Unsigned wall distances are invalid as thickness if crossings exist.'
 (out/'candidate-g.json').write_text(json.dumps(r,indent=2));print({k:r[k] for k in ['intersections','nonmanifold','winding','degenerate','exterior_deviation_m','exterior_preserved','wall_threshold_pass','inner_globe_pass','neutral_admitted']});print(distances)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
