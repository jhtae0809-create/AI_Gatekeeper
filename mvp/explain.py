"""Explanations for the care demo, kept out of sight until asked for: the "How it works" dialog and the section tooltips.
Numbers come from experiments/ (Masking_v1, Vision_v1) and mvp/PLAN.md; check them there before changing.
"""

DEVICE, API = "#2a9d8f", "#5b6cff"


def _box(x, y, w, h, lines, color=None, bold=0):
    fill = f'fill="{color}" fill-opacity=".13" stroke="{color}"' if color else 'fill="none" stroke="currentColor" stroke-opacity=".45"'
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" {fill} stroke-width="1.4"/>']
    y0 = y + h / 2 - (len(lines) - 1) * 8 + 4
    for i, t in enumerate(lines):
        weight = ' font-weight="600"' if i < bold else ""
        out.append(f'<text x="{x + w / 2}" y="{y0 + i * 16}" text-anchor="middle"{weight}>{t}</text>')
    return "".join(out)


def _arrow(x1, y1, x2, y2, dash=False):
    d = ' stroke-dasharray="4 3"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="currentColor" stroke-opacity=".55" stroke-width="1.4" marker-end="url(#ah)"{d}/>'


def diagram():
    p = ['<svg viewBox="0 0 1000 380" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="12.5" fill="currentColor">',
         '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0 0L10 5L0 10z" fill="currentColor" fill-opacity=".6"/></marker></defs>']
    # inputs and conversion to text
    for i, t in enumerate(["🎤 Voice", "💬 Chat", "⌚ Wearable", "📷 Camera"]):
        p.append(_box(10, 30 + i * 65, 110, 40, [t], DEVICE))
    p.append(_box(150, 30, 130, 40, ["Speech to text", "(Whisper)"], DEVICE, 1))
    p.append(_box(150, 225, 130, 40, ["Text in the photo", "(Apple Vision OCR)"], DEVICE, 1))
    p += [_arrow(120, 50, 148, 50), _arrow(120, 245, 148, 245)]
    # answer and record
    p.append(_box(310, 10, 150, 50, ["Answer", "(Claude Haiku 5.5)"], API, 1))
    p.append(_box(310, 100, 150, 130, ["Record", "what was said + answer,", "a reading, or a photo", "question + its text + answer"], None, 1))
    p += [_arrow(280, 45, 308, 38), _arrow(120, 115, 308, 50), _arrow(385, 60, 385, 98),
          _arrow(280, 55, 308, 130), _arrow(120, 115, 308, 150), _arrow(120, 180, 308, 180), _arrow(280, 245, 308, 210), _arrow(280, 235, 308, 58)]
    # gatekeeper
    p.append('<rect x="490" y="10" width="240" height="300" rx="12" fill="none" stroke="currentColor" stroke-width="2"/>')
    p.append('<text x="610" y="32" text-anchor="middle" font-weight="700" font-size="14">Gatekeeper</text>')
    p.append(_box(505, 45, 210, 72, ["1  On-device finders", "regex, Presidio, GLiNER,", "detect-secrets, password rules", "mark names, numbers, secrets"], DEVICE, 1))
    p.append(_box(505, 130, 210, 72, ["2  AI check (gpt-6-luna)", "adds values the finders missed", "can add masks, never remove", "fails → record blocked"], API, 1))
    p.append(_box(505, 215, 210, 80, ["3  Harmful flag", "Granite Guardian on device,", "or the provider's safety filter", "(off for photos)"], DEVICE, 1))
    p += [_arrow(460, 165, 503, 80), _arrow(610, 117, 610, 128), _arrow(610, 202, 610, 213)]
    # after the gate
    p.append(_box(760, 110, 100, 60, ["Masked", "record"], None, 1))
    p.append(_box(760, 220, 100, 70, ["Routing", "emergency,", "health or none"], API, 1))
    p += [_arrow(730, 140, 758, 140), _arrow(810, 170, 810, 218)]
    for i, (t, s) in enumerate([("Family alerts", "emergencies"), ("Caregiver", "dashboard"), ("Log", "→ blockchain")]):
        p.append(_box(885, 30 + i * 105, 105, 50, [t, s], None, 1))
    p += [_arrow(860, 240, 883, 60), _arrow(860, 255, 883, 160), _arrow(860, 140, 883, 260, True)]
    # legend
    p.append(f'<rect x="10" y="335" width="16" height="16" rx="3" fill="{DEVICE}" fill-opacity=".25" stroke="{DEVICE}"/>'
             '<text x="32" y="348">On this device: nothing leaves</text>'
             f'<rect x="250" y="335" width="16" height="16" rx="3" fill="{API}" fill-opacity=".25" stroke="{API}"/>'
             '<text x="272" y="348">API call with zero data retention</text>'
             '<text x="520" y="348" fill-opacity=".75">Audio and photos are not saved or sent. Raw text stays in this browser session.</text>')
    p.append("</svg>")
    return "".join(p)


HOME = """
**A care device in the home of an older adult who lives alone.** It hears, sees and reads what happens during the day:

| Input | What it catches | Turned into text by |
|---|---|---|
| 🎤 Microphone | what the person says | Whisper, on the device |
| 💬 Messages | what the person types | (already text) |
| ⌚ Wearable or manual log | heart rate, a reading, a note | (already text) |
| 📷 Camera | a pill bottle, letter or bill the person holds up and asks about | Apple Vision OCR, on the device |

Chat, speech and photo questions get a short answer from a language model (Claude Haiku 5.5). For a photo it sees the question and the text read from the photo, not the photo.

Each turn becomes one **record**: what was said plus the answer, a reading, or a photo question with the text in the photo and the answer.
Any topic can come up: soup recipes, a grandchild's phone number, the bank PIN, a fall.
"""

