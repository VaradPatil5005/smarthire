"""The hidden-text scanner. It runs in a child process and imports nothing from Django.

Detection works on the file's rendering instructions and on rendered pixels, because once text is
extracted hidden text looks exactly like normal text. A hit excludes the text and asks a human; it
is never proof of cheating and never changes a score.

Visibility is decided per word, not per line, so covering one keyword in a long line still excludes
that keyword. A word counts as visible only if all of these hold:

- it contrasts with the most common colour inside its own box, with opacity composited in;
- no opaque shape or image is painted over it later in the page's paint order;
- most of its letters leave ink close to their own colour in their own box.

Proof layers (D-011): vectors 1 to 8 and 10 to 12 are proved here. Visible manipulation is a note
only. Repetition is a scoring property, negation an extractor rule. Font remapping (vector 13) needs
the render-and-OCR diff in ocr_core.py, so this fast pass does not claim to catch it.
"""

import re
import unicodedata
import zlib
from collections import Counter
from dataclasses import dataclass

import pymupdf

RENDER_MODE_INVISIBLE = 3
MICRO_FONT_POINTS = 3
MIN_OPACITY = 0.1
METADATA_MAX_CHARS = 150
SCAN_IMAGE_COVERAGE = 0.5
OFF_PAGE_TOLERANCE = 2
RENDER_DPI = 144
BACKGROUND_MARGIN_POINTS = 1
INK_MIN_DISTANCE = 48
INK_FRACTION_OF_CONTRAST = 0.35
VISIBLE_WORD_FRACTION = 0.5
COVERED_CHAR_FRACTION = 0.5
OPAQUE = 0.9
PREVIEW_DPI = 100
COVERING_LOG_ENTRIES = ("fill-path", "fill-image", "fill-imgmask", "fill-shade")
PASSTHROUGH_FILTERS = {"DCTDecode", "JPXDecode", "CCITTFaxDecode", "JBIG2Decode"}

TAG_RANGE = range(0xE0000, 0xE0080)
STRIPPED_RANGES = (
    range(0x200B, 0x2010),
    range(0x202A, 0x202F),
    range(0x2060, 0x2070),
    range(0xFEFF, 0xFF00),
)
SOFT_HYPHEN = 0x00AD
JOINERS = (0x200C, 0x200D)
INDIC_RANGE = range(0x0900, 0x0E00)
MANIPULATION = re.compile(
    r"requirements?\s+(?:have\s+been\s+|were\s+)?updated|ignore\s+(?:all\s+)?previous\s+instructions"
    r"|rank\s+(?:this\s+candidate|me)\s+first|vetted\s+by\s+the\s+ceo",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"\S+")
_XMP_VALUE = re.compile(r">([^<>]{151,})<")
_FILTER_NAME = re.compile(r"/(\w+)")


class ScanFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Limits:
    max_pages: int
    max_page_points: int
    max_decompressed_bytes: int
    min_contrast: float
    audit_text_max_chars: int


def _is_stripped(code):
    return code == SOFT_HYPHEN or any(code in r for r in STRIPPED_RANGES)


def _is_indic(char):
    return ord(char) in INDIC_RANGE


def clean_text(text):
    """Return (clean text, tag payload, strip counts). Indic joiners between Indic letters stay."""
    payload = "".join(chr(ord(c) - 0xE0000) for c in text if ord(c) in TAG_RANGE)
    without_tags = "".join(c for c in text if ord(c) not in TAG_RANGE)
    counts = Counter()
    kept = []
    for index, char in enumerate(without_tags):
        code = ord(char)
        if _is_stripped(code):
            before = without_tags[index - 1] if index else ""
            after = without_tags[index + 1] if index + 1 < len(without_tags) else ""
            if code in JOINERS and before and after and _is_indic(before) and _is_indic(after):
                kept.append(char)
                continue
            counts[f"U+{code:04X}"] += 1
            continue
        kept.append(char)
    cleaned = "".join(kept)
    if not any(_is_indic(c) for c in cleaned):
        cleaned = unicodedata.normalize("NFKC", cleaned)
    return cleaned, payload, counts


def _script(char):
    if not char.isalpha():
        return None
    name = unicodedata.name(char, "")
    for script in ("LATIN", "CYRILLIC", "GREEK"):
        if name.startswith(script):
            return script
    return None


def mixed_script_tokens(text):
    """Tokens that mix Latin with Cyrillic or Greek, such as "Pуthon" with a Cyrillic letter."""
    found = []
    for match in _TOKEN.finditer(text):
        scripts = {_script(c) for c in match.group()} - {None}
        if "LATIN" in scripts and len(scripts) > 1:
            found.append(match)
    return found


