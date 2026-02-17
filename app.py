import streamlit as st
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Multi-Learner Payment Detector", layout="wide")
st.title("🚨 Multi-Learner Account Payment Detector")

st.write("Detects if the same UPI account paid for more than one learner.")

uploaded_file = st.file_uploader(
    "Upload Excel or CSV file (First row must be headers)",
    type=["xlsx", "xls", "csv"]
)

# ----------------------------------------------------
# FUNCTIONS
# ----------------------------------------------------

def extract_handles(text):
    return re.findall(r'[A-Z0-9._-]+@[A-Z0-9]+', text.upper())

def normalize_learner(handle):
    handle = handle.upper()
    handle = handle.split("@")[0]
    handle = handle.split("-")[0]
    return handle.strip()

# ----------------------------------------------------
# MAIN
# ----------------------------------------------------

if uploaded_file:

    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        st.success(f"Loaded {len(df)} rows")

        if "Description" not in df.columns or "Transaction ID" not in df.columns:
            st.error("File must contain 'Description' and 'Transaction ID' columns.")
            st.stop()

        handle_to_learners = defaultdict(set)
        handle_to_txns = defaultdict(list)

        # -------------------------------------------
        # PROCESS EACH TRANSACTION
        # -------------------------------------------
        for _, row in df.iterrows():

            txn_id = str(row["Transaction ID"])
            desc = str(row["Description"]).upper()

            handles = extract_handles(desc)

            if not handles:
                continue

            for handle in handles:
                learner = normalize_learner(handle)

                handle_to_learners[handle].add(learner)
                handle_to_txns[handle].append(txn_id)

        # -------------------------------------------
        # DETECT HANDLES PAYING MULTIPLE LEARNERS
        # -------------------------------------------
        suspicious = []

        for handle, learners in handle_to_learners.items():
            if len(learners) > 1:
                suspicious.append({
                    "UPI_HANDLE": handle,
                    "DISTINCT_LEARNER_COUNT": len(learners),
                    "LEARNERS": ", ".join(sorted(learners)),
                    "FLAG": "🚨 PAID FOR MULTIPLE LEARNERS"
                })

        st.header("🔎 Suspicious UPI Accounts")

        if suspicious:
            suspicious_df = pd.DataFrame(suspicious).sort_values(
                by="DISTINCT_LEARNER_COUNT",
                ascending=False
            )

            st.dataframe(suspicious_df, use_container_width=True)

            st.download_button(
                "Download Suspicious Accounts",
                suspicious_df.to_csv(index=False),
                "suspicious_accounts.csv",
                "text/csv"
            )

            # Evidence
            evidence_rows = []

            for handle in suspicious_df["UPI_HANDLE"]:
                for txn in handle_to_txns[handle]:
                    evidence_rows.append({
                        "UPI_HANDLE": handle,
                        "TRANSACTION_ID": txn
                    })

            evidence_df = pd.DataFrame(evidence_rows)

            st.header("📄 Evidence Transactions")
            st.dataframe(evidence_df, use_container_width=True)

            st.download_button(
                "Download Evidence",
                evidence_df.to_csv(index=False),
                "evidence.csv",
                "text/csv"
            )

        else:
            st.success("✅ No accounts paid for multiple learners.")

    except Exception as e:
        st.error(f"Error: {e}")
