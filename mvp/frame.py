"""App frame: one turn of any app built on the gateway. The app itself is a config module in apps/.

turn(app, history, text, kind):
  kind "speech" or "chat": the LLM answers (ZDR), record = user text + answer
  kind "event": a wearable reading or manual log, record = the event text, no answer
  kind "photo": a question about a camera photo; the text in it is read on the device (photo_text) and the answer model gets
    the question and that text, not the photo; record = question + text in the photo + answer
  then gateway.check(record), then route() sorts the masked record into one of the app's categories,
  and the app's channel for that category receives a short summary and the masked record.
Audio is transcribed in memory and never saved.

Smoke test: python mvp/frame.py care (runs the app's scenarios, about 2 API calls each)
"""
import importlib
import io
import json
import os
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gateway as GW  # noqa: E402
import gate as G  # noqa: E402  (experiments/scripts, on the path through gateway)
import masking as MK  # noqa: E402
import vision as V  # noqa: E402

LLM = GW.AI_MODEL  # routing
REPLY = "anthropic/claude-haiku-5.5"  # answers; gpt-6-luna repeated its answer twice in 3 of 4 tries (2026-11-08)
WHISPER = "small.en"  # shortcut: English only, like every gateway tool; a multilingual model needs non-English masking tools too
BODY = {"provider": {"zdr": True}, "reasoning": {"effort": "none"}, "usage": {"include": True}}

OCR, ORIENT = "apple", "best4"  # gate v2's pick on validation (experiments/Vision_v1.ipynb section 6, 2026-11-12)
PHOTO = V.PHOTO
HISTORY = 6  # messages of earlier turns the answer model sees; older talk (an old fall) stops steering every answer
_whisper = None


def app(name):
    return importlib.import_module(f"apps.{name}")


def stt(audio):
    """Speech to text on device (faster-whisper). audio: bytes of a wav file."""
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(WHISPER, device="cpu", compute_type="int8")
    import numpy as np
    with wave.open(io.BytesIO(audio)) as w:  # decoded here: faster-whisper 1.2.1 fails with the installed av 19
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype={2: np.int16, 4: np.int32}[width]).astype(np.float32)
    x = x.reshape(-1, ch).mean(1) / (2 ** (8 * width - 1))
    x = np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x).astype(np.float32)  # to 16 kHz
    segments, _ = _whisper.transcribe(x, language="en", vad_filter=True)  # without it, silence came back as "you you you"
    return " ".join(s.text.strip() for s in segments).strip()


def _chat(messages, max_tokens, model=LLM):
    """Returns (text, cost, filtered). filtered: the provider's safety filter stopped the answer (counted as unsafe, as in the experiments)."""
    out = G.client().chat.completions.create(model=model, temperature=0, max_tokens=max_tokens, extra_body=BODY, messages=messages)
    cost = getattr(out.usage, "cost", None) if out.usage else None
    if not out.choices or out.choices[0].finish_reason == "content_filter":
        return "", cost, True
    return (out.choices[0].message.content or "").strip(), cost, False


def photo_text(data):
    """Text in a photo, read on the device. data: image file bytes. Returns (image, text, words, QR/barcode boxes); the photo is never saved.
    QR codes are always masked on screen and their content never enters the record (user decision 2026-11-12)."""
    img = V.load(io.BytesIO(data))
    words = V.orient({a: V.ENGINES[OCR](img, a) for a in V.ANGLES}, ORIENT)
    return img, V.text_of(words), words, V.codes(img)


def reply_stream(a, history, text, meta):
    """The app's answer, yielded as it arrives so the screen shows it before the gatekeeper runs.
    Fills meta with answer, cost and filtered; a filtered answer is replaced by the app's fixed SAFE_REPLY."""
    msgs = [{"role": "system", "content": a.ASSISTANT}] + history[-HISTORY:] + [{"role": "user", "content": text}]
    parts = []
    meta.update(cost=None, filtered=False)
    for ch in G.client().chat.completions.create(model=REPLY, temperature=0, max_tokens=300, extra_body=BODY, messages=msgs, stream=True):
        if getattr(ch, "usage", None):
            meta["cost"] = getattr(ch.usage, "cost", None)
        if ch.choices:
            meta["filtered"] |= ch.choices[0].finish_reason == "content_filter"
            if ch.choices[0].delta.content:
                parts.append(ch.choices[0].delta.content)
                yield ch.choices[0].delta.content
    meta["answer"] = a.SAFE_REPLY if meta["filtered"] or not parts else "".join(parts).strip()


