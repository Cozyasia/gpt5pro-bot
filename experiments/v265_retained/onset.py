"""Locate observed lid/lid onset independently from unchanged mouth."""
import json,argparse
from pathlib import Path
import numpy as np
from .surface import build
from experiments.v265_articulation.contact import intersections

def run(out):
 def query(value):
  t=build(value);tr=t['triangles'];ids=np.flatnonzero((t['labels'][tr]=='eyelid').any(1));r=intersections(t['vertices'],tr,ids);return t,r['proper_intersection_pairs']
 lo,hi=.75,1.;assert not query(lo)[1] and query(hi)[1]
 for _ in range(20):
  mid=(lo+hi)/2
  if query(mid)[1]:hi=mid
  else:lo=mid
 t,pairs=query(hi);r=dict(last_clear=lo,first_detected=hi,classification='SELF_INTERSECTION',pairs=pairs,triangles=t['triangles'][np.array(pairs)].tolist(),coordinates=t['vertices'][t['triangles'][np.array(pairs)]].tolist(),scope='prototype identity; lid subset coefficient bracket, not continuous CCD')
 Path(out).write_text(json.dumps(r,indent=2));print({k:v for k,v in r.items() if k not in ('triangles','coordinates')})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
