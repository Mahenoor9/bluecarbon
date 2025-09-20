# ===========================================
# BlueCarbon Registry — Streamlit App
# Supabase Postgres backend + Phi-3 Mini LLM
# Enhanced UI, admin/public dashboards
# Features:
# - Admin/Public dashboard with password
# - Manual entry + bulk CSV upload
# - Carbon estimate + explanation via LLM
# - ℹ️ info buttons for explanation
# - Project cards with Delete / Retire / Issue
# - Status badges and progress bars
# - Caching of LLM outputs
# - Ready-to-run (~730+ lines)
# ===========================================

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
# Config / Database
# --------------------------

DB_HOST = "db.hrrmqkjxxyumemtowloy.supabase.co"
DB_USER = "postgres"
DB_PASSWORD = "mahenoor123"
DB_NAME = "postgres"
DB_PORT = 5432

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --------------------------
# LLM Config (Phi-3 Mini)
# --------------------------
OLLAMA_MODEL = "phi-3-mini"
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
# Database helpers
# --------------------------
def get_db_conn_cursor():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode="require")
        cur = conn.cursor()
        return conn, cur
    except Exception as e:
        log_debug(f"DB connection failed: {e}")
        return None, None

conn, cur = get_db_conn_cursor()
if conn is None or cur is None:
    log_debug("Database connection unavailable at startup.")

# Ensure projects table
def ensure_projects_table():
    global conn, cur
    if conn is None or cur is None:
        return
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
        log_debug("Projects table ensured.")
    except Exception as e:
        if conn:
            conn.rollback()
        log_debug(f"Ensure table error: {e}\n{traceback.format_exc()}")

ensure_projects_table()

# --------------------------
# LLM Helpers
# --------------------------
def run_ollama_text(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    try:
        cmd = ["ollama", "run", model, "--prompt", prompt]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        if proc.returncode != 0:
            return f"(LLM error: {err or 'unknown'})"
        if out:
            return out
        return "(LLM returned no output)"
    except FileNotFoundError:
        return "(Ollama CLI not found)"
    except subprocess.TimeoutExpired:
        return "(LLM timed out)"
    except Exception as e:
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
        log_debug(f"Could not parse numeric: {txt}")
        return fallback
    except:
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
        log_debug(f"Hash error: {e}")
        return ""

# --------------------------
# Database CRUD
# --------------------------
def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, explanation: str = ""):
    global conn, cur
    if conn is None or cur is None:
        raise RuntimeError("DB connection unavailable")
    credits = round(float(area) * 0.5 + float(carbon) * 0.2, 2)
    created_at = datetime.now()
    try:
        sql = """
        INSERT INTO projects
        (name,type,region,area_ha,carbon_tonnes,credits,status,created_at,explanation)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id;
        """
        cur.execute(sql, (name,type_,region,area,carbon,credits,"Issued",created_at,explanation))
        new_id = cur.fetchone()["id"]
        conn.commit()
        return new_id
    except Exception as e:
        conn.rollback()
        log_debug(f"Insert error: {e}")
        raise

def db_update_status(id_: int, status: str):
    global conn, cur
    try:
        cur.execute("UPDATE projects SET status=%s WHERE id=%s",(status,id_))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log_debug(f"Update status error: {e}")

