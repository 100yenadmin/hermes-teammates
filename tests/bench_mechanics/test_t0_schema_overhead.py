"""M0: measure the actual serialized model-facing surface, without a size bar."""
import json


def test_schema_overhead(mount, metrics):
    from model_tools import get_tool_definitions
    try:
        import tiktoken
    except ImportError:
        encoder = None
        metrics('M0', 'tokens_unavailable', True, 'boolean')
    else:
        encoder = tiktoken.get_encoding('cl100k_base')
    surfaces = {}
    for size in (2, 8):
        rig = mount({'teammates': {f'worker{i}': {} for i in range(size)}})
        try:
            configs = [('file_terminal', ['file', 'terminal']),
                       ('plus_delegation', ['file', 'terminal', 'delegation']),
                       (f'plus_teammates_{size}', ['file', 'terminal', 'delegation', 'teammates'])]
            for name, toolsets in configs:
                if name in surfaces:
                    continue
                definitions = get_tool_definitions(enabled_toolsets=toolsets, quiet_mode=True)
                names = {definition['function']['name'] for definition in definitions}
                assert {'read_file', 'write_file', 'terminal'} <= names
                if 'delegation' in toolsets:
                    assert 'delegate_task' in names
                if 'teammates' in toolsets:
                    assert set(rig.handlers) <= names
                    assign = next(d['function'] for d in definitions if d['function']['name'] == 'teammate_assign')
                    assert all(f'worker{i}' in assign['description'] for i in range(size))
                else:
                    assert not (set(rig.handlers) & names)
                serialized = json.dumps(definitions, separators=(',', ':'), ensure_ascii=False)
                surfaces[name] = len(serialized.encode('utf-8'))
                metrics('M0', name + '_schema_bytes', surfaces[name], 'bytes')
                if encoder is not None:
                    metrics('M0', name + '_schema_tokens', len(encoder.encode(serialized)), 'cl100k_base_tokens')
        finally:
            rig.close()
    assert surfaces['plus_teammates_8'] > surfaces['plus_teammates_2']
    assert len(surfaces) == 4
