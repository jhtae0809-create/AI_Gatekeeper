"""Does each PUPA user_query still match its WildChat-1M source? Counts only, no text is printed or saved.

Input:  Dataset/PUPA/hf/PUPA_TNB.csv, PUPA_New.csv and Dataset/WildChat/*.parquet (joined on conversation_hash).
Output: out/pupa_vs_wildchat.json.
For each row: identical to a source user message, differs (closest source message, number of edit operations),
or source not found. Also whether a <PRESIDIO_ANONYMIZED_*> tag sits in PUPA, in the source, or both.

Notebook link: it is the reason for the PUPA cell in pilot_set_v2.ipynb, which replaces names and tags with Faker values.
The notebook reads the GitHub CSVs; these are identical to the HF CSVs used here (provenance log 9.1).

Result (2026-10-02): TNB 69 identical, 152 differ, 16 not found. New 240 identical, 422 differ, 2 not found.
Every Presidio tag in PUPA is also in the source (41 rows), so the tags come from WildChat, not from PUPA.
"""
import glob, json, difflib, collections, pandas as pd, pyarrow.parquet as pq

D = "/Users/jhtae/PaperReview/Gatekeeper_Experiments/Dataset/"
pupa = pd.concat([pd.read_csv(D + f"PUPA/hf/{f}.csv").assign(split=f) for f in ["PUPA_TNB", "PUPA_New"]])
want = set(pupa.conversation_hash)
src = collections.defaultdict(list)  # hash -> user messages
for f in sorted(glob.glob(D + "WildChat/*.parquet")):
    t = pq.read_table(f, columns=["conversation_hash", "conversation"])
    for h, conv in zip(t.column(0).to_pylist(), t.column(1).to_pylist()):
        if h in want:
            src[h] += [m["content"] or "" for m in conv if m["role"] == "user"]

c = collections.Counter()
for split, h, q in zip(pupa.split, pupa.conversation_hash, pupa.user_query.fillna("")):
    msgs = src.get(h)
    if not msgs:
        c[f"{split}|hash_not_in_wildchat_1m"] += 1
        continue
    if q in msgs:
        c[f"{split}|identical_to_source"] += 1
        continue
    best = max(msgs, key=lambda m: difflib.SequenceMatcher(None, q, m, autojunk=False).ratio() if abs(len(m) - len(q)) < 3000 else 0)
    ops = [op for op in difflib.SequenceMatcher(None, best, q, autojunk=False).get_opcodes() if op[0] != "equal"]
    c[f"{split}|differs"] += 1
    c[f"{split}|differs_edit_ops_total"] += len(ops)
    c[f"{split}|differs_presidio_tag_in_pupa"] += "<PRESIDIO_ANONYMIZED_" in q
    c[f"{split}|differs_presidio_tag_in_source"] += "<PRESIDIO_ANONYMIZED_" in best
out = dict(sorted(c.items()))
print(json.dumps(out, indent=1))
json.dump(out, open("/Users/jhtae/PaperReview/Gatekeeper_Experiments/out/pupa_vs_wildchat.json", "w"), indent=1)
