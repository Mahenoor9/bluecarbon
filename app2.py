"""
app1.py

BlueCarbon registry - Streamlit app (Supabase Postgres backend + local Ollama LLM integration)

Features:
- Admin and Public dashboards
- Manual entry (st.form) and Bulk CSV upload (st.form) with safe LLM calls only on submit
- Uses psycopg2 to connect to a Supabase (Postgres) database (shared for all users)
- LLM integration via local `ollama` CLI (phi-3-mini) for human-readable explanations and numeric carbon estimates
- Explanations are stored in the DB in the `explanation` column so Public users can see them
- UI shows projects in table form (st.dataframe) and provides an "ℹ️" expander for explanation per project
- Defensive coding: try/except around DB and LLM calls, no DROPs on startup (persistent DB)
- Designed to avoid Streamlit blackout by using forms and session_state where appropriate

How to use:
1. Set the environment variable SUPABASE_DB_PASSWORD to your Supabase DB password, or replace the placeholder below.
   (Recommended: set env var instead of hardcoding.)
2. Make sure `psycopg2-binary` is installed in the same Python env:
      pip install psycopg2-binary
3. Make sure `ollama` is installed and `phi-3-mini` model is available locally.
4. Run:
      streamlit run app1.py"""
app1_full.py

BlueCarbon registry (Supabase Postgres backend + local Ollama LLM + optional on-chain anchoring)

Features:
- Admin and Public dashboards (Streamlit)
- Manual entry and bulk CSV upload (forms to avoid blackouts)
- Uses psycopg2 to connect to a Postgres DB (Supabase recommended)
- Local Ollama integration (phi-3-mini) for human-readable explanations and numeric carbon estimates
- Optional on-chain anchoring of a record hash (EVM-compatible chains via web3.py)
- Stores explanations, record hash and onchain tx info in the DB
- Defensive error handling and session_state caching to avoid repeated LLM calls
- Uses st.secrets (or environment variables) for credentials (do NOT hardcode in source)

USAGE:
1. Install dependencies in the same Python environment:
   pip install streamlit pandas psycopg2-binary web3

2. Make sure Ollama is installed and model phi-3-mini is available locally if you want LLM features.

3. Put secrets into Streamlit secrets (~/.streamlit/secrets.toml for local dev) like:

[database]
url = "postgresql://postgres:YOUR_DB_PASSWORD@db.<your-project-ref>.supabase.co:5432/postgres"

[evm]
rpc_url = "https://polygon-mumbai.g.alchemy.com/v2/YOUR_ALCHEMY_KEY"
private_key = "YOUR_PRIVATE_KEY"   # only if you want anchoring; keep safe

# Or set environment variables:
# SUPABASE_DATABASE_URL, EVM_RPC_URL, EVM_PRIVATE_KEY

4. Run:
   streamlit run app1_full.py

Note: Never commit secrets to source control.
"""

# --------------------------
# Imports
# --------------------------
import os
import json
import hashlib
import subprocess
import traceback
import time
from datetime import datetime

import streamlit as st
import pandas as pd
import io

# Database driver for Postgres (Supabase)
import psycopg2
from psycopg2.extras import RealDictCursor

# Optional web3 for on-chain anchoring
from web3 import Web3

# --------------------------
# Config / Secrets (secure)
# --------------------------
# Prefer st.secrets (Streamlit) for deployment; fallback to environment variables.
# Users must set these before running the app.

# DATABASE URL (postgres connection string)
# Example: postgresql://postgres:pw@db.xxxxx.supabase.co:5432/postgres
DATABASE_URL = None
if "database" in st.secrets and "url" in st.secrets["database"]:
    DATABASE_URL = st.secrets["database"]["url"]
else:
    DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL") or os.environ.get("DATABASE_URL")

# EVM RPC and private key (optional). Only required if you will anchor on-chain.
EVM_RPC_URL = None
EVM_PRIVATE_KEY = None
if "evm" in st.secrets:
    EVM_RPC_URL = st.secrets["evm"].get("rpc_url")
    EVM_PRIVATE_KEY = st.secrets["evm"].get("private_key")
else:
    EVM_RPC_URL = os.environ.get("EVM_RPC_URL")
    EVM_PRIVATE_KEY = os.environ.get("EVM_PRIVATE_KEY")

# Ollama model name (local)
OLLAMA_MODEL = st.secrets.get("ollama", {}).get("model", "phi-3-mini") if "ollama" in st.secrets else os.environ.get("OLLAMA_MODEL", "phi-3-mini")
OLLAMA_TIMEOUT = 20  # seconds for LLM calls

# --------------------------
# Small helpers
# --------------------------
def log_debug(msg: str):
    """Write debug to server stdout (visible in Streamlit logs)."""
    print(f"[{datetime.now().isoformat()}] {msg}")

def safe_float(x, default=0.0):
    """Parse float safely."""
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)

# --------------------------
# Database connection helpers
# --------------------------
def get_db_conn_cursor():
    """
    Create and return a psycopg2 connection and cursor (RealDictCursor).
    Uses DATABASE_URL; raises helpful error if not configured.
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured. Put your database connection string into st.secrets['database']['url'] or the SUPABASE_DATABASE_URL env var.")
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode="require")
        # We will use a single cursor for simplicity in this Streamlit app
        cur = conn.cursor()
        # autocommit left False; we'll commit explicitly
        return conn, cur
    except Exception as e:
        log_debug(f"Failed to connect to DB: {e}")
        raise

