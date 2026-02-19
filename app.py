import streamlit as st
import pandas as pd
import re
import io
import json
from datetime import datetime

st.set_page_config(page_title="TxnGuard – Duplicate Payment Detector", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
.main-header { font-size: 2.2rem; font-weight: 800; color: #1e3a5f; letter-spacing: -0.5px; }
.sub-header  { color: #555; font-size: 1rem; margin-bottom: 0.4rem; }
.new-badge   { background:#dcfce7; color:#166534; padding:2px 8px; border-radius:10px;
               font-size:0.75rem; font-weight:700; margin-left:8px; }
.old-badge   { background:#f1f5f9; color:#64748b; padding:2px 8px; border-radius:10px;
               font-size:0.75rem; font-weight:600; margin-left:8px; }
</style>
""", unsafe_allow_html=True)

_hc1, _hc2 = st.columns([3, 1])
with _hc1:
    st.markdown('<div class="main-header">🛡️ TxnGuard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Duplicate Payment Detector — flags CR transactions where the same sender appears more than once across UPI, NEFT, RTGS & IMPS.</div>', unsafe_allow_html=True)
with _hc2:
    st.markdown("""
    <div style="text-align:right;padding-top:0.5rem;">
        <div style="font-size:0.72rem;color:#999;">Built by</div>
        <div style="font-weight:800;color:#1e3a5f;font-size:1.05rem;">Nishanth Fiona</div>
        <div style="font-size:0.8rem;color:#2563eb;font-weight:600;">Data Analyst</div>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# PASSWORD GATE
# ══════════════════════════════════════════════════════════════
# Password is stored in Streamlit Cloud secrets, NOT in this code.
# In Streamlit Cloud dashboard → App settings → Secrets → add:
#   PASSWORD = "your_password_here"
_pw_col1, _pw_col2, _pw_col3 = st.columns([1, 1, 1])
with _pw_col2:
    _entered = st.text_input("🔒 Enter password to access TxnGuard", type="password",
                              placeholder="Password")
    if not _entered:
        st.info("Enter your password to continue.")
        st.stop()
    try:
        _correct = st.secrets["PASSWORD"]
    except Exception:
        st.error("⚠️ App not configured: PASSWORD secret missing. "
                 "Add it in Streamlit Cloud → App settings → Secrets.")
        st.stop()
    if _entered != _correct:
        st.error("❌ Incorrect password.")
        st.stop()

# ══════════════════════════════════════════════════════════════
# ACCOUNT ID EXTRACTION (unchanged logic)
# ══════════════════════════════════════════════════════════════
def extract_account_id(description: str) -> tuple:
    if not isinstance(description, str) or not description.strip():
        return None, "UNKNOWN"
    desc = description.strip()

    if re.search(r'\bUPI\b', desc, re.IGNORECASE):
        matches = re.findall(r'([\w.\-]{3,})@([\w]*)', desc)
        for prefix, suffix in matches:
            if len(prefix) > 30: continue
            if re.match(r'^[A-Z]{2,6}$', prefix): continue
            return f"upi:{prefix.lower()}", "UPI"
        return None, "UPI"

    if re.search(r'\b(NEFT|RTGS|INFT)\b', desc, re.IGNORECASE):
        txn_type = "RTGS" if re.search(r'\bRTGS\b', desc, re.IGNORECASE) else "NEFT"
        match = re.search(r'(\d{9,18})-([A-Z]{4}[0-9A-Z]{7})', desc)
        if match:
            return f"acct:{match.group(1)}", txn_type
        fallback = re.search(r'\b(\d{11,18})\b', desc)
        if fallback:
            return f"acct:{fallback.group(1)}", txn_type
        return None, txn_type

    if re.search(r'\b(IMPS|MMT)\b', desc, re.IGNORECASE):
        known_banks = re.compile(
            r'^(federal|hdfc|sbi|icici|axis|kotak|south indian|canara|pnb|bob|'
            r'idfc|yes|union|indian|karnataka|karur|city union|tamilnad|dcb|rbl|'
            r'indusind|bandhan|au small|ujjivan|equitas|jana|central|uco|'
            r'syndicate|corporation|allahabad|dena|vijaya|oriental|'
            r'state bank|bank of|standard chartered|citi|deutsche|hsbc|'
            r'baroda|punjab|federal bank|south indian ba)', re.IGNORECASE)
        parts = [p.strip() for p in desc.split('/')]
        if len(parts) >= 2:
            candidate = parts[-2].strip()
            skip_kw = re.compile(r'^(MMT|IMPS|NEFT|RTGS|UPI|\d+)$', re.IGNORECASE)
            if (candidate and not skip_kw.match(candidate)
                    and not known_banks.match(candidate)
                    and not candidate.isdigit() and len(candidate) > 2):
                return f"imps_name:{candidate.upper()}", "IMPS"
        return None, "IMPS"

    return None, "OTHER"

def clean_id(acct_id: str) -> str:
    return acct_id.replace("upi:", "").replace("acct:", "").replace("imps_name:", "⚠️ ")

# ══════════════════════════════════════════════════════════════
# FILE UPLOAD SECTION
# ══════════════════════════════════════════════════════════════
st.markdown("---")
col_txn, col_dec = st.columns([2, 1])

with col_txn:
    st.markdown("#### 📂 Step 1 — Upload Transaction File")
    uploaded_file = st.file_uploader("Excel or CSV file", type=["xlsx", "xls", "csv"], key="txn_file")

with col_dec:
    st.markdown("#### 💾 Step 2 — Upload Previous Decisions *(optional)*")
    st.caption("Upload the decisions file saved from a previous session to skip re-reviewing old groups.")
    decisions_file = st.file_uploader("decisions_*.json file", type=["json"], key="dec_file")

if not uploaded_file:
    st.info("Upload your transaction file above to begin.")
    st.markdown("""
    **Workflow for daily use:**
    1. Upload your growing transaction file (all history)
    2. Upload your saved decisions file from yesterday *(optional but saves time)*
    3. Tool shows only **new unreviewed** duplicate groups at the top
    4. Review, mark decisions, then **save decisions file** for tomorrow

    | Type | ID used | Reliability |
    |---|---|---|
    | UPI | VPA username before `@` | ✅ Reliable |
    | NEFT/RTGS | Account number before IFSC | ✅ Reliable |
    | IMPS/MMT | Sender name (truncated) | ⚠️ Human review |
    """)
    st.stop()

# ── Load transaction file ──
try:
    df_raw = (pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv")
              else pd.read_excel(uploaded_file))
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

st.success(f"✅ Loaded **{len(df_raw):,}** rows from `{uploaded_file.name}`")

# ── Load previous decisions ──
saved_decisions = {}   # txn_id -> {"decision": ..., "sender_id": ..., "saved_at": ...}
if decisions_file:
    try:
        saved_decisions = json.load(decisions_file)
        st.success(f"💾 Loaded **{len(saved_decisions):,}** previously saved decisions.")
    except Exception as e:
        st.warning(f"Could not read decisions file: {e}")

# ── Column selectors ──
all_cols = list(df_raw.columns)

def best_match(candidates):
    for c in candidates:
        for col in all_cols:
            if c.lower() in col.lower():
                return col
    return all_cols[0]

with st.expander("⚙️ Column Settings", expanded=False):
    c1, c2, c3 = st.columns(3)
    desc_col = c1.selectbox("Description column", all_cols,
                             index=all_cols.index(best_match(["description","desc","narration","particulars"])))
    crdr_options = ["(auto-detect CR)"] + all_cols
    crdr_col = c2.selectbox("CR/DR column", crdr_options,
                             index=crdr_options.index(best_match(["cr/dr","crdr","type","dr cr"]))
                             if best_match(["cr/dr","crdr","type","dr cr"]) in crdr_options else 0)
    txnid_options = ["(none)"] + all_cols
    txnid_col = c3.selectbox("Transaction ID column", txnid_options,
                              index=txnid_options.index(best_match(["transaction id","txn id","txnid","trans id"]))
                              if best_match(["transaction id","txn id","txnid","trans id"]) in txnid_options else 0)

# ── Filter CR only ──
df = df_raw.copy()
if crdr_col != "(auto-detect CR)":
    cr_mask = df[crdr_col].astype(str).str.strip().str.upper().isin(["CR", "CREDIT", "C"])
    df_cr   = df[cr_mask].copy()
else:
    df_cr = df.copy()

# ── Extract IDs ──
extracted = df_cr[desc_col].apply(extract_account_id)
df_cr = df_cr.copy()
df_cr["__account_id"] = extracted.apply(lambda x: x[0])
df_cr["__txn_type"]   = extracted.apply(lambda x: x[1])

# ── Build transaction ID per row (for decision tracking) ──
if txnid_col != "(none)" and txnid_col in df_cr.columns:
    df_cr["__txn_key"] = df_cr[txnid_col].astype(str).str.strip()
else:
    # Fallback: use row index as stable key
    df_cr["__txn_key"] = df_cr.index.astype(str)

df_identified   = df_cr[df_cr["__account_id"].notna()].copy()
df_unidentified = df_cr[df_cr["__account_id"].isna()].copy()

acct_counts  = df_identified["__account_id"].value_counts()
dup_accounts = acct_counts[acct_counts > 1]
df_identified["__is_dup"] = df_identified["__account_id"].isin(dup_accounts.index)

# ══════════════════════════════════════════════════════════════
# DECISION STATE — merge saved decisions with session state
# ══════════════════════════════════════════════════════════════
# saved_decisions = {txn_key: {decision, sender_id, saved_at}}
# session_state.txn_decisions = same structure (in-memory for this session)

if "txn_decisions" not in st.session_state:
    st.session_state.txn_decisions = {}

# Load saved decisions into session on first load of this file
file_sig = f"{uploaded_file.name}_{len(df_raw)}"
if st.session_state.get("__loaded_file") != file_sig:
    st.session_state.txn_decisions = dict(saved_decisions)
    st.session_state["__loaded_file"] = file_sig

def get_txn_decision(txn_key: str) -> str:
    entry = st.session_state.txn_decisions.get(txn_key)
    return entry["decision"] if entry else "⏳ Pending"

def set_txn_decision(txn_key: str, decision: str, sender_id: str):
    st.session_state.txn_decisions[txn_key] = {
        "decision": decision,
        "sender_id": sender_id,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

def get_group_status(group_df) -> dict:
    """
    For a group of transactions, returns:
    - decisions: {txn_key: decision}
    - all_reviewed: bool (all txns have a non-Pending decision)
    - has_new: bool (at least one txn is Pending / not in saved_decisions)
    - consensus: the decision if all reviewed and same, else "Mixed"
    """
    decisions = {}
    for _, row in group_df.iterrows():
        key        = row["__txn_key"]
        widget_key = f"txn_{key}"
        # Prefer the live widget value (set by user interaction this session)
        # over txn_decisions, which may lag by one rerun cycle
        if widget_key in st.session_state:
            decisions[key] = st.session_state[widget_key]
        else:
            decisions[key] = get_txn_decision(key)
    
    values = list(decisions.values())
    all_reviewed = all(v != "⏳ Pending" for v in values)
    has_new      = any(v == "⏳ Pending" for v in values)
    
    unique_vals = set(v for v in values if v != "⏳ Pending")
    if all_reviewed and len(unique_vals) == 1:
        consensus = unique_vals.pop()
    elif all_reviewed:
        consensus = "Mixed"
    else:
        consensus = None

    return {"decisions": decisions, "all_reviewed": all_reviewed,
            "has_new": has_new, "consensus": consensus}

# ── Metrics ──
st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Rows",         f"{len(df_raw):,}")
m2.metric("CR Transactions",    f"{len(df_cr):,}")
m3.metric("IDs Extracted",      f"{df_identified['__account_id'].nunique():,}")
m4.metric("Repeat Senders",     f"{len(dup_accounts):,}")
m5.metric("Flagged Txns",       f"{df_identified['__is_dup'].sum():,}")
st.markdown("---")

with st.expander("📊 Breakdown by transaction type", expanded=False):
    bd  = df_cr.groupby("__txn_type").size().reset_index(name="Total CR")
    ibd = df_identified.groupby("__txn_type").size().reset_index(name="ID Extracted")
    bd  = bd.merge(ibd, on="__txn_type", how="left").fillna(0)
    bd["ID Extracted"]    = bd["ID Extracted"].astype(int)
    bd["Skipped (no ID)"] = bd["Total CR"] - bd["ID Extracted"]
    bd.columns = ["Txn Type", "Total CR", "ID Extracted", "Skipped (no ID)"]
    st.dataframe(bd, use_container_width=True, hide_index=True)

display_cols = list(df_raw.columns)

# ══════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["🚨 Duplicate Accounts", "📋 All CR Transactions", "❓ Unidentified Rows", "📥 Export & Save"])

# ── TAB 1: Duplicate Accounts ─────────────────────────────────
with tab1:
    if dup_accounts.empty:
        st.success("🎉 No duplicate sender account IDs found!")
    else:
        needs_review  = []
        fully_reviewed = []

        for acct_id, count in dup_accounts.items():
            group_df = df_identified[df_identified["__account_id"] == acct_id].copy()
            status   = get_group_status(group_df)
            if status["has_new"]:
                needs_review.append((acct_id, count, group_df, status))
            else:
                fully_reviewed.append((acct_id, count, group_df, status))

        # ────────────────────────────────────────────────────────
        # NEEDS REVIEW
        # ────────────────────────────────────────────────────────
        st.markdown(f"### 🆕 Needs Review — {len(needs_review)} group(s)")
        if not needs_review:
            st.success("✅ All groups reviewed!")
        else:
            for acct_id, count, group_df, status in needs_review:
                txn_types  = group_df["__txn_type"].unique().tolist()
                new_count  = sum(1 for d in status["decisions"].values() if d == "⏳ Pending")
                old_count  = count - new_count
                prev_decs  = [d for d in status["decisions"].values() if d != "⏳ Pending"]
                prev_legit = prev_decs and all(d == "✅ Legitimate" for d in prev_decs)

                label = (f"🔑 {clean_id(acct_id)}  ({', '.join(txn_types)})  ·  {count} txns"
                         + (f"  ·  🆕 {new_count} new" if new_count else "")
                         + (f"  ·  {old_count} reviewed" if old_count else ""))

                with st.expander(label, expanded=True):
                    if prev_legit and new_count > 0:
                        st.warning(
                            f"⚠️ **Previously cleared sender** — {new_count} new transaction(s) appeared. "
                            f"Review carefully before deciding.")

                    # ── Table view: all transactions, clean Excel-like ──
                    table_df = group_df[display_cols].copy()
                    table_df.insert(0, "Status", [
                        ("🆕 New" if get_txn_decision(r["__txn_key"]) == "⏳ Pending"
                         else ("✅ Legitimate" if "Legitimate" in get_txn_decision(r["__txn_key"])
                               else "🚫 Duplicate"))
                        for _, r in group_df.iterrows()
                    ])
                    st.dataframe(table_df.reset_index(drop=True), use_container_width=True,
                                 height=min(400, 45 + count * 36))

                    st.divider()

                    # ── Decision controls ──
                    dc1, dc2, dc3 = st.columns([2, 1, 1])
                    with dc1:
                        group_key    = f"grp_sel_{acct_id}"
                        group_choice = st.selectbox(
                            "Apply to ALL transactions in this group:",
                            options=["— choose —", "✅ Legitimate", "🚫 Flag as Duplicate"],
                            key=group_key
                        )
                    with dc2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("✅ Apply to all", key=f"apply_{acct_id}",
                                     disabled=(group_choice == "— choose —")):
                            for _, r in group_df.iterrows():
                                k = r["__txn_key"]
                                # clear any stale widget key so index param takes effect
                                wk = f"txn_{k}"
                                if wk in st.session_state:
                                    del st.session_state[wk]
                                set_txn_decision(k, group_choice, acct_id)
                            st.rerun()
                    with dc3:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("🆕 Apply to NEW only", key=f"applynew_{acct_id}",
                                     disabled=(group_choice == "— choose —")):
                            for _, r in group_df.iterrows():
                                k = r["__txn_key"]
                                if get_txn_decision(k) == "⏳ Pending":
                                    wk = f"txn_{k}"
                                    if wk in st.session_state:
                                        del st.session_state[wk]
                                    set_txn_decision(k, group_choice, acct_id)
                            st.rerun()

                    # ── Per-transaction override (for edge cases) ──
                    with st.expander("Override individual transactions", expanded=False):
                        for _, row in group_df.iterrows():
                            txn_key    = row["__txn_key"]
                            cur_dec    = get_txn_decision(txn_key)
                            widget_key = f"txn_{txn_key}"
                            rc1, rc2   = st.columns([3, 1])
                            with rc1:
                                st.caption(f"{txn_key} · {str(row[desc_col])[:80]}")
                            with rc2:
                                new_val = st.selectbox(
                                    "Dec", options=["⏳ Pending", "✅ Legitimate", "🚫 Flag as Duplicate"],
                                    index=["⏳ Pending", "✅ Legitimate", "🚫 Flag as Duplicate"].index(cur_dec),
                                    key=widget_key, label_visibility="collapsed")
                                if new_val != cur_dec:
                                    if widget_key in st.session_state:
                                        del st.session_state[widget_key]
                                    set_txn_decision(txn_key, new_val, acct_id)
                                    st.rerun()

        # ────────────────────────────────────────────────────────
        # FULLY REVIEWED
        # ────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"### ✅ Already Reviewed — {len(fully_reviewed)} group(s)")
        for acct_id, count, group_df, status in fully_reviewed:
            txn_types = group_df["__txn_type"].unique().tolist()
            consensus = status["consensus"]
            icon  = "✅" if consensus == "✅ Legitimate" else ("🚫" if consensus and "Duplicate" in consensus else "🔀")
            label = f"{icon} {clean_id(acct_id)}  ({', '.join(txn_types)})  ·  {count} txns  [{consensus}]"
            with st.expander(label, expanded=False):
                table_df = group_df[display_cols].copy()
                table_df.insert(0, "Decision", [
                    ("✅ Legitimate" if "Legitimate" in get_txn_decision(r["__txn_key"])
                     else "🚫 Duplicate")
                    for _, r in group_df.iterrows()
                ])
                st.dataframe(table_df.reset_index(drop=True), use_container_width=True,
                             height=min(400, 45 + count * 36))
                # Allow re-opening for correction via group selector
                rc1, rc2, rc3 = st.columns([2, 1, 1])
                with rc1:
                    rk = f"re_{acct_id}"
                    rechoice = st.selectbox("Change all decisions to:",
                                            ["— no change —", "✅ Legitimate", "🚫 Flag as Duplicate",
                                             "⏳ Reset to Pending"], key=rk)
                with rc2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("Apply", key=f"reapply_{acct_id}",
                                 disabled=(rechoice == "— no change —")):
                        for _, r in group_df.iterrows():
                            k  = r["__txn_key"]
                            wk = f"txn_{k}"
                            if wk in st.session_state:
                                del st.session_state[wk]
                            set_txn_decision(k, rechoice, acct_id)
                        st.rerun()

        # Progress bar
        st.markdown("---")
        all_dup_txns   = df_identified[df_identified["__is_dup"]]
        total_dup_txns = len(all_dup_txns)
        reviewed_count = sum(1 for _, row in all_dup_txns.iterrows()
                             if get_txn_decision(row["__txn_key"]) != "⏳ Pending")
        st.markdown(f"**Review progress: {reviewed_count} / {total_dup_txns} transactions reviewed**")
        st.progress(reviewed_count / total_dup_txns if total_dup_txns else 1.0)

# ── TAB 2: All CR Transactions ────────────────────────────────
with tab2:
    filter_opt = st.radio("Show:", ["All CR", "Flagged (repeat IDs)", "Clean", "No ID"], horizontal=True)
    view = df_cr.copy()
    view["Account ID"]  = view["__account_id"].fillna("—").apply(lambda x: clean_id(x) if isinstance(x, str) else "—")
    view["Txn Type"]    = view["__txn_type"]
    view["Repeat Flag"] = view["__account_id"].apply(
        lambda s: "🔴 REPEAT" if s in dup_accounts.index else ("🟢 UNIQUE" if pd.notna(s) else "⚪ NO ID"))
    view["Decision"]    = view["__txn_key"].apply(get_txn_decision)

    if filter_opt == "Flagged (repeat IDs)":
        view = view[view["__account_id"].isin(dup_accounts.index)]
    elif filter_opt == "Clean":
        view = view[view["__account_id"].notna() & ~view["__account_id"].isin(dup_accounts.index)]
    elif filter_opt == "No ID":
        view = view[view["__account_id"].isna()]

    show_cols = display_cols + ["Account ID", "Txn Type", "Repeat Flag", "Decision"]
    st.dataframe(view[show_cols].reset_index(drop=True), use_container_width=True, height=500)

# ── TAB 3: Unidentified ───────────────────────────────────────
with tab3:
    st.markdown(f"### {len(df_unidentified):,} CR transactions — no identifier extractable")
    st.caption("ATM, bank charges, reversals, or formats where no sender ID could be found.")
    if not df_unidentified.empty:
        show = df_unidentified[display_cols + ["__txn_type"]].rename(columns={"__txn_type": "Txn Type"})
        st.dataframe(show.reset_index(drop=True), use_container_width=True, height=450)

# ── TAB 4: Export & Save ──────────────────────────────────────
with tab4:
    st.markdown("### 📥 Export & 💾 Save Decisions")

    def to_excel_bytes(data: pd.DataFrame, sheet="Sheet1") -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            data.to_excel(writer, index=False, sheet_name=sheet)
            ws = writer.sheets[sheet]
            for col in ws.columns:
                w = max((len(str(c.value or "")) for c in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(w + 4, 55)
        return buf.getvalue()

    # ── SAVE DECISIONS FILE ──
    st.markdown("#### 💾 Save Your Decisions (re-upload tomorrow to skip re-reviewing)")
    decisions_to_save = dict(st.session_state.txn_decisions)
    if decisions_to_save:
        dec_json = json.dumps(decisions_to_save, indent=2)
        st.download_button(
            "⬇️ Download decisions file (decisions.json)",
            data=dec_json,
            file_name=f"decisions_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            help="Save this file and re-upload it next session — all your decisions will be pre-filled automatically."
        )
        st.info(f"📦 {len(decisions_to_save)} transaction decisions saved in this file. "
                "Re-upload it alongside your transaction Excel next time to skip re-reviewing.")
    else:
        st.warning("No decisions made yet — make some reviews in Tab 1 first.")

    st.markdown("---")

    # ── EXCEL EXPORTS ──
    export = df_cr.copy()
    export["Account ID"]  = export["__account_id"].fillna("").apply(lambda x: clean_id(x) if x else "")
    export["Txn Type"]    = export["__txn_type"]
    export["Repeat Flag"] = export["__account_id"].apply(
        lambda s: "REPEAT" if s in dup_accounts.index else ("UNIQUE" if pd.notna(s) and s else "NO_ID"))
    export["Decision"]    = export["__txn_key"].apply(get_txn_decision)
    export_cols = display_cols + ["Account ID", "Txn Type", "Repeat Flag", "Decision"]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### 🔴 Repeat Senders Only")
        dup_exp = export[export["__account_id"].isin(dup_accounts.index)][export_cols]
        st.info(f"{len(dup_exp)} transactions")
        st.download_button("⬇️ Download", data=to_excel_bytes(dup_exp, "RepeatAccounts"),
                           file_name=f"repeat_accounts_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    with col2:
        st.markdown("#### 🚫 Flagged as Duplicate")
        flag_exp = export[export["Decision"] == "🚫 Flag as Duplicate"][export_cols]
        st.info(f"{len(flag_exp)} transactions")
        if flag_exp.empty:
            st.warning("None flagged yet.")
        else:
            st.download_button("⬇️ Download", data=to_excel_bytes(flag_exp, "Flagged"),
                               file_name=f"flagged_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)
    with col3:
        st.markdown("#### 📋 Full CR Report")
        st.info(f"{len(export)} total CR transactions")
        st.download_button("⬇️ Download", data=to_excel_bytes(export[export_cols], "FullCR"),
                           file_name=f"full_cr_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

    # Summary
    st.markdown("---")
    st.markdown("#### 📊 Repeat Sender Summary")
    if not dup_accounts.empty:
        rows = []
        for acct_id, cnt in dup_accounts.items():
            group_df = df_identified[df_identified["__account_id"] == acct_id]
            status   = get_group_status(group_df)
            types    = group_df["__txn_type"].unique().tolist()
            new_cnt  = sum(1 for d in status["decisions"].values() if d == "⏳ Pending")
            rows.append({
                "Account ID":  clean_id(acct_id),
                "ID Type":     "UPI VPA" if acct_id.startswith("upi:") else ("NEFT/RTGS Acct#" if acct_id.startswith("acct:") else "IMPS Name ⚠️"),
                "Txn Type":    ", ".join(types),
                "Total Txns":  cnt,
                "New (unreviewed)": new_cnt,
                "Status":      status["consensus"] or "⏳ Partially reviewed",
            })
        summary = pd.DataFrame(rows).sort_values("New (unreviewed)", ascending=False).reset_index(drop=True)
        st.dataframe(summary, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download Summary",
                           data=to_excel_bytes(summary, "Summary"),
                           file_name=f"summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")