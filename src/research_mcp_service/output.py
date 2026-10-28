"""Model-facing presentation, independent of stored source documents."""
import functools
import inspect
import json
import re

from mcp.types import CallToolResult, TextContent


def clean_text(text):
    return re.sub(r'data:image/[^\s<>"\)]+', '[embedded image omitted]', text, flags=re.I)


def compact_sources(value):
    if isinstance(value, list):
        return [compact_sources(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == 'markdown' and isinstance(item, str):
            if item:
                result['text_available'] = True
                result['text_tool'] = 'web_document'
            continue
        if key == 'excerpt' and isinstance(item, str):
            result[key] = clean_text(item)[:420]
        else:
            result[key] = compact_sources(item)
    return result


class TextOnlyTools:
    """Keep one textual representation on the wire, preserving native images."""
    def __init__(self, server):
        self.server = server

    def __getattr__(self, name):
        return getattr(self.server, name)

    def tool(self, *args, **kwargs):
        register = self.server.tool(*args, **kwargs)
        def decorate(function):
            @functools.wraps(function)
            async def wrapped(*a, **kw):
                result = function(*a, **kw)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, CallToolResult):
                    return result.model_copy(update={'structured_content': None})
                return CallToolResult(content=[TextContent(type='text', text=json.dumps(result, ensure_ascii=False))])
            wrapped.__signature__ = inspect.signature(function, eval_str=True).replace(return_annotation=CallToolResult)
            wrapped.__annotations__ = inspect.get_annotations(function, eval_str=True) | {'return': CallToolResult}
            register(wrapped)
            return function
        return decorate
