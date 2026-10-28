"""Assert the deployed MCP wire format while decoding tool results."""
import json


def tool_data(result):
    assert 'structuredContent' not in result, 'Unexpected duplicate structured output'
    text = [item['text'] for item in result['content'] if item['type'] == 'text']
    assert len(text) == 1, 'Expected exactly one textual representation'
    return json.loads(text[0])
