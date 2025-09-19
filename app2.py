"""
BlueCarbon Registry - Centralized Supabase Version

Features:
- Supabase PostgreSQL backend (everyone sees all projects)
- Admin dashboard: manual + CSV upload
- Public dashboard: read-only view
- Phi-3 Mini LLM generates numeric carbon estimate + explanation automatically
- Caching to avoid repeated LLM calls
- Project table with explanation expanders
- Status buttons: Delete / Retire / Issue
- Record hashing & optional on-chain anchoring (EVM-compatible)
- Defensive error handling

Dependencies:
- streamlit, pandas, psycopg2-binary, web3

Secrets:
- st.secrets['database']['url'] = "postgresql://postgres:YOUR_PW@db.<your-ref>.supabase.co:5432/postgres"
- st.secrets['evm']['rpc_url'] = "https://polygon-mumbai.g.alchemy.com/v2/YOUR_ALCHEMY_KEY"
- st.secrets['evm']['private_key'] = "YOUR_PRIVATE_KEY"
- st.secrets['ollama']['model'] = "phi-3-mini"
"""

# --------------------------
# Imports
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
from web3 import Web3

# --------------------------
# Config / Secrets
# --------------------------
DATABASE_URL = st.secrets.get("database", {}).get("url") or os.environ.get("SUPABASE_DATABASE_URL")
EVM_RPC_URL = st.secrets.get("evm", {}).get("rpc_url") or os.environ.get("EVM_RPC_URL")
EVM_PRIVATE_KEY = st.secrets.get("evm", {}).get("private_key") or os.environ.get("EVM_PRIVATE_KEY")
OLLAMA_MODEL = st.secrets.get("ollama", {}).get("model", "phi-3-mini") or os.environ.get("OLLAMA_MODEL", "phi-3-mini")
OLLAMA_TIMEOUT = 20

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
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured. Use st.secrets['database']['url']")
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode="require")
        cur = conn.cursor()
        return conn, cur
    except Exception as e:
        log_debug(f"DB connect error: {e}")
        raise

try:
    conn, cur = get_db_conn_cursor()
    log_debug("Connected to Supabase PostgreSQL successfully.")
except:
    conn = None
    cur = None
    log_debug("Database connection not available at startup.")

# --------------------------
# Ensure projects table
# --------------------------
def ensure_projects_table():
    global conn, cur
    if not conn or not cur:
        raise RuntimeError("DB not available")
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
        log_debug("Ensured projects table exists.")
    except Exception as e:
        if conn:
            conn.rollback()
        log_debug(f"Error creating projects table: {e}\n{traceback.format_exc()}")
        raise

if conn and cur:
    try:
        ensure_projects_table()
    except:
        pass

# --------------------------
# Ollama LLM helpers
# --------------------------
def run_ollama_text(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    try:
        cmd = ["ollama", "run", model, "--prompt", prompt]
        log_debug(f"OLLAMA CMD: {' '.join(cmd[:3])} ...")
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
    txt = run_ollama_text(prompt)
    try:
        tokens = txt.replace(",", " ").split()
        for tok in tokens:
            try:
                return float(tok.strip(".,:;()[]\"'"))
            except:
                continue
        log_debug(f"Cannot parse number from LLM output: {txt}")
        return fallback
    except Exception as e:
        log_debug(f"Error parsing number: {e}")
        return fallback

# --------------------------
# Record hashing & web3
# --------------------------
def compute_record_hash(record: dict) -> str:
    try:
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        return "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except Exception as e:
        log_debug(f"Hashing error: {e}")
        return ""

def init_web3():
    if not EVM_RPC_URL:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(EVM_RPC_URL))
        if not w3.isConnected():
            log_debug("Web3 connection failed")
            return None
        return w3
    except Exception as e:
        log_debug(f"Web3 init failed: {e}")
        return None

w3 = init_web3()
if w3:
    log_debug("Web3 connected")
else:
    log_debug("Web3 not initialized")

def anchor_hash_on_chain(hex_hash: str, wait_for_receipt: bool = False) -> dict:
    res = {"success": False, "tx_hash": None, "error": None, "receipt": None}
    if not w3:
        res["error"] = "Web3 not configured"
        return res
    if not EVM_PRIVATE_KEY:
        res["error"] = "Private key missing"
        return res
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
        res["tx_hash"] = w3.toHex(tx_hash)
        res["success"] = True
        if wait_for_receipt:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            res["receipt"] = dict(receipt)
            res["onchain_block"] = receipt.blockNumber
        return res
    except Exception as e:
        res["error"] = str(e)
        log_debug(f"Anchor error: {e}")
        return res

# --------------------------
# DB CRUD
# --------------------------
def db_add_project(name, type_, region, area, carbon, explanation="", record_hash=None, onchain_tx=None, onchain_status=None):
    global conn, cur
    if not conn or not cur:
        raise RuntimeError("DB not available")
    credits = round(area*0.5 + carbon*0.2,2)
    try:
        sql = """
        INSERT INTO projects (name,type,region,area_ha,carbon_tonnes,credits,status,created_at,explanation,record_hash,onchain_tx,onchain_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),%s,%s,%s,%s) RETURNING id;
        """
        params = (name,type_,region,area,carbon,credits,"Issued",explanation,record_hash,onchain_tx,onchain_status)
        cur.execute(sql, params)
        new_id = cur.fetchone()["id"]
        conn.commit()
        log_debug(f"Inserted project {new_id}")
        return new_id
    except Exception as e:
        conn.rollback()
        log_debug(f"Insert error: {e}")
        raise

def db_update_record_hash_and_onchain(id_, record_hash, onchain_tx=None, onchain_status=None, onchain_block=None):
    global conn, cur
    try:
        cur.execute(
            "UPDATE projects SET record_hash=%s,onchain_tx=%s,onchain_status=%s,onchain_block=%s WHERE id=%s",
            (record_hash,onchain_tx,onchain_status,onchain_block,id_)
        )
        conn.commit()
        log_debug(f"Updated record_hash/onchain for {id_}")
    except Exception as e:
        conn.rollback()
        log_debug(f"Update error: {e}")
        raise

def db_delete_project(id_):
    global conn, cur
    try:
        cur.execute("DELETE FROM projects WHERE id=%s",(id_,))
        conn.commit()
        log_debug(f"Deleted project {id_}")
    except Exception as e:
        conn.rollback()
        log_debug(f"Delete error: {e}")
        raise

def db_update_status(id_, status):
    global conn, cur
    try:
        cur.execute("UPDATE projects SET status=%s WHERE id=%s",(status,id_))
        conn.commit()
        log_debug(f"Updated status {id_} -> {status}")
    except Exception as e:
        conn.rollback()
        log_debug(f"Update status error: {e}")
        raise

def db_get_all_projects():
    global conn, cur
    try:
        cur.execute("SELECT id,name,type,region,area_ha,carbon_tonnes,credits,status,created_at,explanation,record_hash,onchain_tx,onchain_status,onchain_block FROM projects ORDER BY created_at DESC")
        rows = cur.fetchall()
        if not rows:
            cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame(rows)
        df.rename(columns={'id':'ID','name':'Name','type':'Type','region':'Region','area_ha':'Area_ha','carbon_tonnes':'Carbon_tonnes','credits':'Credits','status':'Status','created_at':'Created_at','explanation':'Explanation','record_hash':'Record_Hash','onchain_tx':'Onchain_Tx','onchain_status':'Onchain_Status','onchain_block':'Onchain_Block'}, inplace=True)
        df = df[['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']]
        return df
    except Exception as e:
        log_debug(f"Fetch error: {e}")
        cols = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation','Record_Hash','Onchain_Tx','Onchain_Status','Onchain_Block']
        return pd.DataFrame(columns=cols)

# --------------------------
# Session cache
# --------------------------
def ensure_session_keys():
    if 'est_cache' not in st.session_state:
        st.session_state['est_cache'] = {}
    if 'explain_cache' not in st.session_state:
        st.session_state['explain_cache'] = {}

# --------------------------
# Safe rerun
# --------------------------
def do_rerun_browser_safe():
    try:
        if hasattr(st,"rerun"):
            st.rerun()
        elif hasattr(st,"experimental_rerun"):
            st.experimental_rerun()
        else:
            st.experimental_set_query_params(_=datetime.now().timestamp())
    except:
        pass

