import json,argparse
from pathlib import Path
from collections import Counter
import numpy as np
from experiments.v265_lid_material.neutral import construct
from experiments.v265_retained.surface import build

def run(out):
 t=construct();base=build();tr=t['triangles'];p=base['vertices'];r=json.loads(Path('docs/engineering/v265-lid-material/contact-map.json').read_text());rows=[]
 for pair in r['pairs']:
  a,b=pair['triangles'];domain=next(d for d in t['domains'] if a in d['outer_triangles']);k=domain['outer_triangles'].index(a);n=len(domain['outer_vertices'])//4;cent=p[tr[a]].mean(0);cx=-.029 if domain['side']=='left' else .029;dx=cent[0]-cx
  zone='central' if abs(dx)<.008 else ('medial_canthus' if dx*cx<0 else 'lateral_canthus')
  rows.append(dict(outer_triangle=a,inner_triangle=b,side=domain['side'],upper_lower='upper' if cent[1]<-.026 else 'lower',band=['orbital','middle','margin'][k//(2*n)],zone=zone,outer_vertices=tr[a].tolist(),inner_vertices=tr[b].tolist(),outer_centroid=cent.tolist()))
 summary={key:dict(Counter(x[key] for x in rows)) for key in ['side','upper_lower','band','zone']}
 Path(out).write_text(json.dumps(dict(summary=summary,pairs=rows,interpretation='Uniform posterior translation intersects a neighboring exterior sheet; material ordering/topology is unchanged. Direction and local folded geometry are implicated, not a new non-manifold seam.'),indent=2));print(summary)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('out');run(a.parse_args().out)
