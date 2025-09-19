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
      streamlit run app1.py
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
