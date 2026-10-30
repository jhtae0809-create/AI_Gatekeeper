"""Scan every message of WildChat-1M (all languages, all turns) with secretscan.

Input:  Dataset/WildChat/*.parquet (14 shards).
Output: out/scan_parts/<shard>.jsonl|.hashes|.json, one set per shard, so a rerun skips finished shards
        (delete scan_parts/ to rescan from scratch). Then merged into:
        - out/wildchat_hits.jsonl: one line per hit. Secret and PII values are masked (first 4 and last 4 characters kept).
          Placeholders are shown as they are.
        - out/wildchat_secret_hashes.txt: SHA-256 of every distinct value with status "secret". Raw values are never written.
        - out/wildchat_scan_summary.json: hit counts by kind and status, and conversations with each status.

Notebook link: pilot_set_v2.ipynb reads wildchat_secret_hashes.txt (`looks_live`) and redraws any generated value
that matches a real WildChat secret. The notebook's Step 1 scans again, but only the English, unredacted, one-turn
candidates, and only to drop them.

Result (rerun 2026-10-21 with the fixed scanner, about 15 minutes on 4 processes): 27,180 hits.
Conversations with a secret 970, with a placeholder 3,500, with PII 2,834. 376 distinct secret values.
Secret hits by kind: generic_assign 687, hf_token 426, telegram_bot 360, openai_key 126, google_api_key 96, jwt 73,
conn_string 50, aws_access_key 9, private_key 5, stripe_key 3. PII hits: email 12,141, phone 4,815, SSN-shaped 463.
First run (2026-10-02, old scanner): 1,631 conversations with a secret, 777 distinct values. The drop is false hits
(code references, constant names, example values) that the old scanner called secrets.
"""
import glob, hashlib, json, os, collections, multiprocessing, pyarrow.parquet as pq
from secretscan import scan, mask

SRC = "/Users/jhtae/PaperReview/Gatekeeper_Experiments/Dataset/WildChat/*.parquet"
OUT = "/Users/jhtae/PaperReview/Gatekeeper_Experiments/out/"
PARTS = OUT + "scan_parts/"


def shard(f):
    p = PARTS + os.path.basename(f).split(".")[0]
    if os.path.exists(p + ".json"):  # written last, so it marks a finished shard
        return
    hashes, tally, convs = set(), collections.Counter(), collections.Counter()
    with open(p + ".jsonl", "w") as hits:
        for r in pq.read_table(f, columns=["conversation_hash", "conversation", "language"]).to_pylist():
            st_conv = set()
            for i, m in enumerate(r["conversation"]):
                for kind, v, st in scan(m["content"]):
                    tally[f"{kind}|{st}"] += 1
                    st_conv.add(st)
                    if st == "secret":
                        hashes.add(hashlib.sha256(v.encode()).hexdigest())
                    hits.write(json.dumps({"conversation_hash": r["conversation_hash"], "turn_identifier": m["turn_identifier"],
                                           "msg": i, "role": m["role"], "language": r["language"], "kind": kind,
                                           "status": st, "masked": v if st == "placeholder" else mask(v)}) + "\n")  # placeholders are not secrets
            convs.update(st_conv)
    open(p + ".hashes", "w").write("\n".join(sorted(hashes)))
    json.dump({"tally": tally, "convs": convs}, open(p + ".json", "w"))
    print(f, dict(convs), flush=True)


if __name__ == "__main__":
    os.makedirs(PARTS, exist_ok=True)
    with multiprocessing.Pool(4) as pool:
        pool.map(shard, sorted(glob.glob(SRC)), chunksize=1)
    tally, convs, hashes = collections.Counter(), collections.Counter(), set()
    with open(OUT + "wildchat_hits.jsonl", "w") as fo:
        for p in sorted(glob.glob(PARTS + "*.json")):
            d = json.load(open(p))
            tally.update(d["tally"]); convs.update(d["convs"])
            hashes.update(x for x in open(p[:-5] + ".hashes").read().split() if x)
            fo.write(open(p[:-5] + ".jsonl").read())
    open(OUT + "wildchat_secret_hashes.txt", "w").write("\n".join(sorted(hashes)))
    json.dump({"by_kind_status": dict(tally.most_common()), "conversations_with": dict(convs),
               "distinct_secret_values": len(hashes)}, open(OUT + "wildchat_scan_summary.json", "w"), indent=1)
    print("done", dict(convs), len(hashes))
