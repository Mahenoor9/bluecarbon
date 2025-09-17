import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# ------------------------------
# Database setup
# ------------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create tables if not exist
c.execute('''CREATE TABLE IF NOT EXISTS projects
             (project_id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT,
              type TEXT,
              region TEXT,
              status TEXT,
              area REAL,
              carbon REAL,
              credits REAL,
              created_at TEXT)''')

# Ensure schema has all required columns (handles older DBs)

def ensure_project_table_schema():
    c.execute("PRAGMA table_info(projects)")
    existing_cols = {row[1] for row in c.fetchall()}
    required = [
        ("status", "TEXT", "issued"),
        ("area", "REAL", 0.0),
        ("carbon", "REAL", 0.0),
        ("credits", "REAL", 0.0),
        ("created_at", "TEXT", None),
    ]
    for col_name, col_type, default in required:
        if col_name not in existing_cols:
            c.execute(f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}")
            if default is not None:
                c.execute(f"UPDATE projects SET {col_name} = ?", (default,))
    conn.commit()

ensure_project_table_schema()

# ------------------------------
# Helper functions
# ------------------------------

def calculate_credits(area_ha, carbon_tonnes):
    # Example formula: 1 credit per 0.1 tonne CO2 per hectare
    return round(carbon_tonnes * 10 * area_ha, 2)

def add_project_to_db(name, type_, region, area, carbon):
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO projects (name, type, region, status, area, carbon, credits, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (name, type_, region, 'issued', area, carbon, credits, created_at))
    conn.commit()
    return credits

def get_all_projects():
    c.execute("SELECT * FROM projects")
    data = c.fetchall()
    columns = ['ID', 'Name', 'Type', 'Region', 'Status', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Created_at']
    return pd.DataFrame(data, columns=columns)

def delete_project(project_id):
    c.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
    conn.commit()

# ------------------------------
# Admin Dashboard
# ------------------------------
def admin_dashboard():
    st.header("Admin Dashboard")

    st.subheader("Add New Project")
    name = st.text_input("Project Name")
    type_ = st.selectbox("Project Type", ["Forest", "Wetland", "Blue Carbon"])
    region = st.text_input("Region")
    area = st.number_input("Area (ha)", min_value=0.0)
    carbon = st.number_input("Carbon Stock (t)", min_value=0.0)

    if st.button("Add Project"):
        if name and region:
            credits = add_project_to_db(name, type_, region, area, carbon)
            st.success(f"Project '{name}' added! Generated Credits: {credits}")
        else:
            st.error("Please fill in all required fields!")

    st.subheader("All Projects")
    df = get_all_projects()
    st.dataframe(df)

    st.subheader("Delete Project")
    delete_id = st.number_input("Enter Project ID to Delete", min_value=1, step=1)
    if st.button("Delete Project"):
        delete_project(delete_id)
        st.success(f"Project ID {delete_id} deleted!")

# ------------------------------
# Public Dashboard
# ------------------------------
def public_dashboard():
    st.header("Public View")
    st.subheader("All Projects")
    df = get_all_projects()
    st.dataframe(df)

# ------------------------------
# Main
# ------------------------------
def main():
    st.title("Blue Carbon Registry")

    if 'admin_logged_in' not in st.session_state:
        st.session_state['admin_logged_in'] = False

    mode = st.sidebar.selectbox("Select Mode", ["Public", "Admin"])

    if mode == "Admin":
        if not st.session_state['admin_logged_in']:
            st.subheader("Admin Login")
            admin_password_input = st.text_input("Enter Admin Password", type="password")
            login_clicked = st.button("Login")
            if login_clicked:
                if admin_password_input == "admin123":  # <-- set your password
                    st.session_state['admin_logged_in'] = True
                    st.success("Login successful!")
                else:
                    st.error("Wrong password")
        else:
            admin_dashboard()
    else:
        public_dashboard()

if __name__ == "__main__":
    main()
