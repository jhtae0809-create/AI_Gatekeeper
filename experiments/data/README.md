# Data

Two labeled sets for gating stored LLM records: a text set of 3,500 conversation records and labels for 1,030 home images.

Content warning: the harmful group holds unsafe text from Aegis 2.0, including hate, harassment, sexual content and criminal planning.

Every personal value and credential in the text set is synthetic. Credentials are format-valid (card numbers pass the Luhn check, keys follow vendor prefixes such as `sk_live_`, `ghp_` and `AIza`), so secret scanners may flag them. None of them opens any account. Generated values were checked against hashes of every secret found in WildChat-1M, so none of them copies a real one.

## Files

| File | Content |
|---|---|
| `eval_v1.zip` | Text set, 3,500 records: `eval_v1.jsonl`, one JSON object per line. Unzip here; the notebooks and scripts read `data/eval_v1.jsonl` |
| `eval_v1_counts.json` | Build counts and checks |
| `frames_v1.jsonl` | Generated message frames with empty slots, used to insert values |
| `image_labels_v1.jsonl` | Labels for 1,030 images of the BIV-Priv-Seg query set |

Build code: `../build_eval_v1.ipynb` and `../scripts/build_eval.py` for the text set, `../Vision_v1.ipynb` and `../scripts/vision.py` for the image labels.

## Text set

Seven groups of 500 records. 700 of the 1,000 PII and credential records have a safe look-alike twin with the same `pair_id`.

| Group | Source | Label |
|---|---|---|
| `pii` | WildChat-1M conversation with an inserted synthetic identifier | pii = 1 |
| `pii_hn` | Same kind of text with the identifier masked, a placeholder, or no value | safe |
| `credential` | WildChat-1M conversation with an inserted synthetic credential | credential = 1 |
| `credential_hn` | Credential talk with no secret, a placeholder, or a masked value | safe |
| `clean` | WildChat-1M conversation as it is | safe |
| `harmful` | Aegis 2.0 record labeled unsafe | harmful = 1 |
| `harmful_safe` | Aegis 2.0 record labeled safe | safe |

Split: 1,064 validation and 2,436 test records, with twins on the same side.

| Field | Meaning |
|---|---|
| `id` | Record id |
| `split` | `validation` or `test` |
| `text` | The record as the gate sees it: `User:` and `Assistant:` turns |
| `prompt`, `response` | The two turns |
| `pii`, `credential`, `harmful` | Risk labels, 0 or 1 |
| `dangerous` | 1 if any risk label is 1 |
| `group` | One of the seven groups |
| `type` | Value type (for example `name_phone`, `api_key`, `card`), `talk` for credential talk, the Aegis category for harmful records |
| `hard_negative` | How a safe twin was made |
| `mask_style` | `masked`, `stars`, `redacted` or `placeholder` for masked twins |
| `location` | Where the value sits (for example `user:end`) |
| `spans` | Character spans of inserted values in `text` |
| `pair_id` | Shared by a risky record and its twin |
| `frame_id` | Frame used for insertion |
| `conv_id`, `origin_dataset`, `origin_id` | Source conversation |

## Image labels

Labels for the 1,030 kept images of the BIV-Priv-Seg query set (26 black frames left out). The images are not included; get them from BIV-Priv-Seg. Values in the images are printed on props.

| Field | Meaning |
|---|---|
| `image` | File name in the BIV-Priv-Seg query set |
| `split` | `validation` or `test` (515 each); images that share a value stay on one side |
| `pii`, `credential` | Risk labels under the text-set rules |
| `risky` | 1 if either label is 1 |
| `values` | Readable values with their kind |
| `label_source` | `checked` for the 157 images checked by hand, `draft` for the 873 kept from the model draft |

309 images are risky (155 validation, 154 test). Drafts came from Claude Opus 5.5 reading each image. On the 157 checked images, the hand labels agree with the drafts on PII for 155 and on credentials for all 157.

## Sources and licenses

| Source | License | Used for |
|---|---|---|
| WildChat-1M | ODC-BY 1.0 | Host conversations for the text set |
| Aegis 2.0 | CC BY 4.0 | Harmful and safe records |
| Nemotron-PII | CC BY 4.0 | Credential formats |
| BIV-Priv-Seg | CC BY 4.0 | Images labeled here |

Records keep the license of their source.
