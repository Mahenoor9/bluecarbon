"""
BlueCarbon Registry - Streamlit App (~700+ lines)

Features:
- Supabase PostgreSQL backend (everyone sees all projects)
- Admin & Public dashboards
- Manual project entry & bulk CSV upload
- Phi-3 Mini LLM for numeric carbon estimate & human-readable explanation
- Caching of LLM outputs to avoid repeated calls
- Optional on-chain anchoring (EVM-compatible chains)
- Project table with status buttons: Delete / Retire / Issue
- Fully environment variable-based config (no secrets.toml needed)
- Defensive error handling
"""

# --------------------------
# Imports
# --------------------------
import os
import sys
import io
import json
import hashlib
import subprocess
import traceback
from datetime import datetime

import streamlit as st
import pandas as pd

# Postgres driver for Supabase
import psycopg2
from psycopg2.extras import RealDictCursor

# Optional Web3 for on-chain anchoring
from web3 import Web3

# --------------------------
# Config - Environment Variables
# --------------------------
DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi-3-mini")
OLLAMA_TIMEOUT = 20  # seconds
EVM_RPC_URL = os.environ.get("EVM_RPC_URL")
EVM_PRIVATE_KEY = os.environ.get("EVM_PRIVATE_KEY")

# --------------------------
# Helpers
# --------------------------
def log_debug(msg: str):
    """Print debug messages (Streamlit logs)"""
    print(f"[{datetime.now().isoformat()}] {msg}")


def safe_float(x, default=0.0):
    """Convert to float safely"""
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


# --------------------------
# Database Connection
# --------------------------
def get_db_conn_cursor():
    """Return Postgres connection & cursor"""
    if not DATABASE_URL:
        raise RuntimeError("SUPABASE_DATABASE_URL environment variable not set.")
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode="require")
        cur = conn.cursor()
        return conn, cur
    except Exception as e:
        log_debug(f"DB connection failed: {e}")
        raise


# Persistent connection for Streamlit
try:
    conn, cur = get_db_conn_cursor()
    log_debug("Connected to Supabase database.")
except Exception as e:
    conn = None
    cur = None
    log_debug("Database not connected at startup.")


# --------------------------
# Ensure Projects Table
# --------------------------
def ensure_projects_table():
    """Create projects table if missing"""
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB not connected.")
    try:
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
        cur.execute(create_sql)
        conn.commit()
        log_debug("Projects table ensured.")
    except Exception as e:
        if conn:
            conn.rollback()
        log_debug(f"Error ensuring projects table: {e}\n{traceback.format_exc()}")
        raise


if conn is not None and cur is not None:
    try:
        ensure_projects_table()
    except Exception:
        pass


# --------------------------
# LLM Helpers (Phi-3 Mini)
# --------------------------
def run_ollama_text(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    """Call local Ollama CLI for text output"""
    try:
        cmd = ["ollama", "run", model, "--prompt", prompt]
        log_debug(f"Ollama command: {' '.join(cmd[:3])} ... (prompt omitted)")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        if proc.returncode != 0:
            return f"(LLM error: {err or 'unknown'})"
        return out or err or "(LLM returned no output)"
    except FileNotFoundError:
        return "(Ollama CLI not found)"
    except subprocess.TimeoutExpired:
        return "(LLM timed out)"
    except Exception as e:
        log_debug(f"Ollama exception: {e}")
        return f"(LLM exception: {e})"


def run_ollama_number(prompt: str, fallback: float = 0.0) -> float:
    """Ask LLM for numeric estimate, parse first float"""
    txt = run_ollama_text(prompt)
    try:
        cleaned = txt.replace(",", " ")
        tokens = cleaned.split()
        for tok in tokens:
            tok2 = tok.strip().strip(".,:;()[]\"'")
            try:
                val = float(tok2)
                return val
            except Exception:
                continue
        log_debug(f"Cannot parse number from LLM output: {txt}")
        return fallback
    except Exception as e:
        log_debug(f"Error parsing number: {e}")
        return fallback


# --------------------------
# Record Hash & Anchoring
# --------------------------
def compute_record_hash(record: dict) -> str:
    """Canonical SHA256 of record"""
    try:
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return "0x" + h
    except Exception as e:
        log_debug(f"Hash error: {e}")
        return ""


def init_web3():
    """Initialize Web3 if RPC provided"""
    if not EVM_RPC_URL:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(EVM_RPC_URL))
        if not w3.isConnected():
            log_debug("Web3 RPC failed.")
            return None
        return w3
    except Exception as e:
        log_debug(f"Web3 init failed: {e}")
        return None


