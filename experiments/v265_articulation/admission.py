"""Fail-closed pre-raster barriers. No empirically uncalibrated default limits."""
import numpy as np
from .contact import intersections
from .root_cause import signed
from experiments.v265_prior.evaluate import topology_metrics

def require_valid(t,reference,posed,envelope=None):
 reasons=[];tri=t['triangles'];sg,area,ref=signed(posed,reference,tri)
 if not np.isfinite(posed).all():raise ValueError('nonfinite geometry')
 if (ref<=1e-12).any():raise ValueError('degenerate reference')
 if (area<=1e-12).any():reasons.append('minimum area')
 if (sg<=0).any():reasons.append('orientation')
 metric=topology_metrics(posed,reference,tri)
 for name,vertices in [('neutral',reference),('posed',posed)]:
  ids=np.flatnonzero(np.isin(t['semantic'][tri],[3,4,5,6]).any(1));contact=intersections(vertices,tri,ids)
  if contact['proper_intersection_pairs']:reasons.append(name+' penetration')
  if contact['unresolved_coplanar_pairs']:reasons.append(name+' unresolved contact')
 if envelope is None:reasons.append('benign edge/area envelope uncalibrated')
 else:
  # Caller must provide versioned independently calibrated bounds.
  p=posed[tri];r=reference[tri];ratio=area/ref
  edge=np.linalg.norm(p[:,[1,2,0]]-p,axis=2)/np.linalg.norm(r[:,[1,2,0]]-r,axis=2)
  if ratio.min()<envelope['area_min'] or ratio.max()>envelope['area_max']:reasons.append('area envelope')
  if edge.min()<envelope['edge_min'] or edge.max()>envelope['edge_max']:reasons.append('edge envelope')
 reasons.append('full contact/visibility clearance incomplete')
 if reasons:raise ValueError('; '.join(reasons))
 return metric
