"""Live checks run inside this project's isolated worker via its Unix RPC socket."""
import base64
import json
import sys

import httpx

URL = 'https://docs.python.org/3/library/urllib.parse.html'
client = httpx.Client(transport=httpx.HTTPTransport(uds='/rpc/worker.sock'), base_url='http://worker',
                     trust_env=False, timeout=85)
failures = []


def job(action, request):
    response = client.post('/run', json={'action': action, 'request': request})
    response.raise_for_status()
    return response.json()


def browser(action, **params):
    response = client.post('/browser', json={'action': action, 'params': params})
    response.raise_for_status()
    value = response.json()
    assert not value.get('error'), value.get('error')
    return value


def check(name, operation):
    try:
        detail = operation()
        print(json.dumps({'check': name, 'status': 'passed', 'detail': detail}), flush=True)
    except Exception as exc:
        failures.append(name)
        print(json.dumps({'check': name, 'status': 'failed', 'error': str(exc)}), flush=True)


def read(strategy, profile):
    value = job('read', {'url': URL, 'strategy': strategy, 'browser_profile': profile})
    assert 'result' in value, value.get('error')
    result = value['result']
    assert 'urlsplit' in result['markdown'] and len(result['markdown']) > 10000
    return {'method': result['method'], 'characters': len(result['markdown'])}


for strategy, profile in [('light', 'standard'), ('standard', 'standard'), ('browser', 'standard'), ('browser', 'stealth')]:
    check(f'read-{strategy}-{profile}', lambda s=strategy, p=profile: read(s, p))


def pdf():
    value = job('convert', {'url': 'https://www.energy.gov/sites/default/files/2023-07/Technology%20Strategy%20Assessment%20-%20Sodium%20Batteries.pdf'})
    assert 'result' in value, value.get('error')
    data = value['result']
    assert data['suffix'] == '.pdf' and '## Page 1' in data['markdown']
    assert base64.b64decode(data['original_base64']).startswith(b'%PDF-')
    return {'characters': len(data['markdown'])}


check('pdf', pdf)


def rss():
    value = job('feed', {'feed_url': 'https://blog.python.org/feeds/posts/default?alt=rss'})
    assert 'result' in value, value.get('error')
    assert value['result']['entries']
    return {'entries': len(value['result']['entries'])}


check('rss', rss)


def denied(strategy, profile):
    value = job('read', {'url': 'http://169.254.169.254/', 'strategy': strategy, 'browser_profile': profile})
    assert 'error' in value and 'result' not in value
    return value['error']['code']


for strategy, profile in [('light', 'standard'), ('standard', 'standard'), ('browser', 'stealth')]:
    check(f'denied-{strategy}-{profile}', lambda s=strategy, p=profile: denied(s, p))


def interaction():
    opened = browser('open', url=URL, profile='standard')
    sid = opened['session_id']
    assert len(sid) == 35
    try:
        assert 'urlsplit' in browser('text', session_id=sid, max_chars=50000)['text']
        assert browser('find', session_id=sid, query='security')['matches'] > 0
        observed = browser('observe', session_id=sid, include_screenshot=True)
        assert base64.b64decode(observed['screenshot_base64']).startswith(b'\x89PNG')
        refs = [n['ref'] for n in observed['snapshot']]
        assert len(refs) == len(set(refs))
        browser('scroll', session_id=sid, direction='down', amount=300)
        browser('wait', session_id=sid, ms=100)
        page = browser('goto', session_id=sid, url='https://docs.python.org/3/search.html')
        inputs = [n for n in page['snapshot'] if n['tag'] == 'input' and n['role'] not in {'button', 'checkbox', 'radio'}]
        assert inputs, 'Search field not found'
        browser('type', session_id=sid, ref=inputs[0]['ref'], text='urllib', clear=True)
        browser('press', session_id=sid, key='Enter', wait_ms=2000)
        page = browser('wait', session_id=sid, ms=3000)
        links = [n for n in page['snapshot'] if n['role'] == 'link' and any(
            a.startswith('url=https://docs.python.org/3/library/urllib.parse.html') for a in n['attrs'])]
        assert links, 'Search result link not found'
        clicked = browser('click', session_id=sid, ref=links[0]['ref'])
        assert '/library/urllib.parse.html' in clicked['url']
        assert any(s['session_id'] == sid for s in browser('sessions')['sessions'])
        return {'session_handle_bits': 128, 'screenshot': 'PNG', 'search_form_and_click': 'ok'}
    finally:
        browser('close', session_id=sid)
        browser('close_all')
        assert not browser('sessions')['sessions']


check('browser-interaction', interaction)
client.close()
sys.exit(bool(failures))
