"""Factorial geometry diagnosis. Any contact blocks admission before training."""
import json,resource,time,argparse
from pathlib import Path
import numpy as np
from .mechanics import assembly,articulate
from .root_cause import signed
from .contact import intersections
from experiments.v265_anatomy.generator import identity,lineage
from experiments.v265_prior.evaluate import topology_metrics

def grid():
 result=[]
 for opening in (0,.25,.5,.75,1):
  for name,mode,value in [('neutral',0,0),('smile',0,1),('compression',2,1),('protrusion',3,1),('asymmetric',4,1),('blink',6,1),('squint',7,1)]:
   e=np.zeros(8);e[1]=opening;e[mode]=value;result.append((name,opening,e))
 return result

def run(out):
 start=time.monotonic();out=Path(out);out.mkdir(parents=True,exist_ok=True);t=assembly();rows=lineage();tri=t['triangles'];selected=np.flatnonzero(np.isin(t['semantic'][tri],[3,4,5,6]).any(1));cases=[]
 for idx in (416,417,428,443):
  n=identity(t,rows[idx]['factors']);contact=intersections(n,tri,selected)
  (out/f'neutral-contact-{idx}.json').write_text(json.dumps(contact,indent=2))
  for candidate in ('A','B'):
   for name,opening,e in grid():
    v=articulate(t,n,e,candidate);sg,area,ref=signed(v,n,tri);metric=topology_metrics(v,n,tri)
    # Contacts are evaluated even after neutral failure, to retain diagnostic evidence.
    ct=intersections(v,tri,selected)
    cases.append(dict(identity=idx,candidate=candidate,mode=name,opening=opening,orientation_failures=int((sg<=0).sum()),min_double_area_m2=float(area.min()),contacts=len(ct['proper_intersection_pairs']),unresolved_coplanar=len(ct['unresolved_coplanar_pairs']),geometry=metric,admitted=False))
 result=dict(stage='diagnostic; neutral already invalid',vertices=len(t['vertices']),triangles=len(tri),cases=cases,full_admission=False,contact_clearance=False,visibility_coverage='NOT_MEASURED',cavity_exposure='NOT_MEASURED',trained=False,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,seconds=time.monotonic()-start)
 (out/'benchmark.json').write_text(json.dumps(result,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
 print({c:{'orientation_failures':sum(r['orientation_failures'] for r in cases if r['candidate']==c),'max_contact_pairs':max(r['contacts'] for r in cases if r['candidate']==c)} for c in ['A','B']})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');a=p.parse_args();run(a.out)
