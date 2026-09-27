"""Immutable retained neutral hashes and old lower-left blink witness."""
import hashlib,json,argparse
from pathlib import Path
import numpy as np
from experiments.v265_retained.surface import build

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);t=build();v=t['vertices'];tr=t['triangles'];pair=np.array([9030,9033]);vertices=np.unique(tr[pair]);neighbor=np.flatnonzero(np.isin(tr,vertices).any(1));edge=np.unique(np.sort(np.concatenate([tr[neighbor][:,[0,1]],tr[neighbor][:,[1,2]],tr[neighbor][:,[2,0]]]),axis=1),axis=0)
 h=lambda a:hashlib.sha256(a.tobytes()).hexdigest()
 fixture=dict(vertices=h(v),topology=h(tr),eye_insertion=h(v[t['labels']=='eyelid']),globe=h(v[t['labels']=='eyeball']),nose=h(v[np.isin(t['labels'],['nostril','nasal_cavity'])]),mouth_positive_sha256=hashlib.sha256(Path('experiments/v265_retained/mouth-positive.json').read_bytes()).hexdigest())
 (out/'neutral-positive.json').write_text(json.dumps(fixture,indent=2));rows=[]
 for b in np.r_[0.,np.linspace(.9,1.,21)]:
  p=build(float(b))['vertices'];tri=p[tr[pair]];normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);areas=np.linalg.norm(normal,axis=1)/2;normal/=np.linalg.norm(normal,axis=1)[:,None]
  old=v[tr[pair]];on=np.cross(old[:,1]-old[:,0],old[:,2]-old[:,0]);on/=np.linalg.norm(on,axis=1)[:,None]
  stretch=np.linalg.norm(p[edge[:,1]]-p[edge[:,0]],axis=1)/np.linalg.norm(v[edge[:,1]]-v[edge[:,0]],axis=1)
  rows.append(dict(blink=float(b),trajectories=p[vertices].tolist(),areas_m2=areas.tolist(),reference_normal_dot=(normal*on).sum(1).tolist(),opposite_vertices_signed_plane_distances_m=[((tri[1]-tri[0,0])@normal[0]).tolist(),((tri[0]-tri[1,0])@normal[1]).tolist()],edge_min=float(stretch.min()),edge_max=float(stretch.max())))
 r=dict(triangles=pair.tolist(),vertices=vertices.tolist(),neutral=v[vertices].tolist(),ownership=['lower-left lid' if v[i,1]>-.026 else 'upper-left lid' for i in vertices],neighbor_ids=neighbor.tolist(),neighbor_triangles=tr[neighbor].tolist(),edges=edge.tolist(),sweep=rows,note='Signed distances are to triangle planes, not penetration depth. Reference normals are not a true-foldover metric.')
 (out/'old-blink-root.json').write_text(json.dumps(r,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