# Create a persistent connection for the process (so we do not reconnect for every small query)
try:
    conn, cur = get_db_conn_cursor()
    log_debug("Connected to Postgres database successfully.")
except Exception as e:
    conn = None
    cur = None
    log_debug("Database connection not available at startup.")

# --------------------------
# Ensure projects table exists and has required columns
# --------------------------
def ensure_projects_table():
    """
    Create projects table if it doesn't exist.
    Also add optional columns if missing.
    """
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("Database connection not available.")
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
        log_debug("Ensured projects table exists with expected columns.")
    except Exception as e:
        if conn:
            conn.rollback()
        log_debug(f"Error ensuring projects table: {e}\n{traceback.format_exc()}")
        raise

# Try to ensure table on startup (if DB is connected)
if conn is not None and cur is not None:
    try:
        ensure_projects_table()
    except Exception:
        pass

# --------------------------
# LLM (Ollama) helpers
# --------------------------
def run_ollama_text(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    """
    Use local Ollama CLI to generate text. Returns model output or helpful error message.
    """
    try:
        # Using: ollama run <model> --prompt "<prompt>"
        cmd = ["ollama", "run", model, "--prompt", prompt]
        log_debug(f"OLLAMA CMD: {' '.join(cmd[:3])} ... (prompt elided)")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        if proc.returncode != 0:
            log_debug(f"Ollama returned non-zero code: {err}")
            return f"(LLM error: {err or 'unknown'})"
        if out:
            return out
        if err:
            return err
        return "(LLM returned no output)"
    except FileNotFoundError:
        return "(Ollama CLI not found - install ollama locally)"
    except subprocess.TimeoutExpired:
        return "(LLM timed out)"
    except Exception as e:
        log_debug(f"Ollama exception: {e}")
        return f"(LLM exception: {e})"

def run_ollama_number(prompt: str, fallback: float = 0.0) -> float:
    """
    Ask Ollama for a numeric estimate. Try to parse first numeric token into float.
    Return fallback if parsing fails.
    """
    txt = run_ollama_text(prompt)
    # try to extract number
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
        log_debug(f"Could not parse numeric from LLM output: {txt}")
        return fallback
    except Exception as e:
        log_debug(f"Error parsing number from LLM output: {e}")
        return fallback

# --------------------------
# Record hashing and anchoring helpers
# --------------------------
def compute_record_hash(record: dict) -> str:
    """
    Compute canonical SHA256 hash of a record dictionary.
    Returns 0x-prefixed hex string.
    """
    try:
        # canonical JSON with sorted keys and no extra whitespace
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return "0x" + h
    except Exception as e:
        log_debug(f"Hashing error: {e}")
        return ""

def init_web3():
    """
    Initialize Web3 instance if RPC URL provided. Returns web3 or None.
    """
    if not EVM_RPC_URL:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(EVM_RPC_URL))
        if not w3.isConnected():
            log_debug("Web3 RPC URL provided but connection failed.")
            return None
        return w3
    except Exception as e:
        log_debug(f"Web3 init failed: {e}")
        return None

w3 = init_web3()
if w3:
    log_debug("Web3 connected to RPC provider.")
else:
    log_debug("Web3 not initialized (no RPC URL or connection failed).")

def anchor_hash_on_chain(hex_hash: str, wait_for_receipt: bool = False) -> dict:
    """
    Anchor a hex hash on-chain by sending a 0-value transaction to self with data=hex_hash.
    Returns dict with keys: success(bool), tx_hash(str), error(str|None), receipt(dict|None)
    IMPORTANT: Requires EVM_PRIVATE_KEY in secrets or environment.
    """
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
        # Build transaction sending 0 to self with data
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
        tx_hex = w3.toHex(tx_hash)
        result["tx_hash"] = tx_hex
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
# Database CRUD wrappers (Postgres)
# --------------------------
def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, explanation: str = "", record_hash: str = None, onchain_tx: str = None, onchain_status: str = None):
    """
    Insert a project row into projects table. Commits on success.
    """
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB connection not available.")
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
        log_debug(f"DB insert error: {e}\n{traceback.format_exc()}")
        raise

def db_update_record_hash_and_onchain(id_: int, record_hash: str, onchain_tx: str = None, onchain_status: str = None, onchain_block: int = None):
    """
    Update the record_hash and optional onchain fields for a project id.
    """
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB connection not available.")
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
        log_debug(f"DB update error: {e}\n{traceback.format_exc()}")
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
        # rename keys
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
        # Ensure column order
        cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
        df = df[cols]
        return df
    except Exception as e:
        log_debug(f"DB fetch error: {e}\n{traceback.format_exc()}")
        cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
        return pd.DataFrame(columns=cols)

# --------------------------
# Session state helpers
# --------------------------
def ensure_session_keys():
    if 'est_cache' not in st.session_state:
        st.session_state['est_cache'] = {}   # keyed by area+type+region
    if 'explain_cache' not in st.session_state:
        st.session_state['explain_cache'] = {}