def _to_rgb(color):
    """Convert a span colour by its component count. CMYK is not RGB: (0,0,0,0) is white."""
    if len(color) == 1:
        return (color[0], color[0], color[0])
    if len(color) == 3:
        return tuple(color)
    if len(color) == 4:
        cyan, magenta, yellow, black = color
        return ((1 - cyan) * (1 - black), (1 - magenta) * (1 - black), (1 - yellow) * (1 - black))
    return (0.0, 0.0, 0.0)


def _luminance(rgb):
    def channel(value):
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(v) for v in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first, second):
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _distance(first, second):
    return sum(abs(a - b) for a, b in zip(first, second, strict=True))


class _PageImage:
    def __init__(self, page):
        self.scale = RENDER_DPI / 72
        # Text traces and drawings use unrotated coordinates; pixmaps honor /Rotate.
        self.rotation = page.rotation_matrix
        pixmap = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csRGB, alpha=False)
        self.width = pixmap.width
        self.height = pixmap.height
        self.stride = pixmap.stride
        self.samples = pixmap.samples

    def _box(self, rect):
        rect = pymupdf.Rect(rect) * self.rotation
        x0 = max(0, int(rect[0] * self.scale))
        y0 = max(0, int(rect[1] * self.scale))
        x1 = min(self.width, int(rect[2] * self.scale) + 1)
        y1 = min(self.height, int(rect[3] * self.scale) + 1)
        return x0, y0, x1, y1

    def _pixel(self, x, y):
        offset = y * self.stride + x * 3
        return (self.samples[offset], self.samples[offset + 1], self.samples[offset + 2])

    def background(self, rect):
        """The most common colour inside the box. Glyphs cover less of it than their background."""
        margin = BACKGROUND_MARGIN_POINTS
        x0, y0, x1, y1 = self._box((rect[0] - margin, rect[1] - margin, rect[2] + margin, rect[3]))
        counts = Counter(self._pixel(x, y) for y in range(y0, y1) for x in range(x0, x1))
        return counts.most_common(1)[0][0] if counts else (255, 255, 255)

    def has_own_ink(self, rect, foreground, background):
        """Pixels near this glyph colour exist in its box. Ink of another colour is no proof."""
        needed = max(INK_MIN_DISTANCE, INK_FRACTION_OF_CONTRAST * _distance(foreground, background))
        x0, y0, x1, y1 = self._box(rect)
        for y in range(y0, y1):
            for x in range(x0, x1):
                pixel = self._pixel(x, y)
                from_background = _distance(pixel, background)
                if (
                    from_background >= needed
                    and _distance(pixel, foreground) < 1.5 * from_background
                ):
                    return True
        return False


def _filters(doc, xref):
    return _FILTER_NAME.findall(doc.xref_get_key(xref, "Filter")[1])


def _declared_image_bytes(doc, xref):
    if doc.xref_get_key(xref, "Subtype")[1] != "/Image":
        return 0
    try:
        width = int(doc.xref_get_key(xref, "Width")[1])
        height = int(doc.xref_get_key(xref, "Height")[1])
    except ValueError as error:
        raise ScanFailure("CORRUPT") from error
    return max(width, 0) * max(height, 0) * 3


def _inflated_size(raw, already, limit):
    """Inflate with a running cap, so a bomb stops before it uses the memory."""
    decoder = zlib.decompressobj()
    pending = raw
    total = 0
    try:
        while pending and not decoder.eof:
            chunk = decoder.decompress(pending, 1024 * 1024)
            total += len(chunk)
            if already + total > limit:
                raise ScanFailure("TOO_MUCH_DATA")
            pending = decoder.unconsumed_tail
            if not chunk and pending:
                break
    except zlib.error as error:
        raise ScanFailure("CORRUPT") from error
    return total


def _check_decompressed_size(doc, limit):
    """Measure every stream. A filter chain this cannot measure fails closed."""
    total = 0
    for xref in range(1, doc.xref_length()):
        if not doc.xref_is_stream(xref):
            continue
        raw = doc.xref_stream_raw(xref) or b""
        filters = _filters(doc, xref)
        if filters == ["FlateDecode"]:
            total += _inflated_size(raw, total, limit)
        elif not filters or (len(filters) == 1 and filters[0] in PASSTHROUGH_FILTERS):
            total += len(raw)
        else:
            raise ScanFailure("TOO_MUCH_DATA")
        total += _declared_image_bytes(doc, xref)
        if total > limit:
            raise ScanFailure("TOO_MUCH_DATA")


def _image_coverage(page):
    area = abs(page.rect)
    if not area:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        covered += abs((pymupdf.Rect(info["bbox"]) * page.rotation_matrix) & page.rect)
    return min(1.0, covered / area)


