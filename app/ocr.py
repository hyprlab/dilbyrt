# SPDX-License-Identifier: AGPL-3.0-or-later
"""Receipt OCR + field extraction.

Runs Tesseract (via ``pytesseract``) over an uploaded receipt image and
applies heuristics to pull out the fields Dilbyrt tracks. Everything is
best-effort: the parsed values pre-fill the entry form, and the user
corrects anything wrong. If Tesseract isn't installed the module degrades
gracefully — ``ocr_available()`` returns False and the UI falls back to
manual entry.

Kept dependency-light on purpose: Pillow for image loading/upscaling,
pytesseract for the OCR call, and pure-Python regex for parsing.
"""
import re
from datetime import datetime

try:
    import pytesseract
    from PIL import Image, ImageOps, ImageFilter
    _IMPORTS_OK = True
except Exception:  # pragma: no cover - optional at runtime
    _IMPORTS_OK = False


# US state names → 2-letter codes, for city/state extraction.
_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
_STATE_CODES = set(_STATES.values())

_MONEY_RE = re.compile(
    r"(-?\$?\s?\d{1,3}(?:,\d{3})*\.\d{2}"   # 1,234.56 / 12.34
    r"|-?\$?\s?\d+,\d{2}(?!\d))"            # 13,49  (comma used as decimal — OCR/EU)
)
# City, ST 12345  — the classic address-line tail.
_CITY_STATE_RE = re.compile(r"([A-Za-z][A-Za-z .'-]+),\s*([A-Z]{2})\b(?:\s+\d{5})?")
# City ST 12345 — no comma (common on Walmart/Target headers). The ZIP anchors it.
_CITY_ST_ZIP_RE = re.compile(r"\b([A-Za-z][A-Za-z .'-]{1,38}?)\s+([A-Z]{2})\s+\d{5}\b")

_TOTAL_KEYS = ("grand total", "total", "amount due", "balance due", "total sale")
_SUBTOTAL_KEYS = ("subtotal", "sub total", "sub-total", "merchandise")
_TAX_KEYS = ("sales tax", "tax", "gst", "hst", "vat")
_SKIP_ITEM_KEYS = _TOTAL_KEYS + _SUBTOTAL_KEYS + _TAX_KEYS + (
    "change", "cash", "credit", "debit", "visa", "mastercard", "amex",
    "tender", "balance", "payment", "auth", "approval", "card", "account",
    "tip", "gratuity", "discount", "savings", "loyalty", "points",
    "redeemed", "award", "reward",
)


def ocr_available():
    """True when pytesseract + a working tesseract binary are present."""
    if not _IMPORTS_OK:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _otsu_level(gray):
    """Otsu's method: the grey level that best separates dark/bright pixels."""
    h = gray.histogram()
    total = sum(h)
    if total == 0:
        return 128
    sum_all = sum(i * h[i] for i in range(256))
    sumB = 0.0
    wB = 0
    maximum = 0.0
    level = 128
    for i in range(256):
        wB += h[i]
        if wB == 0:
            continue
        wF = total - wB
        if wF == 0:
            break
        sumB += i * h[i]
        between = wB * wF * ((sumB / wB) - ((sum_all - sumB) / wF)) ** 2
        if between >= maximum:
            maximum = between
            level = i
    return level


