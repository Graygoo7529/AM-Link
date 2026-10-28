"""Validate the exact wire contract before any domain result is consumed."""
from dataclasses import dataclass
import json
import math

from jsonschema import Draft202012Validator

from .errors import MemoryError
from .text import digest


@dataclass(frozen=True)
class ToolResult:
    name: str
    arguments: dict
    call_id: str
    assistant: dict
    finish_reason: str
    usage: dict
    request_id: str | None

    def __iter__(self):
        yield self.name
        yield self.arguments


def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate key')
        value[key] = item
    return value


def finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('nonfinite number')
    return value


def schema_issue(error):
    expected = error.validator_value
    if isinstance(expected, dict):
        expected = {'keys': list(expected)[:8], 'total': len(expected)}
    elif isinstance(expected, list):
        expected = {'values': [v[:160] if isinstance(v, str) else v if not isinstance(v, (dict, list))
                              else 'schema branch' for v in expected[:8]], 'total': len(expected)}
    elif isinstance(expected, str):
        expected = expected[:160]
    return {'path': list(error.absolute_path), 'schema_path': list(error.absolute_schema_path),
            'constraint': error.validator, 'actual_type': type(error.instance).__name__, 'expected': expected}


def parse_tool(data, tools):
    schemas = {tool['name']: tool['parameters'] for tool in tools}
    diagnostic = {'format_version': 1, 'layer': 'protocol',
                  'schema_fingerprint': digest(schemas), 'response_id': data.get('id')}

    def fail(code, **details):
        raise MemoryError(code, 502, detail={**diagnostic, **details})

    choices = data.get('choices')
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        fail('model_tool_output_invalid', constraint='exactly one choice')
    choice = choices[0]
    diagnostic['finish_reason'] = choice.get('finish_reason')
    if choice.get('finish_reason') in {'length', 'content_filter'}:
        fail('model_output_incomplete', layer='incomplete')
    # Forced named functions can finish with stop while carrying a complete tool call.
    # Stop alone never authorizes content parsing: all call/schema checks below still apply.
    if choice.get('finish_reason') not in {'tool_calls', 'stop'}:
        fail('model_tool_output_invalid', constraint='complete stop or tool_calls finish reason')
    message = choice.get('message')
    calls = message.get('tool_calls') if isinstance(message, dict) else None
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        fail('model_tool_output_invalid', constraint='exactly one tool call')
    call = calls[0]
    if not isinstance(call.get('id'), str) or not call['id'].strip() or call.get('type') != 'function':
        fail('model_tool_output_invalid', constraint='function call with nonempty ID')
    diagnostic['call_id'] = call['id']
    function = call.get('function')
    if not isinstance(function, dict) or not isinstance(function.get('name'), str):
        fail('model_tool_output_invalid', constraint='named function')
    name = function['name']
    if name not in schemas:
        fail('model_unknown_tool', tool=name)
    try:
        arguments = json.loads(function['arguments'], object_pairs_hook=unique_pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite number')),
                               parse_float=finite_float)
    except (KeyError, TypeError, ValueError):
        fail('model_tool_output_invalid', constraint='complete JSON with unique keys and finite numbers')
    validator = Draft202012Validator(schemas[name])
    errors = list(validator.iter_errors(arguments))
    if errors:
        # Paths/keywords are safe metadata; raw values remain only in the private response artifact.
        issues = []
        for error in errors[:12]:
            issue = schema_issue(error)
            if error.context:
                # Show concrete constraints without copying an unbounded anyOf schema.
                issue['causes'] = [schema_issue(e) for e in error.context[:8]]
                issue['cause_count'] = len(error.context)
            issues.append(issue)
        fail('model_tool_schema_invalid', tool=name, errors=issues)
    return ToolResult(name, arguments, call['id'],
                      {'role': 'assistant', 'content': message.get('content'), 'tool_calls': calls},
                      choice['finish_reason'], data.get('usage') or {}, None)