def _off_layers(doc):
    return [c["number"] for c in doc.layer_ui_configs() if not c["on"]]


def _span_text(span):
    return "".join(chr(char[0]) for char in span["chars"])


def _leaves_ink(code):
    return not (chr(code).isspace() or code in TAG_RANGE or _is_stripped(code))


def _covers(page):
    """Opaque fills and images with their paint order. `seqno` indexes this same log."""
    opacity = {
        d["seqno"]: d["fill_opacity"] if d.get("fill_opacity") is not None else 1.0
        for d in page.get_drawings()
    }
    covers = []
    for seqno, (kind, rect) in enumerate(page.get_bboxlog()):
        if kind in COVERING_LOG_ENTRIES and opacity.get(seqno, 1.0) >= OPAQUE:
            covers.append((seqno, pymupdf.Rect(rect)))
    return covers


def _split_words(span):
    """Split a span into runs of (is_space, chars), so each word is judged on its own."""
    runs = []
    for char in span["chars"]:
        is_space = chr(char[0]).isspace()
        if runs and runs[-1][0] == is_space:
            runs[-1][1].append(char)
        else:
            runs.append((is_space, [char]))
    return runs


def _union(chars):
    rect = pymupdf.Rect(chars[0][3])
    for char in chars[1:]:
        rect |= pymupdf.Rect(char[3])
    return rect


class _Scan:
    def __init__(self, limits):
        self.limits = limits
        self.visible = []
        self.audits = []
        self.scanned_pages = []
        self.strip_counts = Counter()

    def audit(self, vector, text, *, page=None, bbox=None, field_name="", note_only=False):
        self.audits.append(
            {
                "page": page,
                "bbox": list(bbox) if bbox is not None else None,
                "vector": vector,
                "field_name": field_name,
                "text": text[: self.limits.audit_text_max_chars],
                "true_length": len(text),
                "note_only": note_only,
            }
        )

    def _span_reason(self, span, rect, page_rect):
        if span["type"] == RENDER_MODE_INVISIBLE:
            return "RENDER_MODE_3"
        if span["opacity"] < MIN_OPACITY:
            return "ZERO_OPACITY"
        if span["size"] < MICRO_FONT_POINTS:
            return "MICRO_FONT"
        if (
            rect.x0 < page_rect.x0 - OFF_PAGE_TOLERANCE
            or rect.y0 < page_rect.y0 - OFF_PAGE_TOLERANCE
            or rect.x1 > page_rect.x1 + OFF_PAGE_TOLERANCE
            or rect.y1 > page_rect.y1 + OFF_PAGE_TOLERANCE
        ):
            return "OFF_PAGE"
        return None

    def _word_reason(self, chars, span, image, covers):
        printable = [c for c in chars if _leaves_ink(c[0])]
        if not printable:
            return None
        background = image.background(tuple(_union(printable)))
        unit_background = tuple(v / 255 for v in background)
        alpha = span["opacity"]
        composited = tuple(
            alpha * fg + (1 - alpha) * bg
            for fg, bg in zip(_to_rgb(span["color"]), unit_background, strict=True)
        )
        if contrast_ratio(composited, unit_background) < self.limits.min_contrast:
            return "LOW_CONTRAST"
        later = [rect for seqno, rect in covers if seqno > span["seqno"]]
        if later:
            covered = 0
            for char in printable:
                box = pymupdf.Rect(char[3])
                area = abs(box) or 1
                if any(abs(box & rect) / area >= COVERED_CHAR_FRACTION for rect in later):
                    covered += 1
            if covered / len(printable) >= COVERED_CHAR_FRACTION:
                return "OCCLUDED_OR_CLIPPED"
        foreground = tuple(v * 255 for v in composited)
        inked = sum(1 for c in printable if image.has_own_ink(c[3], foreground, background))
        if inked / len(printable) < VISIBLE_WORD_FRACTION:
            return "OCCLUDED_OR_CLIPPED"
        return None

    def hidden_layers(self, doc, off_layers):
        """MuPDF leaves switched-off layers out of extraction, so compare with them forced on."""
        baseline = {
            number: Counter(_span_text(s) for s in page.get_texttrace())
            for number, page in enumerate(doc, start=1)
        }
        for number in off_layers:
            doc.set_layer_ui_config(number, 1)
        for number, page in enumerate(doc, start=1):
            remaining = Counter(baseline[number])
            for span in page.get_texttrace():
                text = _span_text(span)
                if remaining[text] > 0:
                    remaining[text] -= 1
                elif text.strip():
                    box = pymupdf.Rect(span["bbox"]) * page.rotation_matrix
                    self.audit("HIDDEN_LAYER", text, page=number, bbox=tuple(box))

    def page(self, page, number):
        traces = [s for s in page.get_texttrace() if _span_text(s).strip()]
        if not traces:
            if _image_coverage(page) >= SCAN_IMAGE_COVERAGE:
                self.scanned_pages.append(number)
            return
        invisible = all(s["type"] == RENDER_MODE_INVISIBLE for s in traces)
        if invisible and _image_coverage(page) >= SCAN_IMAGE_COVERAGE:
            self.scanned_pages.append(number)
            return
        image = _PageImage(page)
        covers = _covers(page)
        unrotated_page = page.rect * page.derotation_matrix
        for span in traces:
            rect = pymupdf.Rect(span["bbox"])
            reason = self._span_reason(span, rect, unrotated_page)
            if reason:
                box = rect * page.rotation_matrix
                self.audit(reason, _span_text(span), page=number, bbox=tuple(box))
                continue
            self._judge_words(span, rect, number, image, covers)

    def _judge_words(self, span, rect, number, image, covers):
        kept = []
        hidden = {}
        for is_space, chars in _split_words(span):
            text = "".join(chr(c[0]) for c in chars)
            reason = None if is_space else self._word_reason(chars, span, image, covers)
            if reason:
                words, box = hidden.get(reason, ([], None))
                words.append(text)
                box = _union(chars) if box is None else box | _union(chars)
                hidden[reason] = (words, box)
            else:
                kept.append(text)
        for reason, (words, box) in hidden.items():
            self.audit(reason, " ".join(words), page=number, bbox=tuple(box * image.rotation))
        self._visible_span("".join(kept), rect * image.rotation, number)

    def _visible_span(self, text, rect, number):
        cleaned, payload, counts = clean_text(text)
        self.strip_counts.update(counts)
        if payload:
            self.audit("UNICODE_TAGS", payload, page=number, bbox=tuple(rect))
        for match in reversed(mixed_script_tokens(cleaned)):
            self.audit("HOMOGLYPH", match.group(), page=number, bbox=tuple(rect))
            cleaned = cleaned[: match.start()] + cleaned[match.end() :]
        cleaned = cleaned.strip()
        if not cleaned:
            return
        if MANIPULATION.search(cleaned):
            self.audit("VISIBLE_MANIPULATION", cleaned, page=number, note_only=True)
        self.visible.append({"page": number, "bbox": list(rect), "text": cleaned})

    def metadata(self, doc):
        for name, value in (doc.metadata or {}).items():
            if value and len(value) > METADATA_MAX_CHARS:
                self.audit("METADATA", value, field_name=str(name), note_only=True)
        xmp = doc.get_xml_metadata() or ""
        for value in _XMP_VALUE.findall(xmp):
            self.audit("METADATA", value, field_name="xmp", note_only=True)

    def result(self, pages, page_sizes):
        offset = 0
        parts = []
        spans = []
        for span in self.visible:
            spans.append({**span, "start": offset, "end": offset + len(span["text"])})
            parts.append(span["text"])
            offset += len(span["text"]) + 1
        flagged = any(not audit["note_only"] for audit in self.audits)
        return {
            "status": "FLAGGED" if flagged else "CLEAN",
            "pages": pages,
            "page_sizes": page_sizes,
            "visible_text": "\n".join(parts),
            "visible_spans": spans,
            "audits": self.audits,
            "scanned_pages": self.scanned_pages,
            "strip_counts": dict(self.strip_counts),
        }


