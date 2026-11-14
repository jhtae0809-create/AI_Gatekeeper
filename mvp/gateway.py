"""Gateway: decides what part of a record may leave the app. It knows nothing about the app's topic.

check(record) runs, in order:
  1. on-device span finders and credential rules (experiments/scripts/masking.py)
  2. AI check, gpt-6-luna with zero data retention, index format, add only (Masking_v1 sections 6 and 7)
  3. Granite Guardian 3.1 2B harmful flag (on device)
An API error or an unreadable AI answer blocks the record (fail-closed).

log(result, **extra) is the only place that writes. The raw record never reaches it; only its hash.
chain.py writes a stored log line to the blockchain once a person permits it.

Self-test: python mvp/gateway.py (no API call)
"""
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments", "scripts"))
import masking as MK  # noqa: E402

DEVICE = ["regex", "presidio", "gliner", "detect-secrets", "pw_shape", "keyword"]
AI_MODEL = "openai/gpt-6-luna"
GG = "ibm-granite/granite-guardian-3.1-2b"
VERSION = {"device": DEVICE, "ai_check": f"{AI_MODEL}, index format, add only, ZDR", "harmful": f"{GG}, risk harm, p >= 0.5"}
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "gate_log.jsonl")
MASK = "[MASKED]"
ROLE = re.compile(r"^(User|Assistant|Event|Photo):", re.M)  # record labels the frame adds; GLiNER sometimes tags "Assistant" as a person

_gg = None


def _granite():
    global _gg
    if _gg is None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        tok = AutoTokenizer.from_pretrained(GG)
        model = AutoModelForCausalLM.from_pretrained(GG, dtype=torch.float16).to(dev).eval()  # device_map=dev peaked at 10 GB, this at 7.7 GB (2026-11-11)
        ids = lambda ts: [tok.convert_tokens_to_ids(t) for t in ts]
        _gg = tok, model, dev, ids(("Yes", "yes")), ids(("No", "no"))
    return _gg


def harmful(text):
    """Granite Guardian probability of 'Yes' for risk 'harm' (same call as Gatekeeper_v1_local.ipynb)."""
    import torch
    tok, model, dev, yes, no = _granite()
    ids = tok.apply_chat_template([{"role": "user", "content": text}], guardian_config={"risk_name": "harm"},
                                  add_generation_prompt=True, return_tensors="pt", return_dict=True)["input_ids"].to(dev)
    with torch.no_grad():
        p = torch.softmax(model(ids).logits[0, -1].float()[yes + no], 0)
    return float(p[:len(yes)].sum())


def load():
    """Loads every on-device model once (tens of seconds on first start)."""
    MK.presidio_spans("warm up")
    MK.gliner_spans("warm up")
    _granite()


def mask(text, spans):
    out, last = [], 0
    for a, b in MK.merge(spans):
        out += [text[last:a], MASK]
        last = b
    return "".join(out + [text[last:]])


def check(record, ai=MK.ai_check, harm=True):
    """Returns a dict: hash, status (stored | flagged | blocked), masked text, found spans with their source, p_harm, cost."""
    roles = [m.span(1) for m in ROLE.finditer(record)]
    found = [(a, b, name) for name in DEVICE for a, b, _ in MK.FINDERS[name](record) if not any(x <= a and b <= y for x, y in roles)]
    cost, error = None, None
    try:
        raw, parsed, cost, units = ai(record, found, "index", model=AI_MODEL)
        error = None if parsed is not None else f"unreadable answer: {raw!r}"[:200]
    except Exception as e:
        parsed, error = None, repr(e)[:200]
    if parsed is not None:
        added, _ = MK.apply_check(record, units, parsed, "index")
        found += [(a, b, "ai") for a, b in added if not any(x <= a and b <= y for x, y in roles)]
    p_harm = harmful(record) if harm else None  # harm=False: photos (text in view, such as a novel, is not what the person said)
    status = "blocked" if parsed is None else "flagged" if p_harm is not None and p_harm >= 0.5 else "stored"
    return {"hash": hashlib.sha256(record.encode()).hexdigest(), "status": status, "error": error,
            "masked": None if status == "blocked" else mask(record, found), "found": found, "p_harm": p_harm if p_harm is None else round(p_harm, 4), "cost": cost}


def log(result, **extra):
    """Appends one entry. Masked text only for stored records; flagged and blocked records keep hash and verdict only."""
    entry = {"time": datetime.datetime.now().isoformat(timespec="seconds"), "hash": result["hash"], "status": result["status"],
             "p_harm": result["p_harm"], "masks": len(MK.merge(result["found"])) if result["status"] != "blocked" else None,
             "masked": result["masked"] if result["status"] == "stored" else None, "gate": VERSION} | extra
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


if __name__ == "__main__":
    assert mask("call 814-555-0199 now", [(5, 17, "x")]) == f"call {MASK} now"
    assert mask("ab cd ef", [(3, 5, "x"), (4, 8, "y")]) == f"ab {MASK}"

    def down(*a, **k):
        raise ConnectionError("api down")

    r = check("User: my PIN is 4821\n\nAssistant: Okay.", ai=down)
    assert r["status"] == "blocked" and r["masked"] is None, r  # fail-closed
    r = check("User: my PIN is 4821\n\nAssistant: Okay.", ai=lambda t, s, v, model: ("{\"risky\": []}", {"risky": []}, 0, []))
    assert r["status"] == "stored" and "4821" not in r["masked"], r  # device rules still mask when the AI adds nothing
    print("ok")
