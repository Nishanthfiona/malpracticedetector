import streamlit as st
import pandas as pd
import re
from collections import defaultdict, Counter

st.set_page_config(page_title="Transaction Malpractice Detector", layout="wide")

st.title("🚨 Transaction Malpractice Detector")
st.write("Upload bank statement file (Excel or CSV).")

uploaded_file = st.file_uploader(
    "Upload Excel or CSV file",
    type=["xlsx", "xls", "csv"]
)

# -----------------------------------
# KEYWORDS
# -----------------------------------

bank_keywords = [
    "BANK", "LTD", "FINANCE", "COOP", "POST",
    "HDFC", "ICICI", "AXIS", "SBI", "STATE",
    "UNION", "KOTAK", "PUNJAB", "INDIAN",
    "OVERSEAS", "BARODA", "KARNATAKA"
]

system_keywords = [
    "PAYMENT", "PAY", "FEES", "COURSE", "NEBOSH",
    "USING", "FROM", "TO", "BALANCE", "ATTN",
    "INB", "GIF", "TRANSFER", "CREDIT",
    "UPI", "IMPS", "NEFT"
]

# -----------------------------------
# HELPERS
# -----------------------------------

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
        return "HANDLE"
    if token.isdigit() and len(token) >= 10:
        return "PHONE"
    if len(token) > 25:
        return "HASH"
    if any(bank in token for bank in bank_keywords):
        return "BANK"
    if any(sys in token for sys in system_keywords):
        return "SYSTEM"
    if re.search(r'[A-Z]', token) and re.search(r'\d', token):
        return "ID_LIKE"
    return "TEXT"


def clean_token(token):
    token = re.sub(r'@.*', '', token)
    token = re.sub(r'[^A-Z0-9]', '', token)
    return token


def auto_detect_columns(df):
    desc_col = None
    txn_col = None

    for col in df.columns:
        c = col.lower()

        if not desc_col and any(x in c for x in ["desc", "narration", "particular", "remark"]):
            desc_col = col

        if not txn_col and any(x in c for x in ["transaction", "txn", "ref", "document", "voucher"]):
            txn_col = col

    return desc_col, txn_col


# -----------------------------------
# MAIN
# -----------------------------------

if uploaded_file:

    try:
        # Load file
        if uploaded_file.name.endswith(".csv"):
            sheets = {"CSV": pd.read_csv(uploaded_file)}
        else:
            sheets = pd.read_excel(uploaded_file, sheet_name=None)

        selected_sheet = st.selectbox("Select Sheet", list(sheets.keys()))
        df = sheets[selected_sheet]

        st.write("Preview of Data:")
        st.dataframe(df.head())

        # Auto detect
        desc_col, txn_col = auto_detect_columns(df)

        # Manual override if needed
        if not desc_col:
            desc_col = st.selectbox("Select Description Column", df.columns)

        if not txn_col:
            txn_col = st.selectbox("Select Transaction ID Column", df.columns)

        if st.button("Run Detection"):

            data = df[[txn_col, desc_col]].dropna()
            data.columns = ["TRANSACTION_ID", "DESCRIPTION"]

            st.success(f"Loaded {len(data)} transactions.")

            # -----------------------------
            # PASS 1: Find Valid Learners
            # -----------------------------

            candidate_tokens = []

            for _, row in data.iterrows():
                tokens = tokenize(row["DESCRIPTION"])
                classified = [(t, classify(t)) for t in tokens]

                for token, typ in classified:
                    if typ in ["HANDLE", "ID_LIKE"]:
                        cleaned = clean_token(token)

                        if 6 <= len(cleaned) <= 18:
                            if not any(bank in cleaned for bank in bank_keywords):
                                candidate_tokens.append(cleaned)

            token_counts = Counter(candidate_tokens)

            valid_learners = {
                token for token, count in token_counts.items()
                if count >= 2
            }

            # -----------------------------
            # PASS 2: Map Learner → Payers
            # -----------------------------
            learner_to_payers = defaultdict(set)
            learner_to_txns = defaultdict(list)
            evidence_rows = []

            for _, row in data.iterrows():
                txn_id = str(row["TRANSACTION_ID"])
                tokens = tokenize(row["DESCRIPTION"])
                classified = [(t, classify(t)) for t in tokens]

                for i, (token, typ) in enumerate(classified):

                    if typ in ["HANDLE", "ID_LIKE"]:
                        cleaned = clean_token(token)

                        if cleaned in valid_learners:

                            # Find payer token before learner
                            payer_name = "UNKNOWN"

                            if i > 0:
                                prev_token, prev_type = classified[i - 1]

                                if prev_type == "TEXT":
                                    payer_name = prev_token.strip()

                            learner_to_payers[cleaned].add(payer_name)
                            learner_to_txns[cleaned].append(txn_id)

                            evidence_rows.append({
                                "LEARNER_ID": cleaned,
                                "TRANSACTION_ID": txn_id,
                                "PAYER_NAME": payer_name
                            })

            # -----------------------------
            # Detect Malpractice
            # -----------------------------

            suspicious = []

            for learner, payers in learner_to_payers.items():
                if len(payers) > 1:
                    suspicious.append({
                        "LEARNER_ID": learner,
                        "DISTINCT_PAYER_COUNT": len(payers),
                        "TOTAL_TRANSACTIONS": len(learner_to_txns[learner]),
                        "FLAG": "🚨 MALPRACTICE"
                    })

            st.header("🔎 Suspicious Learners")

            if suspicious:
                suspicious_df = pd.DataFrame(suspicious).sort_values(
                    by="DISTINCT_PAYER_COUNT",
                    ascending=False
                )

                st.dataframe(suspicious_df, use_container_width=True)

                st.download_button(
                    "Download Suspicious Learners",
                    suspicious_df.to_csv(index=False),
                    "suspicious_learners.csv",
                    "text/csv"
                )

                st.header("📄 Evidence Details")

                evidence_df = pd.DataFrame(evidence_rows)

                evidence_df = evidence_df[
                    evidence_df["LEARNER_ID"].isin(
                        suspicious_df["LEARNER_ID"]
                    )
                ]

                st.dataframe(evidence_df, use_container_width=True)

                st.download_button(
                    "Download Evidence",
                    evidence_df.to_csv(index=False),
                    "evidence.csv",
                    "text/csv"
                )

            else:
                st.success("✅ No malpractice detected.")

    except Exception as e:
        st.error(f"Error: {e}")
