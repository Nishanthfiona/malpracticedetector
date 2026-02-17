import streamlit as st
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Transaction Malpractice Detector", layout="wide")

st.title("🚨 Transaction Malpractice Detector")

uploaded_file = st.file_uploader("Upload Excel or CSV file", type=["xlsx", "xls", "csv"])

# ------------------------------
# TOKEN CLASSIFICATION SETTINGS
# ------------------------------

bank_keywords = [
    "BANK", "LTD", "FINANCE", "CO-OP", "POST", "NBD",
    "HDFC", "ICICI", "AXIS", "SBI", "STATE", "UNION",
    "KOTAK", "PUNJAB", "INDIAN", "OVERSEAS", "BARODA",
    "KARNATAKA"
]

system_keywords = [
    "PAYMENT", "PAY", "FEES", "COURSE", "NEBOSH",
    "USING", "FROM", "TO", "BALANCE", "ATTN",
    "INB", "GIF", "TRANSFER", "CREDIT"
]

# ------------------------------
# HELPER FUNCTIONS
# ------------------------------

def normalize_description(desc):
    desc = str(desc).upper()
    desc = re.sub(r'[-_|]', '/', desc)
    desc = re.sub(r'//+', '/', desc)
    return desc


def tokenize(desc):
    desc = normalize_description(desc)
    tokens = desc.split('/')
    return [t.strip() for t in tokens if t.strip()]


def classify(token):
    if '@' in token:
        return 'HANDLE'
    if len(token) > 25:
        return 'HASH'
    if token.isdigit() and len(token) >= 10:
        return 'PHONE'
    if any(bank in token for bank in bank_keywords):
        return 'BANK'
    if any(sys in token for sys in system_keywords):
        return 'SYSTEM'
    if re.search(r'[A-Z]', token) and re.search(r'\d', token):
        return 'ID_LIKE'
    return 'TEXT'


def detect_columns(df):
    desc_col = None
    txn_col = None

    for col in df.columns:
        col_lower = col.lower()
        if not desc_col and "desc" in col_lower:
            desc_col = col
        if not txn_col and ("transaction" in col_lower or "txn" in col_lower):
            txn_col = col

    return desc_col, txn_col


# ------------------------------
# MAIN LOGIC
# ------------------------------

if uploaded_file:

    try:
        if uploaded_file.name.endswith(".csv"):
            sheets = {"CSV": pd.read_csv(uploaded_file)}
        else:
            sheets = pd.read_excel(uploaded_file, sheet_name=None)

        all_data = []

        for sheet_name, df in sheets.items():
            desc_col, txn_col = detect_columns(df)

            if desc_col and txn_col:
                df = df[[txn_col, desc_col]].dropna()
                df.columns = ["TRANSACTION_ID", "DESCRIPTION"]
                df["SHEET"] = sheet_name
                all_data.append(df)

        if not all_data:
            st.error("❌ Could not detect required columns (Description & Transaction ID).")
            st.stop()

        data = pd.concat(all_data, ignore_index=True)

        st.success(f"Loaded {len(data)} transactions.")

        learner_to_payers = defaultdict(set)
        learner_to_txns = defaultdict(list)

        detailed_rows = []

        for _, row in data.iterrows():
            txn_id = str(row["TRANSACTION_ID"])
            tokens = tokenize(row["DESCRIPTION"])

            classified = [(t, classify(t)) for t in tokens]

            learner_ids = [
                t for t, typ in classified
                if typ in ["HANDLE", "ID_LIKE"]
                and not any(bank in t for bank in bank_keywords)
            ]

            payer_tokens = [
                t for t, typ in classified
                if typ == "TEXT"
                and not any(bank in t for bank in bank_keywords)
                and not any(sys in t for sys in system_keywords)
            ]

            payer_signature = "|".join(sorted(set(payer_tokens)))

            for learner in learner_ids:
                learner_to_payers[learner].add(payer_signature)
                learner_to_txns[learner].append(txn_id)

                detailed_rows.append({
                    "LEARNER_ID": learner,
                    "TRANSACTION_ID": txn_id,
                    "PAYER_SIGNATURE": payer_signature
                })

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

            st.header("📄 Evidence Details")

            details_df = pd.DataFrame(detailed_rows)
            evidence = details_df[
                details_df["LEARNER_ID"].isin(
                    suspicious_df["LEARNER_ID"]
                )
            ]

            st.dataframe(evidence)

            st.download_button(
                "Download Evidence CSV",
                evidence.to_csv(index=False),
                "evidence.csv",
                "text/csv"
            )

        else:
            st.success("✅ No malpractice detected.")

    except Exception as e:
        st.error(f"Error processing file: {e}")
