"""Discrete global boundary/segment preflight at the single frozen depth.
Not a claim of continuum CCD certification over every intermediate depth.
"""
import json,argparse
from pathlib import Path
import numpy as np
from experiments.v265_lid_material.neutral import construct
from experiments.v265_retained.admission import validate
from experiments.v265_shell_feasibility.analyze import ray

def geometry(rows,depth):
    t=construct(depth);d={r['vertex']:np.array(r['direction']) for r in rows}
    for domain in t['domains']:
        ids=domain['outer_vertices'];t['vertices'][domain['inner_vertices']]=t['exterior_reference'][ids]+depth*np.array([d[i] for i in ids])
    return t

def run(out):
    out=Path(out);rows=json.loads((out/'cones.json').read_text());f=json.loads((out/'field.json').read_text());t=geometry(rows,f['fixed_depth_m']);r=validate(t)
    result=dict(scope='Prospective field boundary at frozen depth; local full-interval prism Jacobian evaluated separately',proper_intersections=r['intersections'],pairs=r['pairs'],coplanar_overlaps=r['unresolved_coplanar'],topology_defects=sum(r[x] for x in ['nonmanifold','winding','degenerate','duplicate_faces']),global_boundary_pass=r['structural_pass'])
    (out/'preflight.json').write_text(json.dumps(result,indent=2));print({k:v for k,v in result.items() if k!='pairs'})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
