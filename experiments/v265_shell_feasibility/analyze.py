"""Directional samples on frozen exterior. Bounds are not a continuous proof."""
import json,argparse,hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from experiments.v265_lid_material.neutral import construct
from experiments.v265_retained.surface import build
from experiments.v265_mouth.validate import point_triangle

def ray(p,d,v,tr,exclude):
 ids=np.flatnonzero(~np.isin(tr,exclude).any(1));q=v[tr[ids]];e1=q[:,1]-q[:,0];e2=q[:,2]-q[:,0];h=np.cross(d,e2);det=(e1*h).sum(1);valid=abs(det)>1e-15;inv=np.divide(1.,det,out=np.zeros_like(det),where=valid);s=p-q[:,0];u=(s*h).sum(1)*inv;c=np.cross(s,e1);w=(c*d).sum(1)*inv;t=(c*e2).sum(1)*inv;ok=valid&(u>=-1e-9)&(w>=-1e-9)&(u+w<=1+1e-9)&(t>1e-10)
 if not ok.any():return None
 j=np.flatnonzero(ok)[np.argmin(t[ok])];return dict(metres=float(t[j]),triangle=int(ids[j]))

def fields():
 base=build();v=base['vertices'];tr=base['triangles'];shell=construct();p=v[tr];normal=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);vn=np.zeros_like(v)
 for k in range(3):np.add.at(vn,tr[:,k],normal)
 vn/=np.maximum(np.linalg.norm(vn,axis=1)[:,None],1e-30)
 exterior_ids=np.flatnonzero(~(base['labels'][tr]=='eyeball').any(1));globe_ids=np.flatnonzero((base['labels'][tr]=='eyeball').all(1))
 rows=[]
 for domain in shell['domains']:
  outer=np.array(domain['outer_vertices']);side=domain['side'];cx=-.029 if side=='left' else .029
  for index,i in enumerate(outer):
   d=vn[i].copy()
   # One consistent winding normal, not per-vertex sign toggling.
   near=np.unique(tr[np.isin(tr,i).any(1)]);edge=near[near!=i];le=np.linalg.norm(v[edge]-v[i],axis=1);change=np.linalg.norm(vn[edge]-d,axis=1);curvature=float(np.min(np.divide(le,change,out=np.full_like(le,np.inf),where=change>1e-8)))
   normal_hit=ray(v[i],d,v,tr[exterior_ids],[i]);posterior_hit=ray(v[i],np.array([0.,0.,1.]),v,tr[exterior_ids],[i]);globe_hit=ray(v[i],d,v,tr[globe_ids],[])
   for hit,indices in ((normal_hit,exterior_ids),(posterior_hit,exterior_ids),(globe_hit,globe_ids)):
    if hit:hit['triangle']=int(indices[hit['triangle']])
   gt=v[tr[globe_ids]];gd=point_triangle(np.broadcast_to(v[i],(len(gt),3)),gt);j=int(gd.argmin());globe_distance=dict(metres=float(gd[j]),triangle=int(globe_ids[j]))
   constraints=[curvature*.25,globe_distance['metres']*.5]
   if normal_hit:constraints.append(normal_hit['metres']*.5)
   rows.append(dict(vertex=int(i),side=side,upper_lower='upper' if v[i,1]<-.026 else 'lower',zone='canthus' if abs(v[i,0]-cx)>.008 else 'central',band=int(index//(len(outer)//4)),position=v[i].tolist(),inward_normal=d.tolist(),normal_hit=normal_hit,posterior_hit=posterior_hit,globe_ray_hit=globe_hit,exterior_sample_globe_distance=globe_distance,normal_consistency_length_m=curvature,conservative_sample_depth_m=float(min(constraints))))
 return base,rows

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);base,rows=fields();depth=np.array([r['conservative_sample_depth_m'] for r in rows]);summary=dict(samples=len(rows),depth_quantiles_m=np.quantile(depth,[0,.05,.5,1]).tolist(),minimum_witness=rows[int(depth.argmin())],scope='Vertex rays and discrete normal-consistency bound; no global impossibility or continuous collision-free proof',exterior_sha256=hashlib.sha256(base['vertices'].tobytes()).hexdigest())
 (out/'fields.json').write_text(json.dumps(rows,indent=2));(out/'feasibility.json').write_text(json.dumps(summary,indent=2));print(summary)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
