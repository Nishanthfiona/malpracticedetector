import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime

st.set_page_config(page_title="Duplicate Transaction Detector", layout="wide", page_icon="🔍")

# --- CSS Styling ---
st.markdown("""
<style>
    .main-header { font-size: 2rem; font-weight: 700; color: #1e3a5f; margin-bottom: 0.2rem; }
    .sub-header { color: #555; font-size: 1rem; margin-bottom: 1.5rem; }
    .stat-box { background: #f0f4ff; border-left: 5px solid #3b82f6; padding: 1rem; border-radius: 8px; }
    .dup-box { background: #fff5f5; border-left: 5px solid #ef4444; padding: 1rem; border-radius: 8px; }
    .ok-box { background: #f0fff4; border-left: 5px solid #22c55e; padding: 1rem; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🔍 Duplicate Transaction Detector</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Upload your bank statement Excel file to identify duplicate senders and flag suspicious transactions.</div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────
# HELPER: Extract sender ID from description
# ──────────────────────────────────────────────
def extract_sender_id(description: str) -> str:
    """
    Extract a normalised sender identifier from the description string.
    Handles UPI, IMPS/MMT, NEFT, RTGS, and generic formats.
    """
    if not isinstance(description, str):
        return "UNKNOWN"

    desc = description.strip()

    # UPI: look for VPA (xxx@yyy) or a name segment
    upi_vpa = re.search(r'[\w.\-]+@[\w]+', desc)
    if upi_vpa:
        return upi_vpa.group(0).lower()

    # IMPS / MMT: sender name usually after last '/'
    if re.search(r'(IMPS|MMT)', desc, re.IGNORECASE):
        parts = desc.split('/')
        # Try to find a name-like part (non-numeric, >3 chars)
        for part in reversed(parts):
            part = part.strip()
            if part and not part.isdigit() and len(part) > 3:
                return part.upper()

    # NEFT / RTGS: typically "NEFT/reference/SENDER NAME/..."
    if re.search(r'(NEFT|RTGS)', desc, re.IGNORECASE):
        parts = desc.split('/')
        for part in reversed(parts):
            part = part.strip()
            if part and not part.isdigit() and len(part) > 3:
                return part.upper()

    # Cheque: use ChequeNo if available (handled outside)
    # Fallback: first meaningful token
    tokens = re.split(r'[/|\\,]', desc)
    for tok in tokens:
        tok = tok.strip()
        if tok and len(tok) > 3 and not tok.isdigit():
            return tok.upper()

    return desc[:30].upper()


# ──────────────────────────────────────────────
# FILE UPLOAD
# ──────────────────────────────────────────────
uploaded_file = st.file_uploader("📂 Upload Excel / CSV file", type=["xlsx", "xls", "csv"])

if uploaded_file:
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        st.stop()

    st.success(f"✅ Loaded **{len(df):,}** rows from `{uploaded_file.name}`")

    # ── Column mapping UI ──
    with st.expander("⚙️ Map your columns (auto-detected)", expanded=False):
        cols = ["(none)"] + list(df.columns)
        c1, c2, c3 = st.columns(3)
        # Auto-detect common column names
        def best_guess(candidates):
            for c in candidates:
                for col in df.columns:
                    if c.lower() in col.lower():
                        return col
            return cols[1]

        desc_col = c1.selectbox("Description column", options=list(df.columns),
                                index=list(df.columns).index(best_guess(["description","desc","narration","particulars"])))
        date_col = c2.selectbox("Date column (optional)", options=cols,
                                index=0)
        txn_col  = c3.selectbox("Transaction ID column (optional)", options=cols,
                                index=0)

    # ── Build sender IDs ──
    df["_sender_id"] = df[desc_col].apply(extract_sender_id)

    # ── Find duplicates ──
    dup_counts = df["_sender_id"].value_counts()
    dup_senders = dup_counts[dup_counts > 1].index.tolist()

    df["_is_duplicate_sender"] = df["_sender_id"].isin(dup_senders)
    df["_review_status"] = "Pending"

    # ──────────────────────────────────────────────
    # SUMMARY STATS
    # ──────────────────────────────────────────────
    st.markdown("---")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total Transactions", f"{len(df):,}")
    s2.metric("Unique Senders", f"{df['_sender_id'].nunique():,}")
    s3.metric("Duplicate Senders", f"{len(dup_senders):,}")
    s4.metric("Flagged Transactions", f"{df['_is_duplicate_sender'].sum():,}")

    st.markdown("---")

    # ──────────────────────────────────────────────
    # SESSION STATE for review decisions
    # ──────────────────────────────────────────────
    if "review_map" not in st.session_state:
        st.session_state.review_map = {}  # index -> "Legitimate" | "Duplicate"

    # ──────────────────────────────────────────────
    # TAB LAYOUT
    # ──────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(["🚨 Duplicates for Review", "📋 All Transactions", "📥 Export"])

    # ── TAB 1: Duplicates ──
    with tab1:
        if not dup_senders:
            st.success("🎉 No duplicate senders found!")
        else:
            st.markdown(f"### Found **{len(dup_senders)}** sender(s) who paid more than once")

            for sender in dup_senders:
                sender_rows = df[df["_sender_id"] == sender].copy()
                count = len(sender_rows)

                with st.expander(f"👤 **{sender}** — {count} transactions", expanded=True):
                    # Show the transactions table
                    display_cols = [c for c in df.columns if not c.startswith("_")]
                    st.dataframe(sender_rows[display_cols].reset_index(drop=True), use_container_width=True)

                    st.markdown("**Mark each transaction:**")
                    for idx in sender_rows.index:
                        row = df.loc[idx]
                        label = f"Txn #{idx+1} | {str(row[desc_col])[:80]}"
                        current = st.session_state.review_map.get(idx, "Pending")
                        decision = st.radio(
                            label,
                            options=["Pending", "✅ Legitimate", "🚫 Duplicate"],
                            index=["Pending", "✅ Legitimate", "🚫 Duplicate"].index(current),
                            horizontal=True,
                            key=f"review_{idx}"
                        )
                        st.session_state.review_map[idx] = decision

            # Live review summary
            st.markdown("---")
            st.markdown("### 📊 Review Progress")
            total_flagged = df["_is_duplicate_sender"].sum()
            reviewed = sum(1 for v in st.session_state.review_map.values() if v != "Pending")
            legit = sum(1 for v in st.session_state.review_map.values() if v == "✅ Legitimate")
            dupes = sum(1 for v in st.session_state.review_map.values() if v == "🚫 Duplicate")

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Total Flagged", total_flagged)
            r2.metric("Reviewed", reviewed)
            r3.metric("Marked Legitimate", legit)
            r4.metric("Marked Duplicate", dupes)

    # ── TAB 2: All Transactions ──
    with tab2:
        st.markdown("### All Transactions")
        filter_opt = st.radio("Filter", ["All", "Flagged only", "Clean only"], horizontal=True)

        view_df = df.copy()
        if filter_opt == "Flagged only":
            view_df = view_df[view_df["_is_duplicate_sender"]]
        elif filter_opt == "Clean only":
            view_df = view_df[~view_df["_is_duplicate_sender"]]

        # Add review status from session
        view_df["_review_status"] = view_df.index.map(
            lambda i: st.session_state.review_map.get(i, "Pending")
        )

        display_cols = [c for c in view_df.columns if not c.startswith("_")]
        extra_cols = ["_sender_id", "_is_duplicate_sender", "_review_status"]

        def highlight_dups(row):
            if row["_is_duplicate_sender"]:
                return ["background-color: #fff3cd"] * len(row)
            return [""] * len(row)

        show_df = view_df[display_cols + extra_cols].rename(columns={
            "_sender_id": "Extracted Sender ID",
            "_is_duplicate_sender": "Duplicate Flag",
            "_review_status": "Review Status"
        })

        st.dataframe(
            show_df.style.apply(highlight_dups, axis=1),
            use_container_width=True,
            height=500
        )

    # ── TAB 3: Export ──
    with tab3:
        st.markdown("### 📥 Export Options")

        # Prepare export df
        export_df = df.copy()
        export_df["Extracted Sender ID"] = export_df["_sender_id"]
        export_df["Duplicate Flag"] = export_df["_is_duplicate_sender"].map({True: "YES", False: "NO"})
        export_df["Review Status"] = export_df.index.map(
            lambda i: st.session_state.review_map.get(i, "Pending")
        )
        export_df = export_df[[c for c in export_df.columns if not c.startswith("_")] +
                               ["Extracted Sender ID", "Duplicate Flag", "Review Status"]]

        def to_excel(data: pd.DataFrame) -> bytes:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                data.to_excel(writer, index=False, sheet_name="Transactions")
                # Auto-size columns
                ws = writer.sheets["Transactions"]
                for col in ws.columns:
                    max_len = max((len(str(cell.value)) for cell in col if cell.value), default=10)
                    ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)
            return buf.getvalue()

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### 🔴 Duplicates Only")
            dup_only = export_df[export_df["Duplicate Flag"] == "YES"]
            st.info(f"{len(dup_only)} flagged transactions")
            st.download_button(
                label="⬇️ Download Duplicates Excel",
                data=to_excel(dup_only),
                file_name=f"duplicates_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        with col2:
            st.markdown("#### 📋 Full Report (All Transactions)")
            st.info(f"{len(export_df)} total transactions with flags & review status")
            st.download_button(
                label="⬇️ Download Full Report Excel",
                data=to_excel(export_df),
                file_name=f"full_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        # Marked duplicates export
        st.markdown("---")
        st.markdown("#### 🚫 Only Transactions Marked as 'Duplicate' by Reviewer")
        marked_dup = export_df[export_df.index.map(
            lambda i: st.session_state.review_map.get(i, "") == "🚫 Duplicate"
        )]
        if len(marked_dup) == 0:
            st.warning("No transactions have been marked as Duplicate yet. Go to the Duplicates tab to review.")
        else:
            st.success(f"{len(marked_dup)} transactions marked as duplicate by reviewer")
            st.download_button(
                label="⬇️ Download Reviewer-Marked Duplicates",
                data=to_excel(marked_dup),
                file_name=f"marked_duplicates_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

else:
    st.info("👆 Upload an Excel or CSV file to get started.")
    st.markdown("""
    **How it works:**
    1. Upload your bank statement (`.xlsx`, `.xls`, or `.csv`)
    2. The app auto-detects sender IDs from UPI, IMPS, NEFT, RTGS descriptions
    3. Flags any sender who appears more than once
    4. You review each flagged transaction and mark it as **Legitimate** or **Duplicate**
    5. Export results to Excel — duplicates only, full report, or reviewer-marked list

    **Supported transaction formats:** UPI (`name@vpa`), IMPS/MMT, NEFT, RTGS, and more.
    """)