"""Retained-surface gate. A scientific rejection never permits attachment/training."""
import argparse,json,hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from experiments.v265_articulation.contact import intersections
from .surface import build
from experiments.v265_mouth.validate import clearance

def coplanar_overlap(v,tr,pair):
 # Exact convex 2-D separating-axis test after dominant-axis projection.
 # Shared-edge/point contact has zero area, not forbidden penetration.
 p=v[tr[pair]];normal=np.cross(p[0,1]-p[0,0],p[0,2]-p[0,0]);axis=int(abs(normal).argmax());q=np.delete(p,axis,axis=2)
 for triangle in q:
  for a,b in zip(triangle,np.roll(triangle,-1,axis=0)):
   edge=b-a;direction=np.array([-edge[1],edge[0]]);direction/=np.linalg.norm(direction)
   projection=q@direction
   if min(projection[0].max(),projection[1].max())-max(projection[0].min(),projection[1].min())<=1e-10:return False
 return True

def validate(t):
 v=t['vertices'];tr=t['triangles'];p=v[tr];edges=np.concatenate([tr[:,[0,1]],tr[:,[1,2]],tr[:,[2,0]]]);_,inv,count=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True);w=np.bincount(inv,weights=np.where(edges[:,0]<edges[:,1],1,-1));contact=intersections(v,tr)
 flat=[p for p in contact['unresolved_coplanar_pairs'] if coplanar_overlap(v,tr,p)]
 pairs=contact['proper_intersection_pairs'];categories=Counter(' / '.join(sorted((t['labels'][tr[a,0]],t['labels'][tr[b,0]]))) for a,b in pairs)
 result=dict(vertices=len(v),triangles=len(tr),intersections=len(pairs),categories=dict(categories),pairs=pairs,coplanar_aabb_candidates=len(contact['unresolved_coplanar_pairs']),unresolved_coplanar=len(flat),coplanar_overlap_pairs=flat,nonmanifold=int((count>2).sum()),winding=int(((count==2)&(w!=0)).sum()),degenerate=int((np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)<2e-12).sum()),duplicate_faces=len(tr)-len(np.unique(np.sort(tr,axis=1),axis=0)))
 result['structural_pass']=not any(result[k] for k in ('intersections','unresolved_coplanar','nonmanifold','winding','degenerate','duplicate_faces'))
 result['full_admission']=False # Contact distances and all identities must independently qualify.
 return result

def eye_clearance(t):
 v=t['vertices'];tr=t['triangles'];labels=t['labels'][tr];result={}
 for side in (-1,1):
  mask=side*v[tr].mean(1)[:,0]>0
  eye=np.flatnonzero((labels=='eyeball').all(1)&mask)
  lid=np.flatnonzero((labels=='eyelid').any(1)&mask)
  result[str(side)]=clearance(v,tr,eye,lid)
 return result

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);rows=[]
 for blink,squint in [(0,0),(.25,0),(.5,0),(.75,0),(1,0),(0,1),(.5,1),(1,1)]:
  t=build(blink,squint);r=validate(t);r['eye_clearance']=eye_clearance(t);r['eye_contact_pass']=all(x['metres']>=.0001 for x in r['eye_clearance'].values());rows.append(dict(blink=blink,squint=squint,**r));print(blink,squint,{k:v for k,v in r.items() if k not in ('pairs',)},flush=True)
  (out/'retained.json').write_text(json.dumps(rows,indent=2))
  if not r['structural_pass'] or not r['eye_contact_pass']:break
 (out/'summary.json').write_text(json.dumps(dict(retained_neutral=rows[0]['structural_pass'],tested_states=len(rows),structural_pass=all(r['structural_pass'] for r in rows),contact_policy_qualified=all(r['eye_contact_pass'] for r in rows) and len(rows)==8,attachment='NOT_RUN',training='FORBIDDEN'),indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
