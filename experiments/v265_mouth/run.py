import json,argparse,time,resource
import numpy as np
from pathlib import Path
from .component import build,jaw_only,IDENTITIES
from .validate import validate

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);rows=[];start=time.monotonic()
 for name,params in IDENTITIES.items():
  t=build(**params)
  for i in range(11):
   opening=i/10;r=validate(t,jaw_only(t,opening));r.update(identity=name,opening=opening)
   n=t['vertices'];tri=t['triangles'];v=jaw_only(t,opening);a=n[tri];b=v[tri];ar=np.linalg.norm(np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0]),axis=1)/np.linalg.norm(np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]),axis=1);edges=np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]]);er=np.linalg.norm(v[edges[:,0]]-v[edges[:,1]],axis=1)/np.linalg.norm(n[edges[:,0]]-n[edges[:,1]],axis=1)
   r.update(area_ratio=[float(ar.min()),float(ar.max())],edge_ratio=[float(er.min()),float(er.max())],max_stretch_edge=edges[int(np.argmax(er))].tolist());rows.append(r)
   (out/'results.json').write_text(json.dumps(rows,indent=2))
   print(name,opening,r['pass'],r['intersections'],flush=True)
   if not r['pass']:break
 summary=dict(cases=len(rows),neutral_pass=all(r['pass'] for r in rows if r['opening']==0),jaw_contact_pass=len(rows)==110 and all(r['pass'] for r in rows),jaw_pass=False,jaw_metric_envelope_qualified=False,jaw_blocker='high commissure edge/area distortion; no independently calibrated benign envelope',first_failure=next((r for r in rows if not r['pass']),None),seconds=time.monotonic()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,full_anatomy_admission=False)
 (out/'summary.json').write_text(json.dumps(summary,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
