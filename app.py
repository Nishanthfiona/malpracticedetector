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
st.markdown('<div class="sub-header">Upload your bank statement to find senders who paid multiple times.</div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────
# SENDER EXTRACTION
# ──────────────────────────────────────────────
# These are generic words that appear in descriptions but are NOT real sender IDs
SKIP_WORDS = re.compile(
    r'^(UPI|IMPS|MMT|NEFT|RTGS|INFT|NACH|ECS|ATM|CHQ|CLG|INT|REVERSAL|'
    r'PAYMENT FROM PH|PAYMENT FR|GOOGLE ADS|BPAY|CHARGES|FEE|TAX|GST|'
    r'HDFC|SBI|ICICI|AXIS|KOTAK|PNB|BOB|CANARA|FEDERAL|IDFC|YES BANK|'
    r'STATE BANK|BANK OF BARODA|UNION BANK|INDIAN BANK|PUNJAB NATIONAL|'
    r'HDFC BANK|AXIS BANK|FEDERAL BANK|KOTAK BANK|PAYTM|PHONEPE|GPAY|'
    r'AMAZON|FLIPKART|SWIGGY|ZOMATO|RAZORPAY|CASHFREE|\d+)$',
    re.IGNORECASE
)

def extract_sender_id(description: str) -> str | None:
    """
    Extract a unique sender identifier from a transaction description.
    Returns None for system/bank/generic transactions (not real person senders).
    """
    if not isinstance(description, str) or not description.strip():
        return None

    desc = description.strip()

    # 1. UPI VPA — most reliable: e.g. sruthycs200-2@okhdfcbank, 9912977860-2@ybl
    vpa = re.search(r'([\w.\-]+@[\w]+)', desc)
    if vpa:
        return vpa.group(1).lower()

    # 2. UPI without VPA — parse name from "UPI/REF/NAME/..."
    if re.match(r'UPI/', desc, re.IGNORECASE):
        parts = [p.strip() for p in desc.split('/')]
        for part in parts[1:]:
            if part and not SKIP_WORDS.match(part) and not part.isdigit() and len(part) > 3:
                return part.upper()
        return None  # Could not find real sender in UPI

    # 3. IMPS / MMT — "MMT/IMPS/refno/desc/SENDER NAME/BANK"
    if re.search(r'\b(IMPS|MMT)\b', desc, re.IGNORECASE):
        parts = [p.strip() for p in desc.split('/')]
        candidates = [p for p in parts
                      if p and not p.isdigit()
                      and not SKIP_WORDS.match(p)
                      and len(p) > 3]
        if candidates:
            return candidates[-1].upper()
        return None

    # 4. NEFT / RTGS / INFT — try to get sender name
    if re.search(r'\b(NEFT|RTGS|INFT)\b', desc, re.IGNORECASE):
        parts = [p.strip() for p in re.split(r'[/\-|]', desc)]
        candidates = [p for p in parts
                      if p and not p.isdigit()
                      and not SKIP_WORDS.match(p)
                      and len(p) > 4]
        if candidates:
            return candidates[-1].upper()
        return None  # INFT alone is not a useful sender

    # 5. Everything else (ATM, charges, etc.) — skip
    return None


# ──────────────────────────────────────────────
# FILE UPLOAD
# ──────────────────────────────────────────────
uploaded_file = st.file_uploader("📂 Upload Excel or CSV file", type=["xlsx", "xls", "csv"])

if not uploaded_file:
    st.info("Upload your bank statement Excel/CSV file to begin.")
    st.markdown("""
    **What this tool does:**
    - Extracts the **actual sender account/ID** from UPI, IMPS, NEFT, RTGS descriptions
    - Groups transactions by the same sender to flag repeat payers
    - Lets you mark each group as Legitimate or Duplicate
    - Exports flagged transactions to Excel
    """)
    st.stop()

# Load file
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

def best_match(candidates):
    for c in candidates:
        for col in all_cols:
            if c.lower() in col.lower():
                return col
    return all_cols[0]

with st.expander("⚙️ Column Settings", expanded=False):
    c1, c2, c3 = st.columns(3)
    desc_col   = c1.selectbox("Description column", all_cols,
                               index=all_cols.index(best_match(["description","desc","narration","particulars"])))
    amount_col = c2.selectbox("Amount column (optional)", ["(none)"] + all_cols, index=0)
    date_col   = c3.selectbox("Date column (optional)", ["(none)"] + all_cols, index=0)

# ── Extract sender IDs ──
df = df_raw.copy()
df["__sender_id"] = df[desc_col].apply(extract_sender_id)

df_with_sender = df[df["__sender_id"].notna()].copy()

sender_counts = df_with_sender["__sender_id"].value_counts()
dup_senders   = sender_counts[sender_counts > 1]

df_with_sender["__is_dup"] = df_with_sender["__sender_id"].isin(dup_senders.index)

# ──────────────────────────────────────────────
# SUMMARY METRICS
# ──────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Transactions", f"{len(df):,}")
m2.metric("Identifiable Senders", f"{df_with_sender['__sender_id'].nunique():,}")
m3.metric("Repeat Senders", f"{len(dup_senders):,}")
m4.metric("Flagged Transactions", f"{df_with_sender['__is_dup'].sum():,}")
st.markdown("---")

# Session state for group-level decisions
if "group_decisions" not in st.session_state:
    st.session_state.group_decisions = {}

display_cols = list(df_raw.columns)

# ──────────────────────────────────────────────
# TABS
# ──────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["🚨 Duplicate Senders", "📋 All Transactions", "📥 Export"])

# ── TAB 1: Duplicate Senders ──
with tab1:
    if dup_senders.empty:
        st.success("🎉 No repeat senders found!")
    else:
        st.markdown(f"**{len(dup_senders)}** sender(s) paid more than once. "
                    "Expand each group to review and mark a decision.")

        for sender, count in dup_senders.items():
            group_df   = df_with_sender[df_with_sender["__sender_id"] == sender][display_cols]
            current    = st.session_state.group_decisions.get(sender, "⏳ Pending")

            label = f"👤 {sender}  —  {count} transactions  [{current}]"
            with st.expander(label, expanded=False):
                st.dataframe(group_df.reset_index(drop=True), use_container_width=True,
                             height=min(250, 55 + count * 38))

                new_dec = st.selectbox(
                    "Decision for this sender:",
                    options=["⏳ Pending", "✅ Legitimate", "🚫 Mark as Duplicate"],
                    index=["⏳ Pending", "✅ Legitimate", "🚫 Mark as Duplicate"].index(current),
                    key=f"dec_{sender}"
                )
                st.session_state.group_decisions[sender] = new_dec

        st.markdown("---")
        st.markdown("### 📊 Review Progress")
        decisions = st.session_state.group_decisions
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Total Groups",  len(dup_senders))
        p2.metric("Pending",       sum(1 for v in decisions.values() if v == "⏳ Pending"))
        p3.metric("Legitimate",    sum(1 for v in decisions.values() if v == "✅ Legitimate"))
        p4.metric("Marked Dup",    sum(1 for v in decisions.values() if v == "🚫 Mark as Duplicate"))

# ── TAB 2: All Transactions ──
with tab2:
    filter_opt = st.radio("Show:", ["All", "Flagged (repeat senders)", "Clean only"], horizontal=True)

    view = df_with_sender.copy()
    view["Sender ID"]      = view["__sender_id"]
    view["Repeat Sender"]  = view["__is_dup"].map({True: "🔴 YES", False: "🟢 NO"})
    view["Group Decision"] = view["__sender_id"].map(
        lambda s: st.session_state.group_decisions.get(s, "⏳ Pending")
    )

    if filter_opt == "Flagged (repeat senders)":
        view = view[view["__is_dup"]]
    elif filter_opt == "Clean only":
        view = view[~view["__is_dup"]]

    show_cols = display_cols + ["Sender ID", "Repeat Sender", "Group Decision"]
    st.dataframe(view[show_cols].reset_index(drop=True), use_container_width=True, height=500)

# ── TAB 3: Export ──
with tab3:
    st.markdown("### 📥 Download Options")

    def to_excel_bytes(data: pd.DataFrame, sheet="Sheet1") -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            data.to_excel(writer, index=False, sheet_name=sheet)
            ws = writer.sheets[sheet]
            for col in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)
        return buf.getvalue()

    export_base = df_with_sender.copy()
    export_base["Sender ID"]      = export_base["__sender_id"]
    export_base["Repeat Sender"]  = export_base["__is_dup"].map({True: "YES", False: "NO"})
    export_base["Group Decision"] = export_base["__sender_id"].map(
        lambda s: st.session_state.group_decisions.get(s, "Pending")
    )
    export_cols = display_cols + ["Sender ID", "Repeat Sender", "Group Decision"]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 🔴 Repeat Senders Only")
        dup_export = export_base[export_base["__is_dup"]][export_cols]
        st.info(f"{len(dup_export)} transactions")
        st.download_button("⬇️ Download", data=to_excel_bytes(dup_export, "Duplicates"),
                           file_name=f"duplicates_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

    with col2:
        st.markdown("#### 🚫 Marked as Duplicate")
        marked_senders = [s for s, d in st.session_state.group_decisions.items()
                          if d == "🚫 Mark as Duplicate"]
        marked_export = export_base[export_base["__sender_id"].isin(marked_senders)][export_cols]
        st.info(f"{len(marked_export)} transactions")
        if marked_export.empty:
            st.warning("No groups marked yet. Go to Tab 1.")
        else:
            st.download_button("⬇️ Download", data=to_excel_bytes(marked_export, "MarkedDuplicates"),
                               file_name=f"marked_dup_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)

    with col3:
        st.markdown("#### 📋 Full Report")
        st.info(f"{len(export_base)} transactions")
        st.download_button("⬇️ Download", data=to_excel_bytes(export_base[export_cols], "FullReport"),
                           file_name=f"full_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

    st.markdown("---")
    st.markdown("#### 📊 Repeat Sender Summary Table")
    if not dup_senders.empty:
        summary = pd.DataFrame({
            "Sender ID":         dup_senders.index,
            "Transaction Count": dup_senders.values,
            "Decision":          [st.session_state.group_decisions.get(s, "⏳ Pending")
                                   for s in dup_senders.index]
        }).sort_values("Transaction Count", ascending=False).reset_index(drop=True)
        st.dataframe(summary, use_container_width=True)
        st.download_button("⬇️ Download Summary",
                           data=to_excel_bytes(summary, "Summary"),
                           file_name=f"dup_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")