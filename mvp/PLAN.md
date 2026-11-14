# MVP plan

A local demo: a gateway, an app frame on top of it, and a first app, a senior care companion (IoT care at home: any topic can come up; only health matters and emergencies leave the home). Runs on one Mac, no deploy link. How to run and how to add an app: `README.md`.

## Flow

See the diagram in `README.md`.

## Decisions

| Topic | Decision | Reason |
|---|---|---|
| LLM API | Sees the raw conversation. Requests use `"provider": {"zdr": true}` | The API is a processor under contract. The gate guards what leaves the app (logs, reports, a chain). gpt-6-luna and claude-haiku-5.5 have ZDR endpoints (checked 2026-11-07) |
| Gateway and apps | `gateway.py` holds every check and the log; an app is a config module in `apps/`; `app.py` is one screen for all apps | A new topic needs a new config, not new gateway code |
| Masking | Regex, Presidio, GLiNER, detect-secrets, plus two credential rules (`pw_shape`, `keyword` in `experiments/scripts/masking.py`) | Masking_v1 test: credential secret part masked 82.2% → 91.7% with the rules; PII cleaned 98.9% |
| AI check | gpt-6-luna sees the record with every word numbered and device masks starred, and returns the numbers of risky words. Its answer only adds masks; it never removes one | Masking_v1 test: credential readable 0.3%, PII readable 0.3%, no record blocked, $0.12 per 1,000 records. Letting the AI remove masks put readable PII back (32%); the value format with removal left 6.6% of credentials readable |
| Gate v2 blocking | Not used for PII and credentials | Blocking drops 59% of all records (most of them safe) for credential readable 0.0% and PII 0.3% on test; masking keeps the record |
| Harmful | Flag, never block. Content is not logged, only hash and verdict. A fixed alert text goes to the app's alert channel, never free LLM text. A provider safety-filter stop (answer or routing) also counts as harmful, as in the experiments | A self-harm disclosure is health information even with no name. In the smoke test Granite scored a self-harm statement 0.09 to 0.49 (below 0.5); the provider filter and the routing category caught it |
| Routing | After the gateway, an LLM (gpt-6-luna, ZDR) sorts the masked record into one of the app's categories and writes a one-line summary. Anything outside the categories is not forwarded; an unreadable answer goes to a review channel | The router sees masked text only, so its summary cannot hold the masked values |
| Answer model | claude-haiku-5.5 (ZDR) | gpt-6-luna repeated its whole answer in 3 of 4 tries (2026-11-08) |
| Failure | Any API error or unclear answer blocks (fail-closed) | Same rule as the experiments |
| Raw text | Kept in memory for the session only; never written to disk | The log holds only what may leave the app |
| Log entry | time, record hash, status (stored, flagged, blocked), harmful score, number of masks, masked text if stored, gate version (models, thresholds, tools), app fields (kind, category, receiver) | Audit trail; a permitted chain write carries this line |
| UI | Streamlit (installed, 1.62; `st.audio_input` for the mic) | One page: a scene picture (home, gatekeeper, outside), input and answer, masked spans, verdict, alerts, log table, Permit |
| Gatekeeper queue | The answer shows first; the record then joins a queue that one background worker checks in arrival order | The conversation goes on while the gatekeeper runs; a new message no longer cuts a check short |
| Speech | `faster-whisper` 1.2.1, `small.en`, CPU int8; wav decoded with the standard library (the installed `av` 19 breaks faster-whisper's decoder) | On-device STT, about 2 seconds per clip. Spoken numbers come out as digits (`four eight two nine` → `4829`), so the device rules mask them |
| Record labels | Spans inside `User:`, `Assistant:`, `Event:` are dropped | GLiNER sometimes tags `Assistant` as a person |
| Models | Loaded once at start (Presidio, GLiNER, Granite, Whisper) | First start takes tens of seconds; a decision then takes a few seconds |
| Code | `mvp/` imports `experiments/scripts/` (masking.py, gate.py, secretscan.py); no copies | One detection code base |

## Blockchain (2026-11-14)

`chain.py` writes a stored record to our `LLMVerificationV2` contract on Ethereum Sepolia (`0xF11A5C310Db05ADC4C4f8cb88b144bA900Fe0843`) once a person reads it and presses Permit. The Permit button is the safeguard: nothing goes on chain without it.

- On chain: `storeRecord(sha256 of the record, "none", record)`, where the record is the log line as canonical JSON, masked text included, without the raw-record hash (with the masked text it would let anyone test guesses for a masked value).
- Test write 2026-11-14: [0xc613…84a5](https://sepolia.etherscan.io/tx/0xc61375af93619675cdec85b1970d61dfb875abe4cc7ae56d6e891dc039a584a5), read back with `getRecord`.
- Each write adds a log row (status `anchored`, the content hash, the transaction hash); the log table links it to Etherscan.
- Only records the gate stored can be written. The contract rejects a hash that is already there, so `chain.anchor` checks first.
- Needs `PRIVATE_KEY` of a Sepolia test wallet with test ETH in `experiments/.env`. Without it the Permit button is off; lookups still work through the public RPC.

## Demo scenarios (care app, smoke test 2026-11-08)

| Scenario | Result |
|---|---|
| Small talk | stored, nothing forwarded |
| Medication with names and phone | names and phone masked, health → caregiver dashboard |
| Bank PIN | PIN masked, nothing forwarded |
| Look-alike (`YOUR_WIFI_PASSWORD`) | masked by GLiNER (over-masking), nothing forwarded |
| Fall | emergency → family alert |
| Distress | harmful (provider filter), fixed alert, no text logged |
| Watch reading (148 bpm at rest) | emergency → family alert |
| Voice (macOS `say`, Samantha) | PIN and phone transcribed as digits and masked on device |
| Silence (3 s, 2026-11-13) | nothing transcribed (Whisper VAD; it used to write "you you") |
| Photo: prescription, "When should I take this medicine?" (2026-11-13) | answer from the label text; member ID, date of birth, phone, address, email masked; health → dashboard. First and last name on separate OCR lines stay unmasked |
| Photo: bank statement, "Do I need to pay anything on this?" | answer from the statement text; name, address, account number masked; none → nothing sent |

## Limits to state in the demo

- The test set is WildChat and Aegis chats with fake values. Home talk with first names, family, places and health details was not measured.
- The routing step (which records reach family) was only checked on the demo scenarios.
- English only: Whisper `small.en` and every masking tool.
- Harmful flagging of distress statements was not measured.
- Decisions take seconds, not milliseconds.
- Over-masking: 45% of clean test chats get at least one mask (1.8% of characters). Hard negatives such as `YOUR_API_KEY` talk get masked often (70%).
- The password rule was tuned on the four fake-password styles of the test set. Real passwords may be caught less often.
- Photos: only text in view is checked. Image privacy, including home-camera footage (faces, bodies, the inside of the home, events in it), is outside the scope. Text that OCR cannot read cannot be masked, masks cover whole lines, and blurred or cut-off QR codes are missed.
