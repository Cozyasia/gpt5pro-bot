import argparse,json,hashlib
from pathlib import Path
import numpy as np
from experiments.v265_retained.surface import build
from experiments.v265_retained.admission import validate,eye_clearance
from experiments.v265_commissure.audit import metrics
from .closure import deform,eyes

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);neutral=build();tr=neutral['triangles'];n=neutral['vertices'];rows=[]
 for candidate in ('E','F'):
  for blink in (0.,.5,.9,1.):
   t=deform(candidate,blink);r=validate(t);clear=eye_clearance(t);m=metrics(t['vertices'],n,tr)
   row=dict(candidate=candidate,blink=blink,geometry=r,clearance=clear,metrics=m,wall_thickness_m=None,wall_thickness_reason='No separate inner/outer lid wall exists in frozen single-sheet topology',full_blink_admitted=False)
   rows.append(row);(out/'candidates.json').write_text(json.dumps(rows,indent=2));print(candidate,blink,r['intersections'],r['degenerate'],r['unresolved_coplanar'],m['edge_max'],flush=True)
 (out/'summary.json').write_text(json.dumps(dict(admitted=False,retained_dynamic=False,seam='NOT_RUN',training='FORBIDDEN',reason='Closure contacts and finite eyelid wall must both be demonstrated; no missing metric may silently PASS'),indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
