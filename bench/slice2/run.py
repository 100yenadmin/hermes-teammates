"""Checkpointed phase harness. A caller-supplied executor owns actual provider calls.

The executor receives only a public workspace and a frozen launch specification.
It returns bounded scalar receipts. This module has no credentials or network client.
"""
import argparse
import importlib
import json
from pathlib import Path

from bench.slice2.audit import audit_reads, qualify
from bench.slice2.budget import admit
from bench.slice2.protocol import ARMS, DECLARED, ROOT, config, digest, identity, recipe, schedule, stage


def write_new(path, value):
    with Path(path).open('x') as out:
        out.write(json.dumps(value,indent=2,sort_keys=True)+'\n')


def execute_cell(cell, directory, executor):
    directory.mkdir(parents=True,exist_ok=False)
    stage(cell['case'],directory/'work')
    launch = cell | dict(identity=identity(),model='glm-5.3',provider='zai',
                        endpoint='https://api.z.ai/api/coding/paas/v4',plan='coding',
                        config=config(cell['arm']),recipe=recipe(cell['arm']),wall_limit_s=900,
                        max_children=4,workspace=str(directory/'work'))
    write_new(directory/'launch.json',launch)
    # An interrupted or failed uncheckpointed executor is preserved, never rerun.
    result = executor(launch,directory)
    if result.get('cell') != cell['cell'] or result.get('slice') != 'slice2':
        raise ValueError('Executor identity mismatch')
    result['identity'] = launch['identity']
    write_new(directory/'cell.json',result)
    return result


def run_phase(phase, evidence, executor, limits=None):
    evidence = Path(evidence).resolve()
    if 'slice1' in evidence.parts:
        raise ValueError('slice1 immutable')
    evidence.mkdir(parents=True,exist_ok=True)
    bound = dict(slice='slice2',identity=identity(),declaration_sha256=digest((DECLARED/'DECLARED.md').read_bytes()))
    checkpoint = evidence/'identity.json'
    if checkpoint.exists():
        if json.loads(checkpoint.read_text()) != bound:
            raise ValueError('Resume identity drift')
    else:
        write_new(checkpoint,bound)
    if phase in {'calibration','scored'}:
        qualification = evidence/'qualification.json'
        if not qualification.exists() or not json.loads(qualification.read_text()).get('pass'):
            raise ValueError('Qualification must pass before calibration/scoring')
    if phase=='qualification':
        protected=evidence/'synthetic-protected-read'
        allowed=evidence/'allowed-marker'
        preserved={'protected':{'path':str(protected),'success':True},'allowed':{'path':str(allowed),'success':True}}
        control_path=evidence/'audit-controls.json'
        if not control_path.exists(): write_new(control_path,preserved)
        if json.loads(control_path.read_text())!=preserved:
            raise ValueError('Audit control drift')
        if audit_reads([preserved['protected']],[protected],evidence)['pass'] or not audit_reads([preserved['allowed']],[protected],evidence)['pass']:
            raise ValueError('Audit detection controls failed')
    if phase == 'scored':
        measurements = json.loads((evidence/'calibration.json').read_text())
        decision = admit(measurements,limits or {})
        if decision['decision'] != 'ADMIT':
            raise ValueError('Budget DEFER: no scored selection/trim permitted')
    if phase == 'qualification':
        cells = [dict(slice='slice2',phase=phase,case='dev01-seats',arm=a,rep=1,
                      cell='qualification-'+a,seed=1402) for a in ARMS]
    else:
        cells = schedule(phase)
    output, rows = evidence/(phase+'.json'), []
    for cell in cells:
        destination = evidence/cell['cell']
        if (destination/'cell.json').exists():
            result = json.loads((destination/'cell.json').read_text())
            if result.get('identity') != bound['identity']:
                raise ValueError('Cell resume identity drift')
        elif destination.exists():
            raise ValueError('Interrupted attempt preserved: manual disposition required')
        else:
            result = execute_cell(cell,destination,executor)
        rows.append(result)
        if result.get('quota') or result.get('integrity_violation') or result.get('status')=='HARNESS_ERROR':
            raise ValueError('Stop receipt preserved; no automatic provider fallback or cell retry')
    value = qualify(rows) if phase=='qualification' else rows
    if output.exists():
        if json.loads(output.read_text()) != value:
            raise ValueError('Completed phase mismatch')
    else:
        write_new(output,value)
    return value


def main():
    p=argparse.ArgumentParser(description='Slice2 phase harness; explicit executor, no automatic live calls')
    p.add_argument('--phase',choices=['qualification','calibration','scored'],required=True)
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--executor',required=True,help='Approved module:callable implementing the cell receipt contract')
    p.add_argument('--limits',type=Path)
    a=p.parse_args()
    if Path.cwd().resolve()!=ROOT: raise SystemExit('Use the declared worktree')
    module,symbol=a.executor.split(':',1)
    executor=getattr(importlib.import_module(module),symbol)
    limits=json.loads(a.limits.read_text()) if a.limits else None
    value=run_phase(a.phase,a.evidence,executor,limits)
    print(json.dumps(value,sort_keys=True))


if __name__ == '__main__':
    main()
