"""Live authenticated gateway/storage/worker integration check for this checkout."""
from pathlib import Path
import os
import httpx


def main():
    token = Path('.secrets/gateway-token').read_text().strip()
    with httpx.Client(base_url=os.environ.get('MCP_GATEWAY_URL', 'http://127.0.0.1:18800'), trust_env=False, timeout=90) as client:
        assert client.get('/health').status_code == 401
        client.headers['Authorization'] = 'Bearer ' + token
        assert client.get('/health').status_code == 200
        assert client.post('/research', json={}).status_code == 404
        response = client.post('/read_url', json={'url': 'https://docs.python.org/3/library/urllib.parse.html',
                                                'strategy': 'light', 'include_markdown': True})
        response.raise_for_status()
        data = response.json()
        assert 'urlsplit' in data['markdown']
        print('Authenticated read and storage: passed', flush=True)
        response = client.get('/documents/' + data['doc_id'])
        response.raise_for_status()
        print('Stored document retrieval: passed', flush=True)
        response = client.post('/browser', json={'action': 'sessions', 'params': {}})
        response.raise_for_status()
        assert 'sessions' in response.json()
        print('Browser RPC through authenticated gateway: passed', flush=True)


if __name__ == '__main__':
    main()
