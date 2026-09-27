import json,hashlib,time,argparse
from pathlib import Path
import numpy as np
from experiments.v265_mouth.component import build,jaw_only,IDENTITIES
from experiments.v265_mouth.validate import validate,clearance
from .candidates import deform_d,deform_c,anchor_weights

def metrics(v,n,tri):
 edges=np.unique(np.sort(np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]]),axis=1),axis=0)
 le=np.linalg.norm(v[edges[:,1]]-v[edges[:,0]],axis=1);ln=np.linalg.norm(n[edges[:,1]]-n[edges[:,0]],axis=1);stretch=le/ln
 p=v[tri];b=n[tri];ar=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/np.linalg.norm(np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0]),axis=1)
 ids=np.flatnonzero(np.isin(tri,[192,193]).any(1));local=np.unique(tri[ids]);mask=np.isin(edges,local).all(1)
 return dict(edge_min=float(stretch.min()),edge_max=float(stretch.max()),worst_edge=edges[stretch.argmax()].tolist(),area_min=float(ar.min()),area_max=float(ar.max()),local_concentration=float(stretch[mask].max()/np.median(stretch[mask])))

def wall(t,v):
 tri=t['triangles'];cent=t['vertices'][tri].mean(1);n=64
 # Complete disjoint outer vermilion and inner-wall triangle bands, including corners.
 outer=np.arange(2*n,4*n);inner=np.arange(6*n,8*n);r={}
 for name,pred in [('left',lambda x:x[:,0]<-.75*t['params']['width']),('right',lambda x:x[:,0]>.75*t['params']['width']),('upper',lambda x:(abs(x[:,0])<=.75*t['params']['width'])&(x[:,1]<0)),('lower',lambda x:(abs(x[:,0])<=.75*t['params']['width'])&(x[:,1]>=0))]:
  a=outer[pred(cent[outer])];b=inner[pred(cent[inner])];r[name]=clearance(v,tri,a,b)
 r['global']=clearance(v,tri,outer,inner);return r

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);t=build(width=.018);n=t['vertices'];tr=t['triangles'];ids=np.flatnonzero(np.isin(tr,[192,193]).any(1));old=[]
 for opening in np.linspace(0,1,21):
  v=jaw_only(t,float(opening));a=n[193]-n[192];b=v[193]-v[192]
  old.append(dict(opening=float(opening),neutral_length_m=float(np.linalg.norm(a)),length_m=float(np.linalg.norm(b)),angle_degrees=float(np.rad2deg(np.arccos(np.clip(a@b/np.linalg.norm(a)/np.linalg.norm(b),-1,1)))),trajectories=v[[192,193]].tolist(),metrics=metrics(v,n,tr)))
 fixture=dict(version=t['version'],vertices_hash=hashlib.sha256(n.tobytes()).hexdigest(),topology_hash=hashlib.sha256(tr.tobytes()).hexdigest(),vertices=len(n),triangles=len(tr),edge=[192,193],region='right inner-lip commissure, ring3 theta0→theta2pi/64',weights=t['weights'][[192,193]].tolist(),neighbors=tr[ids].tolist(),old_sweep=old)
 (out/'fixture.json').write_text(json.dumps(fixture,indent=2));rows=[];start=time.monotonic()
 c,cn,ct=deform_c(t,1);(out/'candidate-c.json').write_text(json.dumps(metrics(c,cn,ct),indent=2))
 for name,p in IDENTITIES.items():
  t=build(**p);n=t['vertices']
  for i in range(21):
   opening=i/20;v=deform_d(t,opening);r=validate(t,v);m=metrics(v,n,t['triangles']);walls=wall(t,v)
   rows.append(dict(identity=name,opening=opening,contact=r,geometry=m,wall_separation=walls))
   (out/'d-results.json').write_text(json.dumps(rows,separators=(',',':')))
   if not r['pass']:print('CONTACT FAIL',name,opening,flush=True);break
  print(name,'done',flush=True)
 summary=dict(cases=len(rows),contact_pass=all(r['contact']['pass'] for r in rows),max_edge=max(r['geometry']['edge_max'] for r in rows),min_edge=min(r['geometry']['edge_min'] for r in rows),max_area=max(r['geometry']['area_max'] for r in rows),min_area=min(r['geometry']['area_min'] for r in rows),max_local_concentration=max(r['geometry']['local_concentration'] for r in rows),min_wall_m=min(r['wall_separation']['global']['metres'] for r in rows),min_teeth_clearance_m=min(r['contact']['teeth_oral_clearance']['metres'] for r in rows),seconds=time.monotonic()-start,jaw_admitted=False,reason='independent benign calibration, broader identity coverage and attachment not qualified')
 (out/'summary.json').write_text(json.dumps(summary,indent=2));print(summary)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
