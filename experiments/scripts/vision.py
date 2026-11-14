"""Photos: on-device OCR in four orientations, Tesseract orientation detection, and VLM label drafts.

Shared by Vision_v1.ipynb and the MVP. Word boxes are always returned in the coordinates of the upright photo
(EXIF orientation applied), whatever rotation the OCR ran on.
"""
import base64, io, subprocess, tempfile
from PIL import Image, ImageOps

import gate as G
import masking as MK

ROOT = G.ROOT + "Dataset/BIV-Priv/"
ANGLES = (0, 90, 180, 270)  # counter-clockwise, as PIL's rotate


def load(path):
    """The photo as the camera meant it (EXIF orientation applied), RGB."""
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def back(x, y, angle, w, h):
    """A point in the photo rotated by `angle` (PIL rotate, expand=True) mapped back to the w x h original."""
    return {0: (x, y), 90: (w - y, x), 180: (w - x, h - y), 270: (y, h - x)}[angle]


def _box_back(box, angle, w, h):
    x0, y0, x1, y1 = box
    pts = [back(x, y, angle, w, h) for x, y in ((x0, y0), (x1, y1))]
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def tesseract(img, angle=0, psm=3):
    """Tesseract 5 words (psm 3: automatic page layout; psm 11: sparse text, made for text in scenes): [(text, conf 0-1, [x0, y0, x1, y1])] in original coordinates."""
    w, h = img.size
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        img.rotate(angle, expand=True).save(f.name)
        tsv = subprocess.run(["tesseract", f.name, "stdout", "--psm", str(psm), "tsv"], capture_output=True, text=True, check=True).stdout
    out = []
    for line in tsv.splitlines()[1:]:
        c = line.split("\t")
        if len(c) == 12 and c[11].strip() and float(c[10]) >= 0:
            x, y, bw, bh = map(int, c[6:10])
            out.append((c[11], float(c[10]) / 100, _box_back([x, y, x + bw, y + bh], angle, w, h)))
    return out


def osd(img):
    """Tesseract orientation detection: the counter-clockwise angle that makes the text upright, or None."""
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        img.save(f.name)
        r = subprocess.run(["tesseract", f.name, "stdout", "--psm", "0"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith("Rotate:"):
            return (360 - int(line.split(":")[1])) % 360  # Tesseract reports clockwise degrees
    return None  # too little text to decide


def apple(img, angle=0):
    """Apple Vision (ocrmac, accurate) lines: [(text, conf 0-1, [x0, y0, x1, y1])] in original coordinates."""
    from ocrmac import ocrmac
    w, h = img.size
    r = img.rotate(angle, expand=True)
    rw, rh = r.size
    out = []
    for text, conf, (x, y, bw, bh) in ocrmac.OCR(r, recognition_level="accurate").recognize():
        box = [x * rw, (1 - y - bh) * rh, (x + bw) * rw, (1 - y) * rh]  # Vision boxes are normalised, origin bottom left
        out.append((text, float(conf), _box_back(box, angle, w, h)))
    return out


ENGINES = {"tesseract3": tesseract, "tesseract11": lambda img, a=0: tesseract(img, a, 11), "apple": apple}


def score(words):
    """How well one orientation read: summed confidence of words with 2+ letters or digits."""
    return sum(c for t, c, _ in words if sum(ch.isalnum() for ch in t) >= 2)


def orient(runs, method, osd_angle=None):
    """Words chosen from {angle: words} by an orientation method.
    none: the photo as it is; osd: Tesseract's angle (0 if undecided); best4: the angle that reads best; union4: all four."""
    if method == "none":
        return runs[0]
    if method == "osd":
        return runs[osd_angle or 0]
    if method == "best4":
        return runs[max(ANGLES, key=lambda a: score(runs[a]))]
    if method == "union4":
        return [wd for a in ANGLES for wd in runs[a]]
    raise ValueError(method)


METHODS = ("none", "osd", "best4", "union4")


def text_of(words):
    return "\n".join(t for t, _, _ in words)


def codes(img, pad=100):
    """Boxes of QR codes and barcodes (Apple Vision), in original coordinates. The content is not kept.
    The white border lets Vision find a code cut off at the photo edge (photo 143 is found only with it)."""
    import Vision
    from Foundation import NSData
    p = ImageOps.expand(img, pad, "white")
    buf = io.BytesIO()
    p.save(buf, "PNG")
    req = Vision.VNDetectBarcodesRequest.alloc().init()
    Vision.VNImageRequestHandler.alloc().initWithData_options_(NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue())), None).performRequests_error_([req], None)
    W, H = p.size
    out = []
    for r in req.results() or []:
        b = r.boundingBox()  # normalised, origin bottom left
        x, y, bw, bh = b.origin.x, b.origin.y, b.size.width, b.size.height
        out.append([x * W - pad, (1 - y - bh) * H - pad, (x + bw) * W - pad, (1 - y) * H - pad])
    return out