# --------------------------
# UI - Admin Dashboard
# --------------------------
def admin_dashboard():
    ensure_session_keys()
    st.title("Admin Dashboard - BlueCarbon")

    # small instructions
    st.markdown(
        """
        **Add projects manually or upload CSV.**
        If Carbon is left blank (0), the local LLM will estimate a numeric value and provide an explanation.
        Optionally, you may anchor the record hash on-chain (requires EVM settings in secrets and gas).
        """
    )

    mode = st.radio("Input Mode", ["Manual Entry", "Bulk CSV Upload"])

    # -------------------------
    # Manual Entry
    # -------------------------
    if mode == "Manual Entry":
        st.subheader("Manual Project Entry")
        with st.form("manual_form", clear_on_submit=False):
            name = st.text_input("Project Name")
            type_ = st.text_input("Project Type")
            region = st.text_input("Region")
            area = st.number_input("Area (ha)", min_value=0.0, format="%.4f", value=0.0)
            carbon = st.number_input("Carbon Stored (tonnes) (leave 0 to estimate)", min_value=0.0, format="%.4f", value=0.0)
            anchor_onchain = st.checkbox("Anchor this record on-chain (requires RPC & key)", value=False)
            submit = st.form_submit_button("Add Project")

        if submit:
            if not name or not type_ or not region or area <= 0:
                st.error("Please provide Name, Type, Region and ensure Area > 0.")
            else:
                # determine carbon and explanation
                if carbon == 0.0:
                    cache_key = f"{area}|{type_}|{region}"
                    if cache_key in st.session_state['est_cache']:
                        est_val, expl = st.session_state['est_cache'][cache_key]
                        log_debug("Using cached LLM estimate")
                    else:
                        fallback = area * 4.0
                        prompt_num = f"Provide a single numeric estimate (in tonnes) of total carbon stored for a {area} ha {type_} project in {region}."
                        with st.spinner("Estimating carbon with LLM..."):
                            est_val = run_ollama_number(prompt_num, fallback=fallback)
                        prompt_explain = f"Explain in simple terms why the carbon for a {area} ha {type_} project in {region} is around {est_val} tonnes."
                        with st.spinner("Generating explanation with LLM..."):
                            expl = run_ollama_text(prompt_explain)
                        st.session_state['est_cache'][cache_key] = (est_val, expl)
                    carbon_val = safe_float(est_val)
                    explanation = expl
                else:
                    carbon_val = safe_float(carbon)
                    explanation = f"Carbon manually entered: {carbon_val} tonnes."

                # Insert into DB
                try:
                    new_id = db_add_project(name, type_, region, float(area), float(carbon_val), explanation)
                    st.success(f"Project added with id {new_id}.")
                except Exception as e:
                    st.error(f"Failed to add project: {e}")
                    return

                # compute record hash and optionally anchor
                record = {
                    "id": new_id,
                    "name": name,
                    "type": type_,
                    "region": region,
                    "area_ha": float(area),
                    "carbon_tonnes": float(carbon_val),
                    "created_at": datetime.now().isoformat()
                }
                rec_hash = compute_record_hash(record)
                try:
                    db_update_record_hash_and_onchain(new_id, rec_hash, None, "not_anchored", None)
                except Exception as e:
                    st.warning(f"Could not update record hash: {e}")

                if anchor_onchain:
                    if not w3 or not EVM_PRIVATE_KEY:
                        st.error("On-chain anchoring not available (RPC or private key not configured).")
                    else:
                        with st.spinner("Sending anchor transaction to blockchain..."):
                            anchor_res = anchor_hash_on_chain(rec_hash, wait_for_receipt=False)
                        if anchor_res.get("success"):
                            txh = anchor_res.get("tx_hash")
                            try:
                                db_update_record_hash_and_onchain(new_id, rec_hash, txh, "pending", None)
                            except Exception:
                                pass
                            st.success(f"Anchored on-chain. Tx: {txh}")
                        else:
                            st.error(f"Anchoring failed: {anchor_res.get('error')}")

                do_rerun_browser_safe()

    # -------------------------
    # Bulk CSV Upload
    # -------------------------
    elif mode == "Bulk CSV Upload":
        st.subheader("Bulk CSV Upload (multiple files allowed)")
        sample = pd.DataFrame({
            "name": ["Project A"],
            "type": ["Afforestation"],
            "region": ["India"],
            "area_ha": [100],
            "carbon_tonnes": [400]
        })
        buf = io.BytesIO()
        sample.to_csv(buf, index=False)
        st.download_button("Download CSV Template", buf.getvalue(), "template.csv", "text/csv")

        uploaded = st.file_uploader("Upload CSVs", type=["csv"], accept_multiple_files=True)
        previews = []
        if uploaded:
            for f in uploaded:
                st.markdown(f"### 📂 {f.name}")
                try:
                    df = pd.read_csv(f)
                    st.dataframe(df.head())
                    previews.append(df)
                except Exception as e:
                    st.warning(f"Could not read {f.name}: {e}")

        with st.form("bulk_form"):
            anchor_bulk = st.checkbox("Anchor each record on-chain (if possible)", value=False)
            bulk_submit = st.form_submit_button("Add All Projects")

        if bulk_submit and previews:
            added = 0
            skipped = 0
            for df in previews:
                for _, row in df.iterrows():
                    try:
                        name = row.get("name")
                        type_ = row.get("type")
                        region = row.get("region")
                        area = row.get("area_ha")
                        carbon = row.get("carbon_tonnes")
                        if pd.isna(area) or float(area) <= 0:
                            skipped += 1
                            continue
                        if pd.isna(carbon):
                            fallback = float(area) * 4.0
                            prompt_num = f"Numeric estimate for {area} ha {type_} in {region}"
                            cval = run_ollama_number(prompt_num, fallback=fallback)
                            prompt_exp = f"Explain why carbon for {area} ha {type_} in {region} is {cval} tonnes."
                            expl = run_ollama_text(prompt_exp)
                            carbon = float(cval)
                            explanation = expl
                        else:
                            carbon = float(carbon)
                            explanation = ""
                        new_id = db_add_project(name, type_, region, float(area), float(carbon), explanation)
                        rec = {"id": new_id, "name": name, "type": type_, "region": region, "area_ha": float(area), "carbon_tonnes": float(carbon), "created_at": datetime.now().isoformat()}
                        rh = compute_record_hash(rec)
                        db_update_record_hash_and_onchain(new_id, rh, None, "not_anchored", None)
                        if anchor_bulk and w3 and EVM_PRIVATE_KEY:
                            anchor_res = anchor_hash_on_chain(rh, wait_for_receipt=False)
                            if anchor_res.get("success"):
                                db_update_record_hash_and_onchain(new_id, rh, anchor_res.get("tx_hash"), "pending", None)
                        added += 1
                    except Exception as e:
                        log_debug(f"Bulk insert error: {e}")
                        skipped += 1
            st.success(f"Bulk import done. Added: {added}, Skipped: {skipped}")
            do_rerun_browser_safe()

    # -------------------------
    # Projects Overview
    # -------------------------
    st.subheader("Projects Overview (Admin)")
    df = db_get_all_projects()
    if not df.empty:
        df_display = df[['Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Record_Hash','Onchain_Status']].copy()
        # nice formatting for created_at
        try:
            df_display['Created_at'] = df_display['Created_at'].apply(lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if not pd.isna(x) else "")
        except Exception:
            pass
        st.dataframe(df_display, use_container_width=True)

        st.write("---")
        st.markdown("**Manage each project below**")

        for _, row in df.iterrows():
            left, right = st.columns([4,2])
            with left:
                st.markdown(f"### {row['Name']}")
                st.markdown(f"- **Type:** {row['Type']}")
                st.markdown(f"- **Region:** {row['Region']}")
                st.markdown(f"- **Area (ha):** {row['Area_ha']}")
                st.markdown(f"- **Carbon (t):** {row['Carbon_tonnes']}")
                st.markdown(f"- **Credits:** {row['Credits']}")
                st.markdown(f"- **Status:** {row['Status']}")
                st.markdown(f"- **Created at:** {row['Created_at']}")
                st.markdown(f"- **Record hash:** {row['Record_Hash']}")
                st.markdown(f"- **On-chain tx:** {row['Onchain_Tx'] or '—'}")
                st.markdown(f"- **On-chain status:** {row['Onchain_Status'] or '—'}")
            with right:
                with st.expander("ℹ️ Explanation", expanded=False):
                    if row['Explanation']:
                        st.write(row['Explanation'])
                    else:
                        st.write("No explanation available")
                # Action buttons
                if st.button(f"🗑️ Delete {row['ID']}", key=f"del_{row['ID']}"):
                    try:
                        db_delete_project(row['ID'])
                        st.success("Deleted.")
                        do_rerun_browser_safe()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")
                if st.button(f"🚫 Retire {row['ID']}", key=f"ret_{row['ID']}"):
                    try:
                        db_update_status(row['ID'], "Retired")
                        st.success("Retired.")
                        do_rerun_browser_safe()
                    except Exception as e:
                        st.error(f"Retire failed: {e}")
                if st.button(f"✅ Issue {row['ID']}", key=f"iss_{row['ID']}"):
                    try:
                        db_update_status(row['ID'], "Issued")
                        st.success("Issued.")
                        do_rerun_browser_safe()
                    except Exception as e:
                        st.error(f"Issue failed: {e}")
            st.write("---")
    else:
        st.info("No projects yet.")

