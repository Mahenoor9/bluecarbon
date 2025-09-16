import streamlit as st
import pandas as pd
import hashlib
import time

st.title("🌱 Blue Carbon MRV + Registry Demo")

# Step 1: Upload CSV
uploaded_file = st.file_uploader("Upload your mangrove dataset (CSV)", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    st.subheader("Raw Dataset")
    st.write(df)

    # Step 2: MRV Calculation (dummy logic)
    if "Carbon_Stock_tonnes" in df.columns and "Area_ha" in df.columns:
        df["Carbon_Credits"] = df["Area_ha"] * df["Carbon_Stock_tonnes"]
        st.subheader("MRV Results (Carbon Credits)")
        st.write(df)

        # Step 3: Save into Registry (simulate as dataframe)
        registry = df[["Region", "Area_ha", "Carbon_Credits"]].copy()
        registry["Verified"] = True
        registry["Timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        st.subheader("Registry Table")
        st.write(registry)

        # Step 4: Mock Blockchain Transactions
        blockchain = []
        prev_hash = "0x0"
        for _, row in registry.iterrows():
            tx_data = f"{row.Region}-{row.Carbon_Credits}-{row.Timestamp}"
            tx_hash = hashlib.sha256(tx_data.encode()).hexdigest()
            blockchain.append({
                "transaction": tx_data,
                "hash": tx_hash,
                "previous_hash": prev_hash
            })
            prev_hash = tx_hash

        st.subheader("Blockchain Log (Simulated)")
        st.json(blockchain)
    else:
        st.warning("CSV must include columns: Region, Area_ha, Carbon_Stock_tonnes")
