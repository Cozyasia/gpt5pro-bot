"""Two explicit jaw candidates on one shared diagnostic assembly.

Both are blocked by pre-existing neutral contacts. No production or training use.
Units metres, y down, z away from camera. Jaw hinge is approximate, not fitted.
"""
import numpy as np
from experiments.v265_anatomy.generator import template,identity,express

def assembly():
 t=template();teeth=np.flatnonzero(t['semantic']==6);lookup=np.full(len(t['vertices']),-1);lookup[teeth]=np.arange(len(teeth))+len(t['vertices'])
 dental=np.flatnonzero(np.isin(t['triangles'],teeth).all(1));offset=np.array([0,.013,0])
 t['triangles']=np.concatenate([t['triangles'],lookup[t['triangles'][dental]].astype(int)])
 t['vertices']=np.concatenate([t['vertices'],t['vertices'][teeth]+offset])
 t['uv']=np.concatenate([t['uv'],(t['vertices'][len(t['uv']):,:2]/[.075,.105])])
 t['semantic']=np.concatenate([t['semantic'],np.full(len(teeth),6)])
 t['object']=np.concatenate([t['object'],np.full(len(teeth),20)])
 t['upper_teeth']=teeth;t['lower_teeth']=lookup[teeth].astype(int)
 return t

def smooth(a):
 a=np.clip(a,0,1);return a*a*(3-2*a)

def jaw_weights(t,candidate):
 x,y=t['uv'].T;w=smooth((y-.25)/.45);mouth=t['parts']['mouth'];loops=np.array(mouth).reshape(5,-1)
 # All depth rings share material ownership from outer ring (not contracted UV).
 material=t['uv'][loops[0]];phase=(material[:,1]-.43)/(.075*.9)
 if candidate=='A': mw=smooth((phase+.15)/.30)
 elif candidate=='B':mw=smooth((phase+1)/2)
 else:raise ValueError('only A/B')
 for loop in loops:w[loop]=mw
 w[t['object']==1]=0;w[t['object']==2]=0
 w[t['upper_teeth']]=0;w[t['lower_teeth']]=1
 return w

def articulate(t,neutral,e,candidate='A'):
 e=np.asarray(e,float)
 if e.shape!=(8,) or not np.isfinite(e).all() or not 0<=e[1]<=1:raise ValueError('invalid expression')
 if not np.any(e):return neutral.copy()
 hinge=np.array([0,-.015,.035]);angle=-np.deg2rad(22)*e[1];c,s=np.cos(angle),np.sin(angle)
 rotation=np.array([[1,0,0],[0,c,-s],[0,s,c]])
 moved=(neutral-hinge)@rotation.T+hinge
 w=jaw_weights(t,candidate);v=neutral+(moved-neutral)*w[:,None]
 # Soft modes after jaw; teeth remain rigid, not soft-skin owned.
 soft=e.copy();soft[1]=0
 delta=express(t,neutral,soft)-neutral;delta[t['semantic']==6]=0
 return v+delta