# --------------------------
# UI - Public Dashboard
# --------------------------
def public_dashboard():
    st.title("Public Registry - BlueCarbon")
    st.markdown("A public view of projects. Explanations are visible via the ℹ️ expanders.")

    df = db_get_all_projects()
    if not df.empty:
        display = df[['Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Record_Hash','Onchain_Status']].copy()
        try:
            display['Created_at'] = display['Created_at'].apply(lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if not pd.isna(x) else "")
        except Exception:
            pass
        st.dataframe(display, use_container_width=True)

        st.subheader("Explanations")
        for _, row in df.iterrows():
            with st.expander(f"{row['Name']} — {row['Region']} — {row['Type']}"):
                if row['Explanation']:
                    st.write(row['Explanation'])
                else:
                    st.write("No explanation available.")
                st.markdown(f"- **Record hash:** {row['Record_Hash'] or '—'}")
                st.markdown(f"- **On-chain tx:** {row['Onchain_Tx'] or '—'}")
                st.markdown(f"- **On-chain status:** {row['Onchain_Status'] or '—'}")
    else:
        st.info("No projects available publicly.")

# --------------------------
# Safe rerun helper (works across streamlit versions)
# --------------------------
def do_rerun_browser_safe():
    try:
        if hasattr(st, "rerun"):
            st.rerun()
        elif hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
        else:
            st.experimental_set_query_params(_=datetime.now().timestamp())
    except Exception:
        # last-resort: no-op
        pass

