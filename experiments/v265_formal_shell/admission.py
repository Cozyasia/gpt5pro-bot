"""Single G2 neutral candidate. Finite sampling never becomes a global certificate."""
import json,argparse,hashlib
from pathlib import Path
import numpy as np
from .preflight import geometry
from .material import minimum_thickness
from experiments.v265_retained.surface import build
from experiments.v265_retained.admission import validate
from experiments.v265_mouth.validate import point_triangle,clearance
from experiments.v265_shell_feasibility.analyze import ray

def decide(measured,certified):
    return bool(measured and certified)

def run(out):
    out=Path(out);cpath=Path(__file__).with_name('contract.json');c=json.loads(cpath.read_text());rows=json.loads((out/'cones.json').read_text());field=json.loads((out/'field.json').read_text());t=geometry(rows,c['construction_depth_m']);base=build();v=t['vertices'];tr=t['triangles'];r=validate(t);thickness=[];hits=[];canthi=[];distances=[]
    for domain in t['domains']:
        mapping=dict(zip(domain['outer_vertices'],domain['inner_vertices']));outer=np.array(domain['outer_triangles']);inner=np.array([[mapping[int(i)] for i in face] for face in tr[outer]])
        delta=v[inner]-v[tr[outer]]
        # Convex triangle distance of displacement vectors: exact material
        # thickness minimum for linear barycentric correspondence, not surface distance.
        thick=np.array([minimum_thickness(x) for x in delta])
        for i,th in zip(outer,thick):thickness.append(dict(triangle=int(i),side=domain['side'],minimum_m=float(th)))
        for corner in domain['canthi']:
            neighboring=np.unique(tr[outer][(tr[outer]==corner).any(1)]);neighboring=neighboring[neighboring!=corner]
            canthi.append(dict(vertex=corner,inner= mapping[corner],wall_m=float(np.linalg.norm(v[mapping[corner]]-v[corner])),minimum_inner_edge_m=float(min(np.linalg.norm(v[mapping[int(i)]]-v[mapping[corner]]) for i in neighboring))))
        weights=np.array([[1,0,0],[0,1,0],[0,0,1],[.5,.5,0],[0,.5,.5],[.5,0,.5],[1/3,1/3,1/3]])
        for face,inside,tid in zip(tr[outer],inner,outer):
            for k,b in enumerate(weights):
                p=b@v[face];q=b@v[inside];length=float(np.linalg.norm(q-p));hit=ray(p,(q-p)/length,v,tr,[])
                if hit and hit['metres']<length-1e-10:hits.append(dict(material_triangle=int(tid),sample=k,barycentric=b.tolist(),hit=hit,segment_length_m=length))
        side=-1 if domain['side']=='left' else 1;eye=np.flatnonzero((t['labels'][tr]=='eyeball').all(1)&(side*v[tr].mean(1)[:,0]>0));lookup={tuple(f):i for i,f in enumerate(tr)};innerids=np.array([lookup[tuple(f)] for f in domain['inner_triangles']]);distances.append(dict(side=domain['side'],exterior_globe=clearance(v,tr,eye,outer),inner_globe=clearance(v,tr,eye,innerids),nearest_surface_diagnostic=clearance(v,tr,outer,innerids)))
    r.update(candidate='G2',contract_sha256=hashlib.sha256(cpath.read_bytes()).hexdigest(),exterior_bit_exact=bool(np.array_equal(v[:len(base['vertices'])],base['vertices']) and np.array_equal(tr[:len(base['triangles'])],base['triangles'])),minimum_material_thickness_m=min(x['minimum_m'] for x in thickness),material_thickness_witness=min(thickness,key=lambda x:x['minimum_m']),material_thickness_failures=[x for x in thickness if not np.isfinite(x['minimum_m']) or x['minimum_m']<=c['thickness_min_m']],segment_samples=7*len(thickness),segment_hits=hits,canthi=canthi,clearances=distances,local_material_jacobian_pass=not field['local_jacobian_failures'],global_injectivity_certified=False)
    r['measured_gates_pass']=bool(r['structural_pass'] and r['exterior_bit_exact'] and not r['material_thickness_failures'] and not hits and r['local_material_jacobian_pass'] and all(x['inner_globe']['metres']>=c['inner_globe_min_m'] for x in distances) and all(x['wall_m']>c['thickness_min_m'] and x['minimum_inner_edge_m']>0 for x in canthi))
    r['neutral_admitted']=decide(r['measured_gates_pass'],r['global_injectivity_certified']);r['global_field_evidence']=json.loads((out/'global-field.json').read_text());r['inverse_witness_evidence']=json.loads((out/'inverse-witnesses.json').read_text());r['result']='FAIL' if not r['measured_gates_pass'] else 'UNQUALIFIED_GLOBAL_INJECTIVITY';r['blink']=r['seam']=r['training']='NOT_RUN'
    (out/'candidate-g2.json').write_text(json.dumps(r,indent=2));print({k:r[k] for k in ['intersections','unresolved_coplanar','nonmanifold','winding','degenerate','exterior_bit_exact','minimum_material_thickness_m','material_thickness_witness','segment_samples','local_material_jacobian_pass','measured_gates_pass','result']});print('THICKNESS_FAILURES',len(r['material_thickness_failures']),'SEGMENT_HITS',len(hits));print('FIRST_SEGMENT_HIT',hits[:1]);print('clearances',distances)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
