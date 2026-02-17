import streamlit as st
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Institution Payment Detector", layout="wide")
st.title("🚨 Institutional Payment Malpractice Detector")
st.write("Detects if same payer paid for multiple learners.")

uploaded_file = st.file_uploader(
    "Upload Excel or CSV file (First row must be headers)",
    type=["xlsx", "xls", "csv"]
)

# ---------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------

def extract_handles(text):
    return re.findall(r'[A-Z0-9._-]+@[A-Z0-9]+', text)

def normalize_learner(handle):
    handle = handle.upper()
    handle = handle.split("@")[0]
    handle = handle.split("-")[0]
    return handle.strip()

def tokenize(text):
    text = str(text).upper()
    text = text.replace("-", "-")  # keep dash
    return [t.strip() for t in text.split("/") if t.strip()]

# ---------------------------------------------------
# MAIN
# ---------------------------------------------------

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

        payer_to_learners = defaultdict(set)
        payer_to_txns = defaultdict(list)

        # -------------------------------------------
        # PROCESS ROWS
        # -------------------------------------------
        for _, row in df.iterrows():

            txn_id = str(row["Transaction ID"])
            desc = str(row["Description"]).upper()

            handles = extract_handles(desc)

            if not handles:
                continue

            tokens = tokenize(desc)

            for handle in handles:

                learner = normalize_learner(handle)

                # find payer by locating handle in token list
                for i, token in enumerate(tokens):
                    if handle in token:
                        if i > 0:
                            payer = tokens[i - 1]
                        else:
                            payer = "UNKNOWN"

                        payer_to_learners[payer].add(learner)
                        payer_to_txns[payer].append(txn_id)

        # -------------------------------------------
        # DETECT INSTITUTIONAL PAYERS
        # -------------------------------------------
        suspicious = []

        for payer, learners in payer_to_learners.items():
            if len(learners) > 1:
                suspicious.append({
                    "PAYER_NAME": payer,
                    "DISTINCT_LEARNER_COUNT": len(learners),
                    "FLAG": "🚨 INSTITUTIONAL PAYMENT"
                })

        st.header("🔎 Suspicious Institutional Payers")

        if suspicious:
            suspicious_df = pd.DataFrame(suspicious).sort_values(
                by="DISTINCT_LEARNER_COUNT",
                ascending=False
            )

            st.dataframe(suspicious_df, use_container_width=True)

            st.download_button(
                "Download Suspicious Payers",
                suspicious_df.to_csv(index=False),
                "suspicious_payers.csv",
                "text/csv"
            )

            # Evidence
            evidence_rows = []

            for payer in suspicious_df["PAYER_NAME"]:
                for txn in payer_to_txns[payer]:
                    evidence_rows.append({
                        "PAYER_NAME": payer,
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
            st.success("✅ No institutional malpractice detected.")

    except Exception as e:
        st.error(f"Error: {e}")