# --------------------------
# Main
# --------------------------
def main():
    st.sidebar.title("BlueCarbon Registry")
    st.sidebar.caption("Supabase Postgres + Ollama + optional on-chain anchoring")

    mode = st.sidebar.selectbox("Mode", ["Public", "Admin"])

    if mode == "Admin":
        st.sidebar.markdown("**Admin access** — simple password gate (replace with real auth in production).")
        pwd = st.sidebar.text_input("Admin password", type="password")
        if pwd == "admin123":
            admin_dashboard()
        elif pwd:
            st.sidebar.error("Wrong password")
        else:
            st.sidebar.info("Enter admin password to manage projects.")
    else:
        public_dashboard()

# --------------------------
# Run app
# --------------------------
if __name__ == "__main__":
    if conn is None or cur is None:
        st.title("BlueCarbon Registry — Database Not Connected")
        st.error("Database connection failed. Please add your DATABASE_URL to st.secrets['database']['url'] or set SUPABASE_DATABASE_URL environment variable. Also ensure network access and that psycopg2-binary is installed.")
        st.markdown("Example connection string (do NOT share):")
        st.code("postgresql://postgres:YOUR_DB_PASSWORD@db.<your-ref>.supabase.co:5432/postgres")
    else:
        main()

"""

# --------------------------
# Imports and basic setup
# --------------------------
import os
import subprocess
import shlex
import time
import traceback

import streamlit as st
import pandas as pd
import io

# psycopg2 for Postgres (Supabase)
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from datetime import datetime

# --------------------------
# Configuration - Fill this
# --------------------------
# Host and DB are based on your Supabase connection string.
# Keep the password out of source control — use environment variable SUPABASE_DB_PASSWORD.
SUPABASE_HOST = "db.hrrmqkjxxyumemtowloy.supabase.co"
SUPABASE_DB = "postgres"
SUPABASE_USER = "postgres"
SUPABASE_PORT = 5432

# Prefer reading password from environment variable:
SUPABASE_PASSWORD = os.environ.get("SUPABASE_DB_PASSWORD", "YOUR_PASSWORD_HERE")
# Replace "YOUR_PASSWORD_HERE" only if you understand security risk.

# Ollama model name (local). Change if your model name differs.
OLLAMA_MODEL = "phi-3-mini"

# Timeout for the ollama subprocess (seconds)
OLLAMA_TIMEOUT = 20

# --------------------------
# Utility: simple debug logging
# --------------------------
def log_debug(msg: str):
    """Print debug messages to console (visible in Streamlit logs)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[DEBUG] {ts} - {msg}")

# --------------------------
# Database connection helpers
# --------------------------
def connect_db():
    """
    Create and return a new database connection and cursor (RealDictCursor).
    We return both conn, cur so callers can commit and close as needed.
    """
    try:
        conn = psycopg2.connect(
            host=SUPABASE_HOST,
            database=SUPABASE_DB,
            user=SUPABASE_USER,
            password=SUPABASE_PASSWORD,
            port=SUPABASE_PORT,
            cursor_factory=RealDictCursor,
        )
        cur = conn.cursor()
        # Good practice to set autocommit off and commit explicitly
        conn.autocommit = False
        return conn, cur
    except Exception as e:
        log_debug(f"DB connection failed: {e}")
        raise

# We'll create one persistent connection for the Streamlit process.
# (psycopg2 connections are not thread-safe across multiple threads; this is fine for basic Streamlit apps).
try:
    conn, c = connect_db()
    log_debug("Connected to Supabase Postgres successfully.")
except Exception as e:
    # If connection fails, provide a helpful message in the app UI (we also re-raise later if needed)
    log_debug("Unable to connect to database at startup.")
    conn = None
    c = None