def _autocrop_receipt(gray):
    """When a receipt is photographed on a dark surface, crop away that dark
    surround so OCR isn't polluted by background texture. Finds the bounding
    box of the bright paper region (Otsu threshold on a downscaled blur) and
    crops to it — but only when the result is a substantial, plausible region;
    otherwise returns the image unchanged."""
    try:
        sw, sh = max(1, gray.width // 4), max(1, gray.height // 4)
        small = gray.resize((sw, sh)).filter(ImageFilter.GaussianBlur(3))
        level = _otsu_level(small)
        mask = small.point(lambda v: 255 if v > level else 0)
        bbox = mask.getbbox()
        if not bbox:
            return gray
        pad = 12
        x0 = max(0, bbox[0] * 4 - pad)
        y0 = max(0, bbox[1] * 4 - pad)
        x1 = min(gray.width, bbox[2] * 4 + pad)
        y1 = min(gray.height, bbox[3] * 4 + pad)
        if x1 - x0 < 40 or y1 - y0 < 40:
            return gray
        frac = ((x1 - x0) * (y1 - y0)) / float(gray.width * gray.height)
        if 0.12 <= frac <= 0.95:      # removed a border, kept the bulk
            return gray.crop((x0, y0, x1, y1))
        return gray
    except Exception:
        return gray


def extract_text(path):
    """Run OCR on an image file and return the raw text (or "" on failure).

    Pipeline tuned for phone photos of receipts, including faded / crumpled
    ones shot on a dark surface: honour EXIF rotation, greyscale, crop to the
    paper, normalise brightness/contrast (autocontrast), upscale, sharpen, and
    run Tesseract in single-block mode (``--psm 6``) which reads receipts far
    better than the default page-segmentation."""
    if not _IMPORTS_OK:
        return ""
    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)          # honour phone rotation
        gray = img.convert("L")                       # greyscale
        gray = _autocrop_receipt(gray)                # drop dark surround
        gray = ImageOps.autocontrast(gray, cutoff=2)  # fix faded/uneven exposure
        w, h = gray.size
        if max(w, h) < 2200:                          # upscale for small text
            scale = 2200 / max(w, h)
            gray = gray.resize((int(w * scale), int(h * scale)))
        gray = gray.filter(ImageFilter.SHARPEN)
        return pytesseract.image_to_string(gray, config="--oem 3 --psm 6")
    except Exception:
        return ""


def _to_amount(token):
    """'$1,234.56' → 1234.56 ; '13,49' → 13.49 ; None when unparseable."""
    if token is None:
        return None
    t = token.replace("$", "").replace(" ", "")
    # Comma as decimal separator (e.g. "13,49") when there's no period.
    if "." not in t and re.search(r",\d{2}$", t):
        t = t.replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _amounts_in(line):
    return [_to_amount(m) for m in _MONEY_RE.findall(line) if _to_amount(m) is not None]


