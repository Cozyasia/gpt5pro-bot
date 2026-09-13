import json
import numpy as np
from experiments.v265_anatomy.generator import template,identity,express,lineage

def signed(v,n,tri):
 a=v[tri];b=n[tri];nn=np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]);rn=np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0]);length=np.linalg.norm(rn,axis=1)
 return (nn*rn).sum(1)/length, np.linalg.norm(nn,axis=1), length

def labels(t):
 p=t['parts']['mouth'];count=len(p)//5;out={}
 for k,ids in enumerate(np.array(p).reshape(5,count)):
  for i in ids:
   side='upper' if t['uv'][i,1]<.43 else 'lower'
   out[int(i)]=('outer_'+side+'_lip' if k<2 else 'inner_'+side+'_lip' if k==2 else side+'_cavity')
 return out

def run():
 t=template();rows=lineage();rng=np.random.default_rng(265406);result=[];tag=labels(t)
 for i in range(32):
  n=identity(t,rows[416+i]['factors']);e=rng.uniform(-1,1,8);e[1]=abs(e[1]);v=express(t,n,e);sg,area,ref=signed(v,n,t['triangles'])
  for tid in np.flatnonzero(sg<=0):
   # First loss of positive reference-normal projected area along full e ray.
   grid=np.linspace(0,1,201);vals=[signed(express(t,n,e*s),n,t['triangles'][[tid]])[0][0] for s in grid]
   k=next(k for k,vv in enumerate(vals) if vv<=0);lo,hi=grid[k-1],grid[k]
   for _ in range(35):
    mid=(lo+hi)/2
    if signed(express(t,n,e*mid),n,t['triangles'][[tid]])[0][0]>0:lo=mid
    else:hi=mid
   ids=t['triangles'][tid];neighbors=np.flatnonzero(np.isin(t['triangles'],ids).any(1))
   alone=[]
   for j in range(8):
    q=np.zeros(8);q[j]=e[j];alone.append(float(signed(express(t,n,q),n,t['triangles'][[tid]])[0][0]))
   result.append(dict(identity=416+i,triangle=int(tid),vertices=ids.tolist(),vertex_regions=[tag.get(int(j),'skin') for j in ids],uv=t['uv'][ids].tolist(),neighbor_triangles=neighbors.tolist(),neighbor_vertices=np.unique(t['triangles'][neighbors]).tolist(),neutral_xyz=n[ids].tolist(),expressed_xyz=v[ids].tolist(),expression=e.tolist(),first_normal_failure_scale=hi,first_normal_failure_expression=(e*hi).tolist(),signed_double_area_m2=float(sg[tid]),actual_double_area_m2=float(area[tid]),neutral_double_area_m2=float(ref[tid]),single_mode_signed_double_area_m2=alone,classification='reference normal reversal; intersection requires separate contact test'))
 from .contact import intersections
 selected=np.flatnonzero(np.isin(t['semantic'][t['triangles']],[3,4,5,6]).any(1));cache={}
 for f in result:
  i=f['identity']
  if i not in cache:
   n=identity(t,rows[i]['factors']);cache[i]=intersections(express(t,n,np.array(f['expression'])),t['triangles'],selected)
  f['intersections_involving_triangle']=[pair for pair in cache[i]['proper_intersection_pairs'] if f['triangle'] in pair]
  f['classification']='normal reversal with proper intersection witness' if f['intersections_involving_triangle'] else 'normal reversal; no proper intersection witness for this triangle; not clearance'
 return dict(failures=result,count=len(result),triangle_ids=sorted(set(x['triangle'] for x in result)),cause='semantic-mask discontinuity: added opening on vermilion stops abruptly at cavity ring; upper/lower sign split at commissure; no jaw/maxilla ownership')
if __name__=='__main__':print(json.dumps(run(),indent=2))