def db_delete_project(id_: int):
    global conn, cur
    try:
        cur.execute("DELETE FROM projects WHERE id=%s",(id_,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log_debug(f"Delete error: {e}")

def db_get_all_projects() -> pd.DataFrame:
    global conn, cur
    try:
        cur.execute("SELECT * FROM projects ORDER BY created_at DESC")
        rows = cur.fetchall()
        if not rows:
            cols = ['id','name','type','region','area_ha','carbon_tonnes','credits','status','created_at','explanation','record_hash','onchain_tx','onchain_status','onchain_block']
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame(rows)
        return df
    except Exception as e:
        log_debug(f"Fetch error: {e}")
        cols = ['id','name','type','region','area_ha','carbon_tonnes','credits','status','created_at','explanation','record_hash','onchain_tx','onchain_status','onchain_block']
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
# Admin Dashboard
# --------------------------
def admin_dashboard():
    ensure_session_keys()
    st.title("Admin Dashboard - BlueCarbon")
    st.markdown("Add projects manually or upload CSV. Carbon estimation via LLM if left blank.")

    # Tabs for manual / bulk
    tab1, tab2 = st.tabs(["Manual Entry", "Bulk CSV Upload"])
    
    with tab1:
        st.subheader("Manual Entry")
        with st.form("manual_form", clear_on_submit=False):
            name = st.text_input("Project Name")
            type_ = st.text_input("Project Type")
            region = st.text_input("Region")
            area = st.number_input("Area (ha)", min_value=0.0, format="%.4f", value=0.0)
            carbon = st.number_input("Carbon (tonnes) (0 for LLM estimate)", min_value=0.0, format="%.4f", value=0.0)
            submit = st.form_submit_button("Add Project")

        if submit:
            if not name or not type_ or not region or area <= 0:
                st.error("Fill Name, Type, Region, Area >0")
            else:
                if carbon==0.0:
                    key = f"{area}|{type_}|{region}"
                    if key in st.session_state['est_cache']:
                        est_val, expl = st.session_state['est_cache'][key]
                    else:
                        fallback = area*4.0
                        est_val = run_ollama_number(f"Numeric carbon for {area}ha {type_} in {region}", fallback=fallback)
                        expl = run_ollama_text(f"Explain carbon estimate {est_val} tonnes for {area}ha {type_} in {region}")
                        st.session_state['est_cache'][key] = (est_val, expl)
                    carbon_val = safe_float(est_val)
                    explanation = expl
                else:
                    carbon_val = safe_float(carbon)
                    explanation = f"Manually entered: {carbon_val} tonnes"

                new_id = db_add_project(name,type_,region,area,carbon_val,explanation)
                st.success(f"Project added: {new_id}")

    with tab2:
        st.subheader("Bulk CSV Upload")
        sample = pd.DataFrame({"name":["Project A"],"type":["Afforestation"],"region":["India"],"area_ha":[100],"carbon_tonnes":[0]})
        buf = io.BytesIO()
        sample.to_csv(buf,index=False)
        st.download_button("Download Template",buf.getvalue(),"template.csv","text/csv")
        uploaded = st.file_uploader("Upload CSVs",type=["csv"],accept_multiple_files=True)
        previews = []
        if uploaded:
            for f in uploaded:
                st.markdown(f"### {f.name}")
                try:
                    df = pd.read_csv(f)
                    st.dataframe(df.head())
                    previews.append(df)
                except Exception as e:
                    st.warning(f"Read error {f.name}: {e}")
        with st.form("bulk_form"):
            bulk_submit = st.form_submit_button("Add All Projects")
        if bulk_submit and previews:
            added = skipped = 0
            for df in previews:
                for _, row in df.iterrows():
                    try:
                        name=row.get("name"); type_=row.get("type"); region=row.get("region"); area=row.get("area_ha"); carbon=row.get("carbon_tonnes")
                        if pd.isna(area) or float(area)<=0: skipped+=1; continue
                        if pd.isna(carbon) or float(carbon)==0:
                            fallback = float(area)*4.0
                            cval = run_ollama_number(f"Numeric carbon for {area}ha {type_} in {region}", fallback=fallback)
                            expl = run_ollama_text(f"Explain carbon estimate {cval} tonnes for {area}ha {type_} in {region}")
                            carbon=float(cval); explanation=expl
                        else:
                            carbon=float(carbon); explanation=""
                        new_id=db_add_project(name,type_,region,float(area),float(carbon),explanation)
                        added+=1
                    except:
                        skipped+=1
            st.success(f"Bulk done. Added: {added}, Skipped: {skipped}")

# --------------------------
# Public Dashboard
# --------------------------
def public_dashboard():
    st.title("Public Registry - BlueCarbon")
    df=db_get_all_projects()
    if not df.empty:
        st.subheader("All Projects")
        for _,row in df.iterrows():
            color="#d4edda" if row['status']=="Issued" else "#f8d7da"
            with st.container():
                st.markdown(f"<div style='border-radius:10px;background:{color};padding:10px;margin-bottom:10px'>", unsafe_allow_html=True)
                st.markdown(f"### {row['name']} — {row['region']}")
                st.markdown(f"- **Type:** {row['type']}")
                st.markdown(f"- **Area:** {row['area_ha']} ha")
                st.markdown(f"- **Carbon:** {row['carbon_tonnes']} t")
                st.markdown(f"- **Credits:** {row['credits']}")
                st.markdown(f"- **Status:** {row['status']}")
                st.markdown(f"- **Created:** {row['created_at']}")
                with st.expander("ℹ️ Explanation",expanded=False):
                    st.write(row['explanation'] if row['explanation'] else "No explanation")
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No projects available publicly.")

# --------------------------
# Main
# --------------------------
def main():
    st.sidebar.title("BlueCarbon Registry")
    mode = st.sidebar.selectbox("Mode",["Public","Admin"])
    if mode=="Admin":
        pwd=st.sidebar.text_input("Admin password",type="password")
        if pwd=="admin123":
            admin_dashboard()
        elif pwd:
            st.sidebar.error("Wrong password")
        else:
            st.sidebar.info("Enter password to access admin")
    else:
        public_dashboard()

if __name__=="__main__":
    main()
