import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime

st.set_page_config(page_title="Duplicate Transaction Detector", layout="wide", page_icon="🔍")

st.markdown("""
<style>
.main-header { font-size: 2rem; font-weight: 700; color: #1e3a5f; }
.sub-header { color: #666; font-size: 1rem; margin-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🔍 Duplicate Transaction Detector</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Finds CR transactions where the same sender account ID appears more than once.</div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────
# ACCOUNT ID EXTRACTION — strict rules only
# ──────────────────────────────────────────────
def extract_account_id(description: str) -> str | None:
    """
    Extract ONLY a reliable unique sender account identifier.
    
    Rules (in priority order):
    
    1. UPI VPA — full: name@bank  (e.g. sruthycs200-2@okhdfcbank, 9912977860-2@ybl)
       Also handles TRUNCATED VPAs ending with '@' — use the prefix as the ID.
       These are the ONLY reliable unique IDs for UPI transactions.

    2. NEFT/RTGS — extract the numeric account number (10–18 digits) that appears
       just before the IFSC code (pattern: digits-IFSC). This is the sender's
       account number, which is unique and reliable.

    3. IMPS/MMT — NO reliable account ID available in standard descriptions.
       The ref number is unique per transaction (not a sender ID).
       The sender name is often truncated and not unique enough.
       → Return None (skip IMPS for duplicate detection).

    4. Everything else → None.
    """
    if not isinstance(description, str) or not description.strip():
        return None

    desc = description.strip()

    # ── 1. UPI VPA ──
    # Full VPA: word@word  (e.g. sruthycs200-2@okhdfcbank)
    full_vpa = re.search(r'([\w.\-]+@[\w]{2,})', desc)
    if full_vpa:
        return full_vpa.group(1).lower()

    # Truncated VPA ending with '@' (e.g. "sruthycs200-2@")
    # Appears when bank truncates the description
    truncated_vpa = re.search(r'([\w.\-]{4,}@)(?=[/\s]|$)', desc)
    if truncated_vpa:
        # Use the part before '@' as the ID (it's the unique username)
        username = truncated_vpa.group(1).rstrip('@').lower()
        return f"upi:{username}"

    # ── 2. NEFT / RTGS — extract sender account number ──
    # Pattern: long numeric string (10-18 digits) followed by IFSC code
    # e.g. "12552100113212-FDRL0000037" or "99982102028058-FDRL0000037"
    if re.search(r'\b(NEFT|RTGS)\b', desc, re.IGNORECASE):
        # Look for: digits (10-18) followed by dash/space and IFSC (4 alpha + 7 alphanum)
        acct_match = re.search(r'(\d{10,18})[-\s]([A-Z]{4}[0-9A-Z]{7})', desc)
        if acct_match:
            return f"acct:{acct_match.group(1)}"
        # Fallback: just a standalone 10-18 digit number (less reliable but better than nothing)
        num_match = re.search(r'\b(\d{10,18})\b', desc)
        if num_match:
            return f"acct:{num_match.group(1)}"

    # ── 3. IMPS / MMT — skip (no reliable account ID) ──
    # Do NOT extract bank name, sender name, or reference number.

    # ── 4. Everything else — skip ──
    return None


# ──────────────────────────────────────────────
# FILE UPLOAD
# ──────────────────────────────────────────────
uploaded_file = st.file_uploader("📂 Upload Excel or CSV file", type=["xlsx", "xls", "csv"])

if not uploaded_file:
    st.info("Upload your bank statement Excel/CSV file to begin.")
    st.markdown("""
    **What this tool detects as duplicate:**
    - **UPI:** Same VPA (e.g. `sruthycs200-2@okhdfcbank`) appearing in multiple CR transactions
    - **NEFT/RTGS:** Same sender account number appearing in multiple CR transactions
    - **IMPS:** Skipped — descriptions don't contain a reliable unique sender account ID
    
    Only **CR (credit) transactions** are checked.
    """)
    st.stop()

# Load
try:
    if uploaded_file.name.endswith(".csv"):
        df_raw = pd.read_csv(uploaded_file)
    else:
        df_raw = pd.read_excel(uploaded_file)
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

st.success(f"✅ Loaded **{len(df_raw):,}** rows from `{uploaded_file.name}`")

all_cols = list(df_raw.columns)

def best_match(candidates, default=None):
    for c in candidates:
        for col in all_cols:
            if c.lower() in col.lower():
                return col
    return default or all_cols[0]

with st.expander("⚙️ Column Settings", expanded=False):
    c1, c2, c3 = st.columns(3)
    desc_col  = c1.selectbox("Description column", all_cols,
                              index=all_cols.index(best_match(["description","desc","narration","particulars"])))
    crdr_col  = c2.selectbox("CR/DR column", ["(none)"] + all_cols,
                              index=([0] + all_cols).index(best_match(["cr/dr","crdr","type","dr/cr"], "(none)")))
    date_col  = c3.selectbox("Date column (optional)", ["(none)"] + all_cols, index=0)

# ── Filter CR only ──
df = df_raw.copy()

if crdr_col != "(none)":
    cr_mask = df[crdr_col].astype(str).str.strip().str.upper().isin(["CR", "CREDIT", "C"])
    df_cr   = df[cr_mask].copy()
    df_dr   = df[~cr_mask].copy()
    st.info(f"Filtered to **{len(df_cr):,} CR transactions** (excluded {len(df_dr):,} DR/other rows)")
else:
    df_cr = df.copy()
    df_dr = pd.DataFrame()
    st.warning("No CR/DR column selected — processing all rows. Select the CR/DR column above for accurate results.")

# ── Extract account IDs ──
df_cr["__account_id"]  = df_cr[desc_col].apply(extract_account_id)
df_cr["__txn_type"]    = df_cr[desc_col].apply(lambda d:
    "UPI"  if re.search(r'\bUPI\b', str(d), re.IGNORECASE) else
    "NEFT" if re.search(r'\bNEFT\b', str(d), re.IGNORECASE) else
    "RTGS" if re.search(r'\bRTGS\b', str(d), re.IGNORECASE) else
    "IMPS" if re.search(r'\bIMPS\b|MMT', str(d), re.IGNORECASE) else
    "OTHER"
)

# Rows with a detected account ID
df_identified  = df_cr[df_cr["__account_id"].notna()].copy()
df_unidentified = df_cr[df_cr["__account_id"].isna()].copy()

# Find duplicates
acct_counts  = df_identified["__account_id"].value_counts()
dup_accounts = acct_counts[acct_counts > 1]
df_identified["__is_dup"] = df_identified["__account_id"].isin(dup_accounts.index)

# ──────────────────────────────────────────────
# SUMMARY
# ──────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Rows",         f"{len(df_raw):,}")
m2.metric("CR Transactions",    f"{len(df_cr):,}")
m3.metric("IDs Extracted",      f"{df_identified['__account_id'].nunique():,}")
m4.metric("Repeat Account IDs", f"{len(dup_accounts):,}")
m5.metric("Flagged Txns",       f"{df_identified['__is_dup'].sum():,}")
st.markdown("---")

# Breakdown by type
with st.expander("📊 Breakdown by Transaction Type"):
    breakdown = df_cr.groupby("__txn_type").size().reset_index(name="Count")
    identified_by_type = df_identified.groupby("__txn_type").size().reset_index(name="With Account ID")
    breakdown = breakdown.merge(identified_by_type, on="__txn_type", how="left").fillna(0)
    breakdown["With Account ID"] = breakdown["With Account ID"].astype(int)
    breakdown["Skipped (no ID)"] = breakdown["Count"] - breakdown["With Account ID"]
    st.dataframe(breakdown, use_container_width=True)
    st.caption("IMPS transactions are skipped — their descriptions don't contain a reliable unique sender account ID (only bank names and truncated sender names).")

# Session state
if "group_decisions" not in st.session_state:
    st.session_state.group_decisions = {}

display_cols = list(df_raw.columns)

# ──────────────────────────────────────────────
# TABS
# ──────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["🚨 Duplicate Accounts", "📋 All CR Transactions", "❓ Unidentified", "📥 Export"])

# ── TAB 1: Duplicates ──
with tab1:
    if dup_accounts.empty:
        st.success("🎉 No duplicate sender account IDs found in CR transactions!")
    else:
        st.markdown(f"**{len(dup_accounts)}** account ID(s) appear in more than one CR transaction.")
        st.caption("Each entry below is a real unique account ID (UPI VPA or NEFT account number).")

        for acct_id, count in dup_accounts.items():
            group_df  = df_identified[df_identified["__account_id"] == acct_id][display_cols + ["__txn_type"]]
            current   = st.session_state.group_decisions.get(acct_id, "⏳ Pending")
            txn_types = group_df["__txn_type"].unique().tolist()

            label = f"🔑 {acct_id}  ({', '.join(txn_types)})  —  {count} transactions  [{current}]"
            with st.expander(label, expanded=False):
                st.dataframe(
                    group_df.drop(columns=["__txn_type"]).reset_index(drop=True),
                    use_container_width=True,
                    height=min(280, 60 + count * 38)
                )
                new_dec = st.selectbox(
                    "Decision:",
                    options=["⏳ Pending", "✅ Legitimate (same person, multiple payments)", "🚫 Flag as Duplicate"],
                    index=["⏳ Pending", "✅ Legitimate (same person, multiple payments)", "🚫 Flag as Duplicate"].index(current),
                    key=f"dec_{acct_id}"
                )
                st.session_state.group_decisions[acct_id] = new_dec

        st.markdown("---")
        decisions = st.session_state.group_decisions
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Total Groups",  len(dup_accounts))
        p2.metric("Pending",       sum(1 for v in decisions.values() if v == "⏳ Pending"))
        p3.metric("Legitimate",    sum(1 for v in decisions.values() if "Legitimate" in v))
        p4.metric("Flagged",       sum(1 for v in decisions.values() if "Duplicate" in v))

# ── TAB 2: All CR Transactions ──
with tab2:
    filter_opt = st.radio("Show:", ["All CR", "Flagged (repeat account IDs)", "Clean"], horizontal=True)

    view = df_identified.copy()
    view["Account ID"]     = view["__account_id"]
    view["Txn Type"]       = view["__txn_type"]
    view["Repeat Flag"]    = view["__is_dup"].map({True: "🔴 REPEAT", False: "🟢 UNIQUE"})
    view["Group Decision"] = view["__account_id"].map(
        lambda s: st.session_state.group_decisions.get(s, "⏳ Pending")
    )

    if filter_opt == "Flagged (repeat account IDs)":
        view = view[view["__is_dup"]]
    elif filter_opt == "Clean":
        view = view[~view["__is_dup"]]

    show_cols = display_cols + ["Account ID", "Txn Type", "Repeat Flag", "Group Decision"]
    st.dataframe(view[show_cols].reset_index(drop=True), use_container_width=True, height=500)

# ── TAB 3: Unidentified (IMPS etc.) ──
with tab3:
    st.markdown(f"### {len(df_unidentified):,} CR transactions where no account ID could be extracted")
    st.caption(
        "These are mostly IMPS/MMT transactions. Their descriptions only contain bank names and "
        "truncated sender names — not unique account IDs — so duplicate detection isn't possible for these. "
        "If you need IMPS duplicate detection, you would need account numbers from your core banking system."
    )
    if not df_unidentified.empty:
        show = df_unidentified[display_cols + ["__txn_type"]].copy()
        show = show.rename(columns={"__txn_type": "Txn Type"})
        st.dataframe(show.reset_index(drop=True), use_container_width=True, height=400)

# ── TAB 4: Export ──
with tab4:
    st.markdown("### 📥 Download Options")

    def to_excel_bytes(data: pd.DataFrame, sheet="Sheet1") -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            data.to_excel(writer, index=False, sheet_name=sheet)
            ws = writer.sheets[sheet]
            for col in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 55)
        return buf.getvalue()

    # Enrich export
    export_base = df_identified.copy()
    export_base["Account ID"]     = export_base["__account_id"]
    export_base["Txn Type"]       = export_base["__txn_type"]
    export_base["Repeat Flag"]    = export_base["__is_dup"].map({True: "REPEAT", False: "UNIQUE"})
    export_base["Group Decision"] = export_base["__account_id"].map(
        lambda s: st.session_state.group_decisions.get(s, "Pending")
    )
    export_cols = display_cols + ["Account ID", "Txn Type", "Repeat Flag", "Group Decision"]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 🔴 Repeat Accounts Only")
        dup_export = export_base[export_base["__is_dup"]][export_cols]
        st.info(f"{len(dup_export)} transactions")
        st.download_button("⬇️ Download", data=to_excel_bytes(dup_export, "RepeatAccounts"),
                           file_name=f"repeat_accounts_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

    with col2:
        st.markdown("#### 🚫 Flagged as Duplicate")
        flagged_ids   = [s for s, d in st.session_state.group_decisions.items() if "Duplicate" in d]
        flagged_export = export_base[export_base["__account_id"].isin(flagged_ids)][export_cols]
        st.info(f"{len(flagged_export)} transactions")
        if flagged_export.empty:
            st.warning("No groups flagged yet — go to Tab 1.")
        else:
            st.download_button("⬇️ Download", data=to_excel_bytes(flagged_export, "Flagged"),
                               file_name=f"flagged_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)

    with col3:
        st.markdown("#### 📋 Full CR Report")
        st.info(f"{len(export_base)} CR transactions with IDs")
        st.download_button("⬇️ Download", data=to_excel_bytes(export_base[export_cols], "FullCR"),
                           file_name=f"full_cr_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

    st.markdown("---")
    st.markdown("#### 📊 Repeat Account Summary")
    if not dup_accounts.empty:
        summary_rows = []
        for acct_id, count in dup_accounts.items():
            types = df_identified[df_identified["__account_id"] == acct_id]["__txn_type"].unique().tolist()
            summary_rows.append({
                "Account ID":        acct_id,
                "Txn Type":          ", ".join(types),
                "Transaction Count": count,
                "Decision":          st.session_state.group_decisions.get(acct_id, "⏳ Pending")
            })
        summary = pd.DataFrame(summary_rows).sort_values("Transaction Count", ascending=False).reset_index(drop=True)
        st.dataframe(summary, use_container_width=True)
        st.download_button("⬇️ Download Summary",
                           data=to_excel_bytes(summary, "Summary"),
                           file_name=f"dup_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")