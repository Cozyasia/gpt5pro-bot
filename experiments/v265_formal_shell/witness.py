"""Invert a material prism at a supplied point using all real cubic roots."""
import json,argparse
from pathlib import Path
import numpy as np
from .preflight import geometry

def inverse_prism(p,delta,x):
    a=[p[1]-p[0],delta[1]-delta[0]];b=[p[2]-p[0],delta[2]-delta[0]];z=[x-p[0],-delta[0]];coef=np.zeros(4)
    for i in range(2):
        for j in range(2):
            for k in range(2):coef[i+j+k]+=np.cross(a[i],b[j])@z[k]
    roots=np.polynomial.polynomial.polyroots(np.trim_zeros(coef,'b'));answers=[]
    for s in roots:
        if abs(s.imag)>1e-8 or not 0<float(s.real)<1:continue
        s=float(s.real);m=np.stack([a[0]+s*a[1],b[0]+s*b[1]],axis=1);uv=np.linalg.lstsq(m,z[0]+s*z[1],rcond=None)[0];res=float(np.linalg.norm(m@uv-z[0]-s*z[1]))
        if min(uv)>1e-8 and uv.sum()<1-1e-8 and res<1e-8:answers.append(dict(u=float(uv[0]),v=float(uv[1]),depth_fraction=s,residual_mm=res))
    return answers

def run(out):
    out=Path(out);r=json.loads((out/'global-field.json').read_text());rows=json.loads((out/'cones.json').read_text());c=json.loads(Path(__file__).with_name('contract.json').read_text());t=geometry(rows,c['construction_depth_m']);v=t['vertices']*1000;tr=t['triangles'];d={x['vertex']:np.array(x['direction'])*c['construction_depth_m']*1000 for x in rows};witnesses=[];tested=0
    bad={tuple(x['triangles']) for x in r['ruled_separations'] if not x['separated']}
    for pair in r['enclosure_overlap_pairs']:
        if tuple(pair['triangles']) not in bad:continue
        tested+=1;x=np.array(pair['witness_mm']);inverses=[inverse_prism(v[tr[i]],np.array([d[int(k)] for k in tr[i]]),x) for i in pair['triangles']]
        if all(inverses):witnesses.append(dict(**pair,material_preimages=inverses))
    result=dict(tested_witness_points=tested,actual_multiple_preimage_witnesses=witnesses,scope='A double interior preimage is a genuine global material-map collision. No double preimage at these points does not prove injectivity.')
    (out/'inverse-witnesses.json').write_text(json.dumps(result,indent=2));print('tested',tested,'actual collisions',len(witnesses));print(witnesses[:1])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
