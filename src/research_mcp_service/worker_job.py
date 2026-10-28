"""One disposable read/conversion/feed job. No storage operations or credentials."""
import asyncio
import base64
import json
from pathlib import Path
import resource
import sys

from research_gateway.errors import GatewayError
from research_gateway.models import ReadUrlRequest, ConvertDocumentRequest, DocumentStrategy
from research_gateway import services
from .worker_io import download


async def execute(job):
    action = job['action']
    if action == 'read':
        request = ReadUrlRequest.model_validate(job['request'])
        title, markdown, method, strategy, attempts, html = await services._read_with_strategy(request)
        if not markdown.strip():
            raise GatewayError('empty_read', 'No readable content was extracted', status_code=502)
        return dict(title=title, markdown=markdown, method=method, strategy_used=strategy.value,
                    attempts=[a.model_dump(mode='json') for a in attempts], raw_html=html)
    if action == 'convert':
        request = ConvertDocumentRequest.model_validate(job['request'])
        if request.strategy != DocumentStrategy.text:
            raise GatewayError('unsupported_strategy', 'Only text conversion is implemented', status_code=400)
        response = await download(str(request.url))
        content_type = response.headers.get('content-type')
        suffix = services._suffix_for_document(str(response.url), content_type)
        if services._document_method_for_suffix(suffix) == 'unsupported':
            raise GatewayError('unsupported_format', 'Unsupported document format', status_code=400)
        try:
            markdown = await services._convert_document_content(response.content, suffix)
        except Exception:
            raise GatewayError('document_conversion_failed', 'Document conversion failed', status_code=502) from None
        if not markdown.strip():
            raise GatewayError('no_document_text', 'No document text was extracted; OCR is not enabled', status_code=502)
        from research_gateway.pdf_links import link_metadata
        return dict(conversion_metadata=link_metadata(response.content, suffix),
                    original_base64=base64.b64encode(response.content).decode('ascii'),
                    content_type=content_type, suffix=suffix, markdown=markdown,
                    final_url=str(response.url))
    if action == 'feed':
        from pydantic import HttpUrl
        url = str(HttpUrl(job['request']['feed_url']))
        response = await download(url, max_bytes=5 * 1024 * 1024)
        return services._parse_rss_feed(response.text, url)
    raise ValueError('Unknown worker action')


def main():
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    raw = sys.stdin.buffer.read(65537)
    try:
        if len(raw) > 65536:
            raise ValueError('Oversized job')
        result = {'result': asyncio.run(execute(json.loads(raw)))}
    except GatewayError as exc:
        from .error_details import safe_error
        result = {'error': {'code': exc.code, **safe_error({'code': exc.code, **exc.context})}}
    except Exception:
        result = {'error': {'code': 'worker_failed', 'message': 'Worker operation failed'}}
    Path(sys.argv[1]).write_text(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
