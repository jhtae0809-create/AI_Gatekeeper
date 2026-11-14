"""Span-level masking: on-device span finders, credential rules, and an AI check of the masks.

Used by Masking_v1.ipynb and by the MVP. Every finder returns [(start, end, label)] for one text.
Self-test (no model, no API): python scripts/masking.py
"""
import json
import os
import re
import tempfile

import gate as G
import secretscan as S

# ---------------------------------------------------------------- on-device span finders


def find_all(text, value):
    return [(m.start(), m.end()) for m in re.finditer(re.escape(value), text)] if value else []


def regex_spans(text):
    """The scanner's 'secret' and 'pii' hits, plus Luhn-valid card numbers (same rule as the regex gate). Placeholders are not masked."""
    out = []
    for kind, v, st in S.scan(text):
        if st in ("secret", "pii"):
            out += [(a, b, kind) for a, b in find_all(text, v)]
    out += [(m.start(), m.end(), "card") for m in G.CARD.finditer(text) if S.luhn(re.sub(r"\D", "", m.group(0)))]
    return out


def presidio_spans(text):
    """Presidio PERSON and the gate's ID types, score 0.5 or more. LOCATION and DATE_TIME are left out: they match most chats."""
    G.presidio("warm up")  # loads spaCy once
    return [(r.start, r.end, r.entity_type) for r in G._presidio.analyze(text=text, language="en", entities=["PERSON"] + G.PRESIDIO_ID)
            if r.score >= 0.5]


_gliner = None
GLINER_LABELS = ["person", "phone number", "email", "address", "date of birth", "medical record number", "social security number",
                 "passport number", "credit card number", "bank account number", "password", "api key", "pin"]


def gliner_spans(text, size=1000, step=800):
    """GLiNER PII model, the 13 labels of the gate run, threshold 0.5, 1,000-character windows."""
    global _gliner
    if _gliner is None:
        from gliner import GLiNER
        _gliner = GLiNER.from_pretrained("knowledgator/gliner-pii-base-v1.0")
    out = []
    for s in range(0, max(len(text) - 200, 1), step):
        out += [(s + e["start"], s + e["end"], e["label"]) for e in _gliner.predict_entities(text[s:s + size], GLINER_LABELS, threshold=0.5)]
    return sorted(set(out))


def ds_spans(text):
    """detect-secrets with default plugins; the reported value is found again in the text."""
    from detect_secrets import SecretsCollection
    from detect_secrets.settings import default_settings
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(text)
    try:
        with default_settings():
            sc = SecretsCollection()
            sc.scan_file(f.name)
            return [(a, b, s.type) for _, s in sc for a, b in find_all(text, s.secret_value)]
    finally:
        os.remove(f.name)


