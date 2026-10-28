"""Prepare document bytes/text before storage. Hosted mode always uses the isolated worker."""
import base64

import httpx

from .config import settings
from .errors import GatewayError
from .models import DocumentStrategy


async def prepare_document(req):
    if req.strategy != DocumentStrategy.text:
        raise GatewayError('document_strategy_not_implemented', 'Structured document conversion is not implemented', status_code=400)
    if settings.worker_socket:
        from research_mcp_service.worker_client import get_worker
        data = await get_worker(settings.worker_socket).run('convert', req.model_dump(mode='json'))
        if data['suffix'] not in {'.pdf', '.txt', '.md', '.html', '.htm', '.docx', '.pptx'}:
            raise GatewayError('invalid_worker_result', 'Worker returned an unsupported document type', status_code=502)
        return (base64.b64decode(data['original_base64'], validate=True), data['content_type'],
                data['suffix'], data['markdown'], data.get('conversion_metadata', {}))

    # Retained standalone-library path; the hosted gateway must configure WORKER_SOCKET.
    from .services import _suffix_for_document, _convert_document_content
    url = str(req.url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            response = await client.get(url, headers={'User-Agent': 'local-web-research-gateway/0.1'})
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise GatewayError('fetch_bad_status', 'Document URL returned an unsuccessful HTTP status',
                           status_code=502, http_status=exc.response.status_code) from None
    except httpx.HTTPError:
        raise GatewayError('fetch_failed', 'Could not fetch document URL', status_code=502) from None
    content_type = response.headers.get('content-type')
    suffix = _suffix_for_document(url, content_type)
    try:
        markdown = await _convert_document_content(response.content, suffix)
    except Exception:
        raise GatewayError('document_conversion_failed', 'Could not convert document', status_code=502) from None
    from .pdf_links import link_metadata
    return response.content, content_type, suffix, markdown, link_metadata(response.content, suffix)
