import argparse,json
from pathlib import Path
import numpy as np
from .neutral import construct
from experiments.v265_retained.admission import validate
from experiments.v265_retained.surface import build
from experiments.v265_mouth.validate import clearance

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);t=construct();r=validate(t);tr=t['triangles'];v=t['vertices'];rows=[];base=build();bt=base['triangles']
 for d in t['domains']:
  side=-1 if d['side']=='left' else 1;eye=np.flatnonzero((t['labels'][tr]=='eyeball').all(1)&(side*v[tr].mean(1)[:,0]>0));lid=np.flatnonzero(np.isin(t['labels'][tr],['eyelid','inner_eyelid']).any(1)&(side*v[tr].mean(1)[:,0]>0))
  oldeye=np.flatnonzero((base['labels'][bt]=='eyeball').all(1)&(side*base['vertices'][bt].mean(1)[:,0]>0));oldlid=np.flatnonzero((base['labels'][bt]=='eyelid').any(1)&(side*base['vertices'][bt].mean(1)[:,0]>0))
  start=len(base['triangles']);lookup={tuple(f):i for i,f in enumerate(tr)};inner=np.array([lookup[tuple(f)] for f in d['inner_triangles']]);wall=clearance(v,tr,np.array(d['outer_triangles']),inner)
  rows.append(dict(side=d['side'],wall_surface_min=wall,globe_clearance=clearance(v,tr,eye,lid),baseline_globe_clearance=clearance(base['vertices'],bt,oldeye,oldlid)))
 r['material_domains']=t['domains'];r['thickness_measurement_status']='UNQUALIFIED if contacts exist; unsigned separation is not valid wall thickness';r['distances']=rows;r['exterior_max_deviation_m']=float(abs(v[:len(base['vertices'])]-base['vertices']).max());r['globe_envelope_preserved']=all(x['globe_clearance']['metres']>=x['baseline_globe_clearance']['metres']-1e-15 for x in rows);r['positive_unsigned_wall_distance']=all(x['wall_surface_min']['metres']>0 for x in rows);r['positive_wall']=r['positive_unsigned_wall_distance'] and r['structural_pass'];r['neutral_admitted']=r['structural_pass'] and r['globe_envelope_preserved'] and r['positive_wall'];r['blink']='NOT_RUN';r['seam']='NOT_RUN';r['training']='FORBIDDEN'
 (out/'neutral.json').write_text(json.dumps(r,indent=2));print({k:r[k] for k in ['intersections','unresolved_coplanar','nonmanifold','winding','degenerate','positive_wall','globe_envelope_preserved','exterior_max_deviation_m','neutral_admitted']});print(rows)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
