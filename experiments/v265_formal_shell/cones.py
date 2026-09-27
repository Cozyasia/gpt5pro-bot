"""Numerically certified polyhedral cones; zero vector is excluded from EMPTY meaning."""
import json, argparse
from pathlib import Path
from collections import Counter
import numpy as np
from scipy.optimize import linprog
from experiments.v265_retained.surface import build
from experiments.v265_lid_material.neutral import construct

TOL=1e-9

def classify(normals):
    n=np.asarray(normals,float)
    # max rho subject to N d >= rho, |d_k| <= 1.
    r=linprog([0,0,0,-1],A_ub=np.c_[-n,np.ones(len(n))],b_ub=np.zeros(len(n)),bounds=[(-1,1)]*3+[(None,None)],method='highs')
    if not r.success: raise RuntimeError(r.message)
    rho=float(r.x[3]); direction=r.x[:3]; certificate=None
    if rho>TOL:
        direction/=np.linalg.norm(direction);status='FEASIBLE_CONE'
    else:
        # Every nonzero cone direction scales onto some signed cube face.
        face_results=[]
        for k in range(3):
            for sign in [-1,1]:
                bounds=[(-1,1)]*3;bounds[k]=(sign,sign)
                q=linprog(np.zeros(3),A_ub=-n,b_ub=np.zeros(len(n)),bounds=bounds,method='highs')
                face_results.append(dict(axis=k,sign=sign,status=int(q.status)))
                if q.success: direction=q.x
                elif q.status!=2: raise RuntimeError(q.message)
        status='DEGENERATE_CONE' if any(x['status']==0 for x in face_results) else 'EMPTY_CONE'
        certificate=dict(cube_face_feasibility=face_results,margin_dual_weights=(-r.ineqlin.marginals).tolist(),weighted_normal_sum=((-r.ineqlin.marginals)@n).tolist())
        # A strictly positive dependence of spanning normals proves cone={0}.
        if status=='EMPTY_CONE':
            m=len(n);q=linprog(np.r_[np.zeros(m),-1],A_ub=np.c_[-np.eye(m),np.ones(m)],b_ub=np.zeros(m),A_eq=np.c_[np.vstack([n.T,np.ones(m)]),np.zeros(4)],b_eq=[0,0,0,1],bounds=[(0,None)]*m+[(0,None)],method='highs')
            certificate['positive_dependence']=None if not q.success else dict(weights=q.x[:m].tolist(),min_weight=float(q.x[-1]),residual=float(np.linalg.norm(n.T@q.x[:m])),normal_rank=int(np.linalg.matrix_rank(n)))
    return dict(classification=status,max_cube_margin=rho,direction=direction.tolist(),minimum_dot=float((n@direction).min()),certificate=certificate)

def run(out):
    t=build();v=t['vertices'];tr=t['triangles'];p=v[tr];fn=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);fn/=np.linalg.norm(fn,axis=1)[:,None];rows=[]
    for domain in construct()['domains']:
        for i in domain['outer_vertices']:
            ids=np.flatnonzero((tr==i).any(1));r=classify(fn[ids]);r.update(vertex=i,position_m=v[i].tolist(),side=domain['side'],region='upper' if v[i,1]<-.026 else 'lower',label=str(t['labels'][i]),incident_triangles=ids.tolist(),incident_normals=fn[ids].tolist());rows.append(r)
    out=Path(out);out.mkdir(parents=True,exist_ok=True);(out/'cones.json').write_text(json.dumps(rows,indent=2));summary=dict(counts=dict(Counter(r['classification'] for r in rows)),vertices=len(rows),tolerance=TOL,definition='EMPTY excludes zero: closed oriented cone contains only zero; DEGENERATE has nonzero directions but no strictly positive facet margin',scope='Incident facet cone only; not nonincident collision or continuous-field certification')
    (out/'cone-summary.json').write_text(json.dumps(summary,indent=2));print(summary)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
