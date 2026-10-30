import nbformat as nbf

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip("\n")))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip("\n")))

md("""
# Gatekeeper experiments on eval set v1

Data: `data/eval_v1.jsonl` (3,500 records, built in `build_eval_v1.ipynb`). Design: `Dataset/docs/eval_v1_design.md`. Build and run decisions: `Dataset/docs/eval_v1_build_log.md`.

- Lineup: `gpt-6-luna`, `claude-haiku-5.5` (both with reasoning off), `gemini-2.5-flash-lite`, `llama-3.1-8b-instruct`, `deepseek-chat` via OpenRouter, temperature 0, plus Jev (TypeSafe).
- Every choice (k, thresholds, models, combiners) is made on the validation split (1,064 records). The test split (2,436) is scored with the chosen settings.
- Cost of an error: a false positive costs 1, a missed risky record costs r. r = 4 (F2) and r = 25 (F5); references in E2.
- Local models (Presidio, GLiNER, detect-secrets, Granite Guardian) run in `Gatekeeper_v1_local.ipynb` and are read from the same run folder.

Code shared with the local notebook is in `scripts/gate.py` (prompts, run loop, scoring, regex gate, McNemar, bootstrap).
""")
md("""
## Summary (test split, all three risks)

| | Paper gate | Final v1 | Final v2 |
|---|---|---|---|
| Recall | 0.352 | 0.955 | 0.982 |
| False-positive rate | 0.078 | 0.127 | 0.300 |
| Cost, r = 4 | 1.156 | 0.150 | 0.203 |
| Cost, r = 25 | 6.992 | 0.555 | 0.367 |
| Risky records sent to an outside API | 100% | 100% | 11.2% |

- v1: regex + `gpt-6-luna` (PII prompt, credential prompt) + Jev `h_any` (harmful).
- v2: regex and local detectors on the device first (Presidio, GLiNER, detect-secrets, Granite Guardian), then v1's questions for the rest.
- On PII and credential records alone, recall is 0.983 (v1) and 0.999 (v2).

Details are in the last section, Final gates.
""")
md("## 0. Setup")
code("""
import collections, json, math, os, sys
from itertools import combinations
import numpy as np
import pandas as pd
from IPython.display import display
sys.path.insert(0, "/Users/jhtae/PaperReview/Gatekeeper_Experiments/scripts")
import gate as G

recs = [json.loads(l) for l in open(G.DATA)]
N = len(recs)
VAL = [i for i, r in enumerate(recs) if r["split"] == "validation"]
TEST = [i for i, r in enumerate(recs) if r["split"] == "test"]
AXES = G.AXES
Y = {k: [r[k] for r in recs] for k in AXES + ["dangerous"]}
GROUP = [r["group"] for r in recs]
NEG_GROUPS = ["harmful_safe", "credential_hn", "pii_hn", "clean"]
R = [4, 25]
SHORT = {m: m.split("/")[-1] for m in G.MODELS}
print(N, "records:", len(VAL), "validation,", len(TEST), "test")
pd.crosstab(pd.Series(GROUP, name="group"), pd.Series([r["split"] for r in recs], name="split"))
""")
md("""
Prompts. B v1 and the three axis prompts share the shell and the axis definitions word for word (design doc section 6).
""")
code("""
for k in ["B1", "P_PII", "P_CRED", "P_HARM"]:
    print(f"--- {k}\\n{G.EXPS[k][0]}\\n")
print("--- Jev questions"); print(pd.Series(G.JEV_Q).to_string())
""")
md("""
## 1. Runs

### Smoke test (5 records per model and prompt)

One record from five groups. The raw answers, parsing and saved files are checked before the full run. Smoke files go to `out/eval_v1_smoke/`.
""")
code("""
SMOKE_RUNS = G.ROOT + "out/eval_v1_smoke/"
SMOKE = [next(i for i in VAL if GROUP[i] == g) for g in ["credential", "pii_hn", "harmful", "pii", "clean"]]
for exp in G.EXPS:
    G.run(exp, G.MODELS if exp in ("A", "B1") else G.LLMS, data=G.DATA, runs=SMOKE_RUNS, idx=SMOKE)
G.run("JEVQ", ["jev"], runs=SMOKE_RUNS, idx=SMOKE)
smoke = {f"{e} | {SHORT[m]}": {GROUP[i]: (str(G.load(e, m, SMOKE_RUNS, "raw").get(i))[:12], G.load(e, m, SMOKE_RUNS).get(i)) for i in SMOKE}
         for e in list(G.EXPS) + ["JEVQ"] for m in G.MODELS if G.load(e, m, SMOKE_RUNS)}
pd.DataFrame(smoke).T
""")
md("""
### Full runs

Resumable: a rerun only asks about records not yet saved
""")
code("""
for exp in G.EXPS:
    G.run(exp, G.MODELS if exp in ("A", "B1") else G.LLMS)
G.run("JEVQ", ["jev"])
""")
code("""
done = {f"{e} | {SHORT[m]}": dict(answered=len(G.load(e, m)), invalid=sum(v is None for v in G.load(e, m).values()),
                                  blocked=sum(v == "BLOCKED" for v in G.load(e, m, field="raw").values()),
                                  usd=round(G.run_cost(e, m)[0], 3))
        for e in list(G.EXPS) + ["JEVQ"] for m in G.MODELS if os.path.exists(G.run_path(e, m))}
pd.DataFrame(done).T
""")
md("""
## 2. Helpers

- A gate is a 0/1 list over all records (`None` = invalid answer, counted as "pass", i.e. a miss on a risky record).
- `report` gives recall on `dangerous` and per axis, the false-positive rate per label-0 group and overall, and the cost per record at r = 4 and r = 25.
""")
code("""
def P(exp, m):
    p = G.load(exp, m)
    return [p.get(i) for i in range(N)]


def prob(exp, key=None):
    raw = G.load(exp, "jev", field="raw")
    return [None if i not in raw else float(raw[i][key] if key else raw[i]) for i in range(N)]


def vote(vs, k):
    return [int(sum(v[i] == 1 for v in vs) >= k) for i in range(N)]


def OR(*vs):
    return [int(any(v[i] == 1 for v in vs)) for i in range(N)]


def thr(p, t):
    return [int(x is not None and x >= t) for x in p]


def metrics(pred, idx, label="dangerous"):
    y = [Y[label][i] for i in idx]
    x = [pred[i] for i in idx]
    out = G.prf(list(zip(y, x)))
    row = {"recall": out["recall"], "fp_rate": out["fp_rate"], "precision": out["precision"]}
    for ax in AXES:
        pos = [i for i in idx if Y[ax][i]]
        row[f"recall_{ax}"] = sum(pred[i] == 1 for i in pos) / len(pos)
    for g in NEG_GROUPS:
        neg = [i for i in idx if GROUP[i] == g]
        row[f"fp_{g}"] = sum(pred[i] == 1 for i in neg) / len(neg)
    for r in R:
        row[f"cost_r{r}"] = G.cost(y, x, r)
    return row


def report(gates, idx=TEST):
    return pd.DataFrame({k: metrics(v, idx) for k, v in gates.items()}).T.astype(float).round(3)


def best(cands, r, idx=VAL, label="dangerous"):
    \"\"\"Name of the candidate with the lowest cost at r on idx.\"\"\"
    return min(cands, key=lambda k: G.cost([Y[label][i] for i in idx], [cands[k][i] for i in idx], r))
""")
md("""
## E1. Baseline: prompt A, prompt B v1, regex alone

Prompt A sees the user prompt only (as in the paper). B v1 sees the prompt and the answer. Regex alone: `scripts/secretscan.py` plus a Luhn check for cards (design doc section 8, step 1). Scored on test.
""")
code("""
RX = [G.regex_gate(r["text"]) for r in recs]
regex = [x["dangerous"] for x in RX]
A = {m: P("A", m) for m in G.LLMS}
B1 = {m: P("B1", m) for m in G.LLMS}
A["jev"], B1["jev"] = thr(prob("A"), 0.5), thr(prob("B1"), 0.5)
e1 = {f"A | {SHORT[m]}": v for m, v in A.items()}
e1["A | consensus 3-of-5 (paper gate)"] = vote([A[m] for m in G.LLMS], 3)
e1.update({f"B1 | {SHORT[m]}": v for m, v in B1.items()})
e1["B1 | consensus 3-of-5"] = vote([B1[m] for m in G.LLMS], 3)
e1["regex alone"] = regex
# USE: which saved runs each gate reads, for its API cost. AXP: per-axis predictions of per-axis gates (for E6).
USE = {f"{e} | {SHORT[m]}": {(e, m)} for e in ["A", "B1"] for m in G.MODELS}
USE |= {"A | consensus 3-of-5 (paper gate)": {("A", m) for m in G.LLMS}, "B1 | consensus 3-of-5": {("B1", m) for m in G.LLMS}, "regex alone": set()}
AXP = {}
E1 = report(e1)
E1
""")
md("Regex alone, recall per type and false positives per hard-negative kind (test).")
code("""
def share(pred, cond, idx=TEST):
    sel = [i for i in idx if cond(recs[i])]
    return round(sum(pred[i] == 1 for i in sel) / len(sel), 3) if sel else None


rows = {}
for t in sorted({r["type"] for r in recs if r["credential"] or r["pii"]}):
    rows[f"positive | {t}"] = share(regex, lambda r: (r["credential"] or r["pii"]) and r["type"] == t)
for g in ["credential_hn", "pii_hn"]:
    for k in ["paired", "talk"]:
        rows[f"{g} | {k}"] = share(regex, lambda r: r["group"] == g and r["hard_negative"] == k)
pd.Series(rows, name="share flagged by regex").to_frame()
""")
md("Recall by turn (credential and PII positives, test). Prompt A cannot see the assistant turn.")
code("""
rows = {}
for k, v in e1.items():
    rows[k] = {t: share(v, lambda r: (r["credential"] or r["pii"]) and r["location"].startswith(t)) for t in ["user", "assistant"]}
pd.DataFrame(rows).T
""")
md("""
## E2. Votes and error costs

How many of the 5 LLMs must say True before the gate blocks (k = 1 to 5)? Expected cost per record = (r × FN + FP) / n.
- **r = 4**: the weighting inside F2, the usual recall-weighted score. F2 = 5TP / (5TP + 4FN + FP).
- **r = 25**: the weighting inside F5, used for PII removal in educational data (arXiv:2501.09765), where a missed PII is far worse than over-removal.
- A permanent public log cannot take a leak back, so r > 1 is expected. There is no standard r for this task.
- For a probability output (Jev), the cost-optimal threshold is p* = C_FP / (C_FP + C_FN) = 1 / (1 + r) (Elkan, 2001). This assumes calibrated probabilities.

k and thresholds are picked on validation, then scored on test.

References
- C. Elkan, "The Foundations of Cost-Sensitive Learning," IJCAI 2001, pp. 973–978. https://mlanthology.org/ijcai/2001/elkan2001ijcai-foundations
- V. S. Sheng and C. X. Ling, "Thresholding for Making Classifiers Cost-sensitive," AAAI 2006. https://www.semanticscholar.org/paper/Thresholding-for-Making-Classifiers-Cost-sensitive-Sheng-Ling/1691c7ea938ab101b3d26fe7a914ba47d141fa79
- "Enhancing the De-identification of Personally Identifiable Information in Educational Data," arXiv:2501.09765, 2025. https://arxiv.org/abs/2501.09765
- scikit-learn, "Post-tuning the decision threshold for cost-sensitive learning." https://scikit-learn.org/stable/auto_examples/model_selection/plot_cost_sensitive_learning.html
""")
code("""
def votes_table(vs, idx):
    y = [Y["dangerous"][i] for i in idx]
    rows = {}
    for k in range(1, len(vs) + 1):
        v = vote(vs, k)
        x = [v[i] for i in idx]
        m = G.prf(list(zip(y, x)))
        rows[f"k={k}"] = {"recall": m["recall"], "fp_rate": m["fp_rate"], **{f"cost r={r}": G.cost(y, x, r) for r in R}}
    return pd.DataFrame(rows).T.round(3)


CHOSEN = {}
for exp, D in [("A", A), ("B1", B1)]:
    vs = [D[m] for m in G.LLMS]
    tv = votes_table(vs, VAL)
    print(exp, "validation"); display(tv)
    for r in R:
        k = int(tv[f"cost r={r}"].idxmin()[2:])
        CHOSEN[f"{exp} | vote k={k} (picked for r={r})"] = vote(vs, k)
        USE[f"{exp} | vote k={k} (picked for r={r})"] = {(exp, m) for m in G.LLMS}
for exp in ["A", "B1"]:
    for r in R:
        CHOSEN[f"{exp} | Jev p*={1 / (1 + r):.3f} (r={r})"] = thr(prob(exp), 1 / (1 + r))
        USE[f"{exp} | Jev p*={1 / (1 + r):.3f} (r={r})"] = {(exp, "jev")}
E2 = report(CHOSEN)
E2
""")
md("""
## E3. One prompt per axis

Each LLM answers three prompts, one per axis (same shell and definitions as B v1). Per-axis recall is the share of that axis's positives the axis prompt flags; false positives are shown for the axis's own hard negatives, clean records and the other groups. The gate is the OR of the three axes.
""")
code("""
AX = {ax: {m: P(G.AXIS_EXP[ax], m) for m in G.LLMS} for ax in AXES}
HN = {"pii": "pii_hn", "credential": "credential_hn", "harmful": "harmful_safe"}


def axis_metrics(pred, ax, idx):
    pos = [i for i in idx if Y[ax][i]]
    row = {"recall": sum(pred[i] == 1 for i in pos) / len(pos)}
    for g in ["harmful", "harmful_safe", "credential", "credential_hn", "pii", "pii_hn", "clean"]:
        if Y[ax][next(i for i in idx if GROUP[i] == g)]:
            continue
        sel = [i for i in idx if GROUP[i] == g]
        row[f"fp_{g}"] = sum(pred[i] == 1 for i in sel) / len(sel)
    neg = [i for i in idx if not Y[ax][i]]
    row["fp_all"] = sum(pred[i] == 1 for i in neg) / len(neg)
    for r in R:
        row[f"cost_r{r}"] = G.cost([Y[ax][i] for i in idx], [pred[i] for i in idx], r)
    return row


for ax in AXES:
    print(ax, "(test)")
    display(pd.DataFrame({SHORT[m]: axis_metrics(AX[ax][m], ax, TEST) for m in G.LLMS}).T.astype(float).round(3))
E3_OR = {}
for m in G.LLMS:
    k = f"3 axis prompts, OR | {SHORT[m]}"
    AXP[k] = [AX[ax][m] for ax in AXES]
    E3_OR[k] = OR(*AXP[k])
    USE[k] = {(G.AXIS_EXP[ax], m) for ax in AXES}
E3 = report({**E3_OR, "B1 | consensus 3-of-5": e1["B1 | consensus 3-of-5"]})
E3
""")
md("""
## E4. Axis specialists

For each axis, the model with the lowest axis cost on validation (r = 4 and r = 25 separately). Then a vote: the 3 best models per axis on validation with k picked on validation. The gate is the OR over axes. Local detectors join when their run files exist (Presidio and GLiNER for pii, detect-secrets for credential, Granite Guardian for harmful).
""")
code("""
LOCAL = {}
for name in ["presidio", "gliner", "detect-secrets", "granite-guardian"]:
    raw = G.load("LOCAL", name, field="raw")
    if raw:
        LOCAL[name] = {ax: [None if i not in raw else raw[i].get(ax) for i in range(N)] for ax in AXES}
print("local detectors found:", list(LOCAL))
LOCAL_AX = {"pii": ["presidio", "gliner"], "credential": ["detect-secrets", "gliner"], "harmful": ["granite-guardian"]}


def axis_cands(ax, r):
    # candidate detectors for one axis: name -> (predictions, runs used)
    c = {SHORT[m]: (AX[ax][m], {(G.AXIS_EXP[ax], m)}) for m in G.LLMS}
    c["jev:" + ax[0] + "_any"] = (thr(prob("JEVQ", ax[0] + "_any"), 1 / (1 + r)), {("JEVQ", "jev")})
    for name in LOCAL_AX[ax]:
        if name in LOCAL and any(v is not None for v in LOCAL[name][ax]):
            c[name] = ([int(v == 1) for v in LOCAL[name][ax]], set())
    return c


def ax_cost(v, ax, idx, r):
    return G.cost([Y[ax][i] for i in idx], [v[i] for i in idx], r)


E4, SPEC = {}, {}
for r in R:
    single, voted, u1, u3 = [], [], set(), set()
    for ax in AXES:
        c = axis_cands(ax, r)
        rank = sorted(c, key=lambda k: ax_cost(c[k][0], ax, VAL, r))
        top = [c[k][0] for k in rank[:3]]
        kbest = min(range(1, 4), key=lambda k: ax_cost(vote(top, k), ax, VAL, r))
        single.append(c[rank[0]][0]); u1 |= c[rank[0]][1]
        voted.append(vote(top, kbest)); u3 |= set().union(*[c[k][1] for k in rank[:3]])
        SPEC[(ax, r)] = (rank[:3], kbest)
    for k, axp, u in [(f"specialist per axis (r={r})", single, u1), (f"top-3 vote per axis (r={r})", voted, u3)]:
        AXP[k], USE[k], E4[k] = axp, u, OR(*axp)
display(pd.DataFrame({f"{ax}, r={r}": {"top 3 on validation": ", ".join(v[0]), "k": v[1]} for (ax, r), v in SPEC.items()}).T)
report(E4)
""")
md("""
## E5. Jev, several questions per axis

One `system_one` call per record with the 15 questions of design doc section 7. Per axis:
- **max**: the highest probability among the four positive questions;
- **logistic regression**: fit on validation on the logits of all five questions (the negative `_fake` question included). Validation scores are out-of-fold (5 folds grouped by pair, frame and conversation), so E8 does not pick it for fitting its own records. Test scores use the fit on all of validation.

Axis threshold p* = 1 / (1 + r). The gate is the OR over axes.
""")
code("""
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold


def components(keys=("pair_id", "frame_id", "conv_id")):
    # union-find over shared pair, frame or conversation, as in the split
    parent = list(range(N))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    first = {}
    for i, r in enumerate(recs):
        for k in keys:
            if r.get(k) is not None:
                parent[find(i)] = find(first.setdefault((k, r[k]), i))
    return [find(i) for i in range(N)]


COMP = components()
JQ = {k: prob("JEVQ", k) for k in G.JEV_Q}
logit = lambda p: math.log(min(max(p, 1e-4), 1 - 1e-4) / (1 - min(max(p, 1e-4), 1 - 1e-4)))
LR, E5 = {}, {}
for ax in AXES:
    keys = G.JEV_AXIS_Q[ax]
    X = np.array([[logit(JQ[k][i] if JQ[k][i] is not None else 0.5) for k in keys] for i in range(N)])
    yv = np.array([Y[ax][i] for i in VAL])
    LR[ax] = LogisticRegression(max_iter=1000).fit(X[VAL], yv)
    p = LR[ax].predict_proba(X)[:, 1]
    oof = np.zeros(len(VAL))  # validation scores come from folds the model did not see, so the selection in E8 is fair
    for tr, te in GroupKFold(5).split(X[VAL], yv, groups=[COMP[i] for i in VAL]):
        oof[te] = LogisticRegression(max_iter=1000).fit(X[VAL][tr], yv[tr]).predict_proba(X[VAL][te])[:, 1]
    p[VAL] = oof
    JQ[ax + "_lr"] = list(p)
    JQ[ax + "_max"] = [max((JQ[k][i] or 0) for k in keys if not k.endswith("_fake")) for i in range(N)]
for r in R:
    t = 1 / (1 + r)
    for label, key in [("any-question", "{a}_any"), ("max", "{ax}_max"), ("logistic", "{ax}_lr")]:
        k = f"Jev {label} per axis, OR (r={r})"
        AXP[k] = [thr(JQ[key.format(a=ax[0], ax=ax)], t) for ax in AXES]
        USE[k], E5[k] = {("JEVQ", "jev")}, OR(*AXP[k])
display(pd.DataFrame({ax: dict(zip(G.JEV_AXIS_Q[ax], LR[ax].coef_[0].round(2))) for ax in AXES}).T)
report(E5)
""")
md("""
## E6. Regex with the LLM gates

- **regex OR gate**: block if regex hits or the gate says unsafe. Same decisions as regex first, then the LLM only for the rest. The difference is cost in use.
- **cost saving** = share of records blocked by regex × LLM cost per record.
- **regex veto** (per-axis gates only): on the pii and credential axes, if regex finds only placeholders or masked values and no live match, the axis is set to 0 even if the LLM said 1.
""")
code("""
veto = [x["neg_only"] for x in RX]


def with_veto(axis_preds):
    out = []
    for ax, v in zip(AXES, axis_preds):
        out.append([0 if ax != "harmful" and veto[i] and v[i] == 1 else v[i] for i in range(N)])
    return OR(*out)


E6 = {}
for name in ["A | consensus 3-of-5 (paper gate)", "B1 | consensus 3-of-5", "B1 | gpt-6-luna", "B1 | jev"]:
    E6[f"regex OR {name}"] = OR(regex, e1[name])
    USE[f"regex OR {name}"] = USE[name]
for name, axp in list(AXP.items()):
    for k, v in [(f"{name} + veto", with_veto(axp)), (f"regex OR {name}", OR(regex, OR(*axp))),
                 (f"regex OR {name} + veto", OR(regex, with_veto(axp)))]:
        E6[k], USE[k] = v, USE[name]
E6r = report({k: v for k, v in E6.items() if "3 axis prompts" in k or "regex OR A" in k or "regex OR B1" in k
               or k.startswith(("specialist", "regex OR specialist", "Jev logistic", "regex OR Jev logistic"))})
blocked = sum(regex[i] for i in range(N)) / N
print(f"regex blocks {blocked:.1%} of eval v1 records; on the clean group {sum(regex[i] for i in range(N) if GROUP[i] == 'clean') / 500:.1%}")
E6r
""")
md("""
## E7. Shared misses per axis

On each axis's positives (test), shared-miss ratio = P(both miss) / (P(a misses) × P(b misses)). 1 means independent misses, above 1 means the models miss the same records. Cells with fewer than 5 shared misses are blank. The ratio cannot exceed 1 / max miss rate, so it is hard to read when miss rates are high.

Same question for all axes (B1) against one question per axis (E3).
""")
code("""
def shared_miss(ax, preds, idx=TEST):
    pos = [i for i in idx if Y[ax][i]]
    miss = {m: {i for i in pos if p[i] != 1} for m, p in preds.items()}
    names = list(preds)
    M = pd.DataFrame(index=names, columns=names, dtype=float)
    for a, b in combinations(names, 2):
        both = len(miss[a] & miss[b])
        exp = len(miss[a]) * len(miss[b]) / len(pos)
        M.loc[a, b] = M.loc[b, a] = both / exp if both >= 5 and exp else float("nan")
    rates = {m: len(s) / len(pos) for m, s in miss.items()}
    obs = sum(sum(preds[m][i] == 1 for m in preds) < 3 for i in pos) / len(pos)
    dist = [1.0]
    for q in rates.values():
        dist = [a * (1 - q) + b * q for a, b in zip(dist + [0], [0] + dist)]
    return M.round(2), rates, {"3-of-5 miss observed": round(obs, 3), "if independent": round(sum(dist[3:]), 3)}


E7 = {}
for ax in AXES:
    for name, preds in [("B1", {SHORT[m]: B1[m] for m in G.LLMS}), ("axis prompt", {SHORT[m]: AX[ax][m] for m in G.LLMS})]:
        M, rates, cm = shared_miss(ax, preds)
        E7[(ax, name)] = cm | {"mean pairwise ratio": round(np.nanmean(M.values[np.triu_indices(5, 1)].astype(float)), 2)
                               if not np.isnan(M.values[np.triu_indices(5, 1)].astype(float)).all() else None}
        print(ax, "|", name, "| miss rate:", {m: round(q, 3) for m, q in rates.items()})
        display(M)
pd.DataFrame(E7).T
""")
md("""
## E8. Final comparison on test

Candidates are every gate above. For each r, the gate with the lowest validation cost is picked, then scored on test with 95% bootstrap intervals (2,000 resamples) and McNemar's exact test against the paper gate (prompt A, 3-of-5 vote).

Three picks per r: the best gate overall, the best without Jev (its price is not reported by the SDK), and the best with no API call (regex and local detectors). Reference rows: the paper gate and the B1 3-of-5 vote.

API cost per 1,000 records is the summed OpenRouter cost of the runs a gate reads, from the saved `usage.cost`.
""")
code("""
ALL = {**e1, **CHOSEN, **E3_OR, **E4, **E5, **E6}
for name in LOCAL:  # local detectors alone, OR over the axes they cover
    ALL[f"local | {name}"], USE[f"local | {name}"] = OR(*[[int(v == 1) for v in LOCAL[name][ax]] for ax in AXES]), set()
ALL["local | all, OR"], USE["local | all, OR"] = OR(*[ALL[f"local | {n}"] for n in LOCAL]), set()
ALL["regex OR local | all, OR"], USE["regex OR local | all, OR"] = OR(regex, ALL["local | all, OR"]), set()
REGEX_SHARE = sum(regex) / N


def usd_per_1000(name):
    # OpenRouter cost of the runs the gate reads, per 1,000 records; '+ Jev' when it also needs Jev (price not reported)
    u = USE[name]
    usd = 1000 * sum(G.run_cost(e, m)[0] for e, m in u if m != "jev") / N
    return f"{usd:.3f}" + (" + Jev" if any(m == "jev" for _, m in u) else "")


paper = e1["A | consensus 3-of-5 (paper gate)"]
yt = [Y["dangerous"][i] for i in TEST]
no_jev = {k: v for k, v in ALL.items() if not any(m == "jev" for _, m in USE[k])}
no_api = {k: v for k, v in ALL.items() if not USE[k]}
rows, PICK = {}, {}
for r in R:
    PICK[r] = {"best on validation": best(ALL, r), "best without Jev": best(no_jev, r), "best with no API call": best(no_api, r)}
    for role, name in [("paper gate", "A | consensus 3-of-5 (paper gate)"), ("B1 vote", "B1 | consensus 3-of-5"), *PICK[r].items()]:
        v = ALL[name]
        x = [v[i] for i in TEST]
        m = G.prf(list(zip(yt, x)))
        lo, hi = G.bootstrap(yt, x, lambda y, p: G.cost(y, p, r))
        rlo, rhi = G.bootstrap(yt, x, lambda y, p: G.prf(list(zip(y, p)))["recall"])
        b, c, pv = G.mcnemar(yt, x, [paper[i] for i in TEST])
        rows[(f"r={r}", role, name)] = {"recall": round(m["recall"], 3), "recall 95% CI": f"{rlo:.3f}-{rhi:.3f}", "fp_rate": round(m["fp_rate"], 3),
                                        **{f"recall_{ax}": round(sum(v[i] == 1 for i in TEST if Y[ax][i]) / sum(Y[ax][i] for i in TEST), 3) for ax in AXES},
                                        "cost": round(G.cost(yt, x, r), 3), "cost 95% CI": f"{lo:.3f}-{hi:.3f}",
                                        "McNemar vs paper (b, c, p)": f"{b}, {c}, {pv:.2g}", "USD per 1,000 (API)": usd_per_1000(name)}
E8 = pd.DataFrame(rows).T
print(f"regex blocks {REGEX_SHARE:.1%} of eval v1 records; for 'regex OR' gates used as regex first, the API cost falls by that share on this mix "
      "and by about 0% on clean WildChat (the clean pool was picked by the same scanner).")
E8
""")
md("Recall by type and false-positive rate by hard-negative style for the picked gates (test).")
code("""
picked = {"paper gate": "A | consensus 3-of-5 (paper gate)", "B1 vote": "B1 | consensus 3-of-5",
          **{f"{k} (r={r})": v for r in R for k, v in PICK[r].items()}}
rows = {}
for t in sorted({r["type"] for r in recs if r["credential"] or r["pii"]}):
    rows[f"recall | {t}"] = {k: share(ALL[v], lambda r: (r["credential"] or r["pii"]) and r["type"] == t) for k, v in picked.items()}
for g in ["credential_hn", "pii_hn"]:
    for st in sorted({r["mask_style"] for r in recs if r["group"] == g and r["mask_style"]}) + ["talk"]:
        cond = (lambda r, g=g, st=st: r["group"] == g and (r["hard_negative"] == "talk" if st == "talk" else r["mask_style"] == st))
        rows[f"fp | {g} | {st}"] = {k: share(ALL[v], cond) for k, v in picked.items()}
pd.DataFrame(rows).T
""")
md("No-API gates on test: regex and the local detectors, alone and combined. With these gates no record text leaves the machine.")
code("""
report({"regex alone": regex, **{k: v for k, v in ALL.items() if k.startswith(("local |", "regex OR local"))}})
""")
md("Where the r = 4 picks go wrong on test: misses and false positives by group.")
code("""
err = {}
for k in ["best on validation", "best without Jev", "best with no API call"]:
    v = ALL[PICK[4][k]]
    for g in sorted({recs[i]["group"] for i in TEST}):
        ids = [i for i in TEST if recs[i]["group"] == g]
        err[(k, "misses")] = {**err.get((k, "misses"), {}), g: sum(Y["dangerous"][i] == 1 and v[i] == 0 for i in ids)}
        err[(k, "false positives")] = {**err.get((k, "false positives"), {}), g: sum(Y["dangerous"][i] == 0 and v[i] == 1 for i in ids)}
pd.DataFrame(err)
""")
md("""
## E9. Main view: PII and credential, harmful as a secondary axis

Decision of 2026-10-30 (build log section 6): the paper leads with PII and credential exposure at r = 4, and reports harmful (Aegis) apart.
- Label `exposure` = pii or credential. Records: the five non-Aegis groups (validation 760, test 1,740).
- Candidates: every gate above, plus each per-axis gate cut to its pii and credential axes (alone, with the regex veto, and with regex OR).
- Picks on validation per r, scored on test, as in E8.
""")
code("""
Y["exposure"] = [int(Y["pii"][i] or Y["credential"][i]) for i in range(N)]
MAIN = {i for i in range(N) if GROUP[i] not in ("harmful", "harmful_safe")}
VAL_M, TEST_M = [i for i in VAL if i in MAIN], [i for i in TEST if i in MAIN]
CAND = dict(ALL)
for name, axp in AXP.items():
    two = axp[:2]  # AXES order is pii, credential, harmful
    for k, v in [(f"{name} | pii+cred", OR(*two)), (f"{name} | pii+cred + veto", with_veto(two)),
                 (f"regex OR {name} | pii+cred", OR(regex, *two)), (f"regex OR {name} | pii+cred + veto", OR(regex, with_veto(two)))]:
        CAND[k], USE[k] = v, {u for u in USE[name] if u[0] != "P_HARM"}  # the harmful prompt is not read
LOCAL_PC = OR(*[[int(v == 1) for v in LOCAL[n][ax]] for ax in ["pii", "credential"] for n in LOCAL_AX[ax] if n in LOCAL])
CAND["regex OR local | pii+cred"], USE["regex OR local | pii+cred"] = OR(regex, LOCAL_PC), set()
PAPER = "A | consensus 3-of-5 (paper gate)"


def final(cands, label, val, test, groups):
    # E8-style table: picks on val per r (overall, without Jev, no API), scored on test with CIs and McNemar vs the paper gate
    yv, yt = [Y[label][i] for i in val], [Y[label][i] for i in test]
    pick = lambda ks, r: min(ks, key=lambda k: G.cost(yv, [cands[k][i] for i in val], r))
    no_j = [k for k in cands if not any(m == "jev" for _, m in USE[k])]
    no_a = [k for k in cands if not USE[k]]
    rows, picks = {}, {}
    for r in R:
        picks[r] = {"best on validation": pick(cands, r), "best without Jev": pick(no_j, r), "best with no API call": pick(no_a, r)}
        for role, name in [("paper gate", PAPER), ("B1 vote", "B1 | consensus 3-of-5"), *picks[r].items()]:
            x = [cands[name][i] for i in test]
            m = G.prf(list(zip(yt, x)))
            lo, hi = G.bootstrap(yt, x, lambda y, p: G.cost(y, p, r))
            rlo, rhi = G.bootstrap(yt, x, lambda y, p: G.prf(list(zip(y, p)))["recall"])
            b, c, pv = G.mcnemar(yt, x, [cands[PAPER][i] for i in test])
            rows[(f"r={r}", role, name)] = {"recall": round(m["recall"], 3), "recall 95% CI": f"{rlo:.3f}-{rhi:.3f}", "fp_rate": round(m["fp_rate"], 3),
                                            **{f"recall_{ax}": round(share(cands[name], lambda q, ax=ax: q[ax] == 1 and q["group"] in groups), 3) for ax in ["pii", "credential"]},
                                            **{f"fp_{g}": round(share(cands[name], lambda q, g=g: q["group"] == g), 3) for g in ["credential_hn", "pii_hn", "clean"]},
                                            "cost": round(G.cost(yt, x, r), 3), "cost 95% CI": f"{lo:.3f}-{hi:.3f}",
                                            "McNemar vs paper (b, c, p)": f"{b}, {c}, {pv:.2g}", "USD per 1,000 (API)": usd_per_1000(name)}
    return pd.DataFrame(rows).T, picks


MAIN_GROUPS = {"credential", "credential_hn", "pii", "pii_hn", "clean"}
E9, PICK9 = final(CAND, "exposure", VAL_M, TEST_M, MAIN_GROUPS)
print(len(VAL_M), "validation,", len(TEST_M), "test records")
E9
""")
md("""
Harmful axis on its own (secondary): Aegis records only (groups harmful and harmful_safe), label `harmful`. Each single detector at its r threshold, plus the paper gate and the B1 vote as references. Sorted by validation cost.
""")
code("""
HSET = {i for i in range(N) if GROUP[i] in ("harmful", "harmful_safe")}
HV, HT = [i for i in VAL if i in HSET], [i for i in TEST if i in HSET]
rows = {}
for r in R:
    c = {k: v for k, (v, _) in axis_cands("harmful", r).items()}
    c |= {"paper gate (A, 3-of-5)": ALL[PAPER], "B1 | consensus 3-of-5": ALL["B1 | consensus 3-of-5"]}
    for k, v in c.items():
        rows[(f"r={r}", k)] = {"validation cost": ax_cost(v, "harmful", HV, r),
                               "recall": share(v, lambda q: q["group"] == "harmful"), "fp_harmful_safe": share(v, lambda q: q["group"] == "harmful_safe"),
                               "cost": ax_cost(v, "harmful", HT, r)}
EH = pd.DataFrame(rows).T.astype(float).round(3)
pd.concat([EH.loc[f"r={r}"].sort_values("validation cost").assign(r=r) for r in R])
""")
md("""
## E10. Two-stage gate: local detectors first, API second

Stage 1 runs on the device: regex and the local PII and credential detectors (`regex OR local | pii+cred`). Two ways to add an API stage:
- **local blocks, API checks the rest**: a record stage 1 flags is blocked and never sent out. Only records stage 1 passes go to the API. The decision is the OR of both stages.
- **API confirms local flags**: only records stage 1 flags go to the API; a record is blocked when both say risky. This can cut false positives, but the records sent out are the ones most likely to hold personal data.

"sent" columns: share of records sent to an outside API, and share of risky records sent (the exposure the gatekeeper is meant to prevent). A one-stage API gate sends 100% of both. Main view (E9 records and label), test.
""")
code("""
S1 = CAND["regex OR local | pii+cred"]
yt = [Y["exposure"][i] for i in TEST_M]
risky = [i for i in TEST_M if Y["exposure"][i]]


def two_stage_row(pred, sent):
    x = [pred[i] for i in TEST_M]
    m = G.prf(list(zip(yt, x)))
    return {"recall": m["recall"], "fp_rate": m["fp_rate"], "cost_r4": G.cost(yt, x, 4), "cost_r25": G.cost(yt, x, 25),
            "sent, all": sum(sent[i] for i in TEST_M) / len(TEST_M), "sent, risky": sum(sent[i] for i in risky) / len(risky)}


rows = {("stage 1 only", "no API"): two_stage_row(S1, [0] * N)}
for role in ["best on validation", "best without Jev"]:
    name = PICK9[4][role]
    a = CAND[name]
    rows[(f"{role}: {name}", "one stage (API only)")] = two_stage_row(a, [1] * N)
    rows[(f"{role}: {name}", "local blocks, API checks the rest")] = two_stage_row(OR(S1, a), [1 - S1[i] for i in range(N)])
    rows[(f"{role}: {name}", "API confirms local flags")] = two_stage_row([int(S1[i] == 1 and a[i] == 1) for i in range(N)], S1)
E10 = pd.DataFrame(rows).T.astype(float).round(3)
E10
""")
md("Summary ladder for the professor (main view, test): each row adds one change.")
code("""
ladder = ["A | consensus 3-of-5 (paper gate)", "B1 | consensus 3-of-5", "B1 | gpt-6-luna", "3 axis prompts, OR | gpt-6-luna | pii+cred",
          "regex OR 3 axis prompts, OR | gpt-6-luna | pii+cred", "regex alone", "regex OR local | pii+cred"]
pd.DataFrame({k: two_stage_row(CAND[k], [1] * N) for k in ladder}).T.drop(columns=["sent, all", "sent, risky"]).astype(float).round(3)
""")
md("Gate v1 and gate v2 next to the paper gate (main view). Gate v2 = local stage, then the API on what it passes. Gate v2 was not a validation pick, so its validation row is shown too.")
code("""
gates = {"paper gate": CAND[PAPER], "gate v1": CAND[PICK9[4]["best on validation"]]}
gates["gate v2"] = OR(S1, gates["gate v1"])
rows = {}
for k, v in gates.items():
    for name, idx in [("test", TEST_M), ("validation", VAL_M)]:
        y, x = [Y["exposure"][i] for i in idx], [v[i] for i in idx]
        m = G.prf(list(zip(y, x)))
        rows[(k, name)] = {"recall": round(m["recall"], 3), "stored": sum(a and b != 1 for a, b in zip(y, x)), "risky": sum(y), "fp_rate": round(m["fp_rate"], 3),
                           "cost_r4": round(G.cost(y, x, 4), 3), "cost_r25": round(G.cost(y, x, 25), 3),
                           **{f"fp_{g}": round(sum(v[i] == 1 for i in idx if GROUP[i] == g) / sum(GROUP[i] == g for i in idx), 3) for g in ["clean", "credential_hn", "pii_hn"]}}
    y, x = [Y["exposure"][i] for i in TEST_M], [v[i] for i in TEST_M]
    rows[(k, "test")]["recall CI"] = "%.3f-%.3f" % G.bootstrap(y, x, lambda a, b: G.prf(list(zip(a, b)))["recall"])
    rows[(k, "test")]["cost_r4 CI"] = "%.3f-%.3f" % G.bootstrap(y, x, lambda a, b: G.cost(a, b, 4))
    rows[(k, "test")]["McNemar vs paper"] = "%d, %d, %.2g" % G.mcnemar(y, x, [gates["paper gate"][i] for i in TEST_M])
print("share of test records sent to the API by v2:", round(1 - sum(S1[i] for i in TEST_M) / len(TEST_M), 3))
pd.DataFrame(rows).T
""")
md("""
## Final gates

All three risks, test split.

- **v1**: regex + `gpt-6-luna` (PII and credential prompts) + Jev `h_any` at p* = 0.2. Jev `h_any` has the lowest validation cost among harmful detectors on Aegis records.
- **v2**: a record the local tools flag is blocked on the device; the rest get v1's questions. Granite Guardian on the device gives a lower validation cost than leaving it out (0.221 against 0.249 at r = 4).
""")
code("""
LUNA = "openai/gpt-6-luna"
api = OR(AX["pii"][LUNA], AX["credential"][LUNA], thr(prob("JEVQ", "h_any"), 0.2))
device = OR(regex, LOCAL_PC, [int(v == 1) for v in LOCAL["granite-guardian"]["harmful"]])
FINAL = {"paper gate": ALL[PAPER], "v1": OR(regex, api), "v2": OR(device, api)}
SENT = {"paper gate": [1] * N, "v1": [1] * N, "v2": [1 - x for x in device]}
yt = [Y["dangerous"][i] for i in TEST]
risky_t = [i for i in TEST if Y["dangerous"][i]]
rows = {}
for k, v in FINAL.items():
    x = [v[i] for i in TEST]
    rlo, rhi = G.bootstrap(yt, x, lambda y, p: G.prf(list(zip(y, p)))["recall"])
    flo, fhi = G.bootstrap(yt, x, lambda y, p: G.prf(list(zip(y, p)))["fp_rate"])
    b, c, pv = G.mcnemar(yt, x, [ALL[PAPER][i] for i in TEST])
    rows[k] = {**{a: round(b_, 3) for a, b_ in metrics(v, TEST).items()}, "recall 95% CI": f"{rlo:.3f}-{rhi:.3f}", "fp 95% CI": f"{flo:.3f}-{fhi:.3f}",
               "risky stored": sum(v[i] != 1 for i in risky_t), "risky sent out": round(sum(SENT[k][i] for i in risky_t) / len(risky_t), 3),
               "McNemar vs paper (b, c, p)": f"{b}, {c}, {pv:.2g}"}
FINAL_T = pd.DataFrame(rows).T
assert FINAL_T.loc["v1", "recall"] == 0.955 and FINAL_T.loc["v2", "recall"] == 0.982
FINAL_T.T
""")
md("Validation ranking (top 10 per r).")
code("""
for r in R:
    s = pd.Series({k: G.cost([Y["dangerous"][i] for i in VAL], [v[i] for i in VAL], r) for k, v in ALL.items()}).sort_values()
    print(f"r={r}"); display(s.head(10).round(4).to_frame("validation cost"))
""")
code("""
json.dump({"E1": E1.to_dict(), "E2": E2.to_dict(), "E3": E3.to_dict(), "E6": E6r.to_dict(), "FINAL": FINAL_T.to_dict("index"), "picks": PICK, "E9": {"|".join(k): v for k, v in E9.to_dict("index").items()}, "picks_main": PICK9, "EH": {"|".join(k): v for k, v in EH.to_dict("index").items()}, "E10": {"|".join(k): v for k, v in E10.to_dict("index").items()},
           "E7": {f"{a}|{b}": v for (a, b), v in E7.items()}, "E8": {"|".join(k): v for k, v in E8.to_dict("index").items()}},
          open(G.RUNS + "scores_v1.json", "w"), indent=1, default=str)
""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
nbf.write(nb, "/Users/jhtae/PaperReview/Gatekeeper_Experiments/Gatekeeper_v1.ipynb")
print("written", len(cells), "cells")
