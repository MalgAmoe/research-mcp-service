"""Deterministic lookup in cleaned cached Markdown, without changing extraction."""
import re


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
    headings = []
    offset = 0
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None:
            match = re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line.rstrip('\n\r'))
            if match:
                headings.append((offset, len(match.group(1)), match.group(2)))
        offset += len(line)
    matches = [i for i, (_, _, title) in enumerate(headings) if heading.casefold() in title.casefold()]
    if len(matches) < occurrence:
        return None, len(matches)
    index = matches[occurrence - 1]
    start, level, title = headings[index]
    end = next((pos for pos, depth, _ in headings[index + 1:] if depth <= level), len(text))
    return {'start': start, 'end': end, 'heading': title, 'match_offset': start}, len(matches)
