"""Deterministic navigation in cleaned cached Markdown; offsets are characters."""
import re


def heading_index(text):
    headings = []
    offset = 0
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if marker:
            token, rest = marker.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not rest.strip():
                fence = None
        elif fence is None:
            match = re.match(r'^ {0,3}(#{1,6})[ \t]+(.+?)\s*$', line.rstrip('\n\r'))
            if match:
                title = re.sub(r'[ \t]+#+[ \t]*$', '', match.group(2))
                headings.append({'offset': offset, 'level': len(match.group(1)), 'title': title})
        offset += len(line)
    return headings


def locate(text, heading=None, query=None, occurrence=1):
    if heading is not None and query is not None:
        raise ValueError('Choose heading or query, not both.')
    if not (heading or query):
        raise ValueError('Provide a nonempty heading or query.')
    if query is not None:
        matches = list(re.finditer(re.escape(query), text, flags=re.I))
        if len(matches) < occurrence:
            return None, len(matches)
        match = matches[occurrence - 1]
        return {'start': max(0, match.start() - 300), 'end': len(text),
                'match_offset': match.start()}, len(matches)
    headings = heading_index(text)
    matches = [i for i, item in enumerate(headings) if heading.casefold() in item['title'].casefold()]
    if len(matches) < occurrence:
        return None, len(matches)
    index = matches[occurrence - 1]
    selected = headings[index]
    end = next((item['offset'] for item in headings[index + 1:] if item['level'] <= selected['level']), len(text))
    return {'start': selected['offset'], 'end': end, 'heading': selected['title'],
            'match_offset': selected['offset']}, len(matches)
