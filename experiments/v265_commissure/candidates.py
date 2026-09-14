import numpy as np
from experiments.v265_mouth.component import jaw_only

def anchor_weights(t):
 """D: half-weight corner anchor; distribute ownership by material arc length.

Each upper-centre -> commissure -> lower-centre arc has the same endpoints.
Weight gradients are defined per metre of neutral inner-lip material, not angle.
"""
 ring=t['loops'][3];p=t['vertices'][ring];n=len(ring);w=np.zeros(n)
 for ids in [np.arange(3*n//4,5*n//4+1)%n,np.arange(3*n//4,n//4-1,-1)]:
  arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p[ids],axis=0),axis=1))]
  w[ids]=arc/arc[-1]
 result=t['weights'].copy()
 for loop in t['loops']:
  depth=np.clip(t['vertices'][loop,2]/.023,0,1);blend=1-depth*depth*(3-2*depth)
  result[loop]=blend*w+(1-blend)*t['weights'][loop]
 return result

def deform_d(t,opening):
 q=dict(t);q['weights']=anchor_weights(t);return jaw_only(q,opening)

def fan(t):
 """C: local barycentric fan redistribution, no neutral shape modification."""
 n=t['vertices'];tri=t['triangles'];cent=n[tri].mean(1);width=t['params']['width']
 selected=(abs(cent[:,0])>.75*width)&(abs(cent[:,1])<.006)&(cent[:,2]<.009)
 v=list(n);faces=[];parents=[]
 for i,face in enumerate(tri):
  if selected[i]:
   c=len(v);v.append(n[face].mean(0));parents.append(face)
   for j in range(3):faces.append([face[j],face[(j+1)%3],c])
  else:faces.append(face.tolist())
 return np.array(v),np.array(faces),np.array(parents)

def deform_c(t,opening):
 v,tri,parents=fan(t);base=jaw_only(t,opening)
 return np.concatenate([base,base[parents].mean(1)]),v,tri
