# ===============================================================
# BlueCarbon Registry - Streamlit + Supabase + Phi-3 Mini
# Single-file app (copy-paste into app.py)
# - Hardcoded Supabase DB URL (no secrets.toml required)
# - Phi-3 Mini LLM via local Ollama HTTP API (http://localhost:11434)
# - Manual entry + bulk CSV upload
# - Public & Admin dashboards
# - Caching of LLM outputs
# - Admin controls: Delete / Retire / Issue
# - Record hashing
# ===============================================================

# --------------------------
# Imports
# --------------------------
import os
import json
import time
import hashlib
import traceback
import requests
import sqlite3  # kept for optional fallback, not used by default
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
from psycopg2.extras import RealDictCursor
import psycopg2

# --------------------------
# Basic Configuration
# --------------------------

# --------------------------
# NOTE: This app intentionally embeds your database credentials directly
# so you do not need secrets.toml or environment variables.
# WARNING: Do not share this file publicly with credentials included.
# --------------------------

DATABASE_URL = "postgresql://postgres:mahenoor123@db.hrrmqkjxxyumemtowloy.supabase.co:5432/postgres"

# Ollama / Phi-3 Mini settings — expects Ollama daemon with HTTP API at localhost:11434
OLLAMA_HTTP_URL = os.environ.get("OLLAMA_HTTP_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi-3-mini")
OLLAMA_TIMEOUT = 40  # seconds for HTTP requests to Ollama

# Optional on-chain anchoring (set to None to disable)
EVM_RPC_URL = None
EVM_PRIVATE_KEY = None

# UI / Behavior settings
CACHE_TTL_SEC = 60 * 60  # 1 hour cache for LLM outputs
MAX_CSV_ROWS = 10000  # safety cap to avoid huge uploads crashing memory

# --------------------------
# Utility helpers
# --------------------------
def log(msg: str):
    """Simple timestamped log to console (Streamlit logs)."""
    print(f"[{datetime.now().isoformat()}] {msg}")

def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def canonical_json(obj: Any) -> str:
    """Return canonical compact JSON for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))

def compute_record_hash(record: Dict[str, Any]) -> str:
    """Compute SHA256 hex hash of canonical JSON (prefixed with 0x)."""
    try:
        c = canonical_json(record)
        h = hashlib.sha256(c.encode("utf-8")).hexdigest()
        return "0x" + h
    except Exception as e:
        log(f"Hash error: {e}")
        return ""

# --------------------------
# Database helpers (Supabase Postgres)
# --------------------------
def get_db_conn_cursor():
    """Return a persistent Postgres connection and cursor (RealDictCursor)."""
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode="require")
        cur = conn.cursor()
        return conn, cur
    except Exception as e:
        log(f"Failed to connect to Postgres: {e}")
        raise

# create top-level connection
try:
    conn, cur = get_db_conn_cursor()
    log("Connected to Supabase Postgres.")
except Exception as e:
    conn = None
    cur = None
    log("DB connection not available at startup. App will show error if DB ops attempted.")

def ensure_projects_table():
    """Create projects table if absent."""
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB connection not available.")
    try:
        sql = """
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
        cur.execute(sql)
        conn.commit()
        log("Ensured projects table exists.")
    except Exception as e:
        if conn:
            conn.rollback()
        log(f"Error ensuring projects table: {e}\n{traceback.format_exc()}")
        raise

# Ensure table now (if DB is connected)
if conn is not None and cur is not None:
    try:
        ensure_projects_table()
    except Exception:
        pass

# CRUD wrappers
def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, explanation: str = "", record_hash: Optional[str] = None, onchain_tx: Optional[str] = None, onchain_status: Optional[str] = None) -> int:
    """Insert project in DB and return new id."""
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB not available.")
    try:
        credits = round(float(area) * 0.5 + float(carbon) * 0.2, 2)
        created_at = datetime.now()
        insert_sql = """
            INSERT INTO projects (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation, record_hash, onchain_tx, onchain_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id;
        """
        params = (name, type_, region, area, carbon, credits, "Issued", created_at, explanation, record_hash, onchain_tx, onchain_status)
        cur.execute(insert_sql, params)
        new_id = cur.fetchone()["id"]
        conn.commit()
        log(f"Inserted project id {new_id}")
        return new_id
    except Exception as e:
        if conn:
            conn.rollback()
        log(f"DB insert error: {e}\n{traceback.format_exc()}")
        raise

