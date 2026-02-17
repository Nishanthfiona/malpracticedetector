import streamlit as st
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Transaction Malpractice Detector", layout="wide")

st.title("🚨 Transaction Malpractice Detector")
st.write("Upload bank statement file. First row must be headers.")

uploaded_file = st.file_uploader("Upload Excel or CSV file", type=["xlsx", "xls", "csv"])

# ---------------------------
# SETTINGS
# ---------------------------

bank_keywords = [
    "BANK", "LTD", "FINANCE", "CO", "POST",
    "HDFC", "ICICI", "AXIS", "SBI", "STATE",
    "UNION", "KOTAK", "PUNJAB", "INDIAN",
    "OVERSEAS", "BARODA", "KARNATAKA"
]

system_keywords = [
    "PAYMENT", "PAY", "FEES", "COURSE",
    "USING", "FROM", "TO", "BALANCE",
    "ATTN", "TRANSFER", "CREDIT"
]

# ---------------------------
# FUNCTIONS
# ---------------------------

def normalize(text):
    text = str(text).upper()
    text = re.sub(r'[-_|]', '/', text)
    text = re.sub(r'//+', '/', text)
    return text

def tokenize(text):
    text = normalize(text)
    return [t.strip() for t in text.split("/") if t.strip()]

def is_handle(token):
    return "@" in token

def is_bank(token):
    return any(b in token for b in bank_keywords)

def is_system(token):
    return any(s in token for s in system_keywords)

def is_hash(token):
    return len(token) > 25

def is_phone(token):
    return token.isdigit() and len(token) >= 10

def is_id_like(token):
    return re.search(r"[A-Z]", token) and re.search(r"\d", token)

# ---------------------------
# MAIN
# ---------------------------

if uploaded_file:

    try:
        if uploaded_file.name.endswith(".csv"):
            sheets = {"CSV": pd.read_csv(uploaded_file)}
        else:
            sheets = pd.read_excel(uploaded_file, sheet_name=None)

        sheet_name = st.selectbox("Select Sheet", list(sheets.keys()))
        df = sheets[sheet_name]

        st.subheader("Preview of Data")
        st.dataframe(df.head())

        desc_col = st.selectbox("Select Description Column", df.columns)
        txn_col = st.selectbox("Select Transaction ID Column", df.columns)

        if st.button("Run Malpractice Detection"):

            df = df[[txn_col, desc_col]].dropna()
            df.columns = ["TRANSACTION_ID", "DESCRIPTION"]

            st.success(f"Loaded {len(df)} transactions.")

            learner_to_payers = defaultdict(set)
            learner_to_txns = defaultdict(list)

            for _, row in df.iterrows():

                txn_id = str(row["TRANSACTION_ID"])
                tokens = tokenize(row["DESCRIPTION"])

                learner_ids = []
                payer_tokens = []

                for token in tokens:

                    if is_bank(token) or is_system(token) or is_hash(token) or is_phone(token):
                        continue

                    if is_handle(token) or is_id_like(token):
                        learner_ids.append(token)
                    else:
                        payer_tokens.append(token)

                payer_signature = "|".join(sorted(set(payer_tokens)))

                for learner in learner_ids:
                    learner_to_payers[learner].add(payer_signature)
                    learner_to_txns[learner].append(txn_id)

            suspicious = []

            for learner, payers in learner_to_payers.items():
                if len(payers) > 1:
                    suspicious.append({
                        "LEARNER_ID": learner,
                        "DISTINCT_PAYER_COUNT": len(payers),
                        "FLAG": "🚨 MALPRACTICE"
                    })

            st.header("🔎 Suspicious Learners")

            if suspicious:
                suspicious_df = pd.DataFrame(suspicious)
                st.dataframe(suspicious_df)

                st.download_button(
                    "Download Suspicious Learners CSV",
                    suspicious_df.to_csv(index=False),
                    "suspicious_learners.csv",
                    "text/csv"
                )

                st.header("📄 Evidence")

                evidence_rows = []

                for learner in suspicious_df["LEARNER_ID"]:
                    for txn in learner_to_txns[learner]:
                        evidence_rows.append({
                            "LEARNER_ID": learner,
                            "TRANSACTION_ID": txn
                        })

                evidence_df = pd.DataFrame(evidence_rows)

                st.dataframe(evidence_df)

                st.download_button(
                    "Download Evidence CSV",
                    evidence_df.to_csv(index=False),
                    "evidence.csv",
                    "text/csv"
                )

            else:
                st.success("✅ No malpractice detected.")

    except Exception as e:
        st.error(f"Error: {e}")
