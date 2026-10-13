"""
A small JSON Schema validator: the subset fixtures/console/console_types.
schema.json uses (type, required, properties, additionalProperties,
propertyNames, items, enum, $ref into $defs). Written here rather than
adding jsonschema to requirements for one test file; the schema itself is
standard draft 2020-12, so 2C can validate the same file with a full
implementation.
"""
import json
import os

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'console_types.schema.json')
with open(SCHEMA_PATH) as fh:
    SCHEMA = json.load(fh)

_TYPES = {
    'string': str, 'boolean': bool, 'object': dict, 'array': list, 'null': type(None),
    'number': (int, float), 'integer': int,
}


def _type_ok(value, name):
    if name in ('number', 'integer') and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def errors(value, schema, path='$'):
    if '$ref' in schema:
        name = schema['$ref'].rsplit('/', 1)[-1]
        return errors(value, SCHEMA['$defs'][name], path)
    out = []
    if 'enum' in schema and value not in schema['enum']:
        out.append(f"{path}: {value!r} not in {schema['enum']}")
    if 'type' in schema:
        names = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not any(_type_ok(value, n) for n in names):
            return out + [f"{path}: {type(value).__name__} is not {names}"]
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                out.append(f"{path}: missing {key!r}")
        props = schema.get('properties', {})
        for key, sub in value.items():
            if key in props:
                out.extend(errors(sub, props[key], f"{path}.{key}"))
            elif isinstance(schema.get('additionalProperties'), dict):
                out.extend(errors(sub, schema['additionalProperties'], f"{path}.{key}"))
            if 'propertyNames' in schema:
                out.extend(errors(key, schema['propertyNames'], f"{path}[key {key!r}]"))
    if isinstance(value, list) and 'items' in schema:
        for i, item in enumerate(value):
            out.extend(errors(item, schema['items'], f"{path}[{i}]"))
    return out


def check(value, type_name):
    problems = errors(value, {'$ref': f'#/$defs/{type_name}'})
    assert not problems, '\n'.join(problems[:20])
