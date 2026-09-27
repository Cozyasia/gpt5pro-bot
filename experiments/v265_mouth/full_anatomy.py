"""Check retained anatomy before training; never substitute local mouth PASS."""
import json,argparse
from pathlib import Path
import numpy as np
from experiments.v265_anatomy.generator import template,identity,lineage,express,accessory
from experiments.v265_articulation.contact import intersections

def run(out):
 out=Path(out)
 if not json.loads((out/'expression-summary.json').read_text())['passed']:raise ValueError('mouth expression admission required')
 t=template();tri=t['triangles'];rows=lineage();results=[]
 for idx in (416,417,428,443):
  neutral=identity(t,rows[idx]['factors'])
  for name,classes in [('eyes',[1,2]),('nostrils',[7,8])]:
   selected=np.flatnonzero(np.isin(t['semantic'][tri],classes).any(1))
   for blink in ([0,.5,1] if name=='eyes' else [0]):
    e=np.zeros(8);e[6]=blink;v=express(t,neutral,e);ct=intersections(v,tri,selected)
    results.append(dict(identity=idx,region=name,blink=blink,proper_intersections=len(ct['proper_intersection_pairs']),pairs=ct['proper_intersection_pairs'],unresolved_coplanar=len(ct['unresolved_coplanar_pairs'])))
 r=dict(retained_anatomy=results,mouth_face_boundary_joined=False,accessory_contact_validated=False,full_anatomy_admission=False,training_allowed=False,reason='local mouth component has one intentional outer rim; not stitched into retained face. Retained anatomy contacts require separate qualification.')
 (out/'full-anatomy.json').write_text(json.dumps(r,indent=2));print([(x['identity'],x['region'],x['blink'],x['proper_intersections']) for x in results])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
