"""Prepare document bytes/text in the isolated worker before storage."""
import base64

from .config import settings
from .errors import GatewayError


async def prepare_document(req):
    if not settings.worker_socket:
        raise GatewayError('worker_unavailable', 'Document conversion requires the isolated worker', status_code=503)
    from research_mcp_service.worker_client import get_worker
    data = await get_worker(settings.worker_socket).run('convert', req.model_dump(mode='json'))
    if data['suffix'] not in {'.pdf', '.txt', '.md', '.html', '.htm', '.docx', '.pptx'}:
        raise GatewayError('invalid_worker_result', 'Worker returned an unsupported document type', status_code=502)
    return (base64.b64decode(data['original_base64'], validate=True), data['content_type'],
            data['suffix'], data['markdown'], data.get('conversion_metadata', {}))
