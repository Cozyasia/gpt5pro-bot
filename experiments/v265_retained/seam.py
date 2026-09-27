"""Boundary-preserving neutral bridge; never modifies frozen mouth geometry."""
import argparse,json
from pathlib import Path
import numpy as np
from .surface import build
from .admission import validate
from experiments.v265_anatomy.generator import boundary_loops
from experiments.v265_mouth.component import build as mouth_build

def construct():
 t=build();v=t['vertices'];tr=t['triangles'];cent=v[tr].mean(1)
 remove=(cent[:,0]/.043)**2+((cent[:,1]-.04515)/.030)**2<1
 tr=tr[~remove];loops=boundary_loops(tr);ring=min(loops,key=lambda ids:np.linalg.norm(v[ids].mean(0)-[0,.04515,0]))
 # Keep the actual boundary traversal. Sorting boundary vertices destroys topology.
 xy=v[ring,:2]-[0,.04515]
 if np.sum(xy[:,0]*np.roll(xy[:,1],-1)-xy[:,1]*np.roll(xy[:,0],-1))<0:ring=ring[::-1]
 start=np.argmin(abs(np.arctan2(v[ring,1]-.04515,v[ring,0])));ring=np.roll(ring,-start)
 m=mouth_build();mv=m['vertices']+m['origin'];rim=m['loops'][0]+len(v)
 # Monotone arc-length zipper in both cyclic boundaries.
 def arc(p):
  l=np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1);return np.r_[0,np.cumsum(l)]/l.sum()
 a=arc(v[ring]);b=arc(mv[m['loops'][0]]);i=j=0;strip=[]
 while i<len(ring) or j<len(rim):
  if j==len(rim) or (i<len(ring) and a[i+1]<=b[j+1]):strip.append([ring[i%len(ring)],ring[(i+1)%len(ring)],rim[j%len(rim)]]);i+=1
  else:strip.append([ring[i%len(ring)],rim[(j+1)%len(rim)],rim[j%len(rim)]]);j+=1
 labels=np.concatenate([t['labels'],m['labels']]);joined=np.concatenate([tr,m['triangles']+len(v),np.array(strip)])
 return dict(vertices=np.concatenate([v,mv]),triangles=joined,labels=labels),dict(retained=len(tr),mouth=len(m['triangles']),seam=len(strip))

def run(out):
 out=Path(out);gate=json.loads((out/'summary.json').read_text())
 if not gate['structural_pass'] or not gate['contact_policy_qualified']:raise ValueError('retained admission required')
 t,ranges=construct();r=validate(t);n=ranges['retained'];end=n+ranges['mouth']
 def group(i):return 'retained' if i<n else 'mouth' if i<end else 'seam'
 from collections import Counter
 r['pair_categories']=dict(Counter('/'.join(sorted([group(a),group(b)])) for a,b in r['pairs']));r['ranges']=ranges;r['jaw_sweep']='NOT_RUN';r['full_admission']=False
 (out/'seam.json').write_text(json.dumps(r,indent=2));print({k:v for k,v in r.items() if k not in ('pairs',)})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
