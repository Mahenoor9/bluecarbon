# --------------------------
# BlueCarbon Registry Streamlit App
# Supabase + Phi-3 Mini + optional EVM anchoring
# ~700+ lines
# --------------------------

import os
import json
import hashlib
import subprocess
import traceback
import io
from datetime import datetime

import streamlit as st
import pandas as pd
from psycopg2.extras import RealDictCursor
import psycopg2

# Optional web3 for on-chain anchoring
try:
    from web3 import Web3
except ImportError:
    Web3 = None

# --------------------------
# Config / Secrets
# --------------------------

# DATABASE URL (Supabase)
DATABASE_URL = None
if "database" in st.secrets and "url" in st.secrets["database"]:
    DATABASE_URL = st.secrets["database"]["url"]
else:
    DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL")

# EVM optional (skip if not configured)
EVM_RPC_URL = None
EVM_PRIVATE_KEY = None
if "evm" in st.secrets:
    EVM_RPC_URL = st.secrets["evm"].get("rpc_url")
    EVM_PRIVATE_KEY = st.secrets["evm"].get("private_key")

# Ollama model
OLLAMA_MODEL = st.secrets.get("ollama", {}).get("model", "phi-3-mini") if "ollama" in st.secrets else os.environ.get("OLLAMA_MODEL", "phi-3-mini")
OLLAMA_TIMEOUT = 20

# --------------------------
# Helper functions
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
# Database helpers
# --------------------------

def get_db_conn_cursor():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured. Please set in secrets.toml or environment variable.")
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode="require")
        cur = conn.cursor()
        return conn, cur
    except Exception as e:
        log_debug(f"Failed to connect to DB: {e}")
        raise

try:
    conn, cur = get_db_conn_cursor()
    log_debug("Connected to Supabase successfully.")
except Exception:
    conn = None
    cur = None
    log_debug("Database not available at startup.")

def ensure_projects_table():
    if conn is None or cur is None:
        raise RuntimeError("DB not available.")
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
        log_debug("Ensured projects table exists.")
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
# Ollama helpers
# --------------------------