# ---------------------------------------------------------------- credential rules (set on the validation split)
TOK = re.compile(r"[^\s,;]+")
EDGE = "\"'`“”‘’()[]{}<>,;:.!?*_~#"
PWSYM = re.compile(r"[!@#$%^&*+=?~]")
# Places where symbols, digits and mixed case are expected in ordinary text and code. A token outside all of them is suspicious.
EXPECTED = [
    re.compile(r"#[A-Za-z]\w*"),                                                          # hashtag
    re.compile(r"@[A-Za-z_][\w.]*"),                                                      # mention, decorator
    re.compile(r"[A-Za-z_][\w.\[\]'\"-]*\s*[:=]=?\s*\S*"),                                # key=value, key:value, a==b
    re.compile(r"[-+]?[\d.,]+%|[$€£¥₩][\d.,]+[kKmMbB]?|[\d.,]+[$€£¥₩]"),                   # percent, money
    re.compile(r"[\d.,()+\-*/^=<>≤≥xX ]+"),                                               # arithmetic, ranges
    re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}(T[\d:.]+Z?)?|\d{1,2}:\d{2}(:\d{2})?([ap]m)?", re.I),  # dates, times
    re.compile(r"v?\d+(\.\d+)+[\w.-]*", re.I),                                            # versions
    re.compile(r"(?i)(https?://|www\.)\S+|[\w.+-]+@[\w-]+\.[\w.]+|[~.]?/[\w./-]+|[A-Za-z]:\\\S+"),  # urls, emails, paths
    re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)+(\(.*\))?|[A-Za-z_]\w*\(.*\)?|\w+\[.*\]"),  # dotted names, calls, indexing
    re.compile(r"[\w-]+\.(py|js|ts|tsx|jsx|html|css|json|md|txt|png|jpe?g|gif|svg|pdf|csv|xlsx?|docx?|java|cpp|c|h|go|rs|sh|yml|yaml|toml"
               r"|ini|exe|dll|so|zip|mp[34]|wav)", re.I),                                 # file names
    re.compile(r"[A-Za-z]+-\d+[A-Za-z]*|[A-Z]{1,5}\d{1,4}[A-Za-z]?|\d+[A-Za-z]{1,3}"),     # model or product codes: GPT-4o, A100, 5km
    re.compile(r"&[a-z]+;|<[^>]*>|\\[nt]|0x[0-9a-fA-F]+|#[0-9a-fA-F]{3,8}"),              # html entities, tags, escapes, hex, colours
    re.compile(r"[A-Za-z]+('[a-z]{1,2})?"),                                               # plain word, contractions
    re.compile(r"[A-Za-z]+(-[A-Za-z]+)+"),                                                # hyphenated words
    re.compile(r"[*_~`]+[^*_~`]+[*_~`]+"),                                                # markdown emphasis
    re.compile(r".*[()\[\]{}<>/\\|].*"),                                                  # code, markup, paths, units
    re.compile(r"[A-Za-z]+[?!.,;:][A-Z\"“][A-Za-z]*"),                                    # two words glued by punctuation: okay?She
    re.compile(r"[A-Za-z]{2,}([*+^][\dA-Za-z.]+)+"),                                      # formulas with words: HP*defense
    re.compile(r"[A-Za-z_]\w*@(0x)?[0-9a-fA-F]+|@0x[0-9a-fA-F]+"),                        # object ids: Connection@5378, @0x470f
]
PASSPHRASE = re.compile(r"[A-Za-z]+([._-][A-Za-z]+){2,}\d{1,3}")  # word.word.word99 is a passphrase, not a code name
ASSIGN = re.compile(r"([A-Za-z_][\w.-]*)\s*[:=]\s*(\S+)")
CRED_KEY = re.compile(r"(?i)pass|pwd|secret|token|api_?key|auth|credential|private")


def expected(t):
    return not PASSPHRASE.fullmatch(t) and any(p.fullmatch(t) for p in EXPECTED)


def _usable(v):
    return not S.is_placeholder(v) and not G.MASKED.search(v)


def shape_ok(t):
    if not (8 <= len(t) <= 64) or not _usable(t):
        return False
    letters, digit, sym, camel = (re.search(p, t) for p in (r"[A-Za-z]", r"\d", PWSYM.pattern, r"[a-z][A-Z]"))
    return bool(letters and (digit or sym or camel)) and not expected(t)


def pw_shape(text):
    """Password-shaped tokens: letters mixed with digits, symbols or inner capitals, outside the places such tokens are expected.
    In key=value the value is checked on its own; under a credential-like key any value of 4+ characters counts."""
    out = []
    for m in TOK.finditer(text):
        raw = m.group(0)
        t = raw.strip(EDGE)
        if not t:
            continue
        s = m.start() + raw.find(t)
        a = ASSIGN.fullmatch(t)
        if a:
            v = a.group(2).strip(EDGE)
            vs = s + a.start(2) + a.group(2).find(v)
            if v and ((CRED_KEY.search(a.group(1)) and len(v) >= 4 and _usable(v)) or shape_ok(v)):
                out.append((vs, vs + len(v), "pw_shape"))
            continue
        if shape_ok(t):
            out.append((s, s + len(t), "pw_shape"))
    return out


