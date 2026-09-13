"""Rejected loop-coordinate reconstruction; not a third articulation candidate."""
import json
import numpy as np
from .mechanics import assembly
from .contact import intersections
from experiments.v265_anatomy.generator import identity,lineage

def run():
 t=assembly();loops=np.array(t['parts']['mouth']).reshape(5,-1);q=t['uv'][loops[0]]
 angle=np.unwrap(np.arctan2((q[:,1]-.43)/.075,q[:,0]/.34));sgn=np.sign(np.median(np.diff(angle)));theta=angle[0]+sgn*np.arange(len(q))*2*np.pi/len(q)
 for ids,sx,ry,z in zip(loops,[.95,.88,.80,.95,1.1],[.006,.004,.0005,.010,.022],[-.010,-.012,-.007,.008,.035]):
  t['vertices'][ids]=np.stack([.0255*sx*np.cos(theta),.04515+ry*np.sin(theta),np.full(len(ids),z)],1)
  t['uv'][ids]=t['vertices'][ids,:2]/[.075,.105]
 tri=t['triangles'];cap=set(tri[np.isin(tri,loops[-1]).sum(1)==2].ravel())-set(loops.ravel())
 for v in cap:
  if t['semantic'][v]==5:t['vertices'][v]=[0,.04515,.035]
 t['vertices'][t['upper_teeth'],2]+=.010;t['vertices'][t['lower_teeth'],2]+=.020
 n=identity(t,lineage()[417]['factors']);ids=np.flatnonzero(np.isin(t['semantic'][tri],[3,4,5,6]).any(1));r=intersections(n,tri,ids)
 return dict(identity=417,selected=False,contacts=r,reason='coordinate-only loop rebuild still intersects; joined surface construction required')
if __name__=='__main__':print(json.dumps(run(),indent=2))
