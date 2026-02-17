import streamlit as st
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Transaction Malpractice Detector", layout="wide")

st.title("🚨 Transaction Malpractice Detector")

uploaded_file = st.file_uploader(
    "Upload Excel or CSV file",
    type=["xlsx", "xls", "csv"]
)

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

bank_keywords = [
    "BANK", "LTD", "FINANCE", "CO-OP", "POST", "NBD",
    "HDFC", "ICICI", "AXIS", "SBI", "STATE", "UNION",
    "KOTAK", "PUNJAB", "INDIAN", "OVERSEAS", "BARODA",
    "KARNATAKA", "CANARA", "IDFC"
]

system_keywords = [
    "PAYMENT", "PAY", "FEES", "COURSE", "NEBOSH",
    "USING", "FROM", "TO", "BALANCE", "ATTN",
    "INB", "GIF", "TRANSFER", "CREDIT",
    "REGISTRATION", "EXAM"
]

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def find_header_row(df):
    """
    Scans first 15 rows to detect actual header row.
    Looks for both Transaction and Description words.
    """
    for i in range(min(15, len(df))):
        row = df.iloc[i].astype(str).str.upper()
        if (
            any("TRANSACTION" in val for val in row)
            and any("DESC" in val for val in row)
        ):
            return i
    return None


def detect_columns(df):
    desc_col = None
    txn_col = None

    for col in df.columns:
        col_lower = str(col).lower()
        if not desc_col and "desc" in col_lower:
            desc_col = col
        if not txn_col and (
            "transaction" in col_lower
            or "txn" in col_lower
            or "ref" in col_lower
        ):
            txn_col = col

    return desc_col, txn_col


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


# --------------------------------------------------
# MAIN PROCESS
# --------------------------------------------------

if uploaded_file:

    try:
        all_data = []

        # ---------------- CSV ----------------
        if uploaded_file.name.endswith(".csv"):

            temp_df = pd.read_csv(uploaded_file, header=None)
            header_row = find_header_row(temp_df)

            if header_row is None:
                st.error("❌ Could not detect transaction table header.")
                st.stop()

            df = pd.read_csv(uploaded_file, header=header_row)
            all_data.append(df)

        # ---------------- EXCEL ----------------
        else:
            raw_sheets = pd.read_excel(uploaded_file, sheet_name=None, header=None)

            for sheet_name, temp_df in raw_sheets.items():
                header_row = find_header_row(temp_df)

                if header_row is not None:
                    df = pd.read_excel(
                        uploaded_file,
                        sheet_name=sheet_name,
                        header=header_row
                    )
                    df["SHEET"] = sheet_name
                    all_data.append(df)

        if not all_data:
            st.error("❌ Could not detect transaction table structure.")
            st.stop()

        combined_df = pd.concat(all_data, ignore_index=True)

        desc_col, txn_col = detect_columns(combined_df)

        if not desc_col or not txn_col:
            st.error("❌ Could not detect Description or Transaction ID column.")
            st.stop()

        data = combined_df[[txn_col, desc_col]].dropna()
        data.columns = ["TRANSACTION_ID", "DESCRIPTION"]

        st.success(f"✅ Loaded {len(data)} transactions successfully.")

        # --------------------------------------------------
        # DETECTION LOGIC
        # --------------------------------------------------

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
        st.error(f"⚠️ Error processing file: {e}")
