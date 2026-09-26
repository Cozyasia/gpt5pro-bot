"""One continuous P1 cone field; exact polynomial local prism Jacobian minimum.
Failure of this field is NOT a nonexistence theorem for every continuous field.
"""
import json,argparse
from pathlib import Path
import numpy as np
from experiments.v265_retained.surface import build
from experiments.v265_lid_material.neutral import construct
from experiments.v265_shell_feasibility.analyze import ray

def prism_min(p,d,depth):
    e1,e2=p[1]-p[0],p[2]-p[0];a,b=d[1]-d[0],d[2]-d[0]
    best=(float('inf'),None)
    # J is affine in barycentrics, quadratic in depth. Its global minimum
    # on triangle x [0,depth] occurs at a triangle corner and quadratic extremum.
    for k in range(3):
        c0=float(np.cross(e1,e2)@d[k]);c1=float((np.cross(a,e2)+np.cross(e1,b))@d[k]);c2=float(np.cross(a,b)@d[k])
        s=[0.,depth]
        if c2>0 and 0< -c1/(2*c2)<depth:s.append(-c1/(2*c2))
        for z in s:
            val=c0+c1*z+c2*z*z
            if val<best[0]:best=(val,dict(corner=k,depth_m=z,polynomial=[c0,c1,c2]))
    return best

def run(out):
    out=Path(out);rows=json.loads((out/'cones.json').read_text());base=build();v=base['vertices'];tr=base['triangles'];c=json.loads(Path('experiments/v265_shell_feasibility/contract.json').read_text());depth=c['construction_depth_m'];d={r['vertex']:np.array(r['direction']) for r in rows};faces=np.unique(np.concatenate([x['outer_triangles'] for x in construct()['domains']]));bad=[];jacs=[];rays=[]
    for i in faces:
        j,w=prism_min(v[tr[i]],np.array([d[int(k)] for k in tr[i]]),depth);jacs.append(j)
        if j<=0:bad.append(dict(triangle=int(i),vertices=tr[i].tolist(),jacobian=j,**w))
    for r in rows:
        hit=ray(v[r['vertex']],d[r['vertex']],v,tr,[r['vertex']])
        if hit and hit['metres']<=depth:rays.append(dict(vertex=r['vertex'],**hit))
    edges=np.unique(np.sort(np.concatenate([tr[faces][:,[0,1]],tr[faces][:,[1,2]],tr[faces][:,[2,0]]]),axis=1),axis=0)
    jump=[float(np.linalg.norm(d[int(a)]-d[int(b)])) for a,b in edges]
    result=dict(field='P1 interpolation of maximum cone-margin unit directions',cones_all_strict=all(r['classification']=='FEASIBLE_CONE' for r in rows),continuous_C0=True,local_jacobian_failures=bad,segment_exterior_or_globe_hits=rays,minimum_prism_jacobian=float(min(jacs)),maximum_neighbor_direction_difference=max(jump),fixed_depth_m=depth,scope='Exact polynomial local test in floating arithmetic; vertex rays are additional rejection only. No global collision-free claim.',family_nonexistence_proven=False)
    result['field_admitted']=not bad and not rays and result['cones_all_strict'];result['decision']='G2_REQUIRES_GLOBAL_CERTIFICATION' if result['field_admitted'] else 'H';(out/'field.json').write_text(json.dumps(result,indent=2));print({k:v for k,v in result.items() if k not in ['local_jacobian_failures','segment_exterior_or_globe_hits']});print('failures',len(bad),len(rays));print('first',bad[:1],rays[:1])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
