# --------------------------
# BlueCarbon Registry App (Part 1/2)
# --------------------------
# Supabase PostgreSQL backend + Phi-3 Mini LLM
# Features:
# - Admin & Public Dashboards
# - Manual & Bulk CSV Upload
# - LLM carbon estimate + human-readable explanation
# - Info ℹ️ buttons for reasoning
# - Status buttons: Delete / Retire / Issue
# - Optional on-chain anchoring
# --------------------------

import os
import json
import hashlib
import subprocess
import traceback
from datetime import datetime
import io

import streamlit as st
import pandas as pd

import psycopg2
from psycopg2.extras import RealDictCursor
from web3 import Web3

# --------------------------
# Config - Database (No secrets, direct password)
# --------------------------
DB_HOST = "db.hrrmqkjxxyumemtowloy.supabase.co"
DB_USER = "postgres"
DB_PASSWORD = "mahenoor123"
DB_NAME = "postgres"
DB_PORT = 5432

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Optional EVM anchoring
EVM_RPC_URL = ""  # add your RPC URL if needed
EVM_PRIVATE_KEY = ""  # add private key if anchoring

OLLAMA_MODEL = "phi-3-mini"
OLLAMA_TIMEOUT = 20  # seconds

# --------------------------
# Helpers
# --------------------------
def log_debug(msg: str):
    print(f"[{datetime.now().isoformat()}] {msg}")

def safe_float(x, default=0.0):
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)

# --------------------------
# Database connection
# --------------------------
def get_db_conn_cursor():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode="require")
        cur = conn.cursor()
        return conn, cur
    except Exception as e:
        log_debug(f"Failed DB connection: {e}")
        return None, None

conn, cur = get_db_conn_cursor()
if conn and cur:
    log_debug("Connected to Postgres successfully.")
else:
    st.error("Could not connect to database. Check DATABASE_URL and network.")

# --------------------------
# Ensure projects table
# --------------------------
def ensure_projects_table():
    global conn, cur
    create_sql = """
    CREATE TABLE IF NOT EXISTS projects (
        id SERIAL PRIMARY KEY,
        name TEXT,
        type TEXT,
        region TEXT,
        area_ha REAL,
        carbon_tonnes REAL,
        credits REAL,
        status TEXT DEFAULT 'Issued',
        created_at TIMESTAMP DEFAULT NOW(),
        explanation TEXT,
        record_hash TEXT,
        onchain_tx TEXT,
        onchain_status TEXT,
        onchain_block BIGINT
    );
    """
    try:
        cur.execute(create_sql)
        conn.commit()
        log_debug("Ensured projects table exists.")
    except Exception as e:
        if conn:
            conn.rollback()
        log_debug(f"Error ensuring projects table: {e}\n{traceback.format_exc()}")

if conn and cur:
    ensure_projects_table()

# --------------------------
# Ollama LLM helpers
# --------------------------
def run_ollama_text(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    try:
        cmd = ["ollama", "run", model, "--prompt", prompt]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        if proc.returncode != 0:
            return f"(LLM error: {err or 'unknown'})"
        return out or "(LLM returned no output)"
    except FileNotFoundError:
        return "(Ollama CLI not found)"
    except subprocess.TimeoutExpired:
        return "(LLM timed out)"
    except Exception as e:
        log_debug(f"Ollama exception: {e}")
        return f"(LLM exception: {e})"

def run_ollama_number(prompt: str, fallback: float = 0.0) -> float:
    txt = run_ollama_text(prompt)
    try:
        cleaned = txt.replace(",", " ")
        tokens = cleaned.split()
        for tok in tokens:
            tok2 = tok.strip().strip(".,:;()[]\"'")
            try:
                return float(tok2)
            except:
                continue
        log_debug(f"Could not parse numeric from LLM output: {txt}")
        return fallback
    except Exception as e:
        log_debug(f"Parsing number error: {e}")
        return fallback

# --------------------------
# Record hash
# --------------------------
def compute_record_hash(record: dict) -> str:
    try:
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return "0x" + h
    except Exception as e:
        log_debug(f"Hashing error: {e}")
        return ""

# --------------------------
# Web3 anchoring (optional)
# --------------------------
def init_web3():
    if not EVM_RPC_URL:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(EVM_RPC_URL))
        if not w3.isConnected():
            log_debug("Web3 connection failed.")
            return None
        return w3
    except Exception as e:
        log_debug(f"Web3 init failed: {e}")
        return None

w3 = init_web3()

