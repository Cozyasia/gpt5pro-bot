"""Nested analytic annuli enclosing an oral cavity, metres in local mouth frame.

x horizontal, y inferior, z posterior. Outer rim is intentional integration boundary.
Teeth are independent closed boxes in maxilla/mandible frames. No asset imports.
"""
import numpy as np

VERSION='mouth-annular-v1'
IDENTITIES={
 'mean':{},'narrow':{'width':.018},'wide':{'width':.031},
 'thin':{'upper':.0015,'lower':.0018},'thick':{'upper':.0045,'lower':.005},
 'short_philtrum':{'philtrum':.009},'long_philtrum':{'philtrum':.020},
 'narrow_jaw':{'jaw':.030},'wide_jaw':{'jaw':.050},
 'asymmetric':{'asymmetry':.08},
}

def build(width=.025,upper=.003,lower=.0035,philtrum=.014,jaw=.040,asymmetry=0.):
 if not (.018<=width<=.031 and .0015<=upper<=.0045 and .0018<=lower<=.005 and abs(asymmetry)<=.08):raise ValueError('outside construction domain')
 count=64;theta=np.arange(count)*2*np.pi/count;sn=np.sin(theta);cs=np.cos(theta)
 # Each cross-section is simple; successive strips occupy disjoint radial/depth bands.
 # A positive 0.4mm gap deliberately avoids ambiguous exact-contact triangles.
 lip=np.where(sn<0,upper,lower);gap=.0002
 specs=[(width+.010,np.where(sn<0,philtrum+.004,jaw*.45),0.,'face_transition'),
        (width+.004,lip+.003,-.002,'outer_vermilion'),
        (width,lip+gap,-.004,'vermilion'),
        (width-.001,np.full(count,gap),-.001,'inner_lip'),
        (width+.002,np.full(count,.009),.008,'cavity_wall'),
        (width+.005,np.full(count,.014),.023,'cavity_wall'),
        (width+.005,np.full(count,.014),.030,'cavity_back')]
 vertices=[];faces=[];labels=[];loops=[];weights=[]
 for rx,ry,z,label in specs:
  ids=np.arange(len(vertices),len(vertices)+count);loops.append(ids)
  p=np.stack([rx*cs,ry*sn*(1+asymmetry*cs),np.full(count,z)],1);vertices.extend(p)
  labels.extend([label]*count);weights.extend((.5+.5*sn).tolist())
 for a,b in zip(loops,loops[1:]):
  for i in range(count):
   j=(i+1)%count;faces.extend([[a[i],a[j],b[i]],[a[j],b[j],b[i]]])
 cap=len(vertices);vertices.append([0,0,.030]);labels.append('cavity_back');weights.append(.5)
 for i in range(count):faces.append([loops[-1][i],loops[-1][(i+1)%count],cap])
 teeth={'upper':[],'lower':[]}
 # Width scales with identity; dental height/depth separated from neutral lip slit.
 for side,cy in [('upper',-.0045),('lower',.0045)]:
  for cx in np.linspace(-width*.44,width*.44,6):
   halfx=width*.055;lo=np.array([cx-halfx,cy-.0015,.017]);hi=np.array([cx+halfx,cy+.0015,.020]);start=len(vertices)
   vertices.extend([[x,y,z] for z in [lo[2],hi[2]] for y in [lo[1],hi[1]] for x in [lo[0],hi[0]]]);labels.extend([side+'_teeth']*8);weights.extend([0 if side=='upper' else 1]*8);teeth[side].extend(range(start,start+8))
   for a,b,c in [(0,2,1),(1,2,3),(4,5,6),(5,7,6),(0,1,4),(1,5,4),(2,6,3),(3,6,7),(0,4,2),(2,4,6),(1,3,5),(3,7,5)]:faces.append([start+a,start+b,start+c])
 return dict(vertices=np.array(vertices,float),triangles=np.array(faces,int),labels=np.array(labels),loops=np.array(loops),weights=np.array(weights),teeth={k:np.array(v) for k,v in teeth.items()},frame=np.eye(3),origin=np.array([0,.04515,0]),hinge=np.array([0,-.060,.035]),params=dict(width=width,upper=upper,lower=lower,philtrum=philtrum,jaw=jaw,asymmetry=asymmetry),version=VERSION)

def jaw_only(t,opening):
 if not 0<=opening<=1:raise ValueError('opening outside benign specification')
 n=t['vertices']
 if opening==0:return n.copy()
 a=np.deg2rad(22)*opening;c,s=np.cos(a),np.sin(a);r=np.array([[1,0,0],[0,c,-s],[0,s,c]])
 moved=(n-t['hinge'])@r.T+t['hinge'];return n+(moved-n)*t['weights'][:,None]

def expression(t,opening=0.,smile=0.,compression=0.,protrusion=0.,asymmetry=0.):
 values=np.array([smile,compression,protrusion,asymmetry])
 if not np.isfinite(values).all() or (abs(values)>1).any():raise ValueError('expression outside specification')
 v=jaw_only(t,opening);skin=~np.char.endswith(t['labels'],'teeth');n=t['vertices'];x=n[:,0]/t['params']['width'];z=n[:,2];falloff=np.exp(-(z/.02)**4)
 # Local-frame soft modes; no semantic cliff between lip and cavity surfaces.
 v[skin,1]-=.002*smile*x[skin]**2*falloff[skin]
 v[skin,1]*=np.exp(-.2*compression*np.exp(-(z[skin]/.01)**2))
 v[skin,2]-=.003*protrusion*np.exp(-x[skin]**4)*falloff[skin]
 v[skin,1]+=.0015*asymmetry*x[skin]*falloff[skin]
 return v