def scan_pdf(path, limits, preview_dir=None):
    """Scan one file and return a JSON-safe result. Raises ScanFailure with a failure code."""
    pymupdf.TOOLS.mupdf_display_errors(False)
    try:
        doc = pymupdf.open(path, filetype="pdf")
    except Exception as error:
        raise ScanFailure("CORRUPT") from error
    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise ScanFailure("ENCRYPTED")
        if doc.page_count == 0:
            raise ScanFailure("CORRUPT")
        if doc.page_count > limits.max_pages:
            raise ScanFailure("TOO_MANY_PAGES")
        for page in doc:
            rect = page.rect
            if max(rect.width, rect.height) > limits.max_page_points:
                raise ScanFailure("PAGE_TOO_LARGE")
        _check_decompressed_size(doc, limits.max_decompressed_bytes)
        scan = _Scan(limits)
        for number, page in enumerate(doc, start=1):
            scan.page(page, number)
            if preview_dir:
                page.get_pixmap(dpi=PREVIEW_DPI).save(f"{preview_dir}/page-{number}.png")
        scan.metadata(doc)
        off_layers = _off_layers(doc)
        if off_layers:
            scan.hidden_layers(doc, off_layers)
        sizes = [[round(page.rect.width, 2), round(page.rect.height, 2)] for page in doc]
        return scan.result(doc.page_count, sizes)
