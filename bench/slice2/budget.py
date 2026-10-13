"""Admission from observed development cells; never select/trim scored cells."""
import json
import math
from pathlib import Path

from bench.slice2.protocol import ARMS, schedule


def admit(cells, limits):
    out = {'decision':'DEFER','reason':'incomplete calibration or unknown plan limits'}
    expected = {r['cell'] for r in schedule('calibration')}
    if len(cells)!=8 or {r.get('cell') for r in cells}!=expected:
        return out
    required = ('request_limit','used_requests','grading_requests','grading_wall_s','reproducer_wall_s','human_wall_s')
    if limits.get('plan')!='GLM coding plan' or any(type(limits.get(k)) not in (int,float) or not math.isfinite(limits[k]) or limits[k]<0 for k in required):
        return out
    for c in cells:
        accounting=c.get('accounting')
        if not (accounting is True or isinstance(accounting,dict) and accounting.get('pass') is True):
            return out
        if c.get('status')!='COMPLETE' or c.get('arm') not in ARMS or any(type(c.get(k)) not in (int,float) or not math.isfinite(c[k]) or c[k]<=0 for k in ('wall_s','requests')):
            return out
    # Conservative arm maxima from four cells, 20 scored cells per arm.
    wall = sum(20*max(c['wall_s'] for c in cells if c['arm']==a) for a in ARMS)
    requests = sum(20*max(c['requests'] for c in cells if c['arm']==a) for a in ARMS)
    overhead = sum(limits[k] for k in ('grading_wall_s','reproducer_wall_s','human_wall_s'))
    used = limits['used_requests'] + sum(c['requests'] for c in cells)
    projected = used + requests + limits['grading_requests']
    decision = 'ADMIT' if wall+overhead<=8*3600 and projected<=limits['request_limit'] else 'DEFER'
    return dict(decision=decision,projected_wall_s=wall+overhead,scored_wall_s=wall,
                projected_requests=projected,scored_requests=requests,
                reason='observed arm-max projection; known remaining plan request allowance required')


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--measurements',type=Path,required=True); p.add_argument('--limits',type=Path,required=True)
    a=p.parse_args()
    value=admit(json.loads(a.measurements.read_text()),json.loads(a.limits.read_text()))
    print(value['decision']); print(json.dumps(value,sort_keys=True))
