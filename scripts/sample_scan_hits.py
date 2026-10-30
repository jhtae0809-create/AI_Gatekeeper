"""Hand-read sample of the hits scan_wildchat.py called "secret": up to 6 per kind (seed 0), 200 characters of context.

Input:  out/wildchat_hits.jsonl and Dataset/WildChat/*.parquet (to fetch the context).
Output: out/review_scan_hits.md, with three boxes per item (real secret, placeholder, false hit).
In the context, every scanner hit and every other token of 20+ characters with entropy of 3.5 bits or more is masked,
since some secrets (AWS secret keys, request signatures) have no scanner pattern.

Notebook link: none. It checks how precise the scanner is. data/review_wildchat.md is the other hand-review sheet;
it checks the pilot originals, which are records the scanner did not flag.

To read items unmasked: `python sample_scan_hits.py 1 3 5` prints items 1, 3 and 5 in full to the terminal, with the hit
between >>> and <<<. Nothing is written to disk, so real secrets stay out of files.

Result: 2026-10-02, 56 items. A first read found real-looking keys (provenance log 9.5). The boxes were not ticked.
2026-10-21: rerun with the fixed scanner and the extra masking (28 long tokens had been left unmasked). 56 items, 0 unmasked tokens.
"""
import glob, json, random, collections, pyarrow.parquet as pq
import re, sys
from secretscan import scan, mask, entropy

OUT = "/Users/jhtae/PaperReview/Gatekeeper_Experiments/out/"
by_kind = collections.defaultdict(list)
for l in open(OUT + "wildchat_hits.jsonl"):
    h = json.loads(l)
    if h["status"] == "secret":
        by_kind[h["kind"]].append(h)
rng = random.Random(0)
pick = [h for k in sorted(by_kind) for h in rng.sample(by_kind[k], min(6, len(by_kind[k])))]
want = {h["turn_identifier"] for h in pick}
text = {}
for f in sorted(glob.glob("/Users/jhtae/PaperReview/Gatekeeper_Experiments/Dataset/WildChat/*.parquet")):
    for conv in pq.read_table(f, columns=["conversation"]).column(0).to_pylist():
        for m in conv:
            if m["turn_identifier"] in want:
                text[(m["turn_identifier"], m["role"])] = m["content"]

def find_hit(h, t):
    return next((v for k, v, st in scan(t) if k == h["kind"] and mask(v) == h["masked"]), None)

if len(sys.argv) > 1:  # terminal view of the given items, unmasked
    for n in map(int, sys.argv[1:]):
        h = pick[n - 1]
        t = text.get((h["turn_identifier"], h["role"]), "")
        hit = find_hit(h, t)
        print(f"===== {n}. {h['kind']} ({h['role']} turn), conversation_hash {h['conversation_hash']}, msg {h['msg']}\n")
        print((t.replace(hit, f">>>{hit}<<<") if hit else t) + "\n")
    sys.exit()

def masked(s):
    for v in sorted({v for k, v, st in scan(s) if st == "secret"}, key=len, reverse=True):
        s = s.replace(v, mask(v))
    return re.sub(r"[A-Za-z0-9+/=_-]{20,}", lambda m: mask(m.group()) if entropy(m.group()) >= 3.5 else m.group(), s)

with open(OUT + "review_scan_hits.md", "w") as fo:
    fo.write("# WildChat secret-scan hits: hand review\n\nSample of hits the scanner called `secret`, up to 6 per kind (seed 0). "
             "Every secret-like value is masked. To see items unmasked, run `python scripts/sample_scan_hits.py N [N ...]` "
             "(prints to the terminal only). Tick one box per item.\n\n")
    for n, h in enumerate(pick, 1):
        t = text.get((h["turn_identifier"], h["role"]), "")
        hit = find_hit(h, t)
        i = t.find(hit) if hit else 0
        ctx = masked(t[max(0, i - 200): i + len(hit or "") + 200])
        head = masked(t[:300]).replace("\n", " ")
        fo.write(f"## {n}. {h['kind']} ({h['role']} turn)\n\nconversation_hash `{h['conversation_hash']}`, msg {h['msg']}, "
                 f"hit `{h['masked']}`, message length {len(t)}\n\nMessage start:\n\n```text\n{head.replace('```', chr(39) * 3)}\n```\n\nAround the hit:\n\n```text\n{ctx.replace('```', chr(39) * 3)}\n```\n\n"
                 "- [ ] looks like a real secret\n- [ ] placeholder or example value\n- [ ] not a secret (false hit)\n\n---\n\n")
print(len(pick), collections.Counter(h["kind"] for h in pick))
