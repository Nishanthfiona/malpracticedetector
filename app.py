import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="Multi-Learner Payment Inspector", layout="wide")

st.title("🚨 Structured Transaction Inspector")

st.write("Upload bank statement. System will structure rows first, then allow duplicate analysis.")

uploaded_file = st.file_uploader("Upload Excel or CSV file (First row must be headers)", type=["xlsx", "xls", "csv"])

# -----------------------------------
# HELPER FUNCTIONS
# -----------------------------------

def normalize(text):
    text = str(text).upper()
    text = re.sub(r'\|', '/', text)   # only replace pipe
    text = re.sub(r'//+', '/', text)
    return text.strip()


def extract_parts(description):

    description = normalize(description)
    tokens = [t.strip() for t in description.split('/') if t.strip()]

    mode = tokens[0] if tokens else None

    learner_handle = None
    learner_id = None
    payer_name = None
    payer_handle = None

    # -----------------------
    # UPI PARSING
    # -----------------------
    if mode == "UPI":

        # find all handles
        handles = [t for t in tokens if '@' in t]

        if handles:
            learner_handle = handles[0]
            learner_id = learner_handle.split('@')[0]

        # payer name = first text before learner handle
        for t in tokens:
            if learner_handle and t == learner_handle:
                break

            if '@' not in t and not t.isdigit() and "BANK" not in t and t != "UPI":
                payer_name = t
                break

    # -----------------------
    # IMPS / MMT PARSING
    # -----------------------
    elif mode in ["MMT", "IMPS"]:

        # payer name is token before BANK
        for i in range(len(tokens)-1, -1, -1):
            if "BANK" in tokens[i]:
                if i-1 >= 0:
                    payer_name = tokens[i-1]
                break

    # -----------------------
    # NEFT parsing (basic)
    # -----------------------
    elif mode == "NEFT":

        for t in tokens:
            if "MR" in t or re.search(r'[A-Z]{3,}\s+[A-Z]{3,}', t):
                payer_name = t
                break

    return mode, learner_handle, learner_id, payer_name, payer_handle


# -----------------------------------
# MAIN LOGIC
# -----------------------------------

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

        structured_rows = []

        for _, row in df.iterrows():
            desc = row["Description"]
            txn_id = row["Transaction ID"]

            mode, learner_handle, learner_id, payer_name, payer_handle = extract_upi_parts(desc)

            structured_rows.append({
                "Transaction_ID": txn_id,
                "Mode": mode,
                "Learner_Handle": learner_handle,
                "Learner_ID": learner_id,
                "Payer_Name": payer_name,
                "Payer_Handle": payer_handle,
                "Raw_Description": desc
            })

        structured_df = pd.DataFrame(structured_rows)

        st.header("📋 Structured Transaction Table")
        st.dataframe(structured_df)

        st.download_button(
            "Download Structured Table",
            structured_df.to_csv(index=False),
            "structured_transactions.csv",
            "text/csv"
        )

        st.header("🔎 Duplicate / Multi-Use Detector")

        column_to_check = st.selectbox(
            "Select column to check duplicates:",
            [
                "Payer_Name",
                "Payer_Handle",
                "Learner_Handle",
                "Learner_ID"
            ]
        )

        if column_to_check:

            dup_df = structured_df.groupby(column_to_check)["Learner_ID"].nunique().reset_index()
            dup_df = dup_df[dup_df["Learner_ID"] > 1]

            if not dup_df.empty:
                st.error("🚨 Multi-Learner Detected!")
                st.dataframe(dup_df)

                st.download_button(
                    "Download Duplicate Report",
                    dup_df.to_csv(index=False),
                    "duplicate_report.csv",
                    "text/csv"
                )
            else:
                st.success("✅ No multi-learner usage detected.")

    except Exception as e:
        st.error(f"Error: {e}")
