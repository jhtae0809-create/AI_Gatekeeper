import nbformat as nbf

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip("\n")))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip("\n")))

md("""
# Local detectors on eval set v1

Runs on this laptop with no API call, so nothing leaves the machine. Results are written to `out/eval_v1_runs/LOCAL__<name>.jsonl` in the same format as the API runs (`idx`, `raw`, `pred`). `raw` holds one 0/1 decision per axis the detector covers. `Gatekeeper_v1.ipynb` reads these files in E4, E6 and E8.

The notebook can run on another laptop: copy `data/eval_v1.jsonl` and `scripts/`, run, and copy the four `LOCAL__*.jsonl` files back.

| Detector | Axis | Model or rules | Licence |
|---|---|---|---|
| Presidio | pii (and card or bank numbers for credential) | Microsoft Presidio analyzer, spaCy `en_core_web_lg` | MIT |
| GLiNER-PII | pii and credential | `knowledgator/gliner-pii-base-v1.0`, zero-shot entity labels | Apache-2.0 |
| detect-secrets | credential | Yelp detect-secrets, default plugins and filters | Apache-2.0 |
| Granite Guardian | harmful | `ibm-granite/granite-guardian-3.1-2b`, risk `harm` | Apache-2.0 |

Llama Guard 3 1B was the plan (design doc section 5). Its Hugging Face repo is gated (licence acceptance and login), and this machine is not logged in, so Granite Guardian 3.1 2B is used instead. Llama Guard can be added later in the same format.

**Rules for the pii axis** (design doc section 3, applied to the entities each detector finds): a full name (two or more words) together with a phone number, email, address or place, date, or medical record number; or an SSN or passport number on its own.
""")
code("""
import collections, json, os, re, sys, time
import pandas as pd
sys.path.insert(0, "/Users/jhtae/PaperReview/Gatekeeper_Experiments/scripts")
import gate as G

recs = [json.loads(l) for l in open(G.DATA)]
N = len(recs)
LIMIT, OUTDIR = None, G.RUNS  # smoke test: LIMIT, OUTDIR = 5, G.ROOT + "out/eval_v1_smoke/"
os.makedirs(OUTDIR, exist_ok=True)


def run_local(name, fn, limit=LIMIT):
    \"\"\"fn(text) -> {axis: 0/1, ...}. Resumable, like G.run.\"\"\"
    path = G.run_path("LOCAL", name, OUTDIR)
    done = {json.loads(l)["idx"] for l in open(path)} if os.path.exists(path) else set()
    todo = [i for i in range(N)[:limit] if i not in done]
    t = time.time()
    with open(path, "a") as fo:
        for i in todo:
            raw = fn(recs[i]["text"])
            fo.write(json.dumps({"idx": i, "raw": raw, "pred": int(any(raw.get(a) == 1 for a in G.AXES))}) + "\\n")
    print(f"{name}: {len(todo)} new in {time.time() - t:.0f}s")
""")
md("## Presidio")
code("""
CRED_ENT = {"CREDIT_CARD", "IBAN_CODE", "US_BANK_NUMBER"}


def presidio_fn(text):
    ents = G.presidio(text, ["PERSON", "LOCATION", "DATE_TIME"] + G.PRESIDIO_ID)
    kinds = {e for e, _, _ in ents}
    return {"pii": G.presidio_pii(text), "credential": int(bool(kinds & CRED_ENT)), "entities": sorted(kinds)}


run_local("presidio", presidio_fn)
""")
md("## detect-secrets")
code("""
run_local("detect-secrets", lambda t: (lambda ty: {"credential": int(bool(ty)), "types": ty})(G.detect_secrets_types(t)))
""")
md("""
## GLiNER-PII

GLiNER reads about 384 tokens at a time, so each record is split into overlapping 1,000-character chunks. Threshold 0.5 (the model card default).
""")
code("""
from gliner import GLiNER

gl = GLiNER.from_pretrained("knowledgator/gliner-pii-base-v1.0")
LABELS = ["person", "phone number", "email", "address", "date of birth", "medical record number", "social security number",
          "passport number", "credit card number", "bank account number", "password", "api key", "pin"]
CONTACT = {"phone number", "email", "address", "date of birth", "medical record number"}
CRED_L = {"credit card number", "bank account number", "password", "api key", "pin"}


def gliner_fn(text, size=1000, step=800):
    ents = []
    for s in range(0, max(len(text) - 200, 1), step):
        ents += gl.predict_entities(text[s:s + size], LABELS, threshold=0.5)
    kinds = {e["label"] for e in ents}
    name = any(e["label"] == "person" and len(e["text"].split()) >= 2 for e in ents)
    pii = int(bool(kinds & {"social security number", "passport number"}) or (name and bool(kinds & CONTACT)))
    return {"pii": pii, "credential": int(bool(kinds & CRED_L)), "labels": sorted(kinds)}


run_local("gliner", gliner_fn)
""")
md("""
## Granite Guardian 3.1 2B (harmful)

The whole record goes in as the user message with risk `harm`. The model answers Yes or No; the score is the probability of Yes from the first output token, as in the model card. Decision at 0.5. float16 on Apple MPS, about 1.6 seconds per record (about 95 minutes for the set).
""")
code("""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

GG = "ibm-granite/granite-guardian-3.1-2b"
dev = "mps" if torch.backends.mps.is_available() else "cpu"
tok = AutoTokenizer.from_pretrained(GG)
gg = AutoModelForCausalLM.from_pretrained(GG, dtype=torch.float16).to(dev).eval()  # float16: 1.6 s per record on this Mac, bfloat16 2.3 s
YES = [tok.convert_tokens_to_ids(t) for t in ("Yes", "yes")]
NO = [tok.convert_tokens_to_ids(t) for t in ("No", "no")]


@torch.no_grad()
def granite_fn(text):
    ids = tok.apply_chat_template([{"role": "user", "content": text}], guardian_config={"risk_name": "harm"},
                                  add_generation_prompt=True, return_tensors="pt", return_dict=True)["input_ids"].to(dev)
    logits = gg(ids).logits[0, -1].float()
    p = torch.softmax(logits[YES + NO], 0)
    p_yes = float(p[:len(YES)].sum())
    return {"harmful": int(p_yes >= 0.5), "p_yes": round(p_yes, 4)}


run_local("granite-guardian", granite_fn)
""")
md("## Quick check (all records)")
code("""
rows = {}
for name in ["presidio", "detect-secrets", "gliner", "granite-guardian"]:
    raw = G.load("LOCAL", name, OUTDIR, field="raw")
    for ax in G.AXES:
        if not any(ax in v for v in raw.values()):
            continue
        pos = [i for i in raw if recs[i][ax]]
        neg = [i for i in raw if not recs[i][ax]]
        rows[f"{name} | {ax}"] = {"recall": sum(raw[i][ax] for i in pos) / len(pos),
                                  "fp_rate": sum(raw[i][ax] for i in neg) / len(neg),
                                  **{f"fp_{g}": sum(raw[i][ax] for i in neg if recs[i]["group"] == g) / max(1, sum(recs[i]["group"] == g for i in neg))
                                     for g in ["clean", "credential_hn", "pii_hn", "harmful_safe"]}}
pd.DataFrame(rows).T.round(3)
""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
nbf.write(nb, "/Users/jhtae/PaperReview/Gatekeeper_Experiments/Gatekeeper_v1_local.ipynb")
print("written", len(cells), "cells")
