"""Sufficient global non-overlap test using convex enclosures of swept cells.
Overlapping convex enclosures are UNKNOWN, not proof of actual map crossing.
"""
import json,argparse
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
from scipy.optimize import linprog
from .preflight import geometry
from .material import ruled_separation

def run(out):
    out=Path(out);c=json.loads(Path(__file__).with_name('contract.json').read_text());rows=json.loads((out/'cones.json').read_text());t=geometry(rows,c['construction_depth_m']);v=t['vertices'];tr=t['triangles'];cells=[]
    for domain in t['domains']:
        m=dict(zip(domain['outer_vertices'],domain['inner_vertices']))
        for i in domain['outer_triangles']:
            points=np.r_[v[tr[i]],v[[m[int(k)] for k in tr[i]]]]*1000 # mm for LP conditioning
            hull=ConvexHull(points);cells.append(dict(triangle=i,outer=tr[i],points=points,planes=hull.equations,lo=points.min(0),hi=points.max(0)))
    lo=np.array([x['lo'] for x in cells]);hi=np.array([x['hi'] for x in cells]);unresolved=[];tested=0
    for i,a in enumerate(cells):
        for j in np.flatnonzero((np.arange(len(cells))>i)&(lo<=a['hi']).all(1)&(hi>=a['lo']).all(1)):
            b=cells[j];planes=np.r_[a['planes'],b['planes']];norm=np.linalg.norm(planes[:,:3],axis=1)
            lp=linprog([0,0,0,-1],A_ub=np.c_[planes[:,:3],norm],b_ub=-planes[:,3],bounds=[(None,None)]*4,method='highs');tested+=1
            if not lp.success:raise RuntimeError(lp.message)
            # radius > numeric resolution proves overlap of enclosures, NOT of curved cells.
            if lp.x[3]>1e-9:unresolved.append(dict(triangles=[a['triangle'],b['triangle']],shared_outer_vertices=np.intersect1d(a['outer'],b['outer']).tolist(),enclosure_overlap_radius_mm=float(lp.x[3]),witness_mm=lp.x[:3].tolist()))
    separations=[]
    direction={r['vertex']:np.array(r['direction'])*c['construction_depth_m'] for r in rows}
    for pair in unresolved:
        shared=pair['shared_outer_vertices']
        if len(shared)!=2:continue
        ta,tb=tr[pair['triangles']];third=[int(x) for x in ta if x not in shared]+[int(x) for x in tb if x not in shared];ids=shared+third
        separations.append(dict(triangles=pair['triangles'],vertices=ids,**ruled_separation(v[ids],np.array([direction[x] for x in ids]))))
    result=dict(ruled_separations=separations,remaining_unresolved=len(unresolved)-sum(x['separated'] for x in separations),cells=len(cells),broadphase_pairs_tested=tested,enclosure_overlap_pairs=unresolved,global_certificate=not unresolved,scope='Disjoint convex enclosures suffice for intercell volume non-overlap. Overlap is inconclusive for bilinear-sided material prisms; no claim of true crossing. A complete global certificate also needs exterior/globe exclusion and boundary/contact classification.',full_global_injectivity_certified=False)
    (out/'global-field.json').write_text(json.dumps(result,indent=2));print('cells',len(cells),'pairs',tested,'unresolved',len(unresolved));print('first',unresolved[:1]);print('remaining',result['remaining_unresolved']);print('failed separators',[x for x in separations if not x['separated']][:1])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