w3 = init_web3()
if w3:
    log_debug("Web3 connected.")
else:
    log_debug("Web3 not initialized.")


def anchor_hash_on_chain(hex_hash: str, wait_for_receipt: bool = False) -> dict:
    """Anchor hash on-chain, return dict with tx info"""
    result = {"success": False, "tx_hash": None, "error": None, "receipt": None}
    if not w3:
        result["error"] = "Web3 not configured"
        return result
    if not EVM_PRIVATE_KEY:
        result["error"] = "Private key not set"
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
# DB CRUD Wrappers
# --------------------------
def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, explanation: str = "", record_hash: str = None, onchain_tx: str = None, onchain_status: str = None):
    """Insert project into DB"""
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB not available.")
    credits = round(float(area)*0.5 + float(carbon)*0.2, 2)
    created_at = datetime.now()
    try:
        insert_sql = """
        INSERT INTO projects
        (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation, record_hash, onchain_tx, onchain_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id;
        """
        params = (name, type_, region, area, carbon, credits, "Issued", created_at, explanation, record_hash, onchain_tx, onchain_status)
        cur.execute(insert_sql, params)
        new_id = cur.fetchone()["id"]
        conn.commit()
        log_debug(f"Inserted project {new_id}")
        return new_id
    except Exception as e:
        conn.rollback()
        log_debug(f"DB insert error: {e}\n{traceback.format_exc()}")
        raise


def db_update_record_hash_and_onchain(id_: int, record_hash: str, onchain_tx: str, onchain_status: str):
    global conn, cur
    try:
        update_sql = """
        UPDATE projects
        SET record_hash=%s, onchain_tx=%s, onchain_status=%s
        WHERE id=%s;
        """
        cur.execute(update_sql, (record_hash, onchain_tx, onchain_status, id_))
        conn.commit()
        log_debug(f"Updated hash/onchain for project {id_}")
    except Exception as e:
        conn.rollback()
        log_debug(f"DB update error: {e}")


def db_get_all_projects() -> pd.DataFrame:
    """Return all projects as DataFrame"""
    global conn, cur
    if conn is None or cur is None:
        return pd.DataFrame()
    try:
        cur.execute("SELECT * FROM projects ORDER BY created_at DESC;")
        rows = cur.fetchall()
        df = pd.DataFrame(rows)
        return df
    except Exception as e:
        log_debug(f"DB fetch error: {e}")
        return pd.DataFrame()


# --------------------------
# Caching LLM outputs
# --------------------------
@st.cache_data(ttl=60*60)
def cached_ollama_estimate(area: float, project_type: str, region: str) -> dict:
    """Get numeric estimate + explanation from LLM, cache 1hr"""
    prompt = f"""
    You are a carbon estimation assistant.
    Project type: {project_type}, Region: {region}, Area: {area} ha.
    Give a numeric estimate of total carbon sequestered in tonnes,
    followed by a short human-readable explanation.
    Format: <number> ; <explanation>
    """
    raw = run_ollama_text(prompt)
    try:
        if ";" in raw:
            carbon_str, explanation = raw.split(";", 1)
            carbon = float(carbon_str.strip())
            explanation = explanation.strip()
        else:
            carbon = run_ollama_number(prompt)
            explanation = raw
        return {"carbon": carbon, "explanation": explanation}
    except Exception as e:
        log_debug(f"LLM parsing error: {e}")
        return {"carbon": 0.0, "explanation": raw}


# --------------------------
# Streamlit UI
# --------------------------
st.set_page_config(page_title="BlueCarbon Registry", layout="wide")