# --------------------------
# Ensure table exists (safe create)
# --------------------------
def ensure_projects_table():
    """
    Ensure the 'projects' table exists with the expected schema.
    We run a CREATE TABLE IF NOT EXISTS so it won't drop existing data.
    """
    global conn, c
    if conn is None or c is None:
        raise RuntimeError("Database connection not available.")
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
            status TEXT,
            created_at TIMESTAMP,
            explanation TEXT
        );
        """
        c.execute(create_sql)
        conn.commit()
        log_debug("Ensured projects table exists.")
    except Exception as e:
        conn.rollback()
        log_debug(f"Error ensuring projects table: {e}")
        raise

# Call on startup
try:
    ensure_projects_table()
except Exception:
    # If table creation fails, we still continue so the user sees the error in the UI.
    pass

# --------------------------
# LLM helpers (Ollama CLI)
# --------------------------
def run_ollama_prompt_text(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    """
    Call local Ollama to generate free-text explanation.
    Uses subprocess to run: ollama run <model> --prompt "<prompt>"
    Returns the model's stdout (trimmed). Falls back to a simple string on failure.
    """
    try:
        # Build command list safely
        # Using "ollama run <model> --prompt <prompt>" is typical; use shlex to be safe
        cmd = ["ollama", "run", model, "--prompt", prompt]
        log_debug(f"Running Ollama text prompt (timeout {timeout}s)")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if proc.returncode != 0:
            log_debug(f"Ollama returned non-zero code. stderr: {stderr}")
            return f"(LLM failed to generate explanation: {stderr or 'unknown error'})"
        if stdout:
            return stdout
        else:
            # Some versions may emit model output to stderr; try that
            if stderr:
                return stderr
            return "(LLM returned empty explanation)"
    except subprocess.TimeoutExpired:
        log_debug("Ollama process timed out.")
        return "(LLM timed out — used fallback explanation)"
    except FileNotFoundError:
        log_debug("Ollama CLI not found on PATH.")
        return "(Ollama CLI not found — install ollama locally or use placeholder explanation)"
    except Exception as e:
        log_debug(f"Ollama call error: {e}")
        return f"(LLM error: {e})"

def run_ollama_prompt_number(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT, fallback: float = 0.0) -> float:
    """
    Ask Ollama to return a numeric estimate.
    We'll run a prompt asking for a single number and attempt to parse float from response.
    On failure, return fallback.
    """
    text = run_ollama_prompt_text(prompt, model=model, timeout=timeout)
    # Try to extract a number: find first token that looks like float/int
    try:
        # Remove commas and non-number characters except . and - and spaces
        cleaned = text.replace(",", " ")
        tokens = cleaned.split()
        for tok in tokens:
            # Strip punctuation
            tok_clean = tok.strip().strip(".,:;()[]{}\"'")
            try:
                val = float(tok_clean)
                return val
            except Exception:
                continue
        # If we couldn't parse, log debug and return fallback
        log_debug(f"Could not parse numeric value from LLM output: {text}")
        return fallback
    except Exception as e:
        log_debug(f"Error parsing LLM numeric output: {e}")
        return fallback

# --------------------------
# Business logic helpers
# --------------------------
def calculate_credits(area, carbon):
    """
    Calculate carbon credits based on area and carbon.
    Re-declared here for clarity (kept identical to previous logic).
    """
    try:
        return round(float(area) * 0.5 + float(carbon) * 0.2, 2)
    except Exception:
        return 0.0

def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, explanation: str = ""):
    """
    Add a project row in Postgres. Uses %s parameter placeholders (psycopg2).
    Commits transaction; rolls back on failure.
    """
    global conn, c
    if conn is None or c is None:
        raise RuntimeError("DB not connected.")
    credits = calculate_credits(area, carbon)
    created_at = datetime.now()
    try:
        insert_sql = """
        INSERT INTO projects
          (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (name, type_, region, area, carbon, credits, "Issued", created_at, explanation)
        c.execute(insert_sql, params)
        conn.commit()
        log_debug(f"Inserted project '{name}' (area={area}, carbon={carbon})")
    except Exception as e:
        conn.rollback()
        log_debug(f"DB insert failed: {e}\n{traceback.format_exc()}")
        raise

def db_delete_project(proj_id: int):
    global conn, c
    try:
        c.execute("DELETE FROM projects WHERE id = %s", (proj_id,))
        conn.commit()
        log_debug(f"Deleted project id {proj_id}")
    except Exception:
        conn.rollback()
        log_debug(f"Failed to delete project id {proj_id}")
        raise

def db_update_status(proj_id: int, status: str):
    global conn, c
    try:
        c.execute("UPDATE projects SET status = %s WHERE id = %s", (status, proj_id))
        conn.commit()
        log_debug(f"Updated status for id {proj_id} to {status}")
    except Exception:
        conn.rollback()
        log_debug(f"Failed to update status for id {proj_id}")
        raise

def db_get_all_projects() -> pd.DataFrame:
    """
    Fetch all projects and return a pandas DataFrame.
    If DB is empty, return empty DataFrame with expected columns.
    """
    global conn, c
    try:
        c.execute("SELECT id, name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation FROM projects ORDER BY created_at DESC")
        rows = c.fetchall()
        if not rows:
            cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation']
            return pd.DataFrame(columns=cols)
        # psycopg2 RealDictCursor returns dict-like rows
        df = pd.DataFrame(rows)
        # Standardize column names to match previous expectations
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
            'explanation': 'Explanation'
        }, inplace=True)
        # Ensure columns order
        expected = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation']
        df = df[expected]
        return df
    except Exception as e:
        log_debug(f"DB fetch failed: {e}")
        cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation']
        return pd.DataFrame(columns=cols)

# --------------------------
# Streamlit UI Helpers
# --------------------------
def safe_number(x, default=0.0):
    """Return float for x or default if x is None/NaN/unparseable."""
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)

def ensure_session_state_keys():
    """Initialize session_state keys used by app to avoid KeyError on reruns."""
    if "last_explanations" not in st.session_state:
        # Map project id -> explanation shown recently (caching)
        st.session_state.last_explanations = {}
    if "last_estimates" not in st.session_state:
        st.session_state.last_estimates = {}

