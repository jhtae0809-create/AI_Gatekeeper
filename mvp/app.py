"""Shared screen for every app built on the gateway.
Run: streamlit run mvp/app.py --client.toolbarMode minimal -- care   (the last word picks apps/<name>.py;
minimal toolbar: Streamlit's "C" shortcut otherwise opens "Clear caches" on Cmd+C)
"""
import base64
import datetime
import hashlib
import html
import json
import os
import queue
import sys
import threading

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain as CH  # noqa: E402
import explain as X  # noqa: E402
import frame as F  # noqa: E402
import gateway as GW  # noqa: E402

A = F.app(sys.argv[1] if len(sys.argv) > 1 else "care")
st.set_page_config(page_title=A.TITLE, layout="wide")
# The scene under the title: the older adult at home (left), the gatekeeper on the home hub (middle), what leaves through the
# door (right). The three zone cards below follow the same order and overlap its floor, so the scene reads as their background.
SCENE = base64.b64encode(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scene.svg"), "rb").read()).decode()
DARK = st.context.theme.type == "dark"
st.markdown(f"""<style>
[data-testid="stMain"] {{background: {"#0e1117" if DARK else "#eef6fd"};}}
.scene {{display: block; width: 100%; border-radius: 16px; {"filter: brightness(.6);" if DARK else ""}}}
[data-testid="stHorizontalBlock"]:has(.st-key-home) {{margin-top: -3.5%;}}
.st-key-home, .st-key-gate, .st-key-outside, .st-key-ledger {{position: relative; border-radius: 16px; padding: 16px 18px 20px;
  background: {"rgba(14, 17, 23, .92)" if DARK else "rgba(255, 255, 255, .94)"};}}
.st-key-home {{border: 2px solid rgba(201, 119, 90, .7);}}
.st-key-gate {{border: 2px solid rgba(233, 185, 73, .9);}}
.st-key-outside {{border: 2px solid rgba(91, 142, 196, .7);}}
.st-key-ledger {{margin-top: 24px; border: 1.5px dashed rgba(95, 111, 134, .7);}}
</style>""", unsafe_allow_html=True)
PHOTO_DIR = F.V.ROOT + "query_images"  # sample photos (experiments/Dataset/BIV-Priv), local only
SOURCE = {"regex": "regex / secret scanner", "presidio": "Presidio", "gliner": "GLiNER", "detect-secrets": "detect-secrets",
          "pw_shape": "password rule", "keyword": "keyword rule", "ai": "AI check (gpt-6-luna)"}


@st.cache_resource(show_spinner="Loading on-device models (first start takes about a minute)")
def boot():
    GW.load()
    return True


boot()
S = st.session_state  # raw text lives here only, for this browser session
for k, v in {"history": [], "turns": [], "jobs": [], "gate_errors": [], "seen_audio": None, "pending": None, "log_rev": 0, "handled": {}}.items():
    S.setdefault(k, v)


@st.dialog("How it works", width="large")
def how():
    tabs = st.tabs(["1. At home", "2. Why filter", "3. The gatekeeper", "4. Photos and scope", "Limits"])
    with tabs[0]:
        st.markdown(X.HOME)
    with tabs[1]:
        st.markdown(X.WHY)
    with tabs[2]:
        st.markdown(X.diagram(), unsafe_allow_html=True)
        st.markdown(X.GATE)
    with tabs[3]:
        st.markdown(X.PHOTOS)
    with tabs[4]:
        st.markdown(X.LIMITS)


@st.cache_resource
def gate_queue():
    """One background worker checks records in the order they came, so the conversation goes on while the gatekeeper runs."""
    q = queue.Queue()

    def work():
        while True:
            job = q.get()
            try:
                job["turn"] = F.turn(A, job["hist"], job["text"], job["kind"], job["said"], job["question"])
                job["turn"]["photo"] = job["photo"]  # (image, OCR lines, QR boxes), this browser session only
            except Exception as e:
                job["error"] = repr(e)[:200]
            job["done"] = True

    threading.Thread(target=work, daemon=True).start()
    return q


def run(text, kind, photo=None, alone=False, question=None):
    """One turn. Chat, speech and photo questions: the answer streams on screen, then the record joins the gatekeeper queue.
    alone: a scenario button, answered without the conversation so far and not added to it.
    photo: (image, OCR lines, QR boxes) and question: what the person asked about it; text is then the OCR text."""
    if kind != "photo" and not text.strip():
        return
    said, hist = None, [] if alone else S.history
    if kind in ("speech", "chat", "photo"):
        text = text if kind == "photo" else text.strip()  # photo text keeps its offsets for the boxes
        with st.chat_message("user", avatar="📷" if kind == "photo" else None):
            if kind == "photo":
                st.image(photo[0], width=160)
            st.write(question if kind == "photo" else text)
        said = {}
        with st.chat_message("assistant"):
            st.write_stream(F.reply_stream(A, hist, F.photo_ask(question, text) if kind == "photo" else text, said))
    job = {"hist": list(hist), "text": text, "kind": kind, "said": said, "question": question, "photo": photo, "done": False}
    S.jobs.append(job)
    gate_queue().put(job)
    if kind in ("speech", "chat", "photo") and not alone:
        S.history += [{"role": "user", "content": F.photo_ask(question, text) if kind == "photo" else text}, {"role": "assistant", "content": said["answer"]}]
    st.rerun()


@st.fragment(run_every=1 if S.jobs else None)
def gate_progress():
    """Moves finished checks, in order, from the queue to the screen."""
    moved = False
    while S.jobs and S.jobs[0]["done"]:
        job = S.jobs.pop(0)
        if "turn" in job:
            S.turns.append(job["turn"])
        else:
            S.gate_errors.append(job["error"])
        moved = True
    if moved:
        S.log_rev += 1  # new table key: the newest record opens instead of an old selection
        st.rerun()
    if S.jobs:
        st.caption(f"Checking {len(S.jobs)} record{'s' if len(S.jobs) > 1 else ''} in order.")


def bubble(kind, text, question, photo, answer):
    if kind == "event":
        st.chat_message("user", avatar="⌚").write(text)
        return
    with st.chat_message("user", avatar={"photo": "📷", "speech": "🎤"}.get(kind)):
        if kind == "photo":
            st.image(photo[0], width=160)
        st.write(question if kind == "photo" else text)
    st.chat_message("assistant").write(answer)


def read_photo(data, question, alone=False):
    with st.spinner("Reading the text in the photo on device"):
        img, text, words, codes = F.photo_text(data)
    run(text, "photo", (img, words, codes), alone, question.strip() or "What does this say?")


def highlight(record, found):
    """Masked spans on the raw record: orange = on-device tools or rules, purple = added by the AI check only."""
    device = [(a, b) for a, b, src in found if src != "ai"]
    out, last = [], 0
    for a, b in GW.MK.merge(found):
        ai_only = not any(x < b and a < y for x, y in device)
        color = "#b48ead55" if ai_only else "#d0877055"
        out += [html.escape(record[last:a]), f'<mark style="background:{color};border-radius:3px">{html.escape(record[a:b])}</mark>']
        last = b
    return "".join(out + [html.escape(record[last:])]).replace("\n", "<br>")


def handle(idx):
    """Marks family alert idx handled and logs it (record hash, time; no text)."""
    S.handled[idx] = datetime.datetime.now().strftime("%H:%M")
    t = S.turns[idx]
    GW.log({"hash": t["gate"]["hash"], "status": "handled", "p_harm": None, "found": [], "masked": None},
           app=A.NAME, kind="alert", category=t["category"], sent_to=t["sent"]["channel"], masks=None)


@st.cache_data(ttl=15, show_spinner=False)
def tx_status(tx):
    return CH.status(tx)


@st.dialog("Permit this record to go on the blockchain")
def confirm_anchor(entry):
    st.markdown(f"Once you permit it, this record goes to the **{CH.CONTRACT[:10]}…** contract on Ethereum Sepolia, masked text included. Anyone can read it there, and it cannot be deleted.")
    st.markdown("**Text that goes on chain**")
    st.code(entry["masked"], language=None, wrap_lines=True)
    with st.expander("Exact data sent"):
        st.code(f"record   {CH.record(entry)}\nhash     {CH.entry_hash(entry)}", language=None, wrap_lines=True)
    st.caption("Permit only if nothing in the text should stay private.")
    a, b = st.columns(2)
    if a.button("Permit", icon=":material/verified_user:", type="primary", width="stretch"):
        try:
            with st.spinner("Sending to Sepolia"):
                out = CH.anchor(entry)
        except Exception as err:
            st.error(f"Not written: {str(err)[:200]}")
            return
        GW.log({"hash": entry["hash"], "status": "anchored", "p_harm": None, "found": [], "masked": None}, app=A.NAME, kind="chain",
               category=entry.get("category"), sent_to="sepolia", masks=None, content_hash=out["content_hash"], tx=out["tx"])
        S.log_rev += 1
        st.rerun()
    if b.button("Not now", width="stretch"):
        st.rerun()


def chain_box(entry):
    """The record's place on chain: its transaction link, or the wait for a person's permit."""
    h = CH.entry_hash(entry)
    done = next((r for r in LOGS if r.get("status") == "anchored" and r.get("content_hash") == h), None)
    if done:
        st.markdown(f"**On blockchain:** [{done['tx'][:18]}…]({CH.tx_url(done['tx'])}) · {tx_status(done['tx'])} · written {done['time'].replace('T', ' ')}")
    elif entry["status"] != "stored":
        st.caption("Flagged and blocked records never go on the blockchain.")
    else:
        st.markdown("**Blockchain:** this record goes on chain once you permit it.")
        if st.button("Permit", icon=":material/verified_user:", disabled=not CH.ready(), key="anchor" + h,
                    help=None if CH.ready() else "Needs PRIVATE_KEY of a Sepolia test wallet in experiments/.env"):
            confirm_anchor(entry)


def show(t=None, e=None):
    """One record in the gateway panel: a turn of this session (raw text available) or a log entry (masked text only)."""
    if e is not None and e["status"] == "handled":
        st.markdown(f"**Alert marked handled** · {e['time'].replace('T', ' ')} · alert for record {e['hash'][:12]}")
        return
    if e is not None and e["status"] == "anchored":
        st.markdown(f"**Written to blockchain** · {e['time'].replace('T', ' ')} · [{e['tx'][:18]}…]({CH.tx_url(e['tx'])}) · {tx_status(e['tx'])}")
        return
    g = t["gate"] if t else e
    label = {"stored": "Stored, masked", "flagged": "Flagged as harmful", "blocked": "Blocked: AI check failed"}[g["status"]]
    harm = "off for photos" if g["p_harm"] is None else f"{g['p_harm']:.2f}"
    when = (t["log"] if t else e)["time"].replace("T", " ")
    kind = t["kind"] if t else e.get("kind")
    st.markdown(f"**{label}** · {kind} · {when} · harm score {harm}" + (f" · API cost ${t['cost']:.5f}" if t else ""))
    if t is None:
        st.caption("Earlier session: only the logged text is available.")
        if e.get("masked"):
            st.markdown("**What left the home**")
            st.code(e["masked"], language=None, wrap_lines=True)
        st.markdown(f"**Routed:** {e.get('category') or '-'} → {e.get('sent_to') or 'nothing sent'}")
        chain_box(e)
        return
    if g["error"]:
        st.caption(g["error"])
    st.markdown("**1. Original record**")
    st.markdown(f'<div style="font-size:0.9em;line-height:1.6">{highlight(t["record"], g["found"])}</div>', unsafe_allow_html=True)
    st.caption("Orange: found on the device. Purple: added by the AI check.")
    st.markdown("**2. What may leave the home**")
    if g["status"] == "stored":
        st.code(g["masked"], language=None, wrap_lines=True)
    else:
        st.caption("No text. Only the record hash and the verdict are logged.")
    st.markdown(f'**3. Routed:** {t["category"] or "-"} → {t["sent"]["channel"] if t["sent"] else "nothing sent"}')
    if t["kind"] == "photo":
        img, words, codes = t["photo"]
        a, b = st.columns(2)
        a.image(img, caption="Photo as taken")
        b.image(F.V.blackout(img, words, g["found"], t["photo_at"], codes), caption="Masked: lines with a masked value and every QR code are black")
    spans = GW.MK.merge(g["found"])
    if spans:
        with st.expander(f"How each of the {len(spans)} masked values was found"):
            rows = [{"value": t["record"][a:b], "found by": ", ".join(sorted({SOURCE.get(s, s) for x, y, s in g["found"] if x < b and a < y}))} for a, b in spans]
            st.table(pd.DataFrame(rows).set_index("value"))
    chain_box(t["log"])


# ---------------------------------------------------------------- top bar
head, btn = st.columns([5, 1], vertical_alignment="bottom")
head.title(A.TITLE)
head.caption("A gatekeeper decides what part of each record may leave the home. New here? Open **How it works**.")
if btn.button("How it works", icon=":material/info:", width="stretch"):
    how()
st.markdown(f'<img class="scene" src="data:image/svg+xml;base64,{SCENE}" alt="An older adult at home speaks to the companion; the gatekeeper on the home hub masks the phone number; only masked text leaves through the door to the AI model, family, the caregiver and, after a permit, the blockchain.">', unsafe_allow_html=True)

# ---------------------------------------------------------------- sidebar: inputs that need no typing
with st.sidebar:
    st.subheader("Scenarios", help="Typed for you. Each one sends a single input through the whole app, on its own: it does not see or join the conversation. All names and numbers are fake.")
    for name, (kind, text) in A.SCENARIOS.items():
        if st.button(name, width="stretch", help=text):
            S.pending = ("scenario", text, kind)
    if os.path.isdir(PHOTO_DIR):
        st.subheader("Sample photos", help="Someone holds up a document and asks about it. Each one runs on its own, like a scenario. Props from the BIV-Priv-Seg data set (photos taken at home with fake documents).")
        for name, (f, q) in A.PHOTOS.items():
            if st.button(name, width="stretch", key="ph" + f, help=q):
                S.pending = ("sample", open(os.path.join(PHOTO_DIR, f), "rb").read(), q)
    with st.expander("Gate version"):
        st.json(GW.VERSION)

LOGS = [json.loads(l) for l in open(GW.LOG)] if os.path.exists(GW.LOG) else []
rows = LOGS[::-1][:50]
home, gate, out = st.columns([1.15, 1.3, 0.9], gap="large")

# ---------------------------------------------------------------- left: the device at home
with home, st.container(key="home"):
        st.subheader("At home", help=X.TIPS["home"])
        if st.button("New conversation", icon=":material/restart_alt:", width="stretch", help="Clears the conversation on screen. The log stays."):
            S.history, S.turns, S.jobs, S.gate_errors, S.pending, S.handled = [], [], [], [], None, {}
            S.log_rev += 1
            st.rerun()
        typed = st.chat_input("Say something to the companion")
        if typed:
            S.pending = ("text", typed, "chat")
        with st.expander("Voice, wearable reading, camera photo"):
            audio = st.audio_input("Speak")
            with st.form("event", clear_on_submit=True, border=False):
                ev = st.text_input(A.EVENT_LABEL, placeholder="Smartwatch: resting heart rate 148 bpm")
                if st.form_submit_button("Send reading"):
                    S.pending = ("text", ev, "event")
            with st.form("photo", clear_on_submit=True, border=False):
                shot = st.file_uploader("Camera photo", type=["jpg", "jpeg", "png"])
                q = st.text_input("Question about the photo", placeholder="What does this say?")
                if st.form_submit_button("Ask about the photo") and shot is not None:
                    S.pending = ("photo", shot.getvalue(), q)

        if audio is not None:
            data = audio.getvalue()
            h = hashlib.sha256(data).hexdigest()
            if h != S.seen_audio:  # transcribe each clip once
                S.seen_audio = h
                with st.spinner("Speech to text on device"):
                    said = F.stt(data)
                if said:
                    run(said, "speech")
                st.caption("Heard nothing.")
        if S.pending:
            p, S.pending = S.pending, None
            if p[0] in ("photo", "sample"):
                read_photo(p[1], p[2], alone=p[0] == "sample")
            else:
                run(p[1], p[2], alone=p[0] == "scenario")

        for e in S.gate_errors:
            st.caption(f"Gatekeeper stopped on one record: {e}")
        for j in reversed(S.jobs):
            bubble(j["kind"], j["text"], j["question"], j["photo"], j["said"] and j["said"]["answer"])
            st.caption("Waiting for the gatekeeper")
        for t in reversed(S.turns):
            bubble(t["kind"], t["text"], t["question"], t["photo"], t["answer"])
        if not S.turns and not S.jobs:
            st.caption("Type a message, or press a scenario or a sample photo on the left.")

# ---------------------------------------------------------------- the gate between them
with gate, st.container(key="gate"):
        sel = S.get(f"log{S.log_rev}")
        picked = rows[sel.selection.rows[0]] if sel and sel.selection.rows else None
        st.subheader("Gatekeeper", help=X.TIPS["gate"])
        gate_progress()
        if picked:
            t = next((t for t in S.turns if t["log"]["hash"] == picked["hash"] and t["log"]["time"] == picked["time"]), None)
            show(t, None if t else picked)
        elif S.turns:
            show(S.turns[-1])
        elif not S.jobs:
            st.info("Nothing checked yet. The newest record will show here.")


# ---------------------------------------------------------------- outside the home: family, caregiver, log and chain
with out, st.container(key="outside"):
        st.subheader("Outputs", help=X.TIPS["out"])
        ALERTS = A.HARMFUL_ALERT[0]  # the channel whose messages wait until someone marks them handled
        sent = {key: [(i, t["sent"]) for i, t in enumerate(S.turns) if t["sent"] and t["sent"]["channel"] == key] for key in A.CHANNELS}
        waiting = [i for i, _ in sent[ALERTS] if i not in S.handled]
        labels = [f"{name} ({len(waiting)} open)" if key == ALERTS and waiting else name for key, name in A.CHANNELS.items()]
        for key, tab in zip(A.CHANNELS, st.tabs(labels)):
            with tab:
                if key == ALERTS and len(waiting) > 1 and st.button("Mark all handled", icon=":material/done_all:"):
                    for i in waiting:
                        handle(i)
                    st.rerun()
                for i, x in reversed(sent[key]):
                    if key != ALERTS:
                        st.info(x["summary"])
                    elif i in S.handled:
                        st.success(f"Handled at {S.handled[i]}: {x['summary']}", icon=":material/check_circle:")
                    else:
                        c1, c2 = st.columns([4, 1], vertical_alignment="center")
                        c1.error(x["summary"], icon=":material/notifications_active:")
                        if c2.button("Handled", key=f"handled{i}", width="stretch", help="A family member has checked in. The alert stops waiting."):
                            handle(i)
                            st.rerun()
                    if x["masked"]:
                        st.caption(x["masked"])
                if not sent[key]:
                    st.caption("Nothing yet.")

# ---------------------------------------------------------------- the log, and what went on the blockchain
with st.container(key="ledger"):
    st.subheader("Log → blockchain", help=X.TIPS["log"])
    if rows:
        df = pd.DataFrame(rows).reindex(columns=["time", "kind", "status", "category", "sent_to", "masks", "masked", "tx"])
        df["tx"] = df["tx"].map(lambda x: CH.tx_url(x) if isinstance(x, str) else "")
        df["masks"] = df["masks"].map(lambda x: "" if pd.isna(x) else int(x))
        df["time"] = df["time"].str.replace("T", " ").str[5:16]
        df["masked"] = df["masked"].fillna("").str.replace("\n", " ").str[:90]
        st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=f"log{S.log_rev}", height=260,
                     column_config={"tx": st.column_config.LinkColumn("chain", display_text="Etherscan")})
    else:
        st.caption("Empty.")