KW = re.compile(r"(?i)\b(pass(?:word|wd|code|phrase)?|pwd|pin(?:\s*(?:code|number))?|acc(?:oun)?t\.?(?:\s*(?:no\.?|number|#))?|routing(?:\s*number)?"
                r"|iban|api[\s_-]?key|token|secret)\b[\"'\s]*(?:is|was|=|:|-|→|to)?[\"'\s]*")


def keyword(text):
    """The token right after a credential word (password, PIN, account number, ...) when it holds a digit."""
    out = []
    for m in KW.finditer(text):
        n = TOK.match(text, m.end())
        if not n:
            continue
        raw = n.group(0)
        v = raw.strip(EDGE)
        s = n.start() + raw.find(v)
        if len(v) < 4 or not re.search(r"\d", v) or G.MASKED.search(v):
            continue
        digits = re.sub(r"\D", "", v)
        # the scanner's placeholder test drops short or sequential digit runs (it needs 6 distinct characters), so digits get their own test
        dummy = len(set(digits)) == 1 or digits in "01234567890" or digits in "98765432109"
        if (digits == v and not dummy) or (digits != v and _usable(v)):
            out.append((s, s + len(v), "kw"))
    return out


FINDERS = {"regex": regex_spans, "presidio": presidio_spans, "gliner": gliner_spans, "detect-secrets": ds_spans,
           "pw_shape": pw_shape, "keyword": keyword}


def merge(spans):
    """Union of spans as sorted, non-overlapping (start, end) pairs."""
    out = []
    for a, b in sorted((a, b) for a, b, *_ in spans if b > a):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


# ---------------------------------------------------------------- AI check of the masks
RISKY = ("Risky values are:\n"
         "1. Personal identifiers of a real person: a name, phone number, email address, home address, date of birth, ID number "
         "(social security, passport, driver's licence), medical record number.\n"
         "2. Credentials: a password, passphrase, PIN, API key, access token, private key, the password in a connection string, "
         "a payment card number, a bank account number.\n"
         "Placeholders, documentation or test examples, values that are already masked, and talk about these things without a value do not count.")

PROMPT_VALUE = ("You check the masks on a conversation record before it is written to a permanent, public log. "
                "Spans that on-device tools flagged are marked like this: [[n|value]].\n\n" + RISKY + "\n\n"
                "Reply with JSON only, no other text: {\"keep\": [numbers of the marked spans that are risky values], "
                "\"add\": [exact text of risky values that are not marked]}. Use [] when there are none.\n\nRecord:\n{record}")

PROMPT_INDEX = ("You check the masks on a conversation record before it is written to a permanent, public log. "
                "Every word has its number in front of it, like [7]word. Words that on-device tools flagged have a star: [7*]word.\n\n" + RISKY + "\n\n"
                "Reply with JSON only, no other text: {\"risky\": [numbers of every word that is part of a risky value, flagged or not]}. "
                "Use [] when there are none.\n\nRecord:\n{record}")


def render_value(text, spans):
    """Text with merged spans marked [[n|value]]. Returns (rendered, [(start, end)])."""
    m = merge(spans)
    out, last = [], 0
    for n, (a, b) in enumerate(m, 1):
        out += [text[last:a], f"[[{n}|{text[a:b]}]]"]
        last = b
    return "".join(out + [text[last:]]), m


def render_index(text, spans):
    """Text with every token numbered, flagged tokens starred. Returns (rendered, [(start, end)] per token)."""
    m = merge(spans)
    toks = [(t.start(), t.end()) for t in TOK.finditer(text)]
    out, last = [], 0
    for n, (a, b) in enumerate(toks, 1):
        star = "*" if any(a < y and x < b for x, y in m) else ""
        out += [text[last:a], f"[{n}{star}]", text[a:b]]
        last = b
    return "".join(out + [text[last:]]), toks


