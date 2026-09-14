"""Local eye/nose replacement; frozen mouth is deliberately absent.
Metres, x horizontal, y inferior, z posterior. Original algorithmic assets only.
"""
import numpy as np
from experiments.v265_anatomy.generator import template,boundary_loops

def build(blink=0.,squint=0.):
 if not 0<=blink<=1 or not 0<=squint<=1:raise ValueError('outside benign domain')
 old=template();allv=old['vertices'];tr=old['triangles'];keep=(old['semantic'][tr]==0).all(1);tr=tr[keep]
 used=np.unique(tr);remap=np.full(len(allv),-1);remap[used]=np.arange(len(used));tr=remap[tr];v=list(allv[used]);faces=tr.tolist();labels=['skin']*len(v)
 loops=boundary_loops(tr);directed=set(map(tuple,np.concatenate([tr[:,[0,1]],tr[:,[1,2]],tr[:,[2,0]]]).tolist()))
 def add(p,label):
  ids=np.arange(len(v),len(v)+len(p));v.extend(p);labels.extend([label]*len(p));return ids
 def join(a,b):
  for i in range(len(a)):
   j=(i+1)%len(a);faces.extend([[a[i],a[j],b[i]],[a[j],b[j],b[i]]])
 for loop in loops[1:]:
  base=np.array(v)[loop];centre=base[:,:2].mean(0)
  if centre[1]>.030:continue # Mouth aperture is reserved, not attached.
  if (int(loop[0]),int(loop[1])) in directed:loop=loop[::-1];base=np.array(v)[loop]
  eye=centre[1]<0
  prev=loop
  if eye:
   cx=-.029 if centre[0]<0 else .029;cy=-.026;xyz=np.array([cx,cy,.002]);radius=np.array([.012,.007,.007])
   # Preserve one-to-one boundary sampling. No equal-angle collapse.
   relative=base[:,:2]-[cx,cy];normalized=relative/np.max(abs(relative),axis=0)
   for level,alpha in enumerate((.35,.7,1.)):
    target=normalized*np.array([.010,.004*(1-.98*blink)*(1-.3*squint)])+[cx,cy]
    xy=(1-alpha)*base[:,:2]+alpha*target
    rr=(((xy-[cx,cy])/radius[:2])**2).sum(1)
    front=xyz[2]-radius[2]*np.sqrt(np.maximum(0,1-rr))-.0008
    z=(1-alpha)*base[:,2]+alpha*front
    ids=add(np.c_[xy,z],'eyelid');join(prev,ids);prev=ids
   # Separate closed rigid globe, behind lid front and contained by orbital aperture.
   rows=[];count=32
   for j in range(1,16):
    phi=np.pi*j/16;theta=np.arange(count)*2*np.pi/count
    p=xyz+radius*np.stack([np.sin(phi)*np.cos(theta),np.full(count,np.cos(phi)),np.sin(phi)*np.sin(theta)],1)
    rows.append(add(p,'eyeball'))
   for a,b in zip(rows,rows[1:]):join(a,b)
   for row,sign in [(rows[0],1),(rows[-1],-1)]:
    cap=add((xyz+[0,sign*radius[1],0])[None],'eyeball')[0]
    for i in range(count):faces.append([row[(i+1)%count],row[i],cap] if sign==1 else [row[i],row[(i+1)%count],cap])
  else:
   # Extrude the actual concave boundary; radial shrinking is not injective.
   # Planar back closure uses ear clipping, not a crossing centroid fan.
   z=float(base[:,2].max()+.010)
   ids=add(np.c_[base[:,:2],np.full(len(base),z)],'nostril');join(prev,ids)
   polygon=list(range(len(ids)));xy=base[:,:2]
   def cross(a,b,c):
    u=b-a;w=c-a;return float(u[0]*w[1]-u[1]*w[0])
   sign=np.sign(sum(cross(np.zeros(2),xy[i],xy[(i+1)%len(xy)]) for i in range(len(xy))))
   while len(polygon)>3:
    found=False
    for k in range(len(polygon)):
     a,b,c=polygon[k-1],polygon[k],polygon[(k+1)%len(polygon)]
     if sign*cross(xy[a],xy[b],xy[c])<=1e-14:continue
     others=[q for q in polygon if q not in (a,b,c)]
     if any(all(sign*cross(xy[u],xy[w],xy[q])>=-1e-14 for u,w in ((a,b),(b,c),(c,a))) for q in others):continue
     faces.append([ids[a],ids[b],ids[c]]);polygon.pop(k);found=True;break
    if not found:raise ValueError('nostril closure polygon not triangulable')
   faces.append([ids[q] for q in polygon])
 return dict(vertices=np.array(v),triangles=np.array(faces),labels=np.array(labels),scope='retained neutral prototype; no mouth attachment')
