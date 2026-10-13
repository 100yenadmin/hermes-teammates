"""Fail-closed preserved read evidence and four-child qualification acceptance."""
from pathlib import Path


def audit_reads(records, protected, run):
    protected = [Path(p).resolve() for p in protected]
    run = Path(run).resolve()
    errors = []
    if not records:
        errors.append('read evidence absent')
    for row in records:
        if not row.get('path') or type(row.get('success')) is not bool:
            errors.append('unclassified read'); continue
        path = Path(row['path']).resolve()
        forbidden = any(path == p or path.is_relative_to(p) for p in protected)
        if row['success'] and (forbidden or not path.is_relative_to(run)):
            errors.append('successful protected read')
        if not row['success'] and forbidden and row.get('error') not in {'EACCES','EPERM'}:
            errors.append('missing file is not denial')
    return {'pass': not errors, 'errors': errors}


def recipe_errors(b):
    """Effective per-batch recipe, shared by qualification and every later cell."""
    errors = []
    if b.get('observer_errors'):
        errors.append('observer error')
    children = b.get('children', [])
    if b.get('arm') not in {'B-briefed', 'C'}:
        errors.append('unknown arm')
    if b.get('peak_concurrency') != 4 or b.get('fanout_batches') != 1:
        errors.append('four-child single batch unproven')
    if len(children) != 4 or len({c.get('session_id') for c in children if c.get('session_id')}) != 4:
        errors.append('four distinct children required')
    if b.get('no_teammate_check') is not True:
        errors.append('forbidden teammate_check or absent tool evidence')
    if b.get('parent_max_turns') != 40 or b.get('parent_compression') is not True:
        errors.append('effective parent settings unproven')
    for c in children:
        if not (c.get('completed') is True and c.get('effective_launch') and c.get('wrapper')
                and c.get('matched_brief') is True and c.get('tools') == ['file', 'terminal']
                and c.get('max_turns') == 250 and c.get('compression') is True):
            errors.append('child recipe incomplete')
    if b.get('arm') == 'C' and (b.get('wait_complete') is not True or b.get('full_wait_ids') is not True):
        errors.append('wait recipe incomplete')
    return errors


def valid_cell(b):
    accounting = b.get('accounting')
    return (b.get('status') in {'COMPLETE', 'FAILED'} and b.get('recipe_valid') is True
            and b.get('integrity') is True and b.get('audit', {}).get('pass') is True
            and (accounting is True or isinstance(accounting, dict) and accounting.get('pass') is True)
            and not b.get('observer_errors') and not b.get('quota') and not b.get('integrity_violation'))


def qualify(batches):
    errors = []
    if [b.get('arm') for b in batches] != ['B-briefed','C']:
        errors.append('qualification must be core then C')
    previous_end = None
    for b in batches:
        errors.extend(recipe_errors(b))
        if b.get('status') != 'COMPLETE':
            errors.append('qualification batch not COMPLETE')
        if previous_end is not None and b.get('started', -1) < previous_end:
            errors.append('batches overlap')
        previous_end = b.get('ended', float('inf'))
        if b.get('accounting',{}).get('pass') is not True or b.get('audit',{}).get('pass') is not True or b.get('integrity') is not True:
            errors.append('accounting or integrity failed')
        if not b.get('outside_readable') or not b.get('parent_denials') or not b.get('parent_allowed_read'):
            errors.append('parent/outside positive controls incomplete')
        for c in b.get('children', []):
            if not all(c.get(k) is True for k in ('os_denials_file', 'os_denials_terminal', 'allowed_read', 'sandbox_inherited')):
                errors.append('child recipe/OS controls incomplete')
    return {'pass': not errors, 'errors': errors}
