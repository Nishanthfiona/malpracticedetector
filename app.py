import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime

st.set_page_config(page_title="TxnGuard – Duplicate Payment Detector", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
.main-header { font-size: 2.2rem; font-weight: 800; color: #1e3a5f; letter-spacing: -0.5px; }
.sub-header  { color: #555; font-size: 1rem; margin-bottom: 0.4rem; }
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
# ACCOUNT ID EXTRACTION
# ══════════════════════════════════════════════════════════════
# Key insight from data analysis:
#
# UPI descriptions truncate VPAs in different ways:
#   "sruthycs200-2@/"        → prefix before @ is "sruthycs200-2"
#   "sruthycs200-2@o/"       → prefix before @ is "sruthycs200-2" (suffix "o" is truncated bank suffix)
#   "9912977860-2@ybl"       → prefix "9912977860-2", suffix "ybl" (full VPA)
#   "7730077724@ybl"         → prefix "7730077724"
#
# Strategy: extract the USERNAME (part before @) as the canonical ID.
# This normalizes all truncation variants of the same VPA to the same key.
#
# NEFT/RTGS descriptions contain the sender's account number:
#   "...ELIGIBLE FOR-12552100113212-FDRL0000037"
#   The 9–18 digit number before the IFSC code is the account number.
#
# IMPS/MMT: descriptions only show bank name + truncated sender name.
# No account number is present → cannot detect duplicates → skipped.

def extract_account_id(description: str) -> tuple[str | None, str]:
    """
    Returns (account_id, txn_type).
    account_id is None if no reliable ID can be extracted.
    """
    if not isinstance(description, str) or not description.strip():
        return None, "UNKNOWN"

    desc = description.strip()

    # ── UPI ──────────────────────────────────────────────────
    if re.search(r'\bUPI\b', desc, re.IGNORECASE):
        # Find all word@word or word@ patterns
        # We want the VPA username (part before @), ignoring hashes and bank codes
        matches = re.findall(r'([\w.\-]{3,})@([\w]*)', desc)
        for prefix, suffix in matches:
            # Skip: too long (transaction hashes), or pure short uppercase (bank codes)
            if len(prefix) > 30:
                continue
            if re.match(r'^[A-Z]{2,6}$', prefix):  # e.g. "SBI", "HDFC", "YBL"
                continue
            # This is the VPA username — use as canonical ID
            return f"upi:{prefix.lower()}", "UPI"
        # No VPA found in this UPI transaction (bank omitted it)
        return None, "UPI"

    # ── NEFT / RTGS ──────────────────────────────────────────
    if re.search(r'\b(NEFT|RTGS|INFT)\b', desc, re.IGNORECASE):
        txn_type = "RTGS" if re.search(r'\bRTGS\b', desc, re.IGNORECASE) else "NEFT"
        # Sender account number: 9–18 digit number immediately before IFSC code
        # IFSC format: 4 alpha letters + 7 alphanumeric chars
        match = re.search(r'(\d{9,18})-([A-Z]{4}[0-9A-Z]{7})', desc)
        if match:
            return f"acct:{match.group(1)}", txn_type
        # Fallback: standalone long number (less reliable)
        fallback = re.search(r'\b(\d{11,18})\b', desc)
        if fallback:
            return f"acct:{fallback.group(1)}", txn_type
        return None, txn_type

    # ── IMPS / MMT ───────────────────────────────────────────
    # Structure: MMT/IMPS/REF/PURPOSE/SENDER_NAME/BANK
    # Sender name is the second-to-last slash-segment (before the bank name).
    # Names are truncated by the bank (e.g. "FAROOQUE B", "SEMBAIYAN") but
    # consistent across transactions from the same sender — good enough to flag duplicates.
    # Flagged results are shown for human review since names aren't guaranteed unique.
    if re.search(r'\b(IMPS|MMT)\b', desc, re.IGNORECASE):
        known_banks = re.compile(
            r'^(federal|hdfc|sbi|icici|axis|kotak|south indian|canara|pnb|bob|'
            r'idfc|yes|union|indian|karnataka|karur|city union|tamilnad|dcb|rbl|'
            r'indusind|bandhan|au small|ujjivan|equitas|jana|central|uco|'
            r'syndicate|corporation|allahabad|dena|vijaya|oriental|'
            r'state bank|bank of|standard chartered|citi|deutsche|hsbc|'
            r'baroda|punjab|federal bank|south indian ba)',
            re.IGNORECASE
        )
        parts = [p.strip() for p in desc.split('/')]
        # Second-to-last part is sender name, last part is bank
        if len(parts) >= 2:
            candidate = parts[-2].strip()
            bank_part = parts[-1].strip()
            # Valid sender: not a bank name, not numeric, not a keyword, len > 2
            skip_kw = re.compile(r'^(MMT|IMPS|NEFT|RTGS|UPI|\d+)$', re.IGNORECASE)
            if (candidate
                    and not skip_kw.match(candidate)
                    and not known_banks.match(candidate)
                    and not candidate.isdigit()
                    and len(candidate) > 2):
                return f"imps_name:{candidate.upper()}", "IMPS"
        return None, "IMPS"

    return None, "OTHER"


# ══════════════════════════════════════════════════════════════
# FILE UPLOAD
# ══════════════════════════════════════════════════════════════
uploaded_file = st.file_uploader("📂 Upload Excel or CSV file", type=["xlsx", "xls", "csv"])

if not uploaded_file:
    st.info("Upload your bank statement Excel/CSV file to begin.")
    st.markdown("""
    **How duplicate detection works:**

    | Transaction Type | How sender is identified | Duplicate detection |
    |---|---|---|
    | **UPI** | VPA username before `@` (e.g. `sruthycs200-2`) | ✅ Reliable |
    | **NEFT / RTGS** | Sender account number before IFSC code | ✅ Reliable |
    | **IMPS / MMT** | Sender name from description (e.g. `FAROOQUE B`) | ⚠️ For human review (names may be truncated) |

    Only **CR transactions** are analysed.
    """)
    st.stop()

# Load file
try:
    df_raw = (pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv")
              else pd.read_excel(uploaded_file))
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

st.success(f"✅ Loaded **{len(df_raw):,}** rows from `{uploaded_file.name}`")

# ── Column selectors ──────────────────────────────────────────
all_cols = list(df_raw.columns)

def best_match(candidates):
    for c in candidates:
        for col in all_cols:
            if c.lower() in col.lower():
                return col
    return all_cols[0]

with st.expander("⚙️ Column Settings", expanded=False):
    c1, c2 = st.columns(2)
    desc_col = c1.selectbox("Description column", all_cols,
                             index=all_cols.index(best_match(["description","desc","narration","particulars"])))
    crdr_options = ["(auto-detect CR)"] + all_cols
    crdr_col = c2.selectbox("CR/DR column", crdr_options,
                             index=crdr_options.index(best_match(["cr/dr","crdr","type","dr cr"])) 
                             if best_match(["cr/dr","crdr","type","dr cr"]) in crdr_options else 0)

# ── Filter CR only ────────────────────────────────────────────
df = df_raw.copy()
if crdr_col != "(auto-detect CR)":
    cr_mask = df[crdr_col].astype(str).str.strip().str.upper().isin(["CR", "CREDIT", "C"])
    df_cr   = df[cr_mask].copy()
    df_dr   = df[~cr_mask].copy()
    st.info(f"Analysing **{len(df_cr):,} CR transactions** · Excluded {len(df_dr):,} DR/other rows")
else:
    df_cr = df.copy()
    st.warning("No CR/DR column selected — analysing all rows. Select it above for accurate results.")

# ── Extract IDs ───────────────────────────────────────────────
extracted = df_cr[desc_col].apply(extract_account_id)
df_cr["__account_id"] = extracted.apply(lambda x: x[0])
df_cr["__txn_type"]   = extracted.apply(lambda x: x[1])

df_identified   = df_cr[df_cr["__account_id"].notna()].copy()
df_unidentified = df_cr[df_cr["__account_id"].isna()].copy()

acct_counts  = df_identified["__account_id"].value_counts()
dup_accounts = acct_counts[acct_counts > 1]
df_identified["__is_dup"] = df_identified["__account_id"].isin(dup_accounts.index)

# ══════════════════════════════════════════════════════════════
# SUMMARY METRICS
# ══════════════════════════════════════════════════════════════
st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Rows",           f"{len(df_raw):,}")
m2.metric("CR Transactions",      f"{len(df_cr):,}")
m3.metric("IDs Extracted",        f"{df_identified['__account_id'].nunique():,}")
m4.metric("Repeat Account IDs",   f"{len(dup_accounts):,}")
m5.metric("Flagged Transactions", f"{df_identified['__is_dup'].sum():,}")
st.markdown("---")

# Breakdown by type
with st.expander("📊 Extraction breakdown by transaction type"):
    bd = df_cr.groupby("__txn_type").agg(
        Total=("__txn_type", "count")
    ).reset_index()
    ibd = df_identified.groupby("__txn_type").size().reset_index(name="ID Extracted")
    bd  = bd.merge(ibd, on="__txn_type", how="left").fillna(0)
    bd["ID Extracted"]    = bd["ID Extracted"].astype(int)
    bd["Skipped (no ID)"] = bd["Total"] - bd["ID Extracted"]
    bd.columns            = ["Txn Type", "Total CR", "ID Extracted", "Skipped (no ID)"]
    st.dataframe(bd, use_container_width=True, hide_index=True)
    st.caption("IMPS/MMT: sender name used as identifier (e.g. 'FAROOQUE B'). Flagged for human review since names may be truncated — not as reliable as a UPI VPA or NEFT account number.")

# Session state
if "group_decisions" not in st.session_state:
    st.session_state.group_decisions = {}

display_cols = list(df_raw.columns)

# ══════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["🚨 Duplicate Accounts", "📋 All CR Transactions", "❓ Unidentified Rows", "📥 Export"])

# ── TAB 1: Duplicates ─────────────────────────────────────────
with tab1:
    if dup_accounts.empty:
        st.success("🎉 No duplicate sender account IDs found in CR transactions!")
    else:
        st.markdown(f"**{len(dup_accounts)}** account ID(s) with more than one CR transaction. "
                    "Expand a group to review and mark your decision.")

        for acct_id, count in dup_accounts.items():
            group_df  = df_identified[df_identified["__account_id"] == acct_id]
            txn_types = group_df["__txn_type"].unique().tolist()
            widget_key = f"dec_{acct_id}"

            # Read from the widget key directly so the label updates immediately
            # without waiting for the next full rerun cycle
            current = st.session_state.get(widget_key,
                      st.session_state.group_decisions.get(acct_id, "⏳ Pending"))

            display_id = acct_id.replace("upi:", "").replace("acct:", "").replace("imps_name:", "⚠️ ")
            label = f"🔑 {display_id}  ({', '.join(txn_types)})  ·  {count} transactions  [{current}]"

            with st.expander(label, expanded=False):
                st.dataframe(
                    group_df[display_cols].reset_index(drop=True),
                    use_container_width=True,
                    height=min(300, 60 + count * 38)
                )
                new_dec = st.selectbox(
                    "Decision for this account:",
                    options=["⏳ Pending", "✅ Legitimate", "🚫 Flag as Duplicate"],
                    index=["⏳ Pending", "✅ Legitimate", "🚫 Flag as Duplicate"].index(current),
                    key=widget_key
                )
                # Sync back to group_decisions so other parts of the app can read it
                st.session_state.group_decisions[acct_id] = new_dec

        st.markdown("---")
        st.markdown("### 📊 Review Progress")
        decisions = st.session_state.group_decisions
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Total Groups", len(dup_accounts))
        p2.metric("Pending",      sum(1 for v in decisions.values() if v == "⏳ Pending"))
        p3.metric("Legitimate",   sum(1 for v in decisions.values() if v == "✅ Legitimate"))
        p4.metric("Flagged",      sum(1 for v in decisions.values() if "Duplicate" in v))

# ── TAB 2: All CR Transactions ────────────────────────────────
with tab2:
    filter_opt = st.radio("Show:", ["All CR", "Flagged (repeat IDs)", "Clean (unique IDs)", "No ID extracted"], horizontal=True)

    view = df_cr.copy()
    view["Account ID"]  = view["__account_id"].fillna("—").str.replace("upi:", "").str.replace("acct:", "")
    view["Txn Type"]    = view["__txn_type"]
    view["Repeat Flag"] = view.apply(
        lambda r: "🔴 REPEAT" if r["__account_id"] in dup_accounts.index
        else ("🟢 UNIQUE" if pd.notna(r["__account_id"]) else "⚪ NO ID"),
        axis=1
    )
    view["Decision"] = view["__account_id"].map(
        lambda s: st.session_state.group_decisions.get(s, "—") if pd.notna(s) else "—"
    )

    if filter_opt == "Flagged (repeat IDs)":
        view = view[view["__account_id"].isin(dup_accounts.index)]
    elif filter_opt == "Clean (unique IDs)":
        view = view[view["__account_id"].notna() & ~view["__account_id"].isin(dup_accounts.index)]
    elif filter_opt == "No ID extracted":
        view = view[view["__account_id"].isna()]

    show_cols = display_cols + ["Account ID", "Txn Type", "Repeat Flag", "Decision"]
    st.dataframe(view[show_cols].reset_index(drop=True), use_container_width=True, height=500)

# ── TAB 3: Unidentified ───────────────────────────────────────
with tab3:
    st.markdown(f"### {len(df_unidentified):,} CR transactions — no identifier extractable")
    st.caption(
        "Transactions where no sender name, VPA, or account number could be found "
        "(e.g. ATM, bank charges, reversals, or unusual formats)."
    )
    if not df_unidentified.empty:
        show = df_unidentified[display_cols + ["__txn_type"]].rename(columns={"__txn_type": "Txn Type"})
        st.dataframe(show.reset_index(drop=True), use_container_width=True, height=450)

# ── TAB 4: Export ─────────────────────────────────────────────
with tab4:
    st.markdown("### 📥 Download Options")

    def to_excel_bytes(data: pd.DataFrame, sheet="Sheet1") -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            data.to_excel(writer, index=False, sheet_name=sheet)
            ws = writer.sheets[sheet]
            for col in ws.columns:
                w = max((len(str(c.value or "")) for c in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(w + 4, 55)
        return buf.getvalue()

    # Build enriched export frame
    export = df_cr.copy()
    export["Account ID"]  = export["__account_id"].fillna("").str.replace("upi:", "").str.replace("acct:", "").str.replace("imps_name:", "[IMPS] ")
    export["Txn Type"]    = export["__txn_type"]
    export["Repeat Flag"] = export["__account_id"].apply(
        lambda s: "REPEAT" if s in dup_accounts.index else ("UNIQUE" if pd.notna(s) and s != "" else "NO_ID")
    )
    export["Decision"]    = export["__account_id"].map(
        lambda s: st.session_state.group_decisions.get(s, "") if pd.notna(s) else ""
    )
    export_cols = display_cols + ["Account ID", "Txn Type", "Repeat Flag", "Decision"]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 🔴 Repeat Accounts Only")
        dup_exp = export[export["__account_id"].isin(dup_accounts.index)][export_cols]
        st.info(f"{len(dup_exp)} transactions")
        st.download_button("⬇️ Download", data=to_excel_bytes(dup_exp, "RepeatAccounts"),
                           file_name=f"repeat_accounts_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

    with col2:
        st.markdown("#### 🚫 Flagged as Duplicate")
        flagged_ids = [s for s, d in st.session_state.group_decisions.items() if "Duplicate" in d]
        flag_exp    = export[export["__account_id"].isin(flagged_ids)][export_cols]
        st.info(f"{len(flag_exp)} transactions")
        if flag_exp.empty:
            st.warning("No groups flagged yet — go to Tab 1.")
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

    # Summary table
    st.markdown("---")
    st.markdown("#### 📊 All Repeat Account IDs")
    if not dup_accounts.empty:
        rows = []
        for acct_id, cnt in dup_accounts.items():
            types = df_identified[df_identified["__account_id"] == acct_id]["__txn_type"].unique().tolist()
            rows.append({
                "Account ID":        acct_id.replace("upi:", "").replace("acct:", "").replace("imps_name:", ""),
                "ID Type":           "UPI VPA" if acct_id.startswith("upi:") else ("NEFT/RTGS Acct#" if acct_id.startswith("acct:") else "IMPS Name ⚠️"),
                "Txn Type":          ", ".join(types),
                "Count":             cnt,
                "Decision":          st.session_state.group_decisions.get(acct_id, "⏳ Pending"),
            })
        summary = pd.DataFrame(rows).sort_values("Count", ascending=False).reset_index(drop=True)
        st.dataframe(summary, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download Summary",
                           data=to_excel_bytes(summary, "Summary"),
                           file_name=f"summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")