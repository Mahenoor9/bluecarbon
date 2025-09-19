import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import io
import subprocess
import re

# -------------------
# LLM Helper
# -------------------
def ask_llm(prompt: str) -> str:
    """
    Sends a prompt to Phi-3 Mini via Ollama and returns the response.
    """
    try:
        result = subprocess.run(
            ["ollama", "run", "phi3:mini"],
            input=prompt.encode(),
            capture_output=True,
            timeout=15
        )
        return result.stdout.decode().strip()
    except Exception as e:
        return f"[LLM Error: {e}]"

def ask_llm_number(prompt: str, fallback: float) -> float:
    """
    Ask LLM to estimate a number. Parses first numeric value from response.
    Returns fallback if parsing fails.
    """
    response = ask_llm(prompt)
    match = re.search(r"\d+(\.\d+)?", response)
    if match:
        return float(match.group())
    else:
        return fallback

# -------------------
# Database Setup
# -------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()
c.execute("PRAGMA foreign_keys = ON")

c.execute('''
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    type TEXT,
    region TEXT,
    area_ha REAL,
    carbon_tonnes REAL,
    credits REAL,
    status TEXT,
    created_at TEXT
)
''')
conn.commit()

def ensure_projects_schema():
    c.execute("PRAGMA table_info(projects)")
    cols = {row[1] for row in c.fetchall()}

    if "area_ha" not in cols:
        c.execute("ALTER TABLE projects ADD COLUMN area_ha REAL")
        if "area" in cols:
            try:
                c.execute("UPDATE projects SET area_ha = area WHERE area_ha IS NULL")
            except Exception:
                pass
        c.execute("UPDATE projects SET area_ha = COALESCE(area_ha, 0.0)")

    if "carbon_tonnes" not in cols:
        c.execute("ALTER TABLE projects ADD COLUMN carbon_tonnes REAL")
        if "carbon" in cols:
            try:
                c.execute("UPDATE projects SET carbon_tonnes = carbon WHERE carbon_tonnes IS NULL")
            except Exception:
                pass
        c.execute("UPDATE projects SET carbon_tonnes = COALESCE(carbon_tonnes, 0.0)")

    if "credits" not in cols:
        c.execute("ALTER TABLE projects ADD COLUMN credits REAL")
        c.execute("UPDATE projects SET credits = COALESCE(credits, 0.0)")

    if "status" not in cols:
        c.execute("ALTER TABLE projects ADD COLUMN status TEXT")
        c.execute("UPDATE projects SET status = COALESCE(status, 'Issued')")

    if "created_at" not in cols:
        c.execute("ALTER TABLE projects ADD COLUMN created_at TEXT")

    conn.commit()

def detect_schema():
    c.execute("PRAGMA table_info(projects)")
    cols = {row[1] for row in c.fetchall()}
    id_col = None
    if "id" in cols:
        id_col = "id"
    elif "project_id" in cols:
        id_col = "project_id"

    area_col = "area_ha" if "area_ha" in cols else ("area" if "area" in cols else None)
    carbon_col = "carbon_tonnes" if "carbon_tonnes" in cols else ("carbon" if "carbon" in cols else None)

    return {
        "id_col": id_col,
        "area_col": area_col,
        "carbon_col": carbon_col,
    }

ensure_projects_schema()
SCHEMA = detect_schema()

# -------------------
# Helpers
# -------------------
def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        try:
            st.experimental_set_query_params(_=datetime.now().timestamp())
        except Exception:
            pass

def calculate_credits(area, carbon):
    return round(area * 0.5 + carbon * 0.2, 2)

def add_project(name, type_, region, area, carbon):
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects (name, type, region, area_ha, carbon_tonnes, credits, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, area, carbon, credits, "Issued", created_at))
    conn.commit()

def delete_project(proj_id):
    if not SCHEMA["id_col"]:
        raise RuntimeError("Projects table has no identifiable primary key column.")
    try:
        conn.execute("BEGIN")
        c.execute(f'DELETE FROM projects WHERE {SCHEMA["id_col"]} = ?', (int(proj_id),))
        if c.rowcount == 1:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise

def update_status(proj_id, status):
    if not SCHEMA["id_col"]:
        raise RuntimeError("Projects table has no identifiable primary key column.")
    c.execute(f'UPDATE projects SET status=? WHERE {SCHEMA["id_col"]} = ?', (status, int(proj_id)))
    conn.commit()

