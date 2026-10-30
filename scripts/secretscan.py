"""Regex + entropy scanner for secrets and PII. A library: other code imports `scan`, `RX`, `mask`, `entropy`.

scan(text) yields (kind, value, status) for every match:
- status "pii": email, phone, SSN.
- status "placeholder": the value looks like a stand-in (YOUR_..., xxx, <...>, example, os.environ, ...).
- status "secret": anything else. For `generic_assign` (password = ..., api_key: ...) values under 3.5 bits of entropy are skipped.

Used by:
- scan_wildchat.py, sample_scan_hits.py (whole-WildChat scan and its hand-read sample).
- pilot_set_v2.ipynb: Step 1 filter (any hit drops a WildChat candidate), the placeholder check on generated values,
  the frame check, PUPA email and phone replacement (`RX`), and the hard-negative check in the output cell.

Changed 2026-10-20 after the user found false hits: code references (passwordInput.getText(), request.POST[, a->b(, config.password)
and non-ASCII values are skipped; values that name their own kind (complex_password) count as placeholders, constant names (DB_PASSWORD) and emails on reserved example domains (example.com) count as placeholders.

Run `python3 secretscan.py` for the self-test (16 asserts).
"""
import math, re, collections

PATTERNS = {
    "openai_key": r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}",
    "anthropic_key": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    "aws_access_key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "github_token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})",
    "google_api_key": r"\bAIza[0-9A-Za-z_-]{35}",
    "slack_token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "stripe_key": r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}",
    "telegram_bot": r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b",
    "jwt": r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    "private_key": r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
    "hf_token": r"\bhf_[A-Za-z0-9]{34,}",
    "conn_string": r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:[^\s@]+@[^\s/]+",
    "generic_assign": r"(?i)\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|password|passwd|pwd|bearer)\b[\"']?\s*[:=]\s*[\"']?([^\s\"',;)]{8,})",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "phone": r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\w)",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
}
RX = {k: re.compile(v) for k, v in PATTERNS.items()}
PII_KINDS = {"email", "phone", "ssn"}
# Reserved example domains (RFC 2606): an address there is a stand-in, not a person.
EXAMPLE_DOMAIN = re.compile(r"(?i)@(?:[\w-]+\.)*(?:example|test|invalid|localhost)(?:\.[a-z]{2,})*$")
# A value that names its own kind (complex_password, passwordRegistration, my_secret) is a variable name or an example.
# shortcut: also catches weak real passwords like "Password123", fine for a scan of WildChat, revisit if used as a gate.
SELF_NAMED = re.compile(r"(?i)pass(?:word|wd)|secret|token|api_?key")
# A constant name such as DB_PASSWORD or TUA_API_KEY names where a secret goes; it is not the secret.
CONST_NAME = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
# A code reference such as passwordInput.getText(, request.POST[, passwordLineEdit->text( or config.password reads a value from elsewhere.
# Non-ASCII values are skipped too: in WildChat they are prose (e.g. Chinese text after "password:").
CODE_REF = re.compile(r"[A-Za-z_](?:[\w.]|->|::)*[(\[].*|[A-Za-z_]\w*(?:(?:\.|->|::)\w+)+")
PLACEHOLDER = re.compile(r"(?i)your|xxx|\*{3}|<[^>]*>|\{[^}]*\}|\.\.\.|example|placeholder|dummy|redacted|changeme|test|abc|1234|here|_KEY\b|\$\{?\w|os\.environ|getenv|process\.env")


def entropy(s):
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in collections.Counter(s).values()) if n else 0.0


def is_placeholder(v):
    return bool(PLACEHOLDER.search(v)) or len(set(v)) < 6 or bool(CONST_NAME.fullmatch(v)) or bool(SELF_NAMED.search(v))


def scan(text):
    """Yield (kind, value, status). status: 'secret' | 'placeholder' | 'pii'."""
    for kind, rx in RX.items():
        for m in rx.finditer(text or ""):
            v = m.group(1) if kind == "generic_assign" else m.group(0)
            if kind == "generic_assign" and (CODE_REF.fullmatch(v) or not v.isascii()):
                continue
            if kind in PII_KINDS:
                yield kind, v, "placeholder" if EXAMPLE_DOMAIN.search(v) else "pii"
            elif is_placeholder(v):
                yield kind, v, "placeholder"
            elif kind == "generic_assign" and entropy(v) < 3.5:
                continue  # low-entropy words like 'password = hunter'... ponytail: fixed 3.5 bits cutoff, tune on hand-read sample
            else:
                yield kind, v, "secret"


def mask(v):
    return v[:4] + "*" * max(len(v) - 8, 3) + v[-4:] if len(v) > 10 else v[:2] + "***"


if __name__ == "__main__":
    t = lambda s: {(k, st) for k, _, st in scan(s)}
    assert ("openai_key", "secret") in t("key sk-" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY")
    assert ("openai_key", "placeholder") in t("openai.api_key = 'sk-YOUR_API_KEY_HERE_xxxxxxxxx'")
    assert ("aws_access_key", "secret") in t("AKIA" + "Q7ZR4M2KXN5LPW3J")
    assert not any(st == "secret" for _, _, st in scan("How do I rotate my API key safely?"))
    assert ("email", "pii") in t("mail me at jane.doe@uhealth.org")
    assert not any(st == "secret" for _, _, st in scan("password = os.environ['DB_PASS']"))
    # false hits found by the user on 2026-10-20 in out/wildchat_hits.jsonl
    assert not list(scan("String password = passwordInput.getText().toString();"))
    assert t('var apiKey = "TUA_API_KEY";') <= {("generic_assign", "placeholder")}
    assert t("access_token={ACCESS_TOKEN}") <= {("generic_assign", "placeholder")}
    assert t("email: 'john.doe@example.com'") == {("email", "placeholder")}
    assert ("email", "pii") in t("write to john.doe@gmail.com")
    assert not list(scan("password = request.POST['password']"))
    assert not list(scan("密码: 用户密码是登录系统的凭证。"))
    assert not list(scan("QString password = passwordLineEdit->text();"))
    assert t("'password': 'complex_password'") == {("generic_assign", "placeholder")}
    assert ("generic_assign", "secret") in t("password = Xk9#mQ2vLp7w")
    print("ok")