def db_get_all_projects() -> pd.DataFrame:
    """Fetch all projects ordered by created_at desc and return DataFrame."""
    global conn, cur
    if conn is None or cur is None:
        return pd.DataFrame(columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block'])
    try:
        cur.execute("SELECT id, name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation, record_hash, onchain_tx, onchain_status, onchain_block FROM projects ORDER BY created_at DESC;")
        rows = cur.fetchall()
        if not rows:
            cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame(rows)
        df.rename(columns={
            'id':'ID','name':'Name','type':'Type','region':'Region','area_ha':'Area_ha','carbon_tonnes':'Carbon_tonnes','credits':'Credits','status':'Status','created_at':'Created_at','explanation':'Explanation','record_hash':'Record_Hash','onchain_tx':'Onchain_Tx','onchain_status':'Onchain_Status','onchain_block':'Onchain_Block'
        }, inplace=True)
        cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
        df = df[cols]
        return df
    except Exception as e:
        log(f"DB fetch error: {e}\n{traceback.format_exc()}")
        cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
        return pd.DataFrame(columns=cols)

def db_delete_project(id_: int):
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB not available.")
    try:
        cur.execute("DELETE FROM projects WHERE id = %s", (id_,))
        conn.commit()
        log(f"Deleted project id {id_}")
    except Exception as e:
        conn.rollback()
        log(f"DB delete error: {e}\n{traceback.format_exc()}")
        raise

def db_update_status(id_: int, status: str):
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB not available.")
    try:
        cur.execute("UPDATE projects SET status = %s WHERE id = %s", (status, id_))
        conn.commit()
        log(f"Updated status for id {id_} -> {status}")
    except Exception as e:
        conn.rollback()
        log(f"DB update status error: {e}\n{traceback.format_exc()}")
        raise

def db_update_record_hash_and_onchain(id_: int, record_hash: str, onchain_tx: Optional[str] = None, onchain_status: Optional[str] = None, onchain_block: Optional[int] = None):
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB not available.")
    try:
        cur.execute("UPDATE projects SET record_hash = %s, onchain_tx = %s, onchain_status = %s, onchain_block = %s WHERE id = %s", (record_hash, onchain_tx, onchain_status, onchain_block, id_))
        conn.commit()
        log(f"Updated record_hash/onchain for id {id_}")
    except Exception as e:
        conn.rollback()
        log(f"DB update error: {e}\n{traceback.format_exc()}")
        raise

# --------------------------
# LLM helpers (Ollama HTTP)
# --------------------------

def run_ollama_text(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    """
    Call the local Ollama HTTP API (assumes Ollama running with API enabled).
    We use a simple request to the generate endpoint.
    """
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "max_tokens": 256,
            "temperature": 0.0,
            "stream": False
        }
        resp = requests.post(OLLAMA_HTTP_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # Ollama local API may return {"response": "..."} or similar; handle robustly:
        if isinstance(data, dict):
            # check standard keys
            if "response" in data:
                return str(data["response"]).strip()
            if "text" in data:
                return str(data["text"]).strip()
            # fallback: stringify body
            return json.dumps(data)[:1000]
        return str(data)[:1000]
    except requests.exceptions.RequestException as e:
        log(f"Ollama HTTP error: {e}")
        return f"(LLM request error: {e})"
    except Exception as e:
        log(f"Ollama exception: {e}\n{traceback.format_exc()}")
        return f"(LLM exception: {e})"

def run_ollama_number(prompt: str, fallback: float = 0.0) -> float:
    """Ask LLM for a number and try to parse first numeric token that looks like a float."""
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
        log(f"Could not parse numeric from LLM output: {txt}")
        return fallback
    except Exception as e:
        log(f"Error parsing number from LLM output: {e}")
        return fallback

# --------------------------
# High-level cached estimator
# --------------------------
@st.cache_data(ttl=CACHE_TTL_SEC)
def cached_estimate(area: float, type_: str, region: str) -> dict:
    """Return {'carbon': float, 'explanation': str} from the LLM, cached."""
    try:
        prompt_num = f"Provide a single numeric estimate (tonnes) of total carbon stored for a {area} ha {type_} project in {region}."
        numeric = run_ollama_number(prompt_num, fallback=area * 4.0)
        prompt_explain = f"Explain in simple terms why the carbon for a {area} ha {type_} project in {region} is around {numeric} tonnes."
        explanation = run_ollama_text(prompt_explain)
        return {"carbon": float(numeric), "explanation": explanation}
    except Exception as e:
        log(f"cached_estimate error: {e}\n{traceback.format_exc()}")
        return {"carbon": area * 4.0, "explanation": f"Fallback estimate: {area * 4.0} t (LLM error)"}

# --------------------------
# Optional Web3 anchoring (placeholder)
# --------------------------
# For this version we keep anchoring optional and non-fatal if not configured.
try:
    from web3 import Web3
except Exception:
    Web3 = None

w3 = None
if Web3 and EVM_RPC_URL:
    try:
        w3 = Web3(Web3.HTTPProvider(EVM_RPC_URL))
        if not w3.isConnected():
            log("Web3 provider provided but connection failed.")
            w3 = None
        else:
            log("Web3 connected.")
    except Exception as e:
        log(f"Web3 init error: {e}")
        w3 = None

def anchor_hash_on_chain(hex_hash: str, wait_for_receipt: bool = False) -> dict:
    """Anchor a hex hash on-chain. Non-fatal if Web3 not available."""
    result = {"success": False, "tx_hash": None, "error": None, "receipt": None}
    if w3 is None:
        result["error"] = "Web3 not configured"
        return result
    if not EVM_PRIVATE_KEY:
        result["error"] = "EVM private key not set"
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
        tx_hex = w3.toHex(tx_hash)
        result["success"] = True
        result["tx_hash"] = tx_hex
        if wait_for_receipt:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            result["receipt"] = dict(receipt)
            result["onchain_block"] = receipt.blockNumber
        return result
    except Exception as e:
        result["error"] = str(e)
        log(f"Anchor error: {e}\n{traceback.format_exc()}")
        return result

# --------------------------
# Session-state keys for caching per-session
# --------------------------
def ensure_session_state():
    if "est_cache" not in st.session_state:
        st.session_state["est_cache"] = {}  # key -> (carbon, explanation)
    if "last_action" not in st.session_state:
        st.session_state["last_action"] = None

ensure_session_state()

# --------------------------
# Streamlit UI layout
# --------------------------
st.set_page_config(page_title="BlueCarbon Registry", layout="wide")
st.title("🌱 BlueCarbon Registry")
st.markdown("Shared registry with Phi-3 Mini predictions. Everyone sees projects stored centrally in Supabase.")

# Sidebar admin access (simple)
st.sidebar.header("Admin Access")
admin_pwd = st.sidebar.text_input("Admin password (default 'admin123')", type="password")
is_admin = (admin_pwd == "admin123")

# Top navigation
tab = st.sidebar.radio("View", ["Public Dashboard", "Admin Dashboard", "Add Project", "Bulk Upload"])

# --------------------------
# Add Project (manual)
# --------------------------
if tab == "Add Project":
    st.header("Add a New Project — Manual Entry")
    with st.form("manual_project_form"):
        name = st.text_input("Project Name")
        type_ = st.selectbox("Project Type", ["Mangrove", "Afforestation", "Reforestation", "Agroforestry", "Other"])
        region = st.text_input("Region / Location")
        area = st.number_input("Area (ha)", min_value=0.0, format="%.3f")
        carbon = st.number_input("Carbon (tonnes) — leave 0 to auto-estimate", min_value=0.0, format="%.3f", value=0.0)
        anchor_opt = st.checkbox("Anchor record on-chain (optional)")
        submit = st.form_submit_button("Add Project")

    if submit:
        if not name or not type_ or not region or area <= 0:
            st.error("Please provide Name, Type, Region and Area > 0.")
        else:
            # Determine carbon & explanation
            if carbon == 0.0:
                cache_key = f"{area}|{type_}|{region}"
                if cache_key in st.session_state["est_cache"]:
                    carbon_val, explanation = st.session_state["est_cache"][cache_key]
                    log("Using session cached estimate.")
                else:
                    # Use cached_estimate (global cache) to avoid repeated LLM calls across sessions
                    with st.spinner("Estimating carbon using Phi-3 Mini..."):
                        est = cached_estimate(area, type_, region)
                        carbon_val = float(est.get("carbon", area * 4.0))
                        explanation = est.get("explanation", "")
                    st.session_state["est_cache"][cache_key] = (carbon_val, explanation)
            else:
                carbon_val = float(carbon)
                explanation = f"Manually entered: {carbon_val} tonnes."

            # Insert into DB
            try:
                rec = {
                    "name": name,
                    "type": type_,
                    "region": region,
                    "area_ha": area,
                    "carbon_tonnes": carbon_val,
                    "created_at": datetime.now().isoformat()
                }
                rec_hash = compute_record_hash(rec)
                new_id = db_add_project(name, type_, region, area, carbon_val, explanation, rec_hash, None, "not_anchored")
                st.success(f"Project added with id {new_id}.")
                # Optional anchor
                if anchor_opt and w3 and EVM_PRIVATE_KEY:
                    with st.spinner("Anchoring on-chain..."):
                        res = anchor_hash_on_chain(rec_hash, wait_for_receipt=False)
                        if res.get("success"):
                            db_update_record_hash_and_onchain(new_id, rec_hash, res.get("tx_hash"), "pending")
                            st.success(f"Anchored on-chain, tx: {res.get('tx_hash')}")
                        else:
                            st.error(f"Anchoring failed: {res.get('error')}")
                # mark last action
                st.session_state["last_action"] = f"added_{new_id}"
            except Exception as e:
                st.error(f"Failed to add project: {e}")
                log(f"Add project error: {e}\n{traceback.format_exc()}")

# --------------------------
# Bulk Upload
# --------------------------
elif tab == "Bulk Upload":
    st.header("Bulk CSV Upload")
    st.markdown("CSV must have columns: name,type,region,area_ha,carbon_tonnes (carbon_tonnes optional or 0 to auto-estimate).")
    uploaded = st.file_uploader("Upload CSV file(s)", type=["csv"], accept_multiple_files=True)
    if uploaded:
        for f in uploaded:
            st.markdown(f"**File:** {f.name}")
            try:
                df = pd.read_csv(f)
                st.dataframe(df.head(5))
                if len(df) > MAX_CSV_ROWS:
                    st.error(f"File too large (> {MAX_CSV_ROWS} rows). Skipping.")
                    continue
                if st.button(f"Process {f.name}"):
                    added = 0
                    skipped = 0
                    for _, row in df.iterrows():
                        try:
                            name = row.get("name")
                            type_ = row.get("type", "Other")
                            region = row.get("region", "Unknown")
                            area = safe_float(row.get("area_ha"))
                            carbon_in = row.get("carbon_tonnes", 0)
                            if area <= 0 or not name:
                                skipped += 1
                                continue
                            if pd.isna(carbon_in) or float(carbon_in) == 0.0:
                                est = cached_estimate(area, type_, region)
                                cval = float(est.get("carbon", area * 4.0))
                                explanation = est.get("explanation", "")
                            else:
                                cval = float(carbon_in)
                                explanation = f"Manually provided in CSV: {cval} tonnes."
                            rec = {"name": name, "type": type_, "region": region, "area_ha": area, "carbon_tonnes": cval, "created_at": datetime.now().isoformat()}
                            rec_hash = compute_record_hash(rec)
                            new_id = db_add_project(name, type_, region, area, cval, explanation, rec_hash, None, "not_anchored")
                            added += 1
                        except Exception as e:
                            log(f"Bulk row error: {e}")
                            skipped += 1
                    st.success(f"Bulk upload complete. Added: {added}, Skipped: {skipped}")
            except Exception as e:
                st.error(f"Failed to read {f.name}: {e}")

# --------------------------
# Admin Dashboard
# --------------------------
elif tab == "Admin Dashboard":
    st.header("Admin Dashboard")
    if not is_admin:
        st.warning("Enter admin password in sidebar to manage projects.")
    df = db_get_all_projects()
    if df.empty:
        st.info("No projects yet.")
    else:
        # show a search/filter bar
        st.markdown("## Projects")
        cols = st.columns([3,2,2,1])
        with cols[0]:
            q_name = st.text_input("Filter by name")
        with cols[1]:
            q_region = st.text_input("Filter by region")
        with cols[2]:
            q_type = st.text_input("Filter by type")
        with cols[3]:
            q_status = st.selectbox("Status", ["All", "Issued", "Retired", "Active"], index=0)

        filtered = df.copy()
        if q_name:
            filtered = filtered[filtered['Name'].str.contains(q_name, case=False, na=False)]
        if q_region:
            filtered = filtered[filtered['Region'].str.contains(q_region, case=False, na=False)]
        if q_type:
            filtered = filtered[filtered['Type'].str.contains(q_type, case=False, na=False)]
        if q_status and q_status != "All":
            filtered = filtered[filtered['Status'].str.contains(q_status, case=False, na=False)]

        st.dataframe(filtered[['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at']].reset_index(drop=True), use_container_width=True)

        st.markdown("---")
        st.markdown("### Manage individual projects")
        for _, row in filtered.iterrows():
            cols = st.columns([4,1,1,1,1])
            with cols[0]:
                st.markdown(f"**{row['Name']}** — {row['Type']} — {row['Region']}")
                st.write(f"Area: {row['Area_ha']} ha | Carbon: {row['Carbon_tonnes']} t | Credits: {row['Credits']} | Status: {row['Status']}")
                st.write(f"Created: {row['Created_at']}")
                with st.expander("Explanation"):
                    st.write(row['Explanation'] or "No explanation available")
                st.write(f"Record Hash: {row['Record_Hash'] or '—'}")
                st.write(f"On-chain Tx: {row['Onchain_Tx'] or '—'} | On-chain Status: {row['Onchain_Status'] or '—'}")
            # action buttons
            with cols[1]:
                if st.button("🗑 Delete", key=f"del_{row['ID']}"):
                    if not is_admin:
                        st.error("Admin password required.")
                    else:
                        try:
                            db_delete_project(int(row['ID']))
                            st.success("Deleted.")
                            time.sleep(0.2)
                            st.experimental_rerun()
                        except Exception as e:
                            st.error(f"Delete failed: {e}")
            with cols[2]:
                if st.button("🚫 Retire", key=f"ret_{row['ID']}"):
                    if not is_admin:
                        st.error("Admin password required.")
                    else:
                        try:
                            db_update_status(int(row['ID']), "Retired")
                            st.success("Retired.")
                            time.sleep(0.2)
                            st.experimental_rerun()
                        except Exception as e:
                            st.error(f"Retire failed: {e}")
            with cols[3]:
                if st.button("✅ Issue", key=f"iss_{row['ID']}"):
                    if not is_admin:
                        st.error("Admin password required.")
                    else:
                        try:
                            db_update_status(int(row['ID']), "Issued")
                            st.success("Issued.")
                            time.sleep(0.2)
                            st.experimental_rerun()
                        except Exception as e:
                            st.error(f"Issue failed: {e}")
            with cols[4]:
                if st.button("🔁 Recompute LLM", key=f"llm_{row['ID']}"):
                    if not is_admin:
                        st.error("Admin password required.")
                    else:
                        try:
                            area_val = float(row['Area_ha'] or 0)
                            type_val = str(row['Type'] or "")
                            region_val = str(row['Region'] or "")
                            with st.spinner("Recomputing estimate..."):
                                est = cached_estimate(area_val, type_val, region_val)
                                new_carbon = float(est.get("carbon", area_val * 4.0))
                                expl = est.get("explanation", "")
                                # update record in DB
                                cur.execute("UPDATE projects SET carbon_tonnes=%s, explanation=%s WHERE id=%s", (new_carbon, expl, int(row['ID'])))
                                conn.commit()
                                st.success("LLM re-run saved.")
                                time.sleep(0.2)
                                st.experimental_rerun()
                        except Exception as e:
                            st.error(f"LLM recompute failed: {e}")

            st.markdown("---")

# --------------------------
# Public Dashboard
# --------------------------
elif tab == "Public Dashboard":
    st.header("Public Registry — All Projects")
    df = db_get_all_projects()
    if df.empty:
        st.info("No projects available yet.")
    else:
        # simple filters
        c1, c2, c3 = st.columns([3,2,2])
        with c1:
            q = st.text_input("Search project name or region")
        with c2:
            tfilter = st.selectbox("Project type", ["All"] + sorted(df['Type'].dropna().unique().tolist()))
        with c3:
            sfilter = st.selectbox("Status", ["All"] + sorted(df['Status'].dropna().unique().tolist()))
        display = df.copy()
        if q:
            display = display[display['Name'].str.contains(q, case=False, na=False) | display['Region'].str.contains(q, case=False, na=False)]
        if tfilter and tfilter != "All":
            display = display[display['Type'] == tfilter]
        if sfilter and sfilter != "All":
            display = display[display['Status'] == sfilter]
        # show table
        st.dataframe(display[['Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at']].reset_index(drop=True), use_container_width=True)
        st.markdown("### Explanations")
        for _, row in display.iterrows():
            with st.expander(f"{row['Name']} — {row['Region']} — {row['Type']}"):
                st.write(f"- **Area (ha):** {row['Area_ha']}")
                st.write(f"- **Carbon (t):** {row['Carbon_tonnes']}")
                st.write(f"- **Credits:** {row['Credits']}")
                st.write(f"- **Status:** {row['Status']}")
                st.write(f"- **Created:** {row['Created_at']}")
                st.markdown("**Explanation:**")
                st.write(row['Explanation'] or "No explanation available.")
                st.markdown(f"- **Record hash:** {row['Record_Hash'] or '—'}")
                st.markdown(f"- **On-chain tx:** {row['Onchain_Tx'] or '—'}")
                st.markdown(f"- **On-chain status:** {row['Onchain_Status'] or '—'}")

# --------------------------
# Footer
# --------------------------
st.markdown("---")
st.caption("BlueCarbon Registry — Supabase + Phi-3 Mini (Ollama). Admin password is 'admin123' (change in code for production).")

# End of file
