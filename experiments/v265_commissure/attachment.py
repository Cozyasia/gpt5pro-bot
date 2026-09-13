"""Local face attachment prototype, gated by standalone expression admission.

Deletes only the old mouth and a surrounding aperture, then zips the new rim.
This is diagnostic until seam/contact tests pass. No training entrypoint.
"""
import json,argparse
from pathlib import Path
import numpy as np
from experiments.v265_anatomy.generator import template,boundary_loops
from experiments.v265_mouth.component import build
from experiments.v265_articulation.contact import intersections

def construct():
 face=template();mouth=build();v=face['vertices'];tr=face['triangles'];c=v[tr].mean(1)
 # Analytic surgical aperture around NEW outer rim; preserve remaining anatomy.
 inside=(c[:,0]/.040)**2+((c[:,1]-.04515)/.026)**2<1
 oldmouth=np.isin(face['semantic'][tr],[3,4,5,6]).any(1)
 kept=tr[~inside&~oldmouth];cycles=boundary_loops(kept)
 ring=min(cycles,key=lambda q:np.linalg.norm(v[q].mean(0)-[0,.04515,-.009]))
 newv=mouth['vertices']+mouth['origin'];rim=mouth['loops'][0]
 # Sort projected boundary angles; bridge cycles without changing old neutral vertices.
 a=np.argsort(np.mod(np.arctan2(v[ring,1]-.04515,v[ring,0]),2*np.pi));ring=ring[a]
 b=np.argsort(np.mod(np.arctan2(newv[rim,1]-.04515,newv[rim,0]),2*np.pi));rim=rim[b]+len(v)
 faces=[];i=j=0
 while i<len(ring) or j<len(rim):
  if j==len(rim) or (i<len(ring) and (i+1)/len(ring)<=(j+1)/len(rim)):
   faces.append([ring[i%len(ring)],ring[(i+1)%len(ring)],rim[j%len(rim)]]);i+=1
  else:faces.append([ring[i%len(ring)],rim[(j+1)%len(rim)],rim[j%len(rim)]]);j+=1
 combined=np.concatenate([kept,mouth['triangles']+len(v),np.array(faces)])
 return np.concatenate([v,newv]),combined,len(faces)

def run(out):
 out=Path(out)
 if not json.loads((out/'expression-summary.json').read_text())['passed']:raise ValueError('expression admission required')
 try:
  v,tr,seams=construct();c=intersections(v,tr);e=np.concatenate([tr[:,[0,1]],tr[:,[1,2]],tr[:,[2,0]]]);_,inv,count=np.unique(np.sort(e,axis=1),axis=0,return_inverse=True,return_counts=True);w=np.bincount(inv,weights=np.where(e[:,0]<e[:,1],1,-1))
  r=dict(seam_triangles=seams,proper_intersections=len(c['proper_intersection_pairs']),pairs=c['proper_intersection_pairs'],unresolved_coplanar=len(c['unresolved_coplanar_pairs']),nonmanifold_edges=int((count>2).sum()),inconsistent_winding=int(((count==2)&(w!=0)).sum()),attachment_admitted=False,full_anatomy_admitted=False,reason='diagnostic seam; jaw/expression propagation through retained face not qualified')
 except ValueError as exc:r=dict(attachment_admitted=False,full_anatomy_admitted=False,error=str(exc))
 (out/'attachment.json').write_text(json.dumps(r,indent=2));print({k:v for k,v in r.items() if k!='pairs'})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