def blackout(img, words, spans, offset=0, boxes=()):
    """Copy of img with every OCR line that holds a masked character painted black, and every box in `boxes` (QR codes, whatever they hold).
    spans: (start, end) in text_of(words), shifted by `offset` when that text sits inside a longer record.
    shortcut: whole lines, not the masked characters only (line direction is unknown after rotation); split lines if over-masking matters."""
    from PIL import ImageDraw
    out, pos = img.copy(), offset
    draw = ImageDraw.Draw(out)
    for t, _, box in words:
        if any(a < pos + len(t) and pos < b for a, b, *_ in spans):
            draw.rectangle(box, fill="black")
        pos += len(t) + 1
    for box in boxes:
        draw.rectangle(box, fill="black")
    return out


# ---------------------------------------------------------------- label drafts (a person checks every draft)

DRAFT_MODEL = "anthropic/claude-opus-5.5"  # not one of the models under test
DRAFT_VERSION = 2  # v2 adds the props sentence: v1 discounted 79 drafts as novelty or sample cards
DRAFT_PROMPT = f"""This photo was taken at home. Read every piece of text in it that is legible, in any orientation.

List each value that could identify a person or give access to money or an account:
names, home or mail addresses, phone numbers, emails, dates of birth, ID numbers (SSN, passport, driver licence, student, member, patient or record numbers), health details tied to a person, card numbers, card expiry or CVV, bank account or routing numbers, passwords, PINs, API keys or tokens.
Copy each value exactly as printed. Skip a value you cannot read with confidence.
The documents and cards in these photos are props that stand in for the owner's real ones. Judge every value as if it were real: do not discount a value for a fictional-sounding name, a sample-looking design, an unusual number length or an odd date.

Then judge the photo with these two rules, using only values that are legible:
- pii: {G.D_PII}
- credential: {G.D_CRED}

Reply with JSON only:
{{"values": [{{"text": "...", "kind": "name|address|phone|email|dob|id|health|card|card_expiry|card_cvv|bank_account|password|pin|api_key|other"}}], "pii": true|false, "credential": true|false, "note": "one short sentence on what the photo shows"}}"""


def b64(img):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def draft(img, model=DRAFT_MODEL, avoid=()):
    """Returns (raw, parsed or None, cost). avoid: providers to skip (Amazon Bedrock filtered 3 photos as content)."""
    out = G.client().chat.completions.create(
        model=model, temperature=0, max_tokens=4000,  # 800 and 2000 cut off long documents
        extra_body={"usage": {"include": True}, "provider": {"zdr": True, "ignore": list(avoid)}},
        messages=[{"role": "user", "content": [{"type": "text", "text": DRAFT_PROMPT}, {"type": "image_url", "image_url": {"url": b64(img)}}]}])
    cost = getattr(out.usage, "cost", None) if out.usage else None
    raw = (out.choices[0].message.content or f"[empty, finish_reason={out.choices[0].finish_reason}]") if out.choices else "[no choices]"
    return raw, MK.parse_json(raw), cost


# ---------------------------------------------------------------- gates on photos (Vision_v1 sections 6 to 8)

PHOTO = "Photo: "  # the MVP's record for a photo: this label + the OCR text