# --------------------------
# Admin Dashboard
# --------------------------
def admin_dashboard():
    """
    Admin dashboard: manual entry (form) and bulk CSV upload (form).
    LLM calls are made only inside form submission handlers to prevent blackouts.
    """
    ensure_session_state_keys()

    st.title("Admin Dashboard")

    # Mode selection
    input_mode = st.radio("Choose Input Method", ["Manual Entry", "Bulk CSV Upload"])

    # ------------------------------
    # Manual Entry - use st.form to prevent rerun on every keystroke
    # ------------------------------
    if input_mode == "Manual Entry":
        st.subheader("Add New Project (Manual Entry)")

        with st.form("manual_project_form", clear_on_submit=False):
            name = st.text_input("Project Name")
            type_ = st.text_input("Project Type")
            region = st.text_input("Region")
            area = st.number_input("Area (ha)", min_value=0.0, format="%.4f")
            carbon = st.number_input("Carbon Stored (tonnes) (leave 0 to auto-estimate)", min_value=0.0, format="%.4f")
            submitted = st.form_submit_button("Add Project")

        if submitted:
            # Validate required fields
            if not name or not type_ or not region or area <= 0:
                st.error("Please provide Project Name, Type, Region and ensure Area > 0.")
            else:
                # If carbon not provided (==0), ask LLM for numeric estimate (safe)
                if carbon == 0.0:
                    # Use cached estimate if available for the same area
                    cache_key = f"est_area_{area}"
                    if cache_key in st.session_state.last_estimates:
                        carbon_est = st.session_state.last_estimates[cache_key]
                        explanation = st.session_state.last_explanations.get(cache_key, "")
                        log_debug("Using cached LLM estimate.")
                    else:
                        fallback = area * 4.0
                        prompt_num = (f"Provide a numeric estimate of total carbon stored (in tonnes) "
                                      f"for a {area} hectare {type_} project in {region}. "
                                      f"Respond with a single number only.")
                        with st.spinner("Estimating carbon with local LLM..."):
                            carbon_est = run_ollama_prompt_number(prompt_num, fallback=fallback)
                        # explanation - ask LLM for a human readable explanation
                        prompt_explain = (f"Explain in simple terms how you estimated carbon for a {area} ha "
                                          f"{type_} project in {region}. Keep it short.")
                        with st.spinner("Generating explanation with local LLM..."):
                            explanation_text = run_ollama_prompt_text(prompt_explain)
                        explanation = explanation_text
                        # cache
                        st.session_state.last_estimates[cache_key] = carbon_est
                        st.session_state.last_explanations[cache_key] = explanation
                    carbon = safe_number(carbon_est)
                else:
                    explanation = f"Carbon manually entered: {carbon} tonnes."

                # Add to database
                try:
                    db_add_project(name, type_, region, float(area), float(carbon), explanation)
                    st.success("Project added successfully!")
                    # show explanation immediately
                    with st.expander("ℹ️ Explanation (LLM or rule):", expanded=True):
                        st.write(explanation or "No explanation provided.")
                    do_rerun()
                except Exception as e:
                    st.error(f"Failed to add project: {e}")

    # ------------------------------
    # Bulk CSV Upload
    # ------------------------------
    elif input_mode == "Bulk CSV Upload":
        st.subheader("Bulk CSV Upload (multiple files allowed)")

        # CSV template
        template = pd.DataFrame({
            "name": ["Project A"],
            "type": ["Afforestation"],
            "region": ["India"],
            "area_ha": [100],
            "carbon_tonnes": [400]
        })
        buffer = io.BytesIO()
        template.to_csv(buffer, index=False)
        st.download_button("Download CSV Template", buffer.getvalue(), "template.csv", "text/csv")

        uploaded_files = st.file_uploader("Upload CSV files (accepts multiple)", type=["csv"], accept_multiple_files=True)
        # show brief preview
        dfs = []
        if uploaded_files:
            for file in uploaded_files:
                st.markdown(f"### 📂 {file.name}")
                try:
                    df = pd.read_csv(file)
                    st.dataframe(df.head())
                    dfs.append(df)
                except Exception as e:
                    st.warning(f"Could not read {file.name}: {e}")

        # Use a form to avoid reruns while user is selecting files
        with st.form("bulk_form"):
            bulk_submit = st.form_submit_button("Add All Projects")

        if bulk_submit and dfs:
            added = 0
            skipped = 0
            for df in dfs:
                for _, row in df.iterrows():
                    try:
                        name = row.get("name")
                        type_ = row.get("type")
                        region = row.get("region")
                        area = row.get("area_ha")
                        carbon = row.get("carbon_tonnes")

                        # Validate
                        if pd.isna(area) or area <= 0:
                            skipped += 1
                            st.warning(f"Skipping '{name}' - missing or invalid area")
                            continue

                        # Ask LLM for missing carbon
                        if pd.isna(carbon):
                            # Use LLM numeric prompt with fallback
                            fallback_val = float(area) * 4.0
                            prompt_num = (f"Provide a numeric estimate (one number) of total carbon stored in tonnes "
                                          f"for a {area} hectare {type_} project in {region}.")
                            with st.spinner(f"Estimating carbon for {name}..."):
                                carbon_val = run_ollama_prompt_number(prompt_num, fallback=fallback_val)
                            # get explanation
                            prompt_explain = (f"Explain briefly why the carbon estimate is {carbon_val} tonnes "
                                              f"for a {area} ha {type_} project in {region}.")
                            with st.spinner(f"Generating explanation for {name}..."):
                                explanation_val = run_ollama_prompt_text(prompt_explain)
                            carbon = float(carbon_val)
                            explanation = explanation_val
                        else:
                            carbon = float(carbon)
                            explanation = ""

                        # Insert
                        db_add_project(name, type_, region, float(area), float(carbon), explanation)
                        added += 1
                    except Exception as e:
                        skipped += 1
                        log_debug(f"Skipping row due to error: {e}")
            st.success(f"Bulk import completed: {added} added, {skipped} skipped.")
            do_rerun()

    # ------------------------------
    # Projects Overview (Admin)
    # ------------------------------
    st.subheader("Projects Overview (Admin)")

    df_all = db_get_all_projects()

    if not df_all.empty:
        # Show dataframe (table) for easy scanning
        display_df = df_all[['Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status', 'Created_at']].copy()
        # Format created_at nicely
        try:
            display_df['Created_at'] = display_df['Created_at'].apply(lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if not pd.isna(x) else "")
        except Exception:
            pass

        st.dataframe(display_df, use_container_width=True)

        st.write("")  # spacing

        st.subheader("Manage Projects")

        # Show action buttons per row (delete/retire/issue) and explanation expanders
        for _, row in df_all.iterrows():
            # Layout: left shows name and details; right shows explanation button/expander
            left_col, right_col = st.columns([4, 1])

            with left_col:
                st.markdown(f"**{row['Name']}** — {row['Type']} — {row['Region']}")
                st.markdown(f"- Area: **{row['Area_ha']} ha**")
                st.markdown(f"- Carbon: **{row['Carbon_tonnes']} tonnes**")
                st.markdown(f"- Credits: **{row['Credits']}**")
                st.markdown(f"- Status: **{row['Status']}**")

            with right_col:
                # Explanation expander toggled by a compact button-like element (expander itself is used)
                with st.expander("ℹ️ Explanation", expanded=False):
                    if row['Explanation']:
                        st.write(row['Explanation'])
                    else:
                        st.write("No explanation available for this project.")

            # Action buttons in their own row
            action_col1, action_col2, action_col3 = st.columns([1,1,1])
            with action_col1:
                if st.button(f"🗑️ Delete {row['ID']}", key=f"del_{row['ID']}"):
                    try:
                        db_delete_project(row['ID'])
                        st.success("Deleted project.")
                        do_rerun()
                    except Exception as e:
                        st.error(f"Failed to delete: {e}")
            with action_col2:
                if st.button(f"🚫 Retire {row['ID']}", key=f"ret_{row['ID']}"):
                    try:
                        db_update_status(row['ID'], "Retired")
                        st.success("Project retired.")
                        do_rerun()
                    except Exception as e:
                        st.error(f"Failed to retire: {e}")
            with action_col3:
                if st.button(f"✅ Issue {row['ID']}", key=f"iss_{row['ID']}"):
                    try:
                        db_update_status(row['ID'], "Issued")
                        st.success("Project issued.")
                        do_rerun()
                    except Exception as e:
                        st.error(f"Failed to issue: {e}")
            st.write("---")  # separator
    else:
        st.info("No projects found in database.")

