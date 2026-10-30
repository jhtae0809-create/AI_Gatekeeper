"""How do the PUPA rows that differ from WildChat differ? Counts only.

Run from scripts/ (it reuses the loading code of pupa_vs_wildchat.py through exec).
Output: out/pupa_diff_kinds.json. Each differing row is sorted by the kinds of its edits: whitespace, case,
a capitalized word swapped for another (what a name replacement would look like), or other.

Notebook link: same as pupa_vs_wildchat.py. This is the evidence that PUPA did not replace names.

Result (2026-10-02): of 574 differing rows, 572 are equal once whitespace is collapsed. 568 differ in whitespace only.
No row has a capitalized-word swap. So names were not replaced on release.
"""
import re, json, difflib, collections
exec(open("pupa_vs_wildchat.py").read().split("c = collections.Counter()")[0])  # reuse loading of pupa + src


def kind(a, b):
    if not a.strip() and not b.strip(): return "whitespace"
    if a.lower() == b.lower(): return "case"
    cap = r"[A-Z][a-z]+( [A-Z][a-z]+)*"
    if re.fullmatch(cap, a.strip()) and re.fullmatch(cap, b.strip()): return "capitalized_word_swap"
    return "other"


c = collections.Counter()
for split, h, q in zip(pupa.split, pupa.conversation_hash, pupa.user_query.fillna("")):
    msgs = src.get(h)
    if not msgs or q in msgs: continue
    best = max(msgs, key=lambda m: difflib.SequenceMatcher(None, q, m, autojunk=False).ratio() if abs(len(m) - len(q)) < 3000 else 0)
    sm = difflib.SequenceMatcher(None, best, q, autojunk=False)
    ks = {kind(best[i1:i2], q[j1:j2]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"}
    c[f"{split}|only_" + "+".join(sorted(ks))] += 1
    c[f"{split}|similarity_below_0.9"] += sm.ratio() < 0.9
    c[f"{split}|strip_equal"] += " ".join(best.split()) == " ".join(q.split())
out = dict(sorted(c.items()))
print(json.dumps(out, indent=1))
json.dump(out, open("/Users/jhtae/PaperReview/Gatekeeper_Experiments/out/pupa_diff_kinds.json", "w"), indent=1)
