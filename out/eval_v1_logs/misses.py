# Hand-read errors of the E9 r = 4 pick (build log section 5). Run from the project root: python out/eval_v1_logs/misses.py miss|fp N|fpkind|veto|local
import sys, json, collections
sys.path.insert(0, "scripts"); import gate as G
recs = [json.loads(l) for l in open(G.DATA)]
N = len(recs)
L = "openai/gpt-6-luna"
pp, pc = G.load("P_PII", L), G.load("P_CRED", L)
rx = [G.regex_gate(r["text"])["dangerous"] for r in recs]
pick = [int(rx[i] == 1 or pp.get(i) == 1 or pc.get(i) == 1) for i in range(N)]
main = [i for i, r in enumerate(recs) if r["split"] == "test" and r["group"] not in ("harmful", "harmful_safe")]
miss = [i for i in main if (recs[i]["pii"] or recs[i]["credential"]) and not pick[i]]
fps = [i for i in main if not (recs[i]["pii"] or recs[i]["credential"]) and pick[i]]
print(len(miss), "misses;", len(fps), "false positives")
print("FP by kind:", collections.Counter((recs[i]["group"], recs[i]["hard_negative"], recs[i]["mask_style"]) for i in fps).most_common())
mode = sys.argv[1]
for i in (miss if mode == "miss" else fps[:int(sys.argv[2])] if mode == "fp" else []):
    r = recs[i]; t = r["text"]
    print("\n=====", i, r["group"], r["type"], r["location"], r["hard_negative"], r["mask_style"], "| P_PII", pp.get(i), "P_CRED", pc.get(i), "| len", len(t))
    sp = json.loads(r["spans"]) if isinstance(r["spans"], str) else r["spans"]
    for s, e, k in (sp or []):
        print(f"  [{k}] ...{t[max(0, s - 200):e + 120]!r}...")
    if not sp:
        print("  ", repr(t[:700]))
if mode == "fpkind":
    import re
    seen = collections.Counter()
    for i in fps:
        r = recs[i]; k = (r["hard_negative"], r["mask_style"])
        if seen[k] >= 4: continue
        seen[k] += 1
        t = r["text"]
        # show the frame text around the masked/placeholder/doc value: the line(s) the generator inserted
        m = re.search(r"(\*{3,}|\[REDACTED|<[A-Z_]+>|YOUR_|example|xxxx|•|\.\.\.|password|key|token)", t, re.I)
        s = m.start() if m else 0
        print("\n=====", i, r["group"], r["type"], k, "| P_PII", pp.get(i), "P_CRED", pc.get(i), "regex", rx[i])
        print("  ", repr(t[max(0, s - 250):s + 250]))
if mode == "veto":
    veto = [G.regex_gate(r["text"])["neg_only"] for r in recs]
    two = [[int(pp.get(i) == 1) for i in range(N)], [int(pc.get(i) == 1) for i in range(N)]]
    vt = [int(rx[i] == 1 or any(v[i] and not veto[i] for v in two)) for i in range(N)]
    for name, idx in [("val", [i for i, r in enumerate(recs) if r["split"] == "validation" and r["group"] not in ("harmful", "harmful_safe")]), ("test", main)]:
        y = [int(recs[i]["pii"] or recs[i]["credential"]) for i in idx]
        for g, p in [("pick", pick), ("pick + veto", vt)]:
            x = [p[i] for i in idx]; m = G.prf(list(zip(y, x)))
            print(name, g, "recall %.3f fp %.3f cost4 %.3f" % (m["recall"], m["fp_rate"], G.cost(y, x, 4)),
                  "veto-killed positives:", sum(1 for i in idx if (recs[i]["pii"] or recs[i]["credential"]) and pick[i] and not vt[i]))
    lost = [i for i in main if (recs[i]["pii"] or recs[i]["credential"]) and pick[i] and not vt[i]]
    for i in lost[:6]:
        t = recs[i]["text"]; sp = json.loads(recs[i]["spans"]) if isinstance(recs[i]["spans"], str) else recs[i]["spans"]
        print("\nLOST", i, recs[i]["type"], [repr(t[s:e]) for s, e, k in sp])
        import re
        m = G.MASKED.search(t) if hasattr(G, "MASKED") else None
        print("  veto matched:", repr(t[max(0, m.start() - 60):m.end() + 40]) if m else None)
if mode == "local":
    loc = {n: G.load("LOCAL", n, field="raw") for n in ["presidio", "gliner", "detect-secrets"]}
    def s1(i):
        return int(rx[i] == 1 or any((loc[n].get(i) or {}).get(ax) == 1 for n in loc for ax in ["pii", "credential"]))
    for i in miss:
        print(i, recs[i]["type"], "stage1:", s1(i), {n: {ax: (loc[n].get(i) or {}).get(ax) for ax in ["pii", "credential"]} for n in loc})
    two = [i for i in main if (recs[i]["pii"] or recs[i]["credential"]) and not pick[i] and not s1(i)]
    print("two-stage misses:", [(i, recs[i]["type"]) for i in two])
