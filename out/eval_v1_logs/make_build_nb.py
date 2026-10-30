import nbformat as nbf

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip("\n")))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip("\n")))

md("""
# Evaluation set v1

Hyuntae Jeong · built 2026-10-30 · seed 0

3,500 records in 7 groups of 500, for the gatekeeper experiments in `Gatekeeper_v1.ipynb`. Design and reasons: `Dataset/docs/eval_v1_design.md`. Decisions made during the build: `Dataset/docs/eval_v1_build_log.md`.

| Group | Source | Label |
|---|---|---|
| `harmful` | Aegis 2.0 train, prompt or response unsafe | harmful = 1 |
| `harmful_safe` | Aegis 2.0 train, prompt and response safe | 0 |
| `credential` | Fake secret injected into a clean WildChat turn, 6 types | credential = 1 |
| `credential_hn` | 350 paired (same frame and conversation, placeholder, documented example or masked value) + 150 talk | 0 |
| `pii` | Fake identity injected into a clean WildChat turn, 5 combinations | pii = 1 |
| `pii_hn` | 350 paired (same frame and conversation, every value masked) + 150 talk | 0 |
| `clean` | Clean WildChat conversation, unchanged | 0 |

`dangerous` = pii or credential or harmful. Running all cells rewrites `data/eval_v1.jsonl` and `data/eval_v1_counts.json`. The generator calls are cached in `data/frames_v1.jsonl`, so a rerun makes no API call.

Part A builds the set. Part B shows it.
""")
md("# Part A. Build")
code("""
import collections, hashlib, json, os, random, re, sys
import pandas as pd
sys.path.insert(0, "/Users/jhtae/PaperReview/Gatekeeper_Experiments/scripts")
import build_eval as B
import gate as G
from secretscan import scan

SEED = 0
OUT = B.ROOT + "data/"
FRAMES_FILE = OUT + "frames_v1.jsonl"   # generator output, one line per job (model, date, prompt, items)
POOL_FILE = B.ROOT + "out/eval_v1_pool.json"  # WildChat Step 1 pool (ids only)
rng = random.Random(SEED)
V = B.Values(SEED)
CRED_N = dict(zip(B.CRED_TYPES, [84, 84, 83, 83, 83, 83]))
PII_N = {"name_phone": 100, "name_email": 100, "name_address": 100, "name_ssn": 50, "name_passport": 50, "name_dob_mrn": 100}
N_PAIRED, N_TALK, N_CLEAN, N_AEGIS = 350, 150, 500, 500
assert sum(CRED_N.values()) == sum(PII_N.values()) == 500
""")
md("""
### 1. Frames

The free generator (`nvidia/nemotron-3-ultra-550b-a55b:free`, reasoning off) wrote chat messages with slots, one call per setting and role (`B.frame_jobs()`, 136 calls). Code fills the slots later; the model never writes a value. A frame is kept if:
- every listed slot is there once or twice, and there is no other `{word}` slot (JSON and code braces are fine);
- one `{v}` exactly for credentials;
- the text without slots has no scanner hit, no placeholder identity (John Doe, example.com, 555-01xx, 123 Main St) and no full name found by Presidio;
- it is not a duplicate (case and punctuation ignored).

Talk messages (hard negatives with no value) are kept if they have no slot, no scanner hit, no Presidio name or ID, and no run of four or more digits.
""")
code("""
if not os.path.exists(FRAMES_FILE):
    B.generate(B.frame_jobs(), FRAMES_FILE)
jobs = [json.loads(l) for l in open(FRAMES_FILE)]
assert not {j["key"] for j in B.frame_jobs()} - {j["key"] for j in jobs}, "some generator jobs are missing: rerun B.generate"


def full_name(t):
    return any(len(v.split()) >= 2 for _, v, _ in G.presidio(t, ["PERSON"], 0.7))


def talk_ok(t):
    return not (B.SLOT_RX.search(t) or any(scan(t)) or re.search(r"\\d{4,}", t) or B.FAKE_IDENTITY.search(t)
                or full_name(t) or G.presidio(t, G.PRESIDIO_ID))


frames, talk, fstats, seen = collections.defaultdict(list), collections.defaultdict(list), collections.Counter(), set()
for j in jobs:
    for x in j["items"]:
        t = x["text"].strip()
        key = re.sub(r"\\W+", " ", t.lower()).strip()
        if key in seen:
            fstats[(j["axis"], j["kind"], "duplicate")] += 1
            continue
        seen.add(key)
        fid = "f" + hashlib.sha1(t.encode()).hexdigest()[:10]
        if j["kind"] == "talk":
            ok = talk_ok(t)
            if ok:
                talk[j["axis"]].append(dict(id=fid, text=t, context=j["context"]))
        else:
            ok = B.frame_ok(t, ["v"] if j["axis"] == "credential" else B.PII_SLOTS[j["kind"]], ner=full_name)
            if ok:
                frames[(j["kind"], j["role"])].append(dict(id=fid, text=t, context=j["context"], vendor=j.get("vendor"), format=x.get("format")))
        fstats[(j["axis"], j["kind"], "kept" if ok else "dropped")] += 1
frame_tbl = pd.Series(fstats).unstack(fill_value=0)
frame_tbl
""")
code("""
pd.DataFrame({"user": {k: len(frames[(k, "user")]) for k in list(CRED_N) + list(PII_N)},
              "assistant": {k: len(frames[(k, "assistant")]) for k in list(CRED_N) + list(PII_N)}}), {a: len(v) for a, v in talk.items()}
""")
md("""
### 2. WildChat conversations

The pool is the pilot's Step 1 filter run over all 14 shards (`B.wildchat_pool()`): English, `redacted=False`, one turn, both turns non-empty, 3,000 characters or less, no hit from our scanner, the name pattern or credential words. Pilot conversations are removed.

Each drawn conversation is then checked:
- WildChat's own OpenAI moderation scores: the highest category score over both turns must be 0.02 or less. WildChat-1M already removed conversations flagged as toxic; the hand read of 100 drawn conversations still found jailbreak prompts and sexual role-play below that flag (6 of 100, all above 0.02). The 0.02 cut drops about 18% of conversations;
- detect-secrets (default plugins and filters, not written by us): any hit drops it;
- Presidio (not written by us): an ID, card, bank or phone number, or our PII rule (a full name with a place, date or contact) drops it.

The second rule drops many conversations about fictional or historical people (for example a novel's author and the year). Their label would be unclear under the rule that public figures count, so they are left out of the label-0 groups. Clean text with names is therefore not measured.

`MANUAL_DROP` holds conversations dropped after the hand read (see the build log).
""")
code("""
MAX_MODERATION = 0.02
MANUAL_DROP = set()  # turn_identifier values; the hand read of 100 conversations found none beyond the moderation cut

if not os.path.exists(POOL_FILE):
    c, p = B.wildchat_pool()
    json.dump({"counts": c, "pool": p}, open(POOL_FILE, "w"))
pool_d = json.load(open(POOL_FILE))
pilot_ids = {str(r["origin_id"]) for r in map(json.loads, open(OUT + "pilot.jsonl")) if r["origin_dataset"] == "WildChat-1M"}
pool = [p for p in pool_d["pool"] if str(p[2]) not in pilot_ids]
cand = random.Random(SEED).sample(pool, 3400)  # 1,800 needed; the rest replaces dropped ones
texts = B.load_wildchat([(f, i) for f, i, _ in cand])


def base_flags(text):
    fl = ["detect-secrets:" + t for t in G.detect_secrets_types(text)]
    fl += ["presidio:" + e for e, _, _ in G.presidio(text, G.PRESIDIO_ID)]
    if G.presidio_pii(text):
        fl.append("presidio:name_with_place_date_or_contact")
    return sorted(set(fl))


bases, base_flagged = [], {}
for f, i, tid in cand:
    u, a, mod = texts[(f, i)]
    fl = (["moderation>0.02"] if mod > MAX_MODERATION else []) or base_flags(B.record_text(u, a))
    fl += ["manual"] if str(tid) in MANUAL_DROP else []
    if fl:
        base_flagged[str(tid)] = fl
    else:
        bases.append(dict(conv_id=str(tid), user=u, assistant=a, shard=f, row=i))
print(len(pool_d["pool"]), "in pool,", len(pool), "after removing pilot;", len(cand), "drawn,", len(base_flagged), "flagged,", len(bases), "left")
pd.Series(collections.Counter(x for fl in base_flagged.values() for x in fl)).sort_values(ascending=False).to_frame("conversations")
""")
md("""
### 3. Injected records

For each axis:
- 500 positives. The type list is shuffled; 2/3 go in the user turn and 1/3 in the assistant turn (the frame's role). Position: start, middle or end of the turn.
- 350 of them (70% per type) get a paired hard negative: the same frame, conversation and position, with a non-secret value (credential: placeholder, documented example or masked value; PII: every slot masked, as stars, `[REDACTED]` or Presidio-style tags).
- 150 talk negatives, each in its own conversation, in the user turn.
- The least-used frame of the right type and role is picked each time, so frames are spread evenly.

API keys use the vendor the frame was written for. Card numbers are random and Luhn-valid (Faker), never a published test number; published test numbers appear only in hard negatives.
""")
code("""
base_iter = iter(bases)
records = []


def roles(n):
    r = ["user"] * round(n * 2 / 3) + ["assistant"] * (n - round(n * 2 / 3))
    rng.shuffle(r)
    return r


def pick_frame(kind, role, use):
    fs = frames[(kind, role)]
    low = min(use[f["id"]] for f in fs)
    f = rng.choice([f for f in fs if use[f["id"]] == low])
    use[f["id"]] += 1
    return f


def put(base, role, pos, snippet, spans, values=None):
    text, sp, loc = B.place(base["user"], base["assistant"], role, pos, snippet, spans)
    for s, e, k in sp:
        assert text[s:e] == values[k]
    return dict(text=text, spans=sp, location=loc)


def build_axis(axis, counts):
    use, n0 = collections.Counter(), len(records)
    for kind, n in counts.items():
        paired = set(rng.sample(range(n), round(n * N_PAIRED / 500)))
        for j, role in enumerate(roles(n)):
            base, f = next(base_iter), pick_frame(kind, role, use)
            pos = rng.choice(["start", "middle", "end"])
            if axis == "credential":
                vals = {"v": V.credential(kind, f["vendor"])}
            else:
                ident = V.identity()
                vals = {s: ident[s] for s in B.PII_SLOTS[kind]}
            pid = f"{axis[:4]}-{len(records) - n0:04d}"
            common = dict(type=kind, pair_id=pid, frame_id=f["id"], conv_id=base["conv_id"], origin_dataset="WildChat-1M", origin_id=base["conv_id"])
            snip, sp = B.fill(f["text"], vals)
            records.append(B.rec(**{axis: 1}, group=axis, **common, **put(base, role, pos, snip, sp, vals)))
            if j in paired:
                if axis == "credential":
                    nv, style = V.cred_negative(kind, vals["v"])
                    nvals = {"v": nv}
                else:
                    nvals, style = V.mask_identity(ident, B.PII_SLOTS[kind])
                snip, sp = B.fill(f["text"], nvals)
                r = B.rec(group=axis + "_hn", hard_negative="paired", mask_style=style, **common, **put(base, role, pos, snip, sp, nvals))
                assert not any(v in r["text"] for v in vals.values() if len(v) > 3)
                records.append(r)
    msgs = rng.sample(talk[axis], N_TALK)
    for m in msgs:
        base = next(base_iter)
        records.append(B.rec(group=axis + "_hn", hard_negative="talk", type="talk", frame_id=m["id"], conv_id=base["conv_id"],
                             origin_dataset="WildChat-1M", origin_id=base["conv_id"],
                             **put(base, "user", rng.choice(["start", "middle", "end"]), m["text"], [])))
    return use


cred_use = build_axis("credential", CRED_N)
pii_use = build_axis("pii", PII_N)
for _ in range(N_CLEAN):
    base = next(base_iter)
    records.append(B.rec(group="clean", conv_id=base["conv_id"], origin_dataset="WildChat-1M", origin_id=base["conv_id"],
                         text=B.record_text(base["user"], base["assistant"])))
collections.Counter(r["group"] for r in records), {"credential frames used": len(cred_use), "max uses": max(cred_use.values()),
                                                    "pii frames used": len(pii_use), "max uses ": max(pii_use.values())}
""")
md("""
### 4. Aegis 2.0

Train split. Kept: a non-empty response, prompt not `REDACTED`, no `PII/Privacy` category (its pii label would be unclear), 3,000 characters or less, one row per prompt, no scanner hit, no Presidio ID and no Presidio PII rule hit (so the pii and credential axes stay 0). `harmful` = 1 if the prompt or the response is labeled unsafe. 500 drawn per label.
""")
code("""
ag = pd.read_json(B.DS + "Aegis2/train.json")
n_all = len(ag)
ag = ag[ag.response.map(lambda r: isinstance(r, str) and r.strip() != "") & (ag.prompt.str.strip() != "REDACTED")
        & ~ag.violated_categories.fillna("").str.contains("PII/Privacy")]
ag = ag.assign(text=[B.record_text(p, r) for p, r in zip(ag.prompt, ag.response)],
               harm=((ag.prompt_label == "unsafe") | (ag.response_label == "unsafe")).astype(int))
ag = ag[ag.text.str.len() <= B.MAX_CHARS].drop_duplicates("prompt")
aegis_counts = {"train rows": n_all, "after filters and dedup": len(ag), "dropped by scanners": 0}
for lab in (1, 0):
    taken = 0
    for _, r in ag[ag.harm == lab].sample(frac=1, random_state=SEED).iterrows():
        if any(scan(r.text)) or G.presidio(r.text, G.PRESIDIO_ID) or G.presidio_pii(r.text):
            aegis_counts["dropped by scanners"] += 1
            continue
        records.append(B.rec(harmful=lab, group="harmful" if lab else "harmful_safe", type=r.violated_categories if lab else None,
                             conv_id="aegis-" + r.id, origin_dataset="Aegis-2.0", origin_id=r.id, text=r.text))
        taken += 1
        if taken == N_AEGIS:
            break
aegis_counts
""")
md("""
### 5. Checks, split and output

- Every span points at its value (asserted while building).
- No paired negative holds its positive's value (asserted).
- Our scanner should not call a hard negative a secret, and Presidio's PII rule should not fire on a masked PII negative. Counts below; records that fail are kept and reported, since a gate may still be right to pass them.
- Split: 30% validation, 70% test. Records sharing a pair, a frame or a conversation stay together (union-find), so a combiner fit on validation never sees a test frame.
""")
code("""
SEP = "\\n\\nAssistant: "
for n, r in enumerate(records):
    assert r["text"].count(SEP) <= 1
    r["id"] = f"v1-{n:04d}"
    r["prompt"], _, r["response"] = r["text"][len("User: "):].partition(SEP)
hn = [r for r in records if r["hard_negative"]]
checks = {
    "hard negatives with a scanner 'secret' hit": sum(any(st == "secret" for _, _, st in scan(r["text"])) for r in hn),
    "masked PII negatives with Presidio PII rule hit": sum(G.presidio_pii(r["text"]) for r in hn if r["group"] == "pii_hn" and r["hard_negative"] == "paired"),
    "positives found by our scanner (credential)": sum(G.regex_gate(r["text"])["credential"] for r in records if r["credential"]),
    "positives found by our scanner (pii)": sum(G.regex_gate(r["text"])["pii"] for r in records if r["pii"]),
}
split = B.group_split(records, 0.3, SEED)
for r, s in zip(records, split):
    r["split"] = s
with open(OUT + "eval_v1.jsonl", "w") as fo:
    for r in records:
        fo.write(json.dumps(r, ensure_ascii=False) + "\\n")
counts = dict(total=len(records), checks=checks, aegis=aegis_counts, wildchat_pool=pool_d["counts"],
              wildchat_drawn=len(cand), wildchat_flagged=collections.Counter(x for fl in base_flagged.values() for x in fl),
              wildchat_flagged_n=len(base_flagged), manual_drop=sorted(MANUAL_DROP),
              frames={str(k): v for k, v in fstats.items()}, generator=sorted({j["model"] for j in jobs}),
              generator_dates=sorted({j["date"] for j in jobs}),
              by_group_split=collections.Counter(f"{r['group']}|{r['split']}" for r in records))
json.dump(counts, open(OUT + "eval_v1_counts.json", "w"), indent=1)
print(len(records), "records written")
checks
""")
md("# Part B. View")
code("""
import html
from IPython.display import HTML, display
df = pd.read_json(OUT + "eval_v1.jsonl", lines=True, dtype={"origin_id": str, "conv_id": str})
GROUPS = ["harmful", "harmful_safe", "credential", "credential_hn", "pii", "pii_hn", "clean"]
df["group"] = pd.Categorical(df.group, GROUPS, ordered=True)
comp = df.groupby("group", observed=True)[["pii", "credential", "harmful", "dangerous"]].sum()
comp.insert(0, "records", df.groupby("group", observed=True).size())
comp["validation"] = df[df.split == "validation"].groupby("group", observed=True).size()
comp["test"] = df[df.split == "test"].groupby("group", observed=True).size()
comp.loc["Total"] = comp.sum()
comp
""")
md("Positives by type and turn, and hard negatives by kind and style.")
code("""
pos = df[df.group.isin(["credential", "pii"])]
display(pd.crosstab(pos.type, pos.location.str.split(":").str[0], margins=True, margins_name="Total"))
hn = df[df.hard_negative.notna()]
display(pd.crosstab([hn.group, hn.hard_negative], hn.mask_style.fillna("-"), margins=True, margins_name="Total"))
display(pd.crosstab(df.location.fillna("-"), df.group, margins=False))
""")
md("Text length (characters), which drives API cost.")
code("""
df.assign(chars=df.text.str.len()).groupby("group", observed=True).chars.describe()[["mean", "50%", "max"]].round(0)
""")
md("""
### Examples

Injected values are highlighted. Each pair shows a positive and its paired hard negative. Aegis records are not shown here.
""")
code("""
CSS = '''<style>.pv table{border-collapse:collapse;font-size:12px}.pv td,.pv th{vertical-align:top;text-align:left!important;padding:4px 6px;border-bottom:1px solid #8884}
.pv .box{max-height:200px;max-width:640px;overflow:auto;white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,Menlo,monospace}
.pv mark{background:#ffe08a;color:#3a2c00}</style>'''


def marked(t, spans):
    out, last = [], 0
    for s, e, _ in sorted(spans):
        out += [html.escape(t[last:s]), "<mark>" + html.escape(t[s:e]) + "</mark>"]
        last = e
    return "".join(out + [html.escape(t[last:])])


def show(d, cols=("id", "group", "type", "hard_negative", "mask_style", "location", "split")):
    rows = [{**{c: getattr(r, c) for c in cols}, "text": f"<div class='box'>{marked(r.text, r.spans)}</div>"} for r in d.itertuples()]
    display(HTML(CSS + "<div class='pv'>" + pd.DataFrame(rows).to_html(escape=False, index=False, na_rep="") + "</div>"))


def show_pairs(axis, n=1, seed=0):
    pids = df[(df.group == axis + "_hn") & (df.hard_negative == "paired")].pair_id.sample(n, random_state=seed)
    show(df[df.pair_id.isin(pids)].sort_values(["pair_id", "credential", "pii"], ascending=[True, False, False]))


for i in range(3):
    show_pairs("credential", 1, seed=i)
for i in range(3):
    show_pairs("pii", 1, seed=i)
""")
md("Talk hard negatives (no value).")
code("""
show(df[df.hard_negative == "talk"].sample(4, random_state=0))
""")
md("""
## Limits

- Frames come from one generator model. Its style may differ from real users, and a gate may learn it. Injected and clean records are reported apart.
- The injected snippet does not follow the topic of the conversation, so some records read as unnatural (as in the pilot).
- The label-0 WildChat groups exclude conversations with an OpenAI moderation score above 0.02, and conversations where Presidio finds a full name with a place, date or contact, and anything our scanner, detect-secrets or Presidio flags. False positives on such text are not measured.
- Aegis labels are used as given. Aegis rows may still hold personal data that the scanners miss.
- `pii`, `credential` and `harmful` never overlap in one record, by design.
""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
nbf.write(nb, "/Users/jhtae/PaperReview/Gatekeeper_Experiments/build_eval_v1.ipynb")
print("written", len(cells), "cells")
