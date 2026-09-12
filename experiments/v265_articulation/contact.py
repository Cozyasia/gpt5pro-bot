"""Non-adjacent surface intersection witnesses; no culling.

Moller-Trumbore segment/triangle tests. Coplanar AABB candidates are
reported separately as unresolved (fail-closed), never counted as clear.
"""
import numpy as np

def pierces(a,b,tri,eps=1e-10):
 d=b-a;e1=tri[:,1]-tri[:,0];e2=tri[:,2]-tri[:,0];h=np.cross(d,e2);det=(e1*h).sum(1)
 valid=abs(det)>1e-15; inv=np.divide(1.,det,out=np.zeros_like(det),where=valid)
 s=a-tri[:,0];u=inv*(s*h).sum(1);q=np.cross(s,e1);v=inv*(d*q).sum(1);t=inv*(e2*q).sum(1)
 return valid&(u>eps)&(v>eps)&(u+v<1-eps)&(t>eps)&(t<1-eps)

def intersections(vertices,triangles,selected=None):
 ids=np.arange(len(triangles)) if selected is None else np.asarray(selected)
 tr=triangles[ids];p=vertices[tr];lo=p.min(1);hi=p.max(1);hits=[];coplanar=[]
 for i in range(len(ids)):
  candidates=np.flatnonzero((np.arange(len(ids))>i)&(lo<=hi[i]+1e-10).all(1)&(hi>=lo[i]-1e-10).all(1))
  candidates=candidates[~np.isin(tr[candidates],tr[i]).any(1)]
  if not len(candidates):continue
  q=p[candidates];hit=np.zeros(len(q),bool)
  for a,b in ((0,1),(1,2),(2,0)):
   hit|=pierces(np.broadcast_to(p[i,a],(len(q),3)),np.broadcast_to(p[i,b],(len(q),3)),q)
   hit|=pierces(q[:,a],q[:,b],np.broadcast_to(p[i],q.shape))
  for j in candidates[hit]:hits.append([int(ids[i]),int(ids[j])])
  normal=np.cross(p[i,1]-p[i,0],p[i,2]-p[i,0]);normal/=max(np.linalg.norm(normal),1e-30)
  flat=(abs((q-p[i,0])@normal)<1e-9).all(1)
  for j in candidates[flat]:coplanar.append([int(ids[i]),int(ids[j])])
 return dict(proper_intersection_pairs=hits,unresolved_coplanar_pairs=coplanar,complete_contact_clearance=False)
