"""Model-facing search output, separate from provider routing diagnostics."""
from copy import deepcopy


def present_search(result: dict, diagnostics: bool = False) -> dict:
    items = deepcopy(result.get('results', []))
    if not diagnostics:
        for item in items:
            item.pop('engines', None)
    output = {'query': result['query'], 'results': items, 'returned_count': len(items)}
    notes = []
    attempts = result.get('attempts', [])
    if result.get('provider') == 'ddgs' and any(a.get('provider') == 'searxng' for a in attempts):
        notes.append('Used the backup search provider.')
    if not items:
        output['message'] = ('Search is temporarily unavailable. Please retry.'
                             if result.get('status') == 'unavailable' else 'No results were returned for this search.')
    if result.get('truncation'):
        notes.append('Some text was shortened or results omitted to stay within response limits.')
    # Keep limitations affecting the requested search visible, but not routine
    # infrastructure/provenance bookkeeping.
    for warning in result.get('warnings', []):
        if not warning.startswith('DDGS per-result engine provenance'):
            notes.append(warning)
    if notes:
        output['notes'] = notes
    if diagnostics:
        output['diagnostics'] = {key: deepcopy(result[key]) for key in (
            'provider', 'status', 'attempts', 'engine_failures', 'error_code',
            'requested_limit', 'truncation', 'warnings') if key in result}
    return output
