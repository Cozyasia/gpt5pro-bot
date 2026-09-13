"""Topology and Euclidean surface clearance; no projected-normal acceptance."""
import numpy as np
from experiments.v265_articulation.contact import intersections

def point_triangle(p,t):
 a,b,c=t[:,0],t[:,1],t[:,2];ab=b-a;ac=c-a;n=np.cross(ab,ac);n2=(n*n).sum(1);h=((p-a)*n).sum(1)/n2;proj=p-h[:,None]*n
 d00=(ab*ab).sum(1);d01=(ab*ac).sum(1);d11=(ac*ac).sum(1);v=proj-a;d20=(v*ab).sum(1);d21=(v*ac).sum(1);den=d00*d11-d01*d01
 u=(d11*d20-d01*d21)/den;w=(d00*d21-d01*d20)/den;inside=(u>=0)&(w>=0)&(u+w<=1)
 result=np.where(inside,np.abs(h)*np.sqrt(n2),np.inf)
 for x,y in [(a,b),(b,c),(c,a)]:
  d=y-x;q=np.clip(((p-x)*d).sum(1)/(d*d).sum(1),0,1);result=np.minimum(result,np.linalg.norm(p-x-q[:,None]*d,axis=1))
 return result

def segment_distance(p1,q1,p2,q2):
 u=q1-p1;v=q2-p2;w=p1-p2;a=(u*u).sum(1);b=(u*v).sum(1);c=(v*v).sum(1);d=(u*w).sum(1);e=(v*w).sum(1);den=a*c-b*b
 s=np.divide(b*e-c*d,den,out=np.zeros_like(a),where=den>1e-20);s=np.clip(s,0,1);t=(b*s+e)/c
 s=np.where(t<0,np.clip(-d/a,0,1),np.where(t>1,np.clip((b-d)/a,0,1),s));t=np.clip(t,0,1)
 return np.linalg.norm(w+s[:,None]*u-t[:,None]*v,axis=1)

def clearance(v,tri,ids1,ids2):
 minimum=np.inf;pair=None
 for i in ids1:
  a=np.broadcast_to(v[tri[i]],(len(ids2),3,3));b=v[tri[ids2]];distance=np.full(len(ids2),np.inf)
  for j in range(3):
   distance=np.minimum(distance,point_triangle(a[:,j],b));distance=np.minimum(distance,point_triangle(b[:,j],a))
   for k in range(3):distance=np.minimum(distance,segment_distance(a[:,j],a[:,(j+1)%3],b[:,k],b[:,(k+1)%3]))
  j=int(np.argmin(distance))
  if distance[j]<minimum:minimum=float(distance[j]);pair=[int(i),int(ids2[j])]
 return dict(metres=minimum,triangle_pair=pair)

def validate(t,v=None):
 v=t['vertices'] if v is None else v;tri=t['triangles'];p=v[tri];area=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/2
 edges=np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]]);unique,inv,count=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True);winding=np.bincount(inv,weights=np.where(edges[:,0]<edges[:,1],1,-1))
 parent=np.arange(len(v))
 def root(i):
  while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
  return i
 for a,b in unique:parent[root(a)]=root(b)
 contact=intersections(v,tri);labels=t['labels'][tri[:,0]];dental=np.flatnonzero(np.char.endswith(labels,'teeth'));oral=np.flatnonzero(~np.char.endswith(labels,'teeth'));upper=np.flatnonzero(labels=='upper_teeth');lower=np.flatnonzero(labels=='lower_teeth')
 close=clearance(v,tri,dental,oral);bite=clearance(v,tri,upper,lower)
 thickness=(v[t['loops'][3]]-v[t['loops'][2]])[:,2]
 pairs=contact['proper_intersection_pairs'];categories={'lip_lip':0,'lip_teeth':0,'cavity_teeth':0,'other':0}
 for a,b in pairs:
  la,lb=labels[a],labels[b];is_tooth='teeth' in la or 'teeth' in lb;is_cavity='cavity' in la or 'cavity' in lb
  key='cavity_teeth' if is_tooth and is_cavity else 'lip_teeth' if is_tooth else 'lip_lip' if not is_cavity else 'other';categories[key]+=1
 result=dict(vertices=len(v),triangles=len(tri),connected_components=len({root(i) for i in range(len(v))}),boundary_edges=int((count==1).sum()),nonmanifold_edges=int((count>2).sum()),inconsistent_winding=int(((count==2)&(winding!=0)).sum()),degenerate_triangles=int((area<=1e-12).sum()),duplicate_faces=len(tri)-len(np.unique(np.sort(tri,axis=1),axis=0)),min_area_m2=float(area.min()),intersections=len(pairs),intersection_categories=categories,unresolved_coplanar=len(contact['unresolved_coplanar_pairs']),min_signed_lip_separation_m=float(thickness.min()),teeth_oral_clearance=close,upper_lower_teeth_clearance=bite,contact_pairs=pairs)
 result['pass']=not any(result[k] for k in ('nonmanifold_edges','inconsistent_winding','degenerate_triangles','duplicate_faces','intersections','unresolved_coplanar')) and result['boundary_edges']==64 and result['connected_components']==13 and thickness.min()>0 and close['metres']>1e-4 and bite['metres']>1e-4
 return result