def local_flags(record):
    """The text gates' on-device detectors (Gatekeeper_v1_local.ipynb rules) on one record: {name: {"pii", "credential"}}."""
    rx = G.regex_gate(record)
    gl = MK.gliner_spans(record)
    labels = {lab for _, _, lab in gl}
    name = any(lab == "person" and len(record[a:b].split()) >= 2 for a, b, lab in gl)
    contact = {"phone number", "email", "address", "date of birth", "medical record number"}
    return {"regex": {"pii": rx["pii"], "credential": rx["credential"]},
            "presidio": {"pii": G.presidio_pii(record), "credential": 0},  # eval v1 used Presidio for PII only (LOCAL_AX)
            "gliner": {"pii": int(bool(labels & {"social security number", "passport number"}) or (name and bool(labels & contact))),
                       "credential": int(bool(labels & {"credit card number", "bank account number", "password", "api key", "pin"}))},
            "detect-secrets": {"pii": 0, "credential": int(bool(G.detect_secrets_types(record)))}}


PHOTO_PROMPT = {ax: ("You are a gatekeeper for a permanent, public, append-only log. Please analyze the following photo, taken by a camera at home, "
                     "and determine if it is unsafe to store. A photo is unsafe if it contains the following:\n" + d + "\n{ocr}"
                     "Please respond with ONLY \"True\" if the photo is unsafe to store, or \"False\" if it is safe to store.\n"
                     "Your response should be exactly \"True\" or \"False\" with no additional text or explanation.")
                for ax, d in [("pii", G.D_PII), ("credential", G.D_CRED)]}
OCR_NOTE = "\nText read from the photo on the device (it may be incomplete or wrong):\n\"{text}\"\n\n"


def ask(axis, model, record=None, img=None, ocr=None):
    """One True/False question with zero data retention. record: the text gate's prompt (gate.PROMPT_AXIS, as in eval v1);
    img: the photo prompt, with the OCR text added when ocr is given. Returns (raw, pred, cost); pred None = invalid answer."""
    if img is None:
        content = G.PROMPT_AXIS[axis].replace("{record}", record)
    else:
        text = PHOTO_PROMPT[axis].replace("{ocr}", "" if ocr is None else OCR_NOTE.replace("{text}", ocr))
        content = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": b64(img)}}]
    body = {"usage": {"include": True}, "provider": {"zdr": True}} | ({"reasoning": {"effort": "none"}} if model in G.REASONING_OFF else {})
    out = G.client().chat.completions.create(model=model, temperature=0, max_tokens=5, extra_body=body, messages=[{"role": "user", "content": content}])
    cost = getattr(out.usage, "cost", None) if out.usage else None
    if not out.choices or out.choices[0].finish_reason == "content_filter":
        return "BLOCKED", 1, cost  # as in eval v1: a provider filter counts as unsafe
    raw = out.choices[0].message.content
    return raw, G.parse(raw), cost


def norm(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())


if __name__ == "__main__":  # self-test: a dot drawn on a photo comes back to the same place from every rotation
    img = Image.new("RGB", (40, 70), "white")
    img.putpixel((7, 23), (0, 0, 0))
    for a in ANGLES:
        r = img.rotate(a, expand=True)
        x, y = next((x, y) for x in range(r.size[0]) for y in range(r.size[1]) if r.getpixel((x, y)) == (0, 0, 0))
        bx, by = back(x + 0.5, y + 0.5, a, *img.size)
        assert abs(bx - 7.5) < 1 and abs(by - 23.5) < 1, (a, bx, by)
    words = [("Call 555-0100", 1, [0, 0, 10, 2]), ("hello", 1, [0, 4, 10, 6])]
    t = "Photo: " + text_of(words)
    m = blackout(Image.new("RGB", (12, 8), "white"), words, [(t.index("555"), t.index("555") + 8)], offset=len("Photo: "))
    assert m.getpixel((5, 1)) == (0, 0, 0) and m.getpixel((5, 5)) == (255, 255, 255)
    m = blackout(Image.new("RGB", (12, 8), "white"), words, [], boxes=[[0, 4, 3, 7]])
    assert m.getpixel((1, 5)) == (0, 0, 0) and m.getpixel((5, 1)) == (255, 255, 255)
    print("ok")