WHY = """
**Records leave the home.** That is the point of the device:
- **Family alerts:** a fall or a call for help reaches family at once.
- **Caregiver dashboard:** sleep, pain and medication notes reach the caregiver.
- **Log and blockchain:** every decision is kept. A stored record goes on a blockchain once a person reads it and presses Permit: its masked text and verdict, which anyone can read and no one can delete.

**Home talk is full of values that should not travel.** Names and phone numbers of family, addresses, dates of birth, health details, card numbers, PINs and passwords.
Once one of them is in a shared dashboard or a permanent log, it cannot be taken back.

**So every record passes the gatekeeper before it leaves.** The gatekeeper:
1. replaces personal values and secrets with `[MASKED]`,
2. flags harmful content (distress, threats) so family gets a fixed alert instead of the text,
3. lets only health matters and emergencies through, with a short summary that names no one.

Small talk ("what soup for a cold day") is masked and logged but sent to no one.
"""

GATE = """
| Step | Where | What it does |
|---|---|---|
| 1. On-device finders | this Mac | **Regex and a secret scanner** (emails, phones, card numbers with a valid checksum, API keys), **Presidio** (names, ID numbers), **GLiNER** (a small model for personal data), **detect-secrets** (keys and tokens), and two rules for passwords and PINs (shape of the value, words such as "PIN is"). Each marks the spans it finds. |
| 2. AI check | API, zero data retention | **gpt-6-luna** sees the record with every word numbered and the marked words starred, and lists every word that is part of a risky value. It can only add masks. If the call fails or the answer is unreadable, the record is blocked. |
| 3. Harmful flag | this Mac | **Granite Guardian 3.1 2B** scores the record for harm (flag at 0.5 or more). A provider's safety filter stopping the answer also counts. A flagged record keeps only its hash and verdict; family gets a fixed alert. Photos get no harmful flag. |
| Routing | API, zero data retention | gpt-6-luna reads the **masked** record only and picks emergency, health or none, with a one-line summary that names no one. |
| Log | this Mac | Time, record hash, verdict, gate version, and the masked text for stored records. The raw record is never written to disk. |
| Blockchain | Ethereum Sepolia, after a person presses Permit | A record the gate stored goes to our contract (`LLMVerificationV2`) once a person reads it and presses Permit: its log line (masked text and verdict) and that line's hash. The transaction links to Etherscan. Flagged and blocked records cannot be written. |

**Measured on 3,500 test records (eval v1, test split):** after masking, 0.3% of PII records and 0.3% of credential records still show a risky value, at $0.12 per 1,000 records.
The price is over-masking: 45% of clean test chats get at least one mask (1.8% of their characters).

**Why two stages:** the on-device tools never send anything, but miss values without a fixed shape (a first name, a short PIN).
The AI check catches those, and it only sees text that the device tools have already marked.
"""

PHOTOS = """
**Why a care device reads photos:** an older adult with weak eyesight holds up a pill bottle, a letter or a bill and asks about it: "When do I take this?", "What does this letter say?".
The answer helps the person; the record of the turn tells the caregiver what came up ("blood pressure pills, once a day", "power bill due on the 25th").
The document is full of names, addresses and account numbers that the caregiver does not need. The gatekeeper keeps those out of the record.

**What happens to a photo:**
1. The text in the photo is read on the device (Apple Vision OCR, in four orientations because photos are often sideways).
2. The answer model gets the question and that text. The photo is not sent.
3. The record (question, text in the photo, answer) goes through the same gatekeeper as speech.
4. On screen, every line with a masked value and every QR code or barcode is painted black.

**In scope:** text in view that identifies a person or gives access: names with an address or phone, dates of birth, ID numbers, card and account numbers.

**Out of scope:** image privacy, including home-camera footage: faces, bodies and nudity, the inside of the home, or something happening in it.

**Why no harmful flag on photos:** text in view, such as a page of a novel or a news story, is not what the person said.
Granite Guardian flagged 47.5% of 695 harmless photos with text as harmful (text records: 10.3%).

**Known limits:** the answer can only use text that OCR reads (71.5% of the risky values in the photo test); masking covers whole lines; blurred or cut-off QR codes are missed.
"""

LIMITS = """
- English only: Whisper `small.en` and every masking tool.
- The test set is WildChat and Aegis chats with fake values. Home talk with first names, family and health details was not measured, so a name can slip through.
- Routing (who receives what) was checked only on the demo scenarios.
- Each turn takes a few seconds: two API calls and several on-device models.
- The answer model sees the last three exchanges, so it may still refer to something said just before.
"""

TIPS = {
    "home": "The device in the home. Speak, type, send a wearable reading or a camera photo. Each input becomes one record. "
            "Audio and photos are not sent; the raw text stays in this browser session.",
    "gate": "What the gatekeeper did to one record: the raw record with each found value highlighted, which tool found it, and what may leave the home. "
            "Click a row in the log below to see another record.",
    "out": "What reached family and the caregiver. Only health matters and emergencies are sent, masked, with a summary that names no one. "
           "A harmful record sends a fixed alert, never its text. Family alerts wait until someone presses Handled.",
    "log": "The gatekeeper's log: one row per record, kept on this Mac. A stored record goes on the blockchain, masked text included, once a person presses Permit; its row links to the transaction. Raw text is never written; stored records keep their masked text, flagged and blocked ones only the hash and verdict. Marking a family alert handled adds a row. "
           "Click a row to open it above.",
}
