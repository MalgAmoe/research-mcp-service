"""Allowlisted failure details; never forward raw exceptions or backend addresses."""
MESSAGES = {
    'fetch_bad_status': 'Website returned an unsuccessful HTTP status.',
    'browser_bad_status': 'Website returned an unsuccessful HTTP status during browser reading.',
    'fetch_failed': 'HTTP fetching failed.',
    'browser_extraction_failed': 'Browser reading failed.',
    'empty_read': 'No readable content was extracted.',
    'worker_busy': 'Worker is busy; retry shortly.',
    'worker_unavailable': 'Worker unavailable or timed out.',
    'download_too_large': 'Download exceeds the configured size limit.',
    'document_conversion_failed': 'Document conversion failed.',
    'no_document_text': 'No extractable document text; OCR is not enabled.',
}


def safe_error(value):
    if not isinstance(value, dict):
        return {}
    code = value.get('code')
    result = {'code': code, 'message': MESSAGES[code]} if code in MESSAGES else {}
    status = value.get('http_status')
    if type(status) is int and 400 <= status <= 599:
        result['http_status'] = status
    return result
