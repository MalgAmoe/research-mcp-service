"""PDF link annotations only: never fetch destinations or infer links from text."""
import ctypes


def link_metadata(data, suffix):
    if suffix != '.pdf':
        return {}
    try:
        return {'pdf_links': extract_pdf_links(data)}
    except Exception:
        return {'pdf_links': {'status': 'failed', 'links': [],
                              'coverage': 'Annotation extraction failed; converted text remains available.'}}


def extract_pdf_links(data):
    import pypdfium2 as pdfium
    from pypdfium2 import raw
    result = {'kind': 'pdf_link_annotations', 'links': [], 'status': 'complete',
              'coverage': 'URI actions and direct internal destinations only; excludes printed/image links and other actions.',
              'omitted_annotations': 0, 'limit': 200}
    document = pdfium.PdfDocument(data)
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                position = ctypes.c_int(0)
                link = raw.FPDF_LINK()
                while raw.FPDFLink_Enumerate(page.raw, ctypes.byref(position), ctypes.byref(link)):
                    if len(result['links']) >= 200:
                        result['status'] = 'limited'
                        return result
                    action = raw.FPDFLink_GetAction(link)
                    size = raw.FPDFAction_GetURIPath(document.raw, action, None, 0) if action else 0
                    if 1 < size <= 2049:
                        buffer = ctypes.create_string_buffer(size)
                        raw.FPDFAction_GetURIPath(document.raw, action, buffer, size)
                        result['links'].append({'page': index + 1, 'uri': buffer.value.decode('utf-8', errors='replace')})
                        continue
                    destination = raw.FPDFLink_GetDest(document.raw, link)
                    if destination:
                        target = raw.FPDFDest_GetDestPageIndex(document.raw, destination)
                        if target >= 0:
                            result['links'].append({'page': index + 1, 'destination_page': target + 1})
                            continue
                    result['omitted_annotations'] += 1
            finally:
                page.close()
    finally:
        document.close()
    if result['omitted_annotations']:
        result['status'] = 'partial'
    return result
