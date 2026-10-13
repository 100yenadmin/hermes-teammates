"""Bounded isolated reproducer execution. Oracle/reference packs are never mounted.

Only a staged variant and submitted proof code enter each owned execution root.
macOS uses the same read-deny profile as slice1, with network also denied.
"""
import json
import os
import resource
import subprocess
from pathlib import Path

from bench.drivers.hermes_cell import sandbox_profile
from bench.slice2.protocol import TASK, stage


def oracle(case):
    return json.loads((TASK/'hidden/oracles.json').read_text())[case]


def variant(case, directory, bug=None, corrected=False):
    stage(case,directory/'work')
    o=oracle(case)
    patches = o['bugs'] if corrected else [bug] if bug else []
    # Longest anchors first handles a whole-expression correction containing a unit correction.
    for patch in sorted(patches,key=lambda p:len(p['old']),reverse=True):
        file=directory/'work/src'/patch['file']
        text=file.read_text()
        if patch['old'] not in text: raise ValueError('Reference anchor drift')
        file.write_text(text.replace(patch['old'],patch['new']))
    if corrected:
        for file,old,new in o.get('reference_extra',[]):
            p=directory/'work/src'/file; p.write_text(p.read_text().replace(old,new))
    return directory/'work'


def reproduce(work, code, python, sandbox=True):
    work=Path(work).resolve()
    if (work.parent/'proof.py').exists(): raise ValueError('Fresh variant required')
    proof=work.parent/'proof.py'
    proof.write_text('import sys\nsys.path.insert(0,"src")\n'+code+'\n')
    command=[str(python),'-B',str(proof)]
    if sandbox:
        profile=work.parent/'proof.sb'
        executable=Path(python).absolute()
        permitted={Path('/Users/m1/repos/worktrees')/name/'.venv/bin/python'
                   for name in ('hermes-main-venv','hermes-teammates-upstream-pin')}
        if executable not in permitted: raise ValueError('Unqualified proof interpreter')
        venv=executable.parent.parent
        metadata=' '.join('(literal '+json.dumps(str(p))+')' for p in venv.parents)
        profile.write_text(sandbox_profile(work.parent)+'(deny network*)\n'
                           +'(allow file-read* (subpath '+json.dumps(str(venv))+'))\n'
                           +'(allow file-read-metadata '+metadata+')\n')
        command=['/usr/bin/sandbox-exec','-f',str(profile)]+command
    def bound():
        resource.setrlimit(resource.RLIMIT_CPU,(2,2))
        resource.setrlimit(resource.RLIMIT_FSIZE,(65536,65536))
    try:
        result=subprocess.run(command,cwd=work,env={'PATH':'/usr/bin:/bin','HERMES_DISABLE_LAZY_INSTALLS':'1'},
                              stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=5,preexec_fn=bound)
        # Return classification only, never raw execution contents.
        return dict(passed=result.returncode==0,returncode=result.returncode,
                    invalid=result.returncode in (71,127) or any(s in result.stderr for s in (b'SyntaxError',b'ModuleNotFoundError',b'ImportError')),
                    sandbox=sandbox)
    except subprocess.TimeoutExpired:
        return dict(passed=False,invalid=True,timeout=True,sandbox=sandbox)
