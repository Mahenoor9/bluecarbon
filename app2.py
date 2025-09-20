# app2.py
# Streamlit Carbon Registry (Supabase Postgres backend)
# Features:
# - Supabase/Postgres cloud DB connection (psycopg2)
# - Admin dashboard: manual entry + bulk CSV upload + validate/confirm
# - Public dashboard: tabular project view + filters + search
# - Admin controls: Issue / Retire / Delete
# - Stats: totals, breakdowns
# - CSV export, pagination, friendly UI
# - NO LLMs (all AI code removed)
# - Read DB credentials from st.secrets or environment variables (safe practice)

import streamlit as st
import pandas as pd
import io
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import csv
import math
import traceback
from typing import Tuple, List, Dict

# ----------------------------------------
# Configuration: read DB credentials
# ----------------------------------------
# Priority: Streamlit secrets -> environment variables -> inline defaults
def load_db_config():
    """
    Load DB configuration from st.secrets or environment variables.
    If none found, fallback to placeholder defaults (edit before production).
    """
    # Prefer Streamlit secrets if present
    try:
        secrets = st.secrets
    except Exception:
        secrets = {}

    host = secrets.get("DB_HOST") or os.environ.get("DB_HOST") or "db.hrrmqkjxxyumemtowloy.supabase.co"
    port = int(secrets.get("DB_PORT") or os.environ.get("DB_PORT") or 5432)
    database = secrets.get("DB_NAME") or os.environ.get("DB_NAME") or "postgres"
    user = secrets.get("DB_USER") or os.environ.get("DB_USER") or "postgres"
    password = secrets.get("DB_PASSWORD") or os.environ.get("DB_PASSWORD") or "mahenoor123"

    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password
    }

DB_CONFIG = load_db_config()

# ----------------------------------------
# Database connection helpers
# ----------------------------------------
# We'll hold a single persistent connection for the app lifecycle.
# Using RealDictCursor so fetch results are dict-like (column names available).
_conn = None
_cursor = None

def get_db_connection():
    """
    Return a persistent psycopg2 connection and cursor.
    If connection is not open, open it.
    """
    global _conn, _cursor
    if _conn is None:
        try:
            _conn = psycopg2.connect(
                host=DB_CONFIG["host"],
                port=DB_CONFIG["port"],
                database=DB_CONFIG["database"],
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                cursor_factory=RealDictCursor,
                connect_timeout=10
            )
            _cursor = _conn.cursor()
            print("[DB] Connected to Postgres")
        except Exception as e:
            # Show error in Streamlit UI if running inside app
            st.error(f"Failed to connect to DB: {e}")
            traceback.print_exc()
            raise
    return _conn, _cursor

def close_db_connection():
    """
    Close DB connection gracefully.
    """
    global _conn, _cursor
    try:
        if _cursor:
            _cursor.close()
        if _conn:
            _conn.close()
    except Exception:
        pass
    _conn = None
    _cursor = None

# Initialize DB connection at import/run
try:
    conn, cur = get_db_connection()
except Exception:
    conn, cur = None, None

# ----------------------------------------
# Ensure projects table exists (run once)
# ----------------------------------------
def ensure_table_exists():
    """
    Create projects table if it doesn't exist. Schema matches previous design.
    Columns:
      - id (serial primary key)
      - name, type, region
      - area_ha (real), carbon_tonnes (real), credits (real)
      - status (text), created_at (timestamp), updated_at (timestamp)
    """
    sql = """
    CREATE TABLE IF NOT EXISTS projects (
        id SERIAL PRIMARY KEY,
        name TEXT,
        type TEXT,
        region TEXT,
        area_ha REAL DEFAULT 0,
        carbon_tonnes REAL DEFAULT 0,
        credits REAL DEFAULT 0,
        status TEXT DEFAULT 'Draft',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );
    """
    try:
        conn, cur = get_db_connection()
        cur.execute(sql)
        conn.commit()
    except Exception as e:
        st.error(f"Error creating projects table: {e}")
        traceback.print_exc()
        raise

# Create table on app start (safe, idempotent)
ensure_table_exists()

# ----------------------------------------
# Utility functions: DB CRUD operations
# ----------------------------------------
def calculate_credits(area: float, carbon: float) -> float:
    """
    Credits formula: credits = area * 0.5 + carbon * 0.2
    Keep consistent with earlier app design.
    """
    try:
        credits = area * 0.5 + carbon * 0.2
        return round(float(credits), 4)
    except Exception:
        return 0.0

