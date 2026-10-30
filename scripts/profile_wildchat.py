"""Row-level profile of the local WildChat-1M shards. Read-only, counts only.

Input:  Dataset/WildChat/*.parquet.  Output: out/wildchat_profile.json.
Counts rows, redacted, toxic, English, languages, models, turns, and conversations with code
(a regex for code fences, def, import, #include, function, public, SELECT ... FROM).

Notebook link: none directly. It checked what the source looks like before the build. The notebook's Step 1 funnel
starts from the same 837,989 rows.

Result (2026-10-02): 837,989 rows. English 478,498. redacted 6,463. toxic 0 (toxic rows are not in this release).
English, non-toxic, unredacted 473,202, of which 74,731 hold code in some turn. One-turn conversations 506,506.
Models: gpt-3.5-turbo 623,854 in total, gpt-4 214,135 in total.
"""
import glob, json, re, collections, pyarrow.parquet as pq

SRC = "/Users/jhtae/PaperReview/Gatekeeper_Experiments/Dataset/WildChat/*.parquet"
CODE = re.compile(r"```|\bdef \w+\(|\bimport \w+|#include|\bfunction\s*\w*\(|\bpublic (static )?\w+|SELECT .+ FROM", re.S)

c = collections.Counter()
lang, model, turns = collections.Counter(), collections.Counter(), collections.Counter()
for f in sorted(glob.glob(SRC)):
    t = pq.read_table(f, columns=["conversation", "turn", "language", "model", "toxic", "redacted"]).to_pylist()
    for r in t:
        c["rows"] += 1
        c["redacted"] += r["redacted"]
        c["toxic"] += r["toxic"]
        en = r["language"] == "English"
        c["english"] += en
        lang[r["language"]] += 1
        model[r["model"]] += 1
        turns[min(r["turn"], 6)] += 1
        conv = r["conversation"]
        first_user = next((m["content"] for m in conv if m["role"] == "user"), "") or ""
        any_code = any(CODE.search(m["content"] or "") for m in conv)
        c["code_any_turn"] += any_code
        c["code_first_prompt"] += bool(CODE.search(first_user))
        c["turn_redacted_msgs"] += sum(bool(m["redacted"]) for m in conv)
        c["msgs"] += len(conv)
        if en and not r["toxic"] and not r["redacted"]:
            c["en_nontoxic_unredacted"] += 1
            c["en_nontoxic_unredacted_code"] += any_code
    print(f, c["rows"], flush=True)

out = {"counts": dict(c), "top_languages": lang.most_common(10),
       "models": model.most_common(), "turns(6=6+)": sorted(turns.items())}
print(json.dumps(out, indent=1))
json.dump(out, open("/Users/jhtae/PaperReview/Gatekeeper_Experiments/out/wildchat_profile.json", "w"), indent=1)
