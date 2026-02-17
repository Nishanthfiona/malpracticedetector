import streamlit as st
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Transaction Malpractice Detector", layout="wide")
st.title("🚨 Transaction Malpractice Detector")

uploaded_file = st.file_uploader("Upload bank statement file (Excel or CSV)", type=["xlsx", "xls", "csv"])

# ------------------------------
# SETTINGS
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
# CLEAN TOKENIZATION
# ------------------------------

def extract_handles(desc):
    """Extract full UPI handles like name@bank"""
    return re.findall(r'[A-Z0-9._-]+@[A-Z0-9]+', desc)

def normalize(desc):
    desc = str(desc).upper()
    desc = re.sub(r'[-_|]', '/', desc)
    desc = re.sub(r'//+', '/', desc)
    return desc

def tokenize(desc):
    desc = normalize(desc)
    return [t.strip() for t in desc.split('/') if t.strip()]

def is_valid_learner(token):
    # Must contain letters
    if not re.search(r'[A-Z]', token):
        return False
    
    # Ignore bank/system noise
    if any(b in token for b in bank_keywords):
        return False
    
    if any(s in token for s in system_keywords):
        return False
    
    # Ignore long hashes
    if len(token) > 25:
        return False
    
    return True

# ------------------------------
# MAIN
# ------------------------------
def normalize_learner(handle):
    handle = handle.upper()
    handle = handle.split("@")[0]   # remove bank part
    handle = handle.split("-")[0]   # remove -2 suffix
    return handle


if uploaded_file:

    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.success(f"Loaded {len(df)} rows")

    if "Description" not in df.columns or "Transaction ID" not in df.columns:
        st.error("File must contain 'Description' and 'Transaction ID' columns.")
        st.stop()

    learner_to_payers = defaultdict(set)
    learner_to_txns = defaultdict(list)

    for _, row in df.iterrows():
        desc = str(row["Description"]).upper()
        txn_id = str(row["Transaction ID"])

        handles = extract_handles(desc)
        tokens = tokenize(desc)

        # Remove handles from tokens so they don’t split
        for h in handles:
            desc = desc.replace(h, "")

        payer_tokens = []
        learner_ids = []

        # Handles are learners
        for h in handles:
            base_learner = normalize_learner(h)
            learner_ids.append(base_learner)

        for token in tokens:
            if is_valid_learner(token):
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
            "Download Suspicious Learners",
            suspicious_df.to_csv(index=False),
            "suspicious_learners.csv",
            "text/csv"
        )

        # Evidence
        evidence_rows = []

        for learner in suspicious_df["LEARNER_ID"]:
            for txn in learner_to_txns[learner]:
                evidence_rows.append({
                    "LEARNER_ID": learner,
                    "TRANSACTION_ID": txn
                })

        evidence_df = pd.DataFrame(evidence_rows)

        st.header("📄 Evidence Transactions")
        st.dataframe(evidence_df)

        st.download_button(
            "Download Evidence",
            evidence_df.to_csv(index=False),
            "evidence.csv",
            "text/csv"
        )

    else:
        st.success("✅ No malpractice detected.")
