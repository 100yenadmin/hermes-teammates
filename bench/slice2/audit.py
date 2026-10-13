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


def qualify(batches):
    errors = []
    if [b.get('arm') for b in batches] != ['B-briefed','C']:
        errors.append('qualification must be core then C')
    previous_end = None
    for b in batches:
        if previous_end is not None and b.get('started', -1) < previous_end:
            errors.append('batches overlap')
        previous_end = b.get('ended', float('inf'))
        if b.get('peak_concurrency') != 4 or b.get('fanout_batches') != 1:
            errors.append('four-child single batch unproven')
        if len(b.get('children', [])) != 4 or len({c.get('session_id') for c in b.get('children',[])}) != 4:
            errors.append('four distinct children required')
        if not b.get('accounting',{}).get('pass') or not b.get('audit',{}).get('pass'):
            errors.append('accounting or integrity failed')
        if not b.get('outside_readable') or not b.get('parent_denials') or not b.get('parent_allowed_read'):
            errors.append('parent/outside positive controls incomplete')
        if b.get('parent_max_turns')!=40 or b.get('parent_compression') is not True:
            errors.append('effective parent settings unproven')
        for c in b.get('children', []):
            if not (c.get('completed') and c.get('effective_launch') and c.get('wrapper') and c.get('matched_brief')
                    and c.get('tools') == ['file','terminal'] and c.get('max_turns') == 250
                    and c.get('compression') is True and c.get('os_denials_file')
                    and c.get('os_denials_terminal') and c.get('allowed_read')
                    and c.get('sandbox_inherited')):
                errors.append('child recipe/OS controls incomplete')
        if b.get('arm') == 'C' and (not b.get('wait_complete') or not b.get('full_wait_ids')):
            errors.append('wait recipe incomplete')
    return {'pass': not errors, 'errors': errors}