def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, status="Draft") -> int:
    """
    Add project to DB; returns inserted project's id.
    Stores created_at and updated_at as NOW().
    """
    conn, cur = get_db_connection()
    credits = calculate_credits(area or 0, carbon or 0)
    sql = """
    INSERT INTO projects (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    RETURNING id;
    """
    cur.execute(sql, (name, type_, region, area, carbon, credits, status))
    conn.commit()
    row = cur.fetchone()
    return row["id"]

def db_get_projects(limit: int = None, offset: int = 0) -> List[Dict]:
    """
    Fetch projects from DB with optional pagination.
    Returns a list of dict rows.
    """
    conn, cur = get_db_connection()
    if limit:
        cur.execute("SELECT * FROM projects ORDER BY id DESC LIMIT %s OFFSET %s", (limit, offset))
    else:
        cur.execute("SELECT * FROM projects ORDER BY id DESC")
    rows = cur.fetchall()
    return rows

def db_get_project_by_id(proj_id: int) -> Dict:
    conn, cur = get_db_connection()
    cur.execute("SELECT * FROM projects WHERE id = %s", (proj_id,))
    row = cur.fetchone()
    return row

def db_delete_project(proj_id: int) -> None:
    conn, cur = get_db_connection()
    cur.execute("DELETE FROM projects WHERE id = %s", (proj_id,))
    conn.commit()

def db_update_status(proj_id: int, status: str) -> None:
    conn, cur = get_db_connection()
    cur.execute("UPDATE projects SET status = %s, updated_at = NOW() WHERE id = %s", (status, proj_id))
    conn.commit()

def db_update_project(proj_id: int, updates: Dict) -> None:
    """
    Updates project fields using provided updates dict.
    Example updates: {"name": "New", "area_ha": 10.0}
    """
    conn, cur = get_db_connection()
    set_parts = []
    vals = []
    for k, v in updates.items():
        set_parts.append(f"{k} = %s")
        vals.append(v)
    if not set_parts:
        return
    vals.append(proj_id)
    sql = f"UPDATE projects SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = %s"
    cur.execute(sql, tuple(vals))
    conn.commit()

# ----------------------------------------
# CSV helpers: validate, preview, parse
# ----------------------------------------
def make_csv_template() -> bytes:
    """
    Return CSV template as bytes (for download).
    """
    template = pd.DataFrame({
        "name": ["Project A"],
        "type": ["Afforestation"],
        "region": ["India"],
        "area_ha": [100],
        "carbon_tonnes": [400],
        "status": ["Draft"]
    })
    buf = io.BytesIO()
    template.to_csv(buf, index=False)
    return buf.getvalue()