# --------------------------
# Public Dashboard
# --------------------------
def public_dashboard():
    """
    Public dashboard: shows a table of projects and provides an expander with explanation for each project.
    """
    st.title("Public Registry")
    st.write("This public view shows projects and allows users to read LLM explanations (if provided).")

    df_all = db_get_all_projects()

    if not df_all.empty:
        display_df = df_all[['Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status', 'Created_at']].copy()
        try:
            display_df['Created_at'] = display_df['Created_at'].apply(lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if not pd.isna(x) else "")
        except Exception:
            pass

        st.dataframe(display_df, use_container_width=True)

        st.write("")  # spacing
        st.subheader("Project explanations (click to expand)")

        for _, row in df_all.iterrows():
            with st.expander(f"{row['Name']} — {row['Region']} — {row['Type']}"):
                if row['Explanation']:
                    st.write(row['Explanation'])
                else:
                    st.write("No explanation available for this project.")
    else:
        st.info("No projects available to display publicly.")

# --------------------------
# Main application
# --------------------------
def main():
    st.sidebar.title("BlueCarbon Registry")
    st.sidebar.write("Manage and view carbon projects (Admin / Public)")

    # Mode selection
    mode = st.sidebar.selectbox("Mode", ["Public", "Admin"])

    # Simple admin password gate (replace with real auth for production)
    if mode == "Admin":
        st.sidebar.write("Admin access required")
        password = st.sidebar.text_input("Enter Admin Password", type="password")
        if password == "admin123":
            admin_dashboard()
        elif password:
            st.sidebar.error("Incorrect password")
        else:
            st.sidebar.info("Enter admin password to manage projects.")
    else:
        public_dashboard()

# --------------------------
# Run the app
# --------------------------
if __name__ == "__main__":
    # Final check: if DB connection missing, show a clear UI error on startup
    if conn is None or c is None:
        st.title("BlueCarbon Registry — ERROR")
        st.error("Database connection to Supabase failed. Please check SUPABASE_DB_PASSWORD and network access.")
        log_debug("Exiting because DB connection is not available.")
    else:
        main()