def parse_json(raw):
    """First JSON object in the answer, or None (an invalid answer)."""
    x = re.search(r"\{.*\}", raw or "", re.S)
    try:
        return json.loads(x.group(0)) if x else None
    except json.JSONDecodeError:
        return None


def ai_check(text, spans, variant, model="openai/gpt-6-luna", max_tokens=400):
    """One API call (zero data retention). Returns (raw, parsed or None, cost, unit spans)."""
    rendered, units = (render_value if variant == "value" else render_index)(text, spans)
    prompt = (PROMPT_VALUE if variant == "value" else PROMPT_INDEX).replace("{record}", rendered)
    body = {"usage": {"include": True}, "provider": {"zdr": True}} | ({"reasoning": {"effort": "none"}} if model in G.REASONING_OFF else {})
    out = G.client().chat.completions.create(model=model, temperature=0, max_tokens=max_tokens, extra_body=body,
                                             messages=[{"role": "user", "content": prompt}])
    cost = getattr(out.usage, "cost", None) if out.usage else None
    raw = out.choices[0].message.content if out.choices else ""
    return raw, parse_json(raw), cost, units


def apply_check(text, units, parsed, variant, unmask=True):
    """Final masked spans from an AI answer. unmask=True lets the AI drop device masks; False only adds.
    Returns (spans, values the AI named that are not in the text)."""
    if variant == "value":
        keep = {int(k) for k in parsed.get("keep", []) if str(k).isdigit()}
        spans = [(a, b) for n, (a, b) in enumerate(units, 1) if not unmask or n in keep]
        lost = []
        for v in parsed.get("add", []):
            hit = find_all(text, str(v).strip())
            spans += hit
            lost += [] if hit else [v]
        return merge(spans), lost
    risky = {int(k) for k in parsed.get("risky", []) if str(k).isdigit()}
    return merge([units[n - 1] for n in risky if 1 <= n <= len(units)]), []


if __name__ == "__main__":
    for t in ["Sunflower92!", "Bl0ss0m!Tree", "apple-tree-river-moon42", "sunFlower7"]:
        assert pw_shape(f"my code is {t} ok"), t
    assert not pw_shape("my code is sunFlowerField ok")  # letters only: same shape as a code identifier, left to the AI check
    for t in ["#MakeNewFriends", "dropout=0.2", "10%", "$4.99", "v2.1.3", "document.querySelector", "user32.dll", "Push-ups",
              "https://x.org/a1", "2024-05-01", "okay?She", "GPT-4o", "getUserName()"]:
        assert not pw_shape(f"see {t} here"), t
    assert [(a, b) for a, b, _ in pw_shape("DB_PASSWORD=hunter2!x")] == [(12, 21)]
    assert [v for v in ("my PIN is 4821", "account number: 582039471") if keyword(v)] == ["my PIN is 4821", "account number: 582039471"]
    assert not keyword("password: YOUR_PASSWORD") and not keyword("PIN: 1234") and not keyword("PIN 0000")
    assert merge([(5, 9, "a"), (1, 3, "b"), (8, 12, "c")]) == [(1, 3), (5, 12)]
    r, u = render_value("ab cd ef", [(3, 5, "x")])
    assert r == "ab [[1|cd]] ef" and u == [(3, 5)]
    r, u = render_index("ab cd", [(3, 5, "x")])
    assert r == "[1]ab [2*]cd" and u == [(0, 2), (3, 5)]
    assert apply_check("ab cd cd", [(3, 5)], {"keep": [], "add": ["cd"]}, "value") == ([(3, 5), (6, 8)], [])
    assert apply_check("ab cd", [(0, 2), (3, 5)], {"risky": [2]}, "index") == ([(3, 5)], [])
    assert parse_json('x {"keep": [1]} y') == {"keep": [1]} and parse_json("nope") is None
    print("ok")