def anchor_hash_on_chain(hex_hash: str, wait_for_receipt: bool = False) -> dict:
    result = {"success": False, "tx_hash": None, "error": None, "receipt": None}
    if not w3:
        result["error"] = "Web3 provider not configured"
        return result
    if not EVM_PRIVATE_KEY:
        result["error"] = "EVM private key not configured"
        return result
    try:
        acct = w3.eth.account.from_key(EVM_PRIVATE_KEY)
        sender = acct.address
        nonce = w3.eth.get_transaction_count(sender)
        txn = {
            "to": sender,
            "value": 0,
            "data": hex_hash,
            "nonce": nonce,
            "gas": 120000,
            "gasPrice": w3.eth.gas_price,
            "chainId": w3.eth.chain_id
        }
        signed = w3.eth.account.sign_transaction(txn, private_key=EVM_PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        result["tx_hash"] = w3.toHex(tx_hash)
        result["success"] = True
        if wait_for_receipt:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            result["receipt"] = dict(receipt)
            result["onchain_block"] = receipt.blockNumber
        return result
    except Exception as e:
        result["error"] = str(e)
        log_debug(f"Anchor error: {e}\n{traceback.format_exc()}")
        return result

# --------------------------
# DB CRUD
# --------------------------
def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, explanation: str = "", record_hash: str = None, onchain_tx: str = None, onchain_status: str = None):
    global conn, cur
    credits = round(float(area) * 0.5 + float(carbon) * 0.2, 2)
    created_at = datetime.now()
    try:
        insert_sql = """
        INSERT INTO projects
        (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation, record_hash, onchain_tx, onchain_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """
        params = (name, type_, region, area, carbon, credits, "Issued", created_at, explanation, record_hash, onchain_tx, onchain_status)
        cur.execute(insert_sql, params)
        new_id = cur.fetchone()["id"]
        conn.commit()
        log_debug(f"Inserted project id {new_id}")
        return new_id
    except Exception as e:
        conn.rollback()
        log_debug(f"DB insert error: {e}")
        raise

def db_update_record_hash_and_onchain(id_: int, record_hash: str, onchain_tx: str = None, onchain_status: str = None, onchain_block: int = None):
    global conn, cur
    try:
        update_sql = """
        UPDATE projects SET record_hash = %s, onchain_tx = %s, onchain_status = %s, onchain_block = %s
        WHERE id = %s
        """
        cur.execute(update_sql, (record_hash, onchain_tx, onchain_status, onchain_block, id_))
        conn.commit()
        log_debug(f"Updated record_hash/onchain for id {id_}")
    except Exception as e:
        conn.rollback()
        log_debug(f"DB update error: {e}")
        raise

def db_delete_project(id_: int):
    global conn, cur
    try:
        cur.execute("DELETE FROM projects WHERE id = %s", (id_,))
        conn.commit()
        log_debug(f"Deleted project id {id_}")
    except Exception as e:
        conn.rollback()
        log_debug(f"DB delete error: {e}")
        raise

def db_update_status(id_: int, status: str):
    global conn, cur
    try:
        cur.execute("UPDATE projects SET status = %s WHERE id = %s", (status, id_))
        conn.commit()
        log_debug(f"Updated status for id {id_} -> {status}")
    except Exception as e:
        conn.rollback()
        log_debug(f"DB update status error: {e}")
        raise

def db_get_all_projects() -> pd.DataFrame:
    global conn, cur
    try:
        cur.execute("SELECT id, name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation, record_hash, onchain_tx, onchain_status, onchain_block FROM projects ORDER BY created_at DESC")
        rows = cur.fetchall()
        if not rows:
            cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame(rows)
        df.rename(columns={
            'id': 'ID',
            'name': 'Name',
            'type': 'Type',
            'region': 'Region',
            'area_ha': 'Area_ha',
            'carbon_tonnes': 'Carbon_tonnes',
            'credits': 'Credits',
            'status': 'Status',
            'created_at': 'Created_at',
            'explanation': 'Explanation',
            'record_hash': 'Record_Hash',
            'onchain_tx': 'Onchain_Tx',
            'onchain_status': 'Onchain_Status',
            'onchain_block': 'Onchain_Block'
        }, inplace=True)
        cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
        df = df[cols]
        return df
    except Exception as e:
        log_debug(f"DB fetch error: {e}")
        cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
        return pd.DataFrame(columns=cols)

# --------------------------
# Session state caching
# --------------------------
def ensure_session_keys():
    if 'est_cache' not in st.session_state:
        st.session_state['est_cache'] = {}
    if 'explain_cache' not in st.session_state:
        st.session_state['explain_cache'] = {}
# --------------------------
# BlueCarbon Registry App (Part 2/2)
# --------------------------
# Contains Streamlit UI, Admin/Public modes, CSV upload, LLM integration, ℹ️ buttons
# --------------------------

# --------------------------
# Utilities for LLM + caching
# --------------------------
def get_carbon_estimate(area: float) -> float:
    if area in st.session_state['est_cache']:
        return st.session_state['est_cache'][area]
    prompt = f"Estimate the carbon sequestration in tonnes for a project area of {area} hectares. Return only the number."
    est = run_ollama_number(prompt, fallback=area*5)  # fallback simplistic
    st.session_state['est_cache'][area] = est
    return est

