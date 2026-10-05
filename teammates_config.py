"""Pure, non-fatal validation of operator settings."""
import re

DEFAULTS = {'teammates': {}, 'lane': 'teammates', 'claim_ttl_seconds': 900,
            'max_live_runs': 4, 'followup_context_chars': 8000}
FIELDS = {'description', 'instructions', 'toolsets', 'model', 'route', 'reasoning_effort'}
NAME = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')


def parse(raw):
    errors, teammates = [], {}
    if not isinstance(raw, dict):
        raw = {}
        errors.append('settings must be a dict')
    result = dict(DEFAULTS)
    for key in raw.keys() - DEFAULTS.keys():
        errors.append(f'unknown setting: {key}')
    for key, low, high in [('claim_ttl_seconds', 60, 86400), ('max_live_runs', 1, 16),
                           ('followup_context_chars', 0, 24000)]:
        value = raw.get(key, DEFAULTS[key])
        if type(value) is int and low <= value <= high:
            result[key] = value
        else:
            errors.append(f'{key}: expected integer {low}..{high}; using default')
    lane = raw.get('lane', 'teammates')
    if isinstance(lane, str) and lane.strip():
        result['lane'] = lane
    else:
        errors.append('lane: expected non-empty string; using default')
    configured = raw.get('teammates', {})
    if not isinstance(configured, dict):
        errors.append('teammates must be a dict')
        configured = {}
    for name, values in configured.items():
        if not isinstance(name, str) or not NAME.fullmatch(name):
            errors.append(f'invalid teammate name: {name}')
            continue
        if not isinstance(values, dict):
            errors.append(f'{name}: expected dict')
            continue
        teammate = {'description': '', 'instructions': '', 'toolsets': None,
                    'model': None, 'route': None, 'reasoning_effort': None}
        for key in values.keys() - FIELDS:
            errors.append(f'{name}: unknown key {key}')
        for key, limit in [('description', 300), ('instructions', 4000)]:
            value = values.get(key, '')
            if isinstance(value, str):
                teammate[key] = value[:limit]
                if len(value) > limit:
                    errors.append(f'{name}.{key}: clipped to {limit}')
            else:
                errors.append(f'{name}.{key}: expected string')
        for key in ('model', 'route', 'reasoning_effort'):
            value = values.get(key)
            if value is None or isinstance(value, str):
                teammate[key] = value
            else:
                errors.append(f'{name}.{key}: expected string or None')
        toolsets = values.get('toolsets')
        if toolsets is None or (isinstance(toolsets, list) and all(isinstance(t, str) for t in toolsets)):
            teammate['toolsets'] = toolsets
        else:
            errors.append(f'{name}.toolsets: expected list of strings')
        teammates[name] = teammate
    result.update(teammates=teammates, config_errors=errors)
    return result


def read(ctx):
    return {key: ctx.get_config(key, default) for key, default in DEFAULTS.items()}