# --------------------------
# Admin Dashboard
# --------------------------
def admin_dashboard():
    ensure_session_keys()
    st.title("Admin Dashboard - BlueCarbon")
    st.markdown("Add projects manually or upload CSV. Leave Carbon blank to auto-estimate via Phi-3 Mini LLM.")

    mode = st.radio("Input Mode",["Manual Entry","Bulk CSV Upload"])

    if mode=="Manual Entry":
        st.subheader("Manual Project Entry")
        with st.form("manual_form"):
            name = st.text_input("Project Name")
            type_ = st.text_input("Project Type")
            region = st.text_input("Region")
            area = st.number_input("Area (ha)",min_value=0.0,format="%.4f")
            carbon = st.number_input("Carbon (tonnes) (0=estimate)",min_value=0.0,format="%.4f",value=0.0)
            anchor_onchain = st.checkbox("Anchor record on-chain")
            submit = st.form_submit_button("Add Project")

        if submit:
            if not name or not type_ or not region or area<=0:
                st.error("Provide Name, Type, Region, and Area>0")
            else:
                # LLM estimate
                if carbon==0.0:
                    key = f"{area}|{type_}|{region}"
                    if key in st.session_state['est_cache']:
                        est_val, expl = st.session_state['est_cache'][key]
                    else:
                        fallback = area*4.0
                        est_val = run_ollama_number(f"Provide numeric carbon for {area} ha {type_} in {region}",fallback=fallback)
                        expl = run_ollama_text(f"Explain carbon for {area} ha {type_} in {region} as {est_val} tonnes")
                        st.session_state['est_cache'][key] = (est_val,expl)
                    carbon_val = safe_float(est_val)
                    explanation = expl
                else:
                    carbon_val = safe_float(carbon)
                    explanation = f"Manually entered: {carbon_val} tonnes"

                # DB insert
                try:
                    new_id = db_add_project(name,type_,region,area,carbon_val,explanation)
                    st.success(f"Project added: {new_id}")
                except Exception as e:
                    st.error(f"Failed: {e}")
                    return

                # record hash
                rec = {"id":new_id,"name":name,"type":type_,"region":region,"area_ha":area,"carbon_tonnes":carbon_val,"created_at":datetime.now().isoformat()}
                rh = compute_record_hash(rec)
                try:
                    db_update_record_hash_and_onchain(new_id,rh,None,"not_anchored",None)
                except:
                    pass

                # anchor
                if anchor_onchain and w3 and EVM_PRIVATE_KEY:
                    res = anchor_hash_on_chain(rh,wait_for_receipt=False)
                    if res.get("success"):
                        db_update_record_hash_and_onchain(new_id,rh,res.get("tx_hash"),"pending",None)
                        st.success(f"Anchored: {res.get('tx_hash')}")
                    else:
                        st.error(f"Anchor failed: {res.get('error')}")

                do_rerun_browser_safe()

    # Bulk CSV upload
    elif mode=="Bulk CSV Upload":
        st.subheader("Bulk CSV Upload")
        sample = pd.DataFrame({"name":["Project A"],"type":["Afforestation"],"region":["India"],"area_ha":[100],"carbon_tonnes":[400]})
        buf = io.BytesIO()
        sample.to_csv(buf,index=False)
        st.download_button("Download CSV Template",buf.getvalue(),"template.csv","text/csv")
        uploaded = st.file_uploader("Upload CSVs",type=["csv"],accept_multiple_files=True)
        previews=[]
        if uploaded:
            for f in uploaded:
                st.markdown(f"### {f.name}")
                try:
                    df = pd.read_csv(f)
                    st.dataframe(df.head())
                    previews.append(df)
                except Exception as e:
                    st.warning(f"{f.name} read error: {e}")

        with st.form("bulk_form"):
            anchor_bulk = st.checkbox("Anchor on-chain")
            bulk_submit = st.form_submit_button("Add All Projects")

        if bulk_submit and previews:
            added=0
            skipped=0
            for df in previews:
                for _,row in df.iterrows():
                    try:
                        name=row.get("name")
                        type_=row.get("type")
                        region=row.get("region")
                        area=row.get("area_ha")
                        carbon=row.get("carbon_tonnes")
                        if pd.isna(area) or float(area)<=0:
                            skipped+=1
                            continue
                        if pd.isna(carbon) or float(carbon)==0:
                            fallback=float(area)*4.0
                            cval=run_ollama_number(f"Numeric carbon {area} ha {type_} in {region}",fallback=fallback)
                            expl=run_ollama_text(f"Explain carbon {area} ha {type_} in {region} = {cval} t")
                            carbon=float(cval)
                            explanation=expl
                        else:
                            carbon=float(carbon)
                            explanation=""
                        new_id=db_add_project(name,type_,region,float(area),carbon,explanation)
                        rec={"id":new_id,"name":name,"type":type_,"region":region,"area_ha":float(area),"carbon_tonnes":carbon,"created_at":datetime.now().isoformat()}
                        rh=compute_record_hash(rec)
                        db_update_record_hash_and_onchain(new_id,rh,None,"not_anchored",None)
                        if anchor_bulk and w3 and EVM_PRIVATE_KEY:
                            res=anchor_hash_on_chain(rh)
                            if res.get("success"):
                                db_update_record_hash_and_onchain(new_id,rh,res.get("tx_hash"),"pending",None)
                        added+=1
                    except Exception as e:
                        skipped+=1
            st.success(f"Bulk import done. Added: {added}, Skipped: {skipped}")
            do_rerun_browser_safe()

# --------------------------
# Public Dashboard
# --------------------------
def public_dashboard():
    st.title("BlueCarbon Public Dashboard")
    st.markdown("View all projects and carbon data. Explanations are expandable.")
    df = db_get_all_projects()
    if df.empty:
        st.info("No projects found")
        return
    for idx,row in df.iterrows():
        with st.expander(f"{row['Name']} ({row['Region']}) - {row['Status']}"):
            st.markdown(f"**Type:** {row['Type']}  \n**Area (ha):** {row['Area_ha']}  \n**Carbon (t):** {row['Carbon_tonnes']}  \n**Credits:** {row['Credits']}")
            st.markdown(f"**Created:** {row['Created_at']}")
            st.markdown(f"**Explanation:** {row['Explanation']}")
            st.markdown(f"**Record Hash:** {row['Record_Hash']}  \n**Onchain Tx:** {row['Onchain_Tx']}  \n**Onchain Status:** {row['Onchain_Status']}  \n**Onchain Block:** {row['Onchain_Block']}")

# --------------------------
# Sidebar navigation
# --------------------------
st.sidebar.title("BlueCarbon Registry")
page = st.sidebar.radio("Page", ["Public Dashboard", "Admin Dashboard"])

if page=="Public Dashboard":
    public_dashboard()
else:
    admin_dashboard()
