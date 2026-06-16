import re
import lxml.html


def parse_bbox_title(bbox_title: str) -> dict:
    """Parses hOCR title attribute into bbox + confidence components.

    Input:  'bbox 23 344 45 66; x_wconf 88'
    Output: {'x1': 23, 'y1': 344, 'x2': 45, 'y2': 66, 'wconf': 88}

    Spec: http://kba.cloud/hocr-spec/1.2/
    """
    result = {'x1': 0, 'y1': 0, 'x2': 0, 'y2': 0, 'wconf': 0}

    bbox_match = re.search(r'bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)', bbox_title)
    if bbox_match:
        result['x1'] = int(bbox_match.group(1))
        result['y1'] = int(bbox_match.group(2))
        result['x2'] = int(bbox_match.group(3))
        result['y2'] = int(bbox_match.group(4))

    wconf_match = re.search(r'x_wconf\s+(\d+)', bbox_title)
    if wconf_match:
        result['wconf'] = int(wconf_match.group(1))

    return result


def extract_words_from(hocr_file) -> list[dict]:
    """Extracts word-level data from an hOCR file.

    Returns list of dicts with keys: text, x1, y1, x2, y2, wconf, title, id
    """
    html = None
    result = []

    with open(hocr_file, "rb") as f:
        text = f.read()
        html = lxml.html.fromstring(text)

    for span in html.xpath("//span[@class='ocrx_word']"):
        title_attr = span.attrib.get('title', '')
        bbox = parse_bbox_title(title_attr)
        word_text = span.text_content().strip()
        if not word_text:
            continue
        elem = {
            'id': span.attrib.get('id', ''),
            'text': word_text,
            'title': title_attr,
            'x1': bbox['x1'],
            'y1': bbox['y1'],
            'x2': bbox['x2'],
            'y2': bbox['y2'],
            'wconf': bbox['wconf'],
        }
        result.append(elem)

    return result
