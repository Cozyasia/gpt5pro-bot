"""Finite lid sleeve: frozen exterior, posterior inner sheet, sewn lid margin.
Orbital inner rim is an explicit attachment boundary; no triple-edge cap.
"""
import numpy as np
from experiments.v265_retained.surface import build
from experiments.v265_anatomy.generator import boundary_loops

def construct(thickness=.0001):
 if thickness<=0:raise ValueError('positive thickness required')
 t=build();n=t['vertices'];tr=t['triangles'];v=n.tolist();faces=tr.tolist();labels=t['labels'].tolist();domains=[]
 for margin in boundary_loops(tr):
  if not (t['labels'][margin]=='eyelid').all():continue
  side='left' if n[margin,0].mean()<0 else 'right';sign=-1 if side=='left' else 1
  selected=np.flatnonzero((t['labels'][tr]=='eyelid').any(1)&(sign*n[tr].mean(1)[:,0]>0));outer=np.unique(tr[selected]);inner=np.arange(len(v),len(v)+len(outer));mapping=dict(zip(outer.tolist(),inner.tolist()))
  p=n[outer].copy();p[:,2]+=thickness;v.extend(p);labels.extend(['inner_eyelid']*len(p));innerfaces=np.array([[mapping[int(i)] for i in f[::-1]] for f in tr[selected]]);faces.extend(innerfaces.tolist())
  directed=set(map(tuple,np.concatenate([tr[selected][:,[0,1]],tr[selected][:,[1,2]],tr[selected][:,[2,0]]]).tolist()))
  for a,b in zip(margin,np.roll(margin,-1)):
   if (int(a),int(b)) not in directed:a,b=b,a
   faces.extend([[int(b),int(a),mapping[int(a)]],[int(b),mapping[int(a)],mapping[int(b)]]])
  # Correspondence follows the material boundary paths between identity-owned canthi.
  left=int(np.argmin(n[margin,0]));right=int(np.argmax(n[margin,0]));paths=[]
  for direction in (1,-1):
   ids=[left];i=left
   while i!=right:i=(i+direction)%len(margin);ids.append(i)
   path=margin[ids];arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(n[path],axis=0),axis=1))];u=arc/arc[-1]
   paths.append(dict(role='upper' if n[path,1].mean()<-.026 else 'lower',outer=path.tolist(),inner=[mapping[int(i)] for i in path],material_u=u.tolist()))
  domains.append(dict(side=side,outer_vertices=outer.tolist(),inner_vertices=inner.tolist(),outer_triangles=selected.tolist(),inner_triangles=innerfaces.tolist(),margin_paths=paths,canthi=margin[[left,right]].tolist(),nominal_posterior_thickness_m=thickness))
 return dict(vertices=np.array(v),triangles=np.array(faces),labels=np.array(labels),domains=domains,original_vertex_count=len(n),exterior_reference=n)