def validate_csv_df(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Validate required columns and rows; return (clean_df, errors)
    - Required columns: name, type, region, area_ha
    - carbon_tonnes optional (if missing, treated as 0)
    - rows with invalid area_ha are skipped and reported
    """
    errors = []
    required = ["name", "type", "region", "area_ha"]
    for col in required:
        if col not in df.columns:
            errors.append(f"Missing required column: {col}")
    if errors:
        return pd.DataFrame(), errors
    cleaned_rows = []
    for idx, row in df.iterrows():
        try:
            name = str(row.get("name", "")).strip()
            type_ = str(row.get("type", "")).strip()
            region = str(row.get("region", "")).strip()
            area = float(row.get("area_ha", 0) or 0)
            carbon = row.get("carbon_tonnes", 0)
            # some CSVs may have empty carbon column -> treat as 0
            carbon = float(carbon or 0)
            status = row.get("status", "Draft") or "Draft"
            if not name or not type_ or not region:
                errors.append(f"Row {idx}: missing required text fields (name/type/region)")
                continue
            if area <= 0:
                errors.append(f"Row {idx}: invalid area_ha ({area}); must be > 0")
                continue
            cleaned_rows.append({
                "name": name,
                "type": type_,
                "region": region,
                "area": area,
                "carbon": carbon,
                "status": status
            })
        except Exception as e:
            errors.append(f"Row {idx}: parsing error: {e}")
    clean_df = pd.DataFrame(cleaned_rows)
    return clean_df, errors

# ----------------------------------------
# UI helpers: badges, columns, formatting
# ----------------------------------------
def status_badge(status: str) -> str:
    """
    Return HTML snippet for a colored status badge for small UI polish.
    Note: Streamlit supports unsafe_allow_html for small spans.
    """
    s = str(status or "").lower()
    color = "#6c757d"  # gray
    if s == "issued" or s == "issued":
        color = "#16a34a"  # green
    elif s == "retired":
        color = "#dc2626"  # red
    elif s == "draft":
        color = "#f59e0b"  # amber
    badge = f"<span style='background:{color};color:white;padding:4px 8px;border-radius:6px;font-size:12px'>{status}</span>"
    return badge

def pretty_timestamp(ts):
    """
    Format a datetime-like object to human readable string.
    """
    try:
        if ts is None:
            return ""
        return pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)

# ----------------------------------------
# Admin dashboard implementation
# ----------------------------------------
def admin_dashboard():
    st.title("Admin Dashboard — Cloud Registry")
    st.markdown("Use this dashboard to add projects (manually or via CSV), manage them, and inspect stats.")
    st.markdown("---")

    # Top row: stats
    df_all = pd.DataFrame(db_get_projects())
    total_projects = len(df_all)
    total_carbon = round(float(df_all['carbon_tonnes'].sum()) if not df_all.empty else 0.0, 4)
    total_credits = round(float(df_all['credits'].sum()) if not df_all.empty else 0.0, 4)

    col1, col2, col3, col4 = st.columns([2,2,2,2])
    with col1:
        st.metric("Total projects", total_projects)
    with col2:
        st.metric("Total carbon (tCO₂)", total_carbon)
    with col3:
        st.metric("Total credits", total_credits)
    with col4:
        st.button("Refresh", on_click=lambda: do_rerun())

    st.markdown("---")

    # Layout: left = input, right = CSV upload/preview
    left, right = st.columns([2,3])

    with left:
        st.header("Manual Entry")
        name = st.text_input("Project name", key="manual_name")
        type_ = st.text_input("Project type", key="manual_type")
        region = st.text_input("Region", key="manual_region")
        area = st.number_input("Area (ha)", min_value=0.0, format="%.2f", key="manual_area")
        carbon = st.number_input("Carbon stored (tonnes) — optional", min_value=0.0, format="%.2f", key="manual_carbon")
        status_select = st.selectbox("Initial status", ["Draft", "Issued", "Retired"])
        st.markdown("If carbon is left blank or 0, it will be stored as 0. No AI/LLM is used in this version.")

        if st.button("Add project (manual)"):
            if not name or not type_ or not region:
                st.error("Name, type, and region are required.")
            elif area <= 0:
                st.error("Area must be > 0.")
            else:
                try:
                    proj_id = db_add_project(name=name, type_=type_, region=region, area=area, carbon=carbon or 0, status=status_select)
                    st.success(f"Project added (ID {proj_id})")
                    # clear fields by rerunning
                    do_rerun()
                except Exception as e:
                    st.error(f"Failed to add project: {e}")
                    traceback.print_exc()

    with right:
        st.header("Bulk CSV Upload")
        st.markdown("Upload CSV files containing columns: `name,type,region,area_ha,carbon_tonnes (optional),status (optional)`")
        template_bytes = make_csv_template()
        st.download_button("Download CSV template", template_bytes, "projects_template.csv", "text/csv")

        uploaded_files = st.file_uploader("Upload CSV files (you can upload multiple)", accept_multiple_files=True, type=["csv"])
        if uploaded_files:
            preview_frames = []
            all_errors = []
            for uploaded in uploaded_files:
                try:
                    df = pd.read_csv(uploaded)
                    st.markdown(f"**Preview — {uploaded.name}**")
                    st.dataframe(df.head(5))
                    clean_df, errors = validate_csv_df(df)
                    if errors:
                        all_errors.extend([f"{uploaded.name}: {err}" for err in errors])
                    preview_frames.append((uploaded.name, clean_df))
                except Exception as e:
                    all_errors.append(f"{uploaded.name}: could not read CSV ({e})")

            if all_errors:
                st.warning("Validation issues detected. See details below.")
                for e in all_errors:
                    st.write("- " + e)

            if preview_frames:
                st.info("Preview valid rows and click 'Confirm & Import' to insert into the cloud DB.")
                for fname, cdf in preview_frames:
                    st.subheader(f"Valid rows from {fname}")
                    st.dataframe(cdf)

                if st.button("Confirm & Import all valid rows"):
                    imported = 0
                    for _, cdf in preview_frames:
                        for _, r in cdf.iterrows():
                            try:
                                name = r["name"]
                                type_v = r["type"]
                                region_v = r["region"]
                                area_v = float(r["area"])
                                carbon_v = float(r["carbon"])
                                status_v = r.get("status", "Draft") or "Draft"
                                db_add_project(name=name, type_=type_v, region=region_v, area=area_v, carbon=carbon_v, status=status_v)
                                imported += 1
                            except Exception as e:
                                st.error(f"Failed to import row: {e}")
                    st.success(f"Imported {imported} rows.")
                    do_rerun()

    st.markdown("---")

    # Controls: filters, search, pagination for admin table
    st.header("Manage Projects")
    st.markdown("Filter, search, and perform bulk actions on existing projects.")

    # Filters
    filter_cols = st.columns(4)
    with filter_cols[0]:
        status_filter = st.multiselect("Status", options=["Draft", "Issued", "Retired"], default=["Draft", "Issued", "Retired"])
    with filter_cols[1]:
        type_filter = st.text_input("Type contains")
    with filter_cols[2]:
        region_filter = st.text_input("Region contains")
    with filter_cols[3]:
        name_search = st.text_input("Search name contains")

    # Pagination controls
    per_page = st.selectbox("Rows per page", [10, 20, 50, 100], index=1)
    page_num = st.number_input("Page number (1-indexed)", min_value=1, value=1, step=1)

    # Apply filters & fetch
    df = pd.DataFrame(db_get_projects())  # full set (we'll paginate locally)
    if df.empty:
        st.info("No projects in the registry yet.")
        return

    # Apply text filters
    if status_filter:
        df = df[df["status"].isin(status_filter)]
    if type_filter:
        df = df[df["type"].str.contains(type_filter, case=False, na=False)]
    if region_filter:
        df = df[df["region"].str.contains(region_filter, case=False, na=False)]
    if name_search:
        df = df[df["name"].str.contains(name_search, case=False, na=False)]

    # Show aggregate stats for filtered subset
    st.markdown("#### Filtered summary")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.write(f"Projects (filtered): {len(df)}")
    with col_b:
        st.write(f"Carbon (filtered): {round(df['carbon_tonnes'].sum(),4)} tCO₂")
    with col_c:
        st.write(f"Credits (filtered): {round(df['credits'].sum(),4)}")

    # Paginate
    total_rows = len(df)
    total_pages = max(1, math.ceil(total_rows / per_page))
    if page_num > total_pages:
        page_num = total_pages
    start_idx = (page_num - 1) * per_page
    end_idx = start_idx + per_page
    df_page = df.iloc[start_idx:end_idx]

    st.markdown(f"Showing page {page_num} of {total_pages}")
    # Admin table with action buttons per row
    for idx, row in df_page.iterrows():
        st.markdown("----")
        # Row header with basic fields
        c1, c2, c3 = st.columns([4,2,2])
        with c1:
            st.markdown(f"**{row['name']}** — {row['type']} — {row['region']}")
            st.write(f"Area: {row['area_ha']} ha | Carbon: {row['carbon_tonnes']} tCO₂ | Credits: {row['credits']}")
            st.write(f"Created: {pretty_timestamp(row['created_at'])} | Updated: {pretty_timestamp(row['updated_at'])}")
        with c2:
            # Status badge and ability to change
            st.markdown(status_badge(row['status']), unsafe_allow_html=True)
            # Inline status change
            new_status = st.selectbox(f"Change status (ID {row['id']})", ["No change", "Draft", "Issued", "Retired"], index=0, key=f"status_{row['id']}")
            if new_status != "No change":
                if st.button(f"Apply status {new_status} (ID {row['id']})", key=f"apply_{row['id']}"):
                    db_update_status(row['id'], new_status)
                    st.success(f"Status updated to {new_status}")
                    do_rerun()
        with c3:
            if st.button("Delete", key=f"del_{row['id']}"):
                db_delete_project(row['id'])
                st.success("Deleted")
                do_rerun()
            # Edit link / inline edit form
            if st.button("Edit", key=f"edit_{row['id']}"):
                # open a small editor modal using expander
                with st.expander(f"Edit project ID {row['id']}", expanded=True):
                    edit_name = st.text_input("Name", value=row['name'], key=f"ename_{row['id']}")
                    edit_type = st.text_input("Type", value=row['type'], key=f"etype_{row['id']}")
                    edit_region = st.text_input("Region", value=row['region'], key=f"eregion_{row['id']}")
                    edit_area = st.number_input("Area (ha)", value=float(row['area_ha'] or 0.0), key=f"earea_{row['id']}")
                    edit_carbon = st.number_input("Carbon (t)", value=float(row['carbon_tonnes'] or 0.0), key=f"ecarbon_{row['id']}")
                    if st.button("Save changes", key=f"save_{row['id']}"):
                        # recalc credits
                        new_credits = calculate_credits(edit_area, edit_carbon)
                        db_update_project(row['id'], {
                            "name": edit_name,
                            "type": edit_type,
                            "region": edit_region,
                            "area_ha": edit_area,
                            "carbon_tonnes": edit_carbon,
                            "credits": new_credits
                        })
                        st.success("Saved")
                        do_rerun()

    # Bulk export of filtered results
    st.markdown("---")
    if not df.empty:
        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button("Export filtered projects (CSV)", csv_data, "projects_export.csv", "text/csv")

# ----------------------------------------
# Public dashboard implementation
# ----------------------------------------
def public_dashboard():
    st.title("Public Registry — Cloud Projects")
    st.markdown("Public table of projects stored in the cloud. Use filters on the left to refine view.")
    st.markdown("---")

    # Sidebar filters (public)
    st.sidebar.header("Public filters")
    status_filter = st.sidebar.multiselect("Status", ["Draft", "Issued", "Retired"], default=["Issued"])
    type_filter = st.sidebar.text_input("Type contains (public)")
    region_filter = st.sidebar.text_input("Region contains (public)")
    name_search = st.sidebar.text_input("Search name contains (public)")

    # Fetch projects
    rows = db_get_projects()
    if not rows:
        st.info("No projects available.")
        return
    df = pd.DataFrame(rows)

    # Apply filters
    if status_filter:
        df = df[df["status"].isin(status_filter)]
    if type_filter:
        df = df[df["type"].str.contains(type_filter, case=False, na=False)]
    if region_filter:
        df = df[df["region"].str.contains(region_filter, case=False, na=False)]
    if name_search:
        df = df[df["name"].str.contains(name_search, case=False, na=False)]

    # Display summary
    total_projects = len(df)
    total_carbon = round(df['carbon_tonnes'].sum(),4) if not df.empty else 0.0
    total_credits = round(df['credits'].sum(),4) if not df.empty else 0.0
    st.markdown(f"**Total projects:** {total_projects} — **Total carbon:** {total_carbon} tCO₂ — **Total credits:** {total_credits}")
    st.markdown("---")

    # Public table: tidy columns
    if not df.empty:
        view_df = df[["id", "name", "type", "region", "area_ha", "carbon_tonnes", "credits", "status", "created_at"]].copy()
        view_df.rename(columns={
            "id": "ID",
            "name": "Name",
            "type": "Type",
            "region": "Region",
            "area_ha": "Area_ha",
            "carbon_tonnes": "Carbon_tonnes",
            "credits": "Credits",
            "status": "Status",
            "created_at": "Created_at"
        }, inplace=True)
        # Format created_at
        view_df["Created_at"] = view_df["Created_at"].apply(pretty_timestamp)
        st.dataframe(view_df)
    else:
        st.info("No projects match your filters.")

# ----------------------------------------
# Main app control (routing)
# ----------------------------------------
def main():
    st.set_page_config(page_title="Carbon Registry (Cloud)", layout="wide", initial_sidebar_state="auto")
    st.sidebar.title("Carbon Registry")
    st.sidebar.markdown("Select view and actions")

    page = st.sidebar.radio("Navigate", ["Public", "Admin", "About"])

    if page == "Admin":
        # simple password gate; for production, replace with proper auth
        st.sidebar.markdown("---")
        password = st.sidebar.text_input("Admin password", type="password")
        if password == "" and "password" not in st.session_state:
            st.sidebar.info("Enter admin password to continue.")
            public_dashboard()
            return
        # For simplicity, default admin password is 'admin123' (change in production)
        if password == "admin123" or st.session_state.get("is_admin"):
            st.session_state["is_admin"] = True
            admin_dashboard()
        else:
            st.sidebar.error("Wrong password.")
            public_dashboard()
    elif page == "Public":
        public_dashboard()
    else:
        st.title("About — Carbon Registry (Cloud)")
        st.markdown("""
        This app stores project data (area, carbon, credits, status) in a cloud PostgreSQL database (Supabase).
        
        Features:
        - Admin: add projects (manual or CSV), manage status, edit, delete.
        - Public: view projects in tabular format with filters.
        - No LLMs or external AI calls in this version (cloud-only registry).
        
        Notes:
        - DB credentials are read from Streamlit secrets or environment variables for safety.
        - Replace the admin password and secure the app before production.
        """)
        st.markdown("### Current DB connection info (for debugging)")
        st.write({
            "host": DB_CONFIG["host"],
            "port": DB_CONFIG["port"],
            "database": DB_CONFIG["database"],
            "user": DB_CONFIG["user"]
        })
        st.markdown("If you want to close the DB connection, use the 'Close DB' button below.")
        if st.button("Close DB connection"):
            close_db_connection()
            st.success("DB connection closed. The app will reconnect on next DB use.")

# ----------------------------------------
# Run the app
# ----------------------------------------
if __name__ == "__main__":
    main()
