# MVP: gateway and app frame

A gateway decides what part of each conversation record may leave the device. Apps on top of it differ only in a config file. The first app is a senior care companion: any topic can come up at home, and only health matters and emergencies reach family and the caregiver, masked.

```
Input                         Processing                                           Output
voice → Whisper (on device) ┐
typed chat ─────────────────┼→ answer: LLM API (ZDR) ┐
wearable / manual log ──────┤
camera photo → OCR (device) ┘                        ├→ record → GATEWAY ──→ route (LLM, masked record only) → app channels
                                                     │     1. on-device tools + credential rules mask spans      (alerts, dashboard)
                                                     │     2. AI check adds missed spans (gpt-6-luna, ZDR)
                                                     │     3. harmful flag (Granite Guardian, on device)        → local log
                                                     │        provider safety filter also counts as harmful       (hash, verdict, masked text)
                                                                                                           → blockchain (Permit)
```

## Run

```bash
streamlit run mvp/app.py --client.toolbarMode minimal -- care
```

- First start loads Presidio, GLiNER, Granite Guardian and Whisper (about a minute). Later turns take about 5 seconds.
- Needs `experiments/.env` with `OPENROUTER_API_KEY`, `faster-whisper` (`pip install faster-whisper`) and, for photos, `ocrmac` (`pip install ocrmac`, macOS only).
- Blockchain writes need `web3` (`pip install web3==7.6.0`) and `PRIVATE_KEY` of a Sepolia test wallet with test ETH in `experiments/.env`. Without the key the app runs and the Permit button is off.
- Smoke test without the screen: `python mvp/frame.py care` (each scenario once, about $0.0002 per turn).
- Gateway self-test, no API: `python mvp/gateway.py`.

## Files

| File | Role |
|---|---|
| `gateway.py` | The engine. `check(record)` returns the verdict and masked text; `log()` is the only writer. No app knowledge |
| `chain.py` | Writes a stored record to our contract on Ethereum Sepolia once a person reads it and presses Permit: its log line (masked text and verdict) and the line's hash. Looks hashes up; links transactions to Etherscan |
| `frame.py` | One turn of any app: speech to text, text in a photo (Apple Vision OCR, `experiments/scripts/vision.py`), answer, gateway, routing to the app's channels. A photo comes with a question; the answer model gets the question and the OCR text (`photo_ask`), and the record is question + text in the photo + answer. No harmful flag on photos (text in view, such as a page of a novel, is not what the person said); lines with a masked value and every QR code or barcode (Apple Vision, content not read into the record) are painted black on screen; the photo is not sent |
| `app.py` | One screen for every app: the scene picture, input on the left, what the gateway did in the middle, what was sent on the right, log and Permit below. Records wait in a queue that one background worker checks in order, so the conversation goes on |
| `scene.svg` | The scene under the title: the person at home, the gatekeeper on the home hub, what leaves through the door |
| `apps/care.py` | The care app: assistant prompt, categories, channels, fixed alert text, demo scenarios and photos |
| `logs/gate_log.jsonl` | Local log, created on first use. Not in git |

Detection code is imported from `experiments/scripts/` (`masking.py`, `gate.py`, `secretscan.py`), the code that was measured.

## A new app

Copy `apps/care.py` to `apps/<name>.py` and change the values:

| Name | Meaning |
|---|---|
| `NAME`, `TITLE` | Log name and page title |
| `ASSISTANT` | System prompt of the answering LLM |
| `SAFE_REPLY` | Fixed answer used when the provider's safety filter stops the answer |
| `ROUTE_CONTEXT`, `CATEGORIES` | What the app forwards: `{category: (what it covers, channel)}`. Anything else stays home |
| `CHANNELS`, `REVIEW_CHANNEL` | Receivers shown as tabs; where unsortable records go |
| `HARMFUL_ALERT` | `(channel, fixed text)` for harmful records. Their text is never forwarded |
| `EVENT_LABEL`, `SCENARIOS`, `PHOTOS` | Label of the sensor/log input; one button per scenario; sample photos and their questions |

Then `streamlit run mvp/app.py --client.toolbarMode minimal -- <name>`. The gateway does not change.