def _parse_date(text):
    """Find the most plausible date in the OCR text. Returns a datetime or None."""
    patterns = [
        (r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", "mdy"),
        (r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", "ymd"),
    ]
    for pat, order in patterns:
        for m in re.finditer(pat, text):
            try:
                a, b, c = (int(x) for x in m.groups())
            except ValueError:
                continue
            try:
                if order == "mdy":
                    year = c if c > 99 else (2000 + c if c < 70 else 1900 + c)
                    dt = datetime(year, a, b)
                else:
                    dt = datetime(a, b, c)
                if 2000 <= dt.year <= datetime.utcnow().year + 1:
                    return dt
            except ValueError:
                continue
    # Textual month, e.g. "Jan 5, 2024"
    m = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", text)
    if m:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(
                    f"{m.group(1)[:9]} {m.group(2)} {m.group(3)}", fmt)
            except ValueError:
                continue
    return None


def _parse_city_state(text):
    # 1. "City, ST 12345" / "City, ST".
    for line in text.splitlines():
        m = _CITY_STATE_RE.search(line)
        if m and m.group(2) in _STATE_CODES:
            city = m.group(1).strip(" .,-")
            if 1 < len(city) <= 40:
                return city.title(), m.group(2)
    # 2. "City ST 12345" without a comma — the trailing ZIP keeps this from
    #    firing on random "<Word> XX" text.
    for line in text.splitlines():
        m = _CITY_ST_ZIP_RE.search(line)
        if m and m.group(2) in _STATE_CODES:
            city = m.group(1).strip(" .,-")
            if 1 < len(city) <= 40:
                return city.title(), m.group(2)
    # 3. Fallback: a bare full state name — but only when a 5-digit ZIP is
    #    present somewhere, so a street like "Washington Pike" doesn't get
    #    mistaken for the state of Washington.
    if re.search(r"\b\d{5}\b", text):
        low = text.lower()
        for name, code in _STATES.items():
            if re.search(r"\b" + re.escape(name) + r"\b", low):
                return "", code
    return "", ""


def _labeled_amount(lines, keys, exclude=()):
    """Return the amount on the last line whose text contains one of ``keys``
    (and none of ``exclude``). Scans bottom-up because totals live near the
    foot of a receipt. ``exclude`` lets the grand-total search ignore the
    ``subtotal`` line, which also contains the substring 'total'."""
    for line in reversed(lines):
        low = line.lower()
        if exclude and any(x in low for x in exclude):
            continue
        if any(k in low for k in keys):
            amts = _amounts_in(line)
            if amts:
                return amts[-1]
    return None


_KNOWN_VENDORS = {
    "wal-mart": "Walmart", "walmart": "Walmart", "target": "Target",
    "costco": "Costco", "kroger": "Kroger", "aldi": "Aldi", "publix": "Publix",
    "safeway": "Safeway", "meijer": "Meijer", "sam's club": "Sam's Club",
    "sams club": "Sam's Club", "dollar general": "Dollar General",
    "dollar tree": "Dollar Tree", "family dollar": "Family Dollar",
    "home depot": "The Home Depot", "lowe's": "Lowe's", "lowes": "Lowe's",
    "menards": "Menards", "ace hardware": "Ace Hardware", "rural king": "Rural King",
    "tractor supply": "Tractor Supply", "walgreens": "Walgreens",
    "rite aid": "Rite Aid", "trader joe": "Trader Joe's", "whole foods": "Whole Foods",
    "best buy": "Best Buy", "food lion": "Food Lion", "giant eagle": "Giant Eagle",
    "wegmans": "Wegmans", "sheetz": "Sheetz", "speedway": "Speedway",
}


def _parse_vendor(lines):
    """Vendor = a known store name found near the top of the receipt, else the
    first line that reads like a name (mostly letters, no digits). The known-
    store lookup makes vendor detection robust even when the top of the receipt
    is noisy (survey blurb, handwriting, faded logo)."""
    joined = "\n".join(lines[:15]).lower()
    for term, display in _KNOWN_VENDORS.items():
        if term in joined:
            return display
    for line in lines[:8]:
        s = line.strip()
        letters = re.sub(r"[^A-Za-z]", "", s)
        compact = re.sub(r"\s", "", s)
        if (len(letters) >= 4 and compact
                and len(letters) / len(compact) >= 0.6
                and not any(c.isdigit() for c in s)):
            return s[:120]
    for line in lines[:8]:
        if len(line.strip()) >= 3:
            return line.strip()[:120]
    return ""


def _alpha_score(s):
    """Number of alphabetic characters — a rough 'how much real text' measure."""
    return len(re.sub(r"[^A-Za-z]", "", s or ""))


def _clean_item_name(s):
    """Tidy an item-name fragment: drop leading bullets/pipes and a single
    stray leading letter (OCR often grabs one from the left margin / a product
    thumbnail, e.g. "B MIDWESTERN…", "A 50 LB…"). Multi-letter words survive."""
    s = (s or "").strip()
    s = re.sub(r"^[^A-Za-z0-9]+", "", s)          # leading punctuation/bullets
    s = re.sub(r"^[A-Za-z]\s+(?=\S)", "", s)       # one stray leading letter
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" .,-\t")


def _extract_upc(text):
    """First run of >=4 digits in a fragment (the UPC/SKU), or ''."""
    m = re.search(r"\d{4,}", text)
    return m.group(0) if m else ""


def _parse_items(lines):
    """Pull line-items, handling two common layouts:

    1. Name + price on the SAME line (typical big-box receipt):
         ``2x4 LUMBER 8FT      5.98``
    2. Name on its OWN line, with the UPC / qty / price on the line BELOW
       (e.g. Rural King):
         ``SELENTUM VITAMIN E GEL LAMB``
         ``362692  jea  13.49  13.06``
       Here the name is taken from the line above and the UPC is appended, so
       the description reads "name then UPC" on one line.

    We decide per priced line: if the immediately-preceding no-price line has
    materially more letters than this line's own leftover text, that line above
    is the name (layout 2); otherwise the leftover text on this line is the
    name (layout 1). Lines matching total/tender/discount keywords are skipped.
    """
    items = []
    prev_name = None
    prev_score = 0
    for line in lines:
        low = line.lower()
        if any(k in low for k in _SKIP_ITEM_KEYS):
            prev_name, prev_score = None, 0
            continue
        amts = _amounts_in(line)
        if not amts:
            # A candidate item-name line (no price on it).
            name = _clean_item_name(line)
            if _alpha_score(name) >= 3:
                prev_name, prev_score = name, _alpha_score(name)
            else:
                prev_name, prev_score = None, 0
            continue

        # Priced line. What's left after removing the money amounts?
        inline = re.sub(r"\s{2,}", " ", _MONEY_RE.sub("", line)).strip(" .-\t")
        inline_name = _clean_item_name(inline)
        inline_score = _alpha_score(inline_name)
        upc = _extract_upc(inline)
        cost = amts[-1]

        if prev_name and prev_score >= inline_score + 3:
            # The descriptive text lives on the line above; this line is the
            # UPC / qty / price detail. Combine: name then UPC.
            desc = prev_name + (" " + upc if upc else "")
            items.append({"description": desc[:200], "qty": 1.0, "cost": cost})
        elif inline_score >= 2:
            # Name and price on the same line.
            items.append({"description": inline_name[:200], "qty": 1.0, "cost": cost})
        elif prev_name:
            # Price line with no usable text of its own (wrapped name above).
            desc = prev_name + (" " + upc if upc else "")
            items.append({"description": desc[:200], "qty": 1.0, "cost": cost})
        prev_name, prev_score = None, 0
    # Drop $0.00 lines — these are almost always footer/terminal junk
    # (EMV tags, "change 0.00") rather than real purchased items.
    return [it for it in items if it["cost"] > 0][:60]


def parse_receipt(text):
    """Parse raw OCR text into a field dict ready to pre-fill the form."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    city, state = _parse_city_state(text)
    dt = _parse_date(text)
    subtotal = _labeled_amount(lines, _SUBTOTAL_KEYS)
    tax = _labeled_amount(lines, _TAX_KEYS)
    # Exclude the subtotal line from the grand-total search (it contains the
    # substring 'total'), so a garbled TOTAL line doesn't fall back to it.
    total = _labeled_amount(lines, _TOTAL_KEYS, exclude=_SUBTOTAL_KEYS)

    # If the total is missing but we have subtotal + tax, synthesize it.
    if total is None and subtotal is not None:
        total = round(subtotal + (tax or 0.0), 2)
    # If subtotal is missing but total + tax known, back it out.
    if subtotal is None and total is not None and tax is not None:
        subtotal = round(total - tax, 2)

    return {
        "vendor_name": _parse_vendor(lines),
        "purchased_at": dt.strftime("%Y-%m-%dT%H:%M") if dt else "",
        "city": city,
        "state": state,
        "subtotal": subtotal if subtotal is not None else "",
        "tax": tax if tax is not None else "",
        "grand_total": total if total is not None else "",
        "items": _parse_items(lines),
    }


def scan(path):
    """One-shot: OCR ``path`` and return (parsed_fields, raw_text)."""
    text = extract_text(path)
    return parse_receipt(text), text