def get_explanation(area: float) -> str:
    if area in st.session_state['explain_cache']:
        return st.session_state['explain_cache'][area]
    prompt = f"Explain in simple language how a project with {area} hectares contributes to carbon sequestration."
    explanation = run_ollama_text(prompt)
    st.session_state['explain_cache'][area] = explanation
    return explanation

# --------------------------
# CSV Upload parsing
# --------------------------
def parse_csv_upload(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file)
        # Ensure required columns
        required_cols = ['name','type','region','area_ha']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            st.error(f"Missing columns in CSV: {missing}")
            return None
        return df
    except Exception as e:
        st.error(f"Failed to parse CSV: {e}")
        return None

# --------------------------
# Admin authentication
# --------------------------
def admin_auth():
    password = st.text_input("Enter admin password", type="password")
    if password == "admin123":
        st.session_state['is_admin'] = True
        st.success("Admin access granted!")
        return True
    elif password:
        st.error("Incorrect password")
        return False
    return False

# --------------------------
# Admin dashboard UI
# --------------------------
def admin_dashboard():
    st.header("Admin Dashboard")
    st.subheader("Add a new project manually")
    with st.form("add_project_form"):
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0, step=0.1)
        submitted = st.form_submit_button("Add Project")
        if submitted:
            if not name or not type_ or not region or area <= 0:
                st.error("Fill all fields correctly.")
            else:
                carbon = get_carbon_estimate(area)
                explanation = get_explanation(area)
                record_dict = {"name": name, "type": type_, "region": region, "area_ha": area, "carbon_tonnes": carbon}
                record_hash = compute_record_hash(record_dict)
                project_id = db_add_project(name, type_, region, area, carbon, explanation, record_hash)
                st.success(f"Project {name} added with ID {project_id}")

    st.subheader("Bulk CSV Upload")
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
    if uploaded_file:
        df = parse_csv_upload(uploaded_file)
        if df is not None:
            for _, row in df.iterrows():
                area = safe_float(row['area_ha'])
                carbon = get_carbon_estimate(area)
                explanation = get_explanation(area)
                record_dict = {"name": row['name'], "type": row['type'], "region": row['region'], "area_ha": area, "carbon_tonnes": carbon}
                record_hash = compute_record_hash(record_dict)
                db_add_project(row['name'], row['type'], row['region'], area, carbon, explanation, record_hash)
            st.success(f"{len(df)} projects added via CSV.")

    st.subheader("All Projects Table")
    df_all = db_get_all_projects()
    for idx, row in df_all.iterrows():
        with st.expander(f"{row['Name']} ({row['Type']}) - {row['Region']}"):
            st.write(f"Area: {row['Area_ha']} ha | Carbon: {row['Carbon_tonnes']} t | Credits: {row['Credits']} | Status: {row['Status']}")
            st.write("Created:", row['Created_at'])
            st.write("Record Hash:", row['Record_Hash'])
            # ℹ️ info button for explanation
            if st.button(f"ℹ️ Explanation {row['ID']}"):
                st.info(row['Explanation'])
            cols = st.columns(3)
            if cols[0].button(f"Delete {row['ID']}"):
                db_delete_project(row['ID'])
                st.success(f"Deleted project ID {row['ID']}")
            if cols[1].button(f"Retire {row['ID']}"):
                db_update_status(row['ID'], "Retired")
                st.success(f"Retired project ID {row['ID']}")
            if cols[2].button(f"Issue {row['ID']}"):
                db_update_status(row['ID'], "Issued")
                st.success(f"Issued project ID {row['ID']}")

# --------------------------
# Public dashboard UI
# --------------------------
def public_dashboard():
    st.header("BlueCarbon Projects (Public View)")
    df_all = db_get_all_projects()
    for idx, row in df_all.iterrows():
        with st.expander(f"{row['Name']} ({row['Type']}) - {row['Region']}"):
            st.write(f"Area: {row['Area_ha']} ha | Carbon: {row['Carbon_tonnes']} t | Credits: {row['Credits']} | Status: {row['Status']}")
            st.write("Created:", row['Created_at'])
            st.write("Record Hash:", row['Record_Hash'])
            if st.button(f"ℹ️ Explanation {row['ID']}", key=f"public_info_{row['ID']}"):
                st.info(row['Explanation'])

# --------------------------
# Main Streamlit app
# --------------------------
def main():
    st.set_page_config(page_title="BlueCarbon Registry", layout="wide")
    st.title("🌱 BlueCarbon Carbon Registry")

    if 'is_admin' not in st.session_state:
        st.session_state['is_admin'] = False

    mode = st.radio("Select Mode", ["Public", "Admin"])
    if mode == "Admin":
        if not st.session_state['is_admin']:
            admin_auth()
        if st.session_state['is_admin']:
            admin_dashboard()
    else:
        public_dashboard()

# --------------------------
# Run main
# --------------------------
if __name__ == "__main__":
    ensure_session_keys()
    main()
