"""Pure, non-fatal validation of operator settings."""
import logging
import re
import threading

DEFAULTS = {'teammates': {}, 'lane': 'teammates', 'claim_ttl_seconds': 900,
            'max_live_runs': 4, 'followup_context_chars': 8000, 'notify_on_completion': False}
FIELDS = {'description', 'instructions', 'toolsets', 'model', 'route', 'reasoning_effort'}
NAME = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
# Bounded so that one explained teammate always fits the roster's reply budget.
TOOLSET = re.compile(r'^[!-~]{1,48}$')
MAX_TOOLSETS, MAX_LABEL = 24, 100
logger = logging.getLogger(__name__)
_logged_errors, _log_lock = set(), threading.Lock()


def parse(raw):
    errors, teammates, invalid = [], {}, {}
    if not isinstance(raw, dict):
        raw = {}
        errors.append('settings must be a dict')
    result = dict(DEFAULTS)
    if type(raw.get('notify_on_completion', False)) is bool:
        result['notify_on_completion'] = raw.get('notify_on_completion', False)
    else:
        errors.append('notify_on_completion: expected boolean; using default')
    for key in raw.keys() - DEFAULTS.keys():
        errors.append(f'unknown setting: {key}')
    for key, low, high in [('claim_ttl_seconds', 60, 86400), ('max_live_runs', 1, 16),
                           ('followup_context_chars', 0, 24000)]:
        value = raw.get(key, DEFAULTS[key])
        if type(value) is float and value.is_integer():
            value = int(value)  # JSON/YAML editors may hand back 900.0 for 900
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
            name = str(name)[:300]
            errors.append(f'invalid teammate name: {name}')
            invalid[name] = errors[-1:]
            continue
        if not isinstance(values, dict):
            errors.append(f'{name}: expected dict')
            invalid[name] = errors[-1:]
            continue
        start = len(errors)
        warnings = []
        teammate = {'description': '', 'instructions': '', 'toolsets': None,
                    'model': None, 'route': None, 'reasoning_effort': None}
        for key in values.keys() - FIELDS:
            errors.append(f'{name}: unknown key {key}')
        for key, limit in [('description', 300), ('instructions', 4000)]:
            value = values.get(key, '')
            if isinstance(value, str):
                teammate[key] = value[:limit]
                if len(value) > limit:
                    warnings.append(f'{name}.{key}: clipped to {limit}')
            else:
                errors.append(f'{name}.{key}: expected string')
        for key in ('model', 'route', 'reasoning_effort'):
            value = values.get(key)
            if isinstance(value, str) and not value.strip():
                value = None
            if value is None or isinstance(value, str) and len(value) <= MAX_LABEL:
                teammate[key] = value
            elif isinstance(value, str):
                errors.append(f'{name}.{key}: longer than {MAX_LABEL} characters')
            else:
                errors.append(f'{name}.{key}: expected string or None')
        toolsets = values.get('toolsets')
        if toolsets is None or (isinstance(toolsets, list) and 0 < len(toolsets) <= MAX_TOOLSETS and
                               all(isinstance(t, str) and TOOLSET.fullmatch(t.strip()) for t in toolsets)):
            teammate['toolsets'] = [t.strip() for t in toolsets] if toolsets is not None else None
        else:
            errors.append(f'{name}.toolsets: expected 1-{MAX_TOOLSETS} toolset names, each 1-48 printable ASCII characters without spaces')
        teammates[name] = teammate
        if len(errors) > start:
            invalid[name] = errors[start:]
        errors.extend(warnings)
    with _log_lock:
        for message in errors:
            if message not in _logged_errors:
                _logged_errors.add(message)
                logger.warning('%s', message)
    result.update(teammates=teammates, invalid_teammates=invalid, config_errors=errors)
    return result


def read(ctx):
    return {key: ctx.get_config(key, default) for key, default in DEFAULTS.items()}