def route(a, masked):
    """Category of the masked record among the app's categories, or 'none'. An unreadable answer gives 'review'."""
    cats = "\n".join(f"- {k}: {d}" for k, (d, _) in a.CATEGORIES.items()) + "\n- none: anything else"
    prompt = (f"{a.ROUTE_CONTEXT}\nPick the one category this record belongs to:\n{cats}\n\n"
              "Judge by what the person says or what the device reports in this record. The assistant's words are context only: "
              "an assistant reply that recalls an earlier emergency does not make this record an emergency.\n"
              "Personal values in the record are replaced by [MASKED]. Reply with JSON only: "
              "{\"category\": \"...\", \"summary\": \"one short sentence for the receiver, with no names or personal values\"}\n\n"
              f"Record:\n{masked}")
    raw, cost, filtered = _chat([{"role": "user", "content": prompt}], 120)
    if filtered:
        return "harmful", "", cost
    p = MK.parse_json(raw) or {}
    cat = p.get("category")
    return (cat if cat in a.CATEGORIES or cat == "none" else "review"), str(p.get("summary", "")), cost


def photo_ask(question, text):
    """What the answer model gets for a photo: the question and the text read on the device, not the photo."""
    return f"{question}\n\nText the camera read from what I am showing you (it may be incomplete or wrong):\n{text or '(no text found)'}"


def turn(a, history, text, kind="chat", said=None, question=None):
    """One input through the whole app. Returns everything the UI shows; nothing raw is written to disk.
    said: the answer already streamed to the screen (meta from reply_stream); None gets it here.
    question: for a photo, what the person asked about it; text is then the OCR text."""
    answered = kind in ("speech", "chat", "photo")
    if answered and said is None:
        said = {}
        for _ in reply_stream(a, history, photo_ask(question, text) if kind == "photo" else text, said):
            pass
    answer, cost, filtered = (said["answer"], said["cost"], said["filtered"]) if answered else (None, None, False)
    head = f"User: {question}\n\n{PHOTO}" if kind == "photo" else ""
    record = {"event": f"Event: {text}", "photo": f"{head}{text}\n\nAssistant: {answer}"}.get(kind) or f"User: {text}\n\nAssistant: {answer}"
    g = GW.check(record, harm=kind != "photo")
    out = {"kind": kind, "text": text, "question": question, "answer": answer, "record": record, "photo_at": len(head), "gate": g,
           "category": None, "sent": None, "cost": (cost or 0) + (g["cost"] or 0)}
    if filtered and kind != "photo" and g["status"] == "stored":
        g["status"] = "flagged"  # the provider's filter stopped the answer: counted as harmful, so only hash and verdict are kept
    cat = "harmful" if g["status"] == "flagged" else None
    if cat is None and g["status"] == "stored":
        cat, summary, rc = route(a, g["masked"])
        out["cost"] += rc or 0
        if cat == "harmful" and kind == "photo":
            cat = "review"  # no harmful verdict from photos; a filtered routing call goes to review instead
        if cat == "harmful":
            g["status"] = "flagged"
    out["category"] = cat
    if cat == "harmful":  # fixed alert text, the masked record is not sent
        channel, message = a.HARMFUL_ALERT
        out["sent"] = {"channel": channel, "summary": message, "masked": None}
    elif g["status"] == "stored":
        if cat in a.CATEGORIES:
            out["sent"] = {"channel": a.CATEGORIES[cat][1], "summary": summary, "masked": g["masked"]}
        elif cat == "review":
            out["sent"] = {"channel": a.REVIEW_CHANNEL, "summary": "Could not be sorted. Please read the masked record.", "masked": g["masked"]}
    out["log"] = GW.log(g, app=a.NAME, kind=kind, category=out["category"], sent_to=out["sent"] and out["sent"]["channel"])
    return out


if __name__ == "__main__":
    a = app(sys.argv[1] if len(sys.argv) > 1 else "care")
    GW.load()
    for name, (kind, text) in a.SCENARIOS.items():
        o = turn(a, [], text, kind)
        g = o["gate"]
        print(json.dumps({"scenario": name, "status": g["status"], "p_harm": g["p_harm"], "category": o["category"],
                          "sent_to": o["sent"] and o["sent"]["channel"], "masked": g["masked"], "summary": o["sent"] and o["sent"]["summary"],
                          "found": [(o["record"][s:e], src) for s, e, src in g["found"]], "cost": round(o["cost"], 6), "error": g["error"]},
                         ensure_ascii=False))