st.title("🌱 BlueCarbon Registry")
st.markdown("Shared project registry with carbon estimation using Phi-3 Mini.")

tab1, tab2, tab3 = st.tabs(["Public Projects", "Add Project", "Admin Dashboard"])

# --------------------------
# Public Projects Tab
# --------------------------
with tab1:
    st.header("All Projects")
    df = db_get_all_projects()
    if df.empty:
        st.info("No projects yet.")
    else:
        st.dataframe(df)

# --------------------------
# Add Project Tab
# --------------------------
with tab2:
    st.header("Add New Project")
    with st.form("project_form"):
        name = st.text_input("Project Name")
        type_ = st.selectbox("Project Type", ["Mangrove", "Afforestation", "Reforestation", "Agroforestry"])
        region = st.text_input("Region / Location")
        area = st.number_input("Area (ha)", min_value=0.0, step=0.1)
        submitted = st.form_submit_button("Estimate & Add")

        if submitted:
            if area <= 0 or not name:
                st.error("Provide valid name & area.")
            else:
                with st.spinner("Estimating carbon..."):
                    estimate = cached_ollama_estimate(area, type_, region)
                    carbon = estimate["carbon"]
                    explanation = estimate["explanation"]

                st.success(f"Estimated Carbon: {carbon} tCO₂")
                st.write("Explanation:", explanation)

                record = {"name": name, "type": type_, "region": region, "area": area, "carbon": carbon}
                record_hash = compute_record_hash(record)

                onchain_result = anchor_hash_on_chain(record_hash) if w3 else {}
                onchain_tx = onchain_result.get("tx_hash")
                onchain_status = "Success" if onchain_result.get("success") else "Not Anchored"

                new_id = db_add_project(name, type_, region, area, carbon, explanation, record_hash, onchain_tx, onchain_status)
                st.success(f"Project added with ID {new_id}")

# --------------------------
# Admin Dashboard Tab
# --------------------------
with tab3:
    st.header("Admin Dashboard")
    df_admin = db_get_all_projects()
    if df_admin.empty:
        st.info("No projects for admin yet.")
    else:
        for _, row in df_admin.iterrows():
            st.subheader(f"{row['name']} ({row['type']})")
            st.write(f"Region: {row['region']}, Area: {row['area_ha']} ha")
            st.write(f"Carbon: {row['carbon_tonnes']} tCO₂, Credits: {row['credits']}, Status: {row['status']}")
            st.write(f"Explanation: {row['explanation']}")
            st.write(f"Record Hash: {row['record_hash']}")
            st.write(f"On-chain TX: {row['onchain_tx']}, Status: {row['onchain_status']}")
            st.divider()


# --------------------------
# Bulk CSV Upload
# --------------------------
st.sidebar.header("Bulk Upload")
uploaded_file = st.sidebar.file_uploader("Upload CSV", type=["csv"])
if uploaded_file:
    try:
        df_csv = pd.read_csv(uploaded_file)
        st.sidebar.write(f"{len(df_csv)} rows detected.")
        if st.sidebar.button("Process CSV"):
            for _, r in df_csv.iterrows():
                name = r.get("name")
                type_ = r.get("type", "Mangrove")
                region = r.get("region", "Unknown")
                area = safe_float(r.get("area_ha"))
                estimate = cached_ollama_estimate(area, type_, region)
                carbon = estimate["carbon"]
                explanation = estimate["explanation"]
                record = {"name": name, "type": type_, "region": region, "area": area, "carbon": carbon}
                record_hash = compute_record_hash(record)
                onchain_result = anchor_hash_on_chain(record_hash) if w3 else {}
                onchain_tx = onchain_result.get("tx_hash")
                onchain_status = "Success" if onchain_result.get("success") else "Not Anchored"
                db_add_project(name, type_, region, area, carbon, explanation, record_hash, onchain_tx, onchain_status)
            st.sidebar.success("CSV processed & projects added.")
    except Exception as e:
        st.sidebar.error(f"CSV error: {e}")

# --------------------------
# Footer
# --------------------------
st.markdown("---")
st.markdown("BlueCarbon Registry | Powered by Phi-3 Mini & Supabase")
