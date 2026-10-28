"""Concise model-facing operational contract, returned by web_capabilities."""
CONTRACT = {
    'workflow': 'Search → fetch selected sources → retrieve saved passages. Use interactive browsing when needed.',
    'success_semantics': 'Operation completed and returned content; completeness, accuracy and fidelity are not verified. Browser observations may precede dynamic results.',
    'routing': 'Use web_read for HTML pages; use web_convert_document for PDF, Office (DOCX/PPTX), TXT and Markdown URLs. Conversion does not follow links.',
    'extraction_tradeoffs': {
        'light': 'Prioritizes speed; static HTTP extraction can lose structure or miss rendered content.',
        'standard': 'Renders Chromium and attempts to retain structure; not a completeness guarantee.',
        'conversion': 'Extracts text; formatting, figures and links may be missing. PDF annotation links have separate coverage/limit metadata.'},
    'cache': {
        'identity': 'Every fresh acquisition gets a new opaque doc_id, even if content is unchanged. Cache hits keep the saved ID.',
        'refresh': 'force_refresh bypasses page cache. Conversion always fetches. New acquisitions do not overwrite previous document IDs or artifacts; explicit retention can delete them.',
        'legacy': 'Earlier prefix-derived IDs remain readable. Versions overwritten before this change cannot be recovered by it.',
        'url_lookup': 'Last saved document for the URL, not a history query; concurrent writes are last-writer-wins.',
        'reuse': 'Only the URL-indexed document is considered. Used strategy must match; auto accepts light/standard/browser. Browser profile must match for browser results. Strategy mismatch fetches anew rather than searching older versions.',
        'timestamps': 'retrieved_at is acquisition time, not publication time; cache hits retain it. content_hash describes extracted Markdown, not full source fidelity.'},
    'rss': {
        'preview': 'Fetches but does not persist feed/entry records or change subscriptions. Preview counts describe returned items, not newly saved entries.',
        'fetch': 'Always contacts the feed and saves a feed record, registering an unknown feed; a failed fetch can also save an error record. force_refresh is currently a compatibility no-op.',
        'content': 'Feed-supplied text, potentially only a summary; linked articles are not fetched. Existing saved entries/read state are not replaced by fetching.',
        'read': 'Reading does not mark read. Use rss_mark_read explicitly.'},
    'browser_timing': 'wait_ms is an extra fixed delay after the action, not a readiness condition. Observe returns current state and replaces refs. Use browser_wait_for for bounded text/element conditions; pre-existing text can match immediately.',
    'browser_lifecycle': 'Sessions are ephemeral, expire after idle time, and are lost on worker/controller resets. Open a new session after expiration. Inspect state before retrying side-effecting actions. close_all affects all sessions on this private owner worker, including other clients using it. Keys are Playwright page keyboard events, not desktop/browser-chrome shortcuts; use browser_back/browser_forward for history.',
    'limits': {
        'batch_urls': 15, 'batch_requested_concurrency': 10, 'worker_job_slots': 2,
        'research_sources': 10, 'passage_default_chars': 12000, 'passage_max_chars': 30000,
        'heading_index_page_entries': 100, 'gateway_json_bytes': 2097152,
        'inline_artifact_bytes': 262144, 'screenshot_bytes': 1048576,
        'browser_sessions_ceiling': 4, 'browser_idle_seconds_ceiling': 1800,
        'browser_condition_wait_max_ms': 10000,
        'recovery': 'Split oversized batches; follow text_range.next_offset or heading_index continuation. Passage slicing still requires the full backend document within its JSON limit. Oversized artifacts cannot be chunked through this API. For screenshots use viewport capture or a smaller viewport. Close idle sessions to free capacity. browser_sessions reports configured session limits.'},
    'health_scope': {
        'mcp_health': 'Authenticated MCP process connectivity and startup source snapshot only; does not probe backends.',
        'gateway_health': 'Control HTTP process responsiveness only.',
        'gateway_health_dependencies': 'Redis ping and MinIO bucket access; not search providers, websites or browser launch.',
        'worker_health': 'Worker HTTP process responsiveness only; not browser launch or external egress.'},
    'error_guidance': 'HTTP status is evidence, not a diagnosis: 403 is not proof of CAPTCHA/blocking, 404 may indicate a missing source. Check URL/access on status errors. Use supported document types for unsupported_format; inspect alternate extraction strategies on conversion/extraction failure. Reduce work or retry later on deadlines/outages without assuming success. Reopen expired sessions; never blindly repeat side effects after browser_reset.',
}