def run_ollama_text(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    try:
        cmd = ["ollama", "run", model, "--prompt", prompt]
        log_debug(f"OLLAMA CMD: {' '.join(cmd[:3])} ... (prompt hidden)")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        if proc.returncode != 0:
            return f"(LLM error: {err or 'unknown'})"
        if out:
            return out
        if err:
            return err
        return "(LLM returned no output)"
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
                val = float(tok2)
                return val
            except Exception:
                continue
        log_debug(f"Could not parse numeric from LLM output: {txt}")
        return fallback
    except Exception as e:
        log_debug(f"Parsing number error: {e}")
        return fallback

# --------------------------
# Record hash / optional EVM
# --------------------------

def compute_record_hash(record: dict) -> str:
    try:
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return "0x" + h
    except Exception as e:
        log_debug(f"Hashing error: {e}")
        return ""

# Initialize Web3 safely
w3 = None
if Web3 and EVM_RPC_URL:
    try:
        w3 = Web3(Web3.HTTPProvider(EVM_RPC_URL))
        if not w3.isConnected():
            log_debug("Web3 RPC not connected")
            w3 = None
        else:
            log_debug("Web3 connected")
    except Exception as e:
        log_debug(f"Web3 init error: {e}")
        w3 = None

def anchor_hash_on_chain(hex_hash: str, wait_for_receipt: bool = False) -> dict:
    result = {"success": False, "tx_hash": None, "error": None, "receipt": None}
    if not w3 or not EVM_PRIVATE_KEY:
        result["error"] = "Web3 not configured"
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
        log_debug(f"Anchor error: {e}")
        return result

# --------------------------
# Database CRUD
# --------------------------

def db_add_project(name, type_, region, area, carbon, explanation="", record_hash=None, onchain_tx=None, onchain_status=None):
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB not available")
    credits = round(float(area)*0.5 + float(carbon)*0.2, 2)
    created_at = datetime.now()
    try:
        sql = """
        INSERT INTO projects
        (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation, record_hash, onchain_tx, onchain_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """
        params = (name, type_, region, area, carbon, credits, "Issued", created_at, explanation, record_hash, onchain_tx, onchain_status)
        cur.execute(sql, params)
        new_id = cur.fetchone()["id"]
        conn.commit()
        return new_id
    except Exception as e:
        conn.rollback()
        log_debug(f"DB insert error: {e}")
        raise

def db_update_record_hash_and_onchain(id_, record_hash, onchain_tx=None, onchain_status=None, onchain_block=None):
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB not available")
    try:
        sql = """
        UPDATE projects SET record_hash=%s,onchain_tx=%s,onchain_status=%s,onchain_block=%s WHERE id=%s
        """
        cur.execute(sql, (record_hash, onchain_tx, onchain_status, onchain_block, id_))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log_debug(f"DB update error: {e}")
        raise

def db_delete_project(id_):
    global conn, cur
    try:
        cur.execute("DELETE FROM projects WHERE id=%s", (id_,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log_debug(f"DB delete error: {e}")
        raise

def db_update_status(id_, status):
    global conn, cur
    try:
        cur.execute("UPDATE projects SET status=%s WHERE id=%s", (status, id_))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log_debug(f"DB update status error: {e}")
        raise

def db_get_all_projects():
    global conn, cur
    try:
        cur.execute("SELECT * FROM projects ORDER BY created_at DESC")
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame(columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block'])
        df = pd.DataFrame(rows)
        df.rename(columns={
            'id':'ID','name':'Name','type':'Type','region':'Region','area_ha':'Area_ha',
            'carbon_tonnes':'Carbon_tonnes','credits':'Credits','status':'Status','created_at':'Created_at',
            'explanation':'Explanation','record_hash':'Record_Hash','onchain_tx':'Onchain_Tx',
            'onchain_status':'Onchain_Status','onchain_block':'Onchain_Block'
        }, inplace=True)
        return df
    except Exception as e:
        log_debug(f"DB fetch error: {e}")
        return pd.DataFrame(columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block'])

# --------------------------
# Session state caching
# --------------------------

def ensure_session_keys():
    if 'est_cache' not in st.session_state:
        st.session_state['est_cache'] = {}
    if 'explain_cache' not in st.session_state:
        st.session_state['explain_cache'] = {}

# --------------------------
# Streamlit Admin Dashboard
# --------------------------

def admin_dashboard():
    ensure_session_keys()
    st.title("Admin Dashboard - BlueCarbon")
    st.markdown("Manual entry or CSV upload. Carbon 0 → Phi-3 Mini prediction. Optional EVM anchoring.")

    mode = st.radio("Input Mode", ["Manual Entry", "Bulk CSV Upload"])

    # Manual
    if mode == "Manual Entry":
        st.subheader("Manual Entry")
        with st.form("manual_form", clear_on_submit=False):
            name = st.text_input("Project Name")
            type_ = st.text_input("Project Type")
            region = st.text_input("Region")
            area = st.number_input("Area (ha)", min_value=0.0, value=0.0, format="%.4f")
            carbon = st.number_input("Carbon (tonnes, 0→LLM estimate)", min_value=0.0, value=0.0, format="%.4f")
            anchor_onchain = st.checkbox("Anchor on-chain (optional)")
            submit = st.form_submit_button("Add Project")

        if submit:
            if not name or not type_ or not region or area <= 0:
                st.error("Provide Name, Type, Region, Area>0")
            else:
                if carbon == 0.0:
                    key = f"{area}|{type_}|{region}"
                    if key in st.session_state['est_cache']:
                        est_val, expl = st.session_state['est_cache'][key]
                    else:
                        fallback = area*4.0
                        est_val = run_ollama_number(f"Estimate carbon tonnes for {area} ha {type_} in {region}", fallback)
                        expl = run_ollama_text(f"Explain why carbon for {area} ha {type_} in {region} is {est_val} tonnes")
                        st.session_state['est_cache'][key] = (est_val, expl)
                    carbon_val = safe_float(est_val)
                    explanation = expl
                else:
                    carbon_val = safe_float(carbon)
                    explanation = f"Carbon manually entered: {carbon_val} tonnes"

                new_id = db_add_project(name, type_, region, area, carbon_val, explanation)
                rec_hash = compute_record_hash({
                    "id": new_id,"name":name,"type":type_,"region":region,"area_ha":area,"carbon_tonnes":carbon_val,
                    "created_at": datetime.now().isoformat()
                })
                db_update_record_hash_and_onchain(new_id, rec_hash, None, "not_anchored")

                if anchor_onchain and w3 and EVM_PRIVATE_KEY:
                    anchor_res = anchor_hash_on_chain(rec_hash, wait_for_receipt=False)
                    if anchor_res.get("success"):
                        db_update_record_hash_and_onchain(new_id, rec_hash, anchor_res.get("tx_hash"), "pending")
                        st.success(f"Anchored on-chain. Tx: {anchor_res.get('tx_hash')}")
                st.success(f"Project added. ID {new_id}")
                do_rerun_browser_safe()

    # Bulk CSV
    elif mode == "Bulk CSV Upload":
        st.subheader("Bulk CSV Upload")
        uploaded = st.file_uploader("Upload CSVs", type=["csv"], accept_multiple_files=True)
        previews = []
        if uploaded:
            for f in uploaded:
                try:
                    df = pd.read_csv(f)
                    st.markdown(f"### {f.name}")
                    st.dataframe(df.head())
                    previews.append(df)
                except Exception as e:
                    st.warning(f"{f.name} read failed: {e}")

        with st.form("bulk_form"):
            anchor_bulk = st.checkbox("Anchor all on-chain if possible")
            bulk_submit = st.form_submit_button("Add All Projects")

        if bulk_submit and previews:
            added = 0
            skipped = 0
            for df in previews:
                for _, row in df.iterrows():
                    try:
                        name=row.get("name"); type_=row.get("type"); region=row.get("region")
                        area=row.get("area_ha"); carbon=row.get("carbon_tonnes")
                        if pd.isna(area) or float(area)<=0: skipped+=1; continue
                        if pd.isna(carbon) or float(carbon)==0.0:
                            fallback=float(area)*4.0
                            carbon=run_ollama_number(f"Estimate carbon {area} ha {type_} {region}", fallback)
                            explanation=run_ollama_text(f"Explain carbon {area} ha {type_} {region} = {carbon}")
                        else:
                            carbon=float(carbon); explanation=""
                        new_id=db_add_project(name,type_,region,float(area),float(carbon),explanation)
                        rec_hash=compute_record_hash({"id":new_id,"name":name,"type":type_,"region":region,"area_ha":float(area),"carbon_tonnes":float(carbon),"created_at":datetime.now().isoformat()})
                        db_update_record_hash_and_onchain(new_id,rec_hash,None,"not_anchored")
                        if anchor_bulk and w3 and EVM_PRIVATE_KEY:
                            anchor_res=anchor_hash_on_chain(rec_hash)
                            if anchor_res.get("success"):
                                db_update_record_hash_and_onchain(new_id,rec_hash,anchor_res.get("tx_hash"),"pending")
                        added+=1
                    except Exception as e:
                        log_debug(f"Bulk error: {e}")
                        skipped+=1
            st.success(f"Bulk upload done. Added {added}, skipped {skipped}")
            do_rerun_browser_safe()

    # Projects overview
    st.subheader("Projects Overview")
    df=db_get_all_projects()
    if not df.empty:
        display=df[['Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Record_Hash','Onchain_Status']].copy()
        st.dataframe(display,use_container_width=True)
        st.write("---")
        st.markdown("**Manage projects**")
        for _, row in df.iterrows():
            left,right=st.columns([4,2])
            with left:
                st.markdown(f"### {row['Name']}")
                st.markdown(f"- Type: {row['Type']}")
                st.markdown(f"- Region: {row['Region']}")
                st.markdown(f"- Area: {row['Area_ha']} ha")
                st.markdown(f"- Carbon: {row['Carbon_tonnes']} t")
                st.markdown(f"- Credits: {row['Credits']}")
                st.markdown(f"- Status: {row['Status']}")
                st.markdown(f"- Created at: {row['Created_at']}")
                st.markdown(f"- Record Hash: {row['Record_Hash']}")
                st.markdown(f"- On-chain tx: {row['Onchain_Tx'] or '—'}")
                st.markdown(f"- On-chain status: {row['Onchain_Status'] or '—'}")
            with right:
                with st.expander("ℹ️ Explanation"):
                    st.write(row['Explanation'] or "No explanation")
                if st.button(f"🗑️ Delete {row['ID']}", key=f"del_{row['ID']}"):
                    db_delete_project(row['ID'])
                    do_rerun_browser_safe()
                if st.button(f"🚫 Retire {row['ID']}", key=f"ret_{row['ID']}"):
                    db_update_status(row['ID'],"Retired")
                    do_rerun_browser_safe()
                if st.button(f"✅ Issue {row['ID']}", key=f"iss_{row['ID']}"):
                    db_update_status(row['ID'],"Issued")
                    do_rerun_browser_safe()
            st.write("---")
    else:
        st.info("No projects yet.")

# --------------------------
# Public Dashboard
# --------------------------

def public_dashboard():
    st.title("Public Registry - BlueCarbon")
    df=db_get_all_projects()
    if not df.empty:
        display=df[['Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Record_Hash','Onchain_Status']].copy()
        st.dataframe(display,use_container_width=True)
        st.subheader("Explanations")
        for _, row in df.iterrows():
            with st.expander(f"{row['Name']} — {row['Region']} — {row['Type']}"):
                st.write(row['Explanation'] or "No explanation")
                st.markdown(f"- Record hash: {row['Record_Hash'] or '—'}")
                st.markdown(f"- On-chain status: {row['Onchain_Status'] or '—'}")
    else:
        st.info("No projects uploaded yet.")

# --------------------------
# Browser safe rerun
# --------------------------

def do_rerun_browser_safe():
    if st._is_running_with_streamlit:
        st.experimental_rerun()

# --------------------------
# Main
# --------------------------

def main():
    st.set_page_config(page_title="BlueCarbon Registry", layout="wide")
    st.sidebar.title("BlueCarbon")
    view_mode = st.sidebar.radio("View As", ["Public", "Admin"])
    if view_mode=="Admin":
        admin_dashboard()
    else:
        public_dashboard()

if __name__=="__main__":
    main()