def get_all_projects():
    if not SCHEMA["id_col"]:
        return pd.DataFrame(columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at'])

    id_col = SCHEMA["id_col"]
    area_col = SCHEMA["area_col"] or "area_ha"
    carbon_col = SCHEMA["carbon_col"] or "carbon_tonnes"

    select_cols = [
        f"{id_col} AS ID",
        "name AS Name",
        "type AS Type",
        "region AS Region",
        f"{area_col} AS Area_ha",
        f"{carbon_col} AS Carbon_tonnes",
        "credits AS Credits",
        "status AS Status",
        "created_at AS Created_at",
    ]
    query = "SELECT " + ", ".join(select_cols) + " FROM projects"

    try:
        c.execute(query)
        data = c.fetchall()
        if data:
            return pd.DataFrame(data, columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at'])
        else:
            return pd.DataFrame(columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at'])
    except Exception:
        return pd.DataFrame(columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at'])

# -------------------
# Admin Dashboard
# -------------------
# -------------------
# Admin Dashboard
# -------------------
# -------------------
# Admin Dashboard
# -------------------
def admin_dashboard():
    st.title("Admin Dashboard")

    input_mode = st.radio("Choose Input Method", ["Manual Entry", "Bulk CSV Upload"])

    # -------------------
    # Manual Entry using st.form
    # -------------------
    if input_mode == "Manual Entry":
        st.subheader("Add New Project")

        with st.form("manual_project_form"):
            name = st.text_input("Project Name")
            type_ = st.text_input("Project Type")
            region = st.text_input("Region")
            area = st.number_input("Area (ha)", min_value=0.0)
            carbon = st.number_input("Carbon Stored (tonnes)", min_value=0.0)

            submitted = st.form_submit_button("Add Project")

        if submitted:
            if name and type_ and region and area > 0:
                # Only call LLM if carbon missing
                if carbon == 0.0:
                    fallback = area * 4.0
                    prompt = f"Estimate carbon tonnes for a mangrove project with area {area} ha in India. Suggest a reasonable range if uncertain."
                    with st.spinner("Estimating carbon with LLM..."):
                        carbon = ask_llm_number(prompt, fallback)

                add_project(name, type_, region, area, carbon)

                # Optional explanation
                explanation_prompt = f"Explain why a mangrove project with area {area} ha has carbon storage of {carbon} tonnes."
                with st.spinner("Generating explanation..."):
                    explanation = ask_llm(explanation_prompt)
                st.info(explanation)

                st.success("Project added successfully!")
                do_rerun()
            else:
                st.error("Fill all required fields and make sure area > 0!")

    # -------------------
    # Bulk Upload
    # -------------------
    elif input_mode == "Bulk CSV Upload":
        st.subheader("Upload Multiple CSV Files")

        # CSV Template download
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

        uploaded_files = st.file_uploader(
            "Upload CSV files", type=["csv"], accept_multiple_files=True
        )

        if uploaded_files:
            all_dfs = []
            for file in uploaded_files:
                st.markdown(f"### 📂 {file.name}")
                df = pd.read_csv(file)
                st.dataframe(df.head())
                all_dfs.append(df)

            with st.form("bulk_upload_form"):
                submitted = st.form_submit_button("Add All Projects")

            if submitted:
                for df in all_dfs:
                    for _, row in df.iterrows():
                        try:
                            name = row["name"]
                            type_ = row["type"]
                            region = row["region"]
                            area = row.get("area_ha")
                            carbon = row.get("carbon_tonnes")

                            if pd.isna(area) or area <= 0:
                                st.warning(f"Skipping row '{name}' because area is missing or zero!")
                                continue

                            # Only call LLM if carbon missing
                            if pd.isna(carbon):
                                fallback = float(area) * 4.0
                                prompt = f"Estimate carbon tonnes for a mangrove project with area {area} ha in India. Suggest a reasonable range if uncertain."
                                with st.spinner(f"Estimating carbon for {name}..."):
                                    carbon = ask_llm_number(prompt, fallback)

                            add_project(name, type_, region, float(area), float(carbon))

                        except Exception as e:
                            st.warning(f"Skipping row due to error: {e}")

                st.success("All uploaded projects imported successfully!")
                do_rerun()

    # -------------------
    # Projects Overview
    # -------------------
    st.subheader("Projects Overview")
    df = get_all_projects()
    if not df.empty:
        st.dataframe(df)

        st.subheader("Manage Projects")
        for _, row in df.iterrows():
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button(f"Delete {row['ID']}", key=f"del_{row['ID']}"):
                    delete_project(int(row['ID']))
                    do_rerun()
            with col2:
                if st.button(f"Retire {row['ID']}", key=f"ret_{row['ID']}"):
                    update_status(int(row['ID']), "Retired")
                    do_rerun()
            with col3:
                if st.button(f"Issue {row['ID']}", key=f"iss_{row['ID']}"):
                    update_status(int(row['ID']), "Issued")
                    do_rerun()
    else:
        st.info("No projects yet!")


# -------------------
# Public Dashboard
# -------------------
def public_dashboard():
    st.title("Public Registry")
    df = get_all_projects()
    if not df.empty:
        st.dataframe(df)
    else:
        st.info("No projects available.")

# -------------------
# Main App
# -------------------
def main():
    st.sidebar.title("Carbon Registry")
    mode = st.sidebar.selectbox("Select Mode", ["Public", "Admin"])

    if mode == "Admin":
        password = st.sidebar.text_input("Enter Admin Password", type="password")
        if password == "admin123":
            admin_dashboard()
        elif password:
            st.sidebar.error("Wrong password!")
    else:
        public_dashboard()

if __name__ == "__main__":
    main()


