"""Two local closure controls. Neutral coordinates/topology are immutable.
No lid thickness is invented: frozen insertion is a single-sheet surface.
"""
import numpy as np
from experiments.v265_retained.surface import build
from experiments.v265_anatomy.generator import boundary_loops

def eyes(t):
 for loop in boundary_loops(t['triangles']):
  if (t['labels'][loop]=='eyelid').all():
   # Each insertion has three consecutive rings, with the boundary last.
   last=np.sort(loop);n=len(last);rings=np.stack([last-2*n,last-n,last])
   yield rings

def curve(t,ring,x,upper_share=.65):
 p=t['vertices'][ring];cy=-.026
 def side(upper):
  q=p[p[:,1]<cy] if upper else p[p[:,1]>=cy];order=np.argsort(q[:,0]);q=q[order];return np.interp(x,q[:,0],q[:,1])
 y=(1-upper_share)*side(True)+upper_share*side(False)
 # Taper at canthi so corners stay at their original identity-owned positions.
 lo,hi=p[:,0].min(),p[:,0].max();u=np.clip((x-lo)/(hi-lo),0,1)
 left=p[p[:,0].argmin(),1];right=p[p[:,0].argmax(),1]
 baseline=left+(right-left)*u
 return baseline+4*u*(1-u)*(y-baseline)

def deform(candidate,blink):
 if candidate not in ('E','F') or not 0<=blink<=1:raise ValueError('invalid closure control')
 t=build();n=t['vertices'];v=n.copy()
 if blink==0:return t
 for rings in eyes(t):
  cx=float(np.sign(n[rings[-1],0].mean())*.029);cy=-.026;cz=.002
  for level,ring in enumerate(rings):
   weight=(level+1)/3;target=curve(t,rings[-1],n[ring,0]);y=n[ring,1]+blink*weight*(target-n[ring,1])
   v[ring,1]=y
   if candidate=='F':
    # Corotated yz arc about globe centre: preserve radial support distance.
    radius2=(n[ring,1]-cy)**2+(n[ring,2]-cz)**2
    v[ring,2]=cz-np.sqrt(np.maximum(0,radius2-(y-cy)**2))
   else:
    # Both margins share one analytic globe-offset closure depth.
    rr=((n[ring,0]-cx)/.012)**2+((target-cy)/.007)**2
    z=cz-.007*np.sqrt(np.maximum(0,1-rr))-.0008
    v[ring,2]=n[ring,2]+blink*weight*(z-n[ring,2])
 t['vertices']=v;return t
