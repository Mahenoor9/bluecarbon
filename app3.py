import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd

# ------------------------
# Database Setup
# ------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

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

# ------------------------
# Helper Functions
# ------------------------
def calculate_credits(area, carbon):
    # Example formula: credits = area * carbon * 0.5 (adjust as needed)
    return round(area * carbon * 0.5, 2)

def add_project(name, type_, region, area, carbon):
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects (name, type, region, area_ha, carbon_tonnes, credits, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, area, carbon, credits, "issued", created_at))
    conn.commit()
    return credits

def get_all_projects():
    c.execute('SELECT * FROM projects')
    data = c.fetchall()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at'])
    return df

def update_status(project_id, new_status):
    c.execute('UPDATE projects SET status=? WHERE id=?', (new_status, project_id))
    conn.commit()

def delete_project(project_id):
    c.execute('DELETE FROM projects WHERE id=?', (project_id,))
    conn.commit()

# ------------------------
# Admin Dashboard
# ------------------------
def admin_dashboard():
    st.subheader("Admin Dashboard")

    # Add Project
    st.markdown("### Add New Project")
    with st.form("add_project_form", clear_on_submit=True):
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0)
        carbon = st.number_input("Carbon Stock (tonnes)", min_value=0.0)
        submitted = st.form_submit_button("Add Project")
        if submitted:
            credits = add_project(name, type_, region, area, carbon)
            st.success(f"Project added successfully! Credits calculated: {credits}")

    # Display Projects
    st.markdown("### Existing Projects")
    df = get_all_projects()
    if df.empty:
        st.info("No projects yet.")
        return

    for index, row in df.iterrows():
        st.write(f"**ID:** {row['ID']} | **Name:** {row['Name']} | **Type:** {row['Type']} | **Region:** {row['Region']} | **Area:** {row['Area_ha']} ha | **Carbon:** {row['Carbon_tonnes']} t | **Credits:** {row['Credits']} | **Status:** {row['Status']}")
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button(f"Issue {row['ID']}", key=f"issue_{row['ID']}"):
                update_status(row['ID'], "issued")
                st.experimental_rerun()
        with col2:
            if st.button(f"Retire {row['ID']}", key=f"retire_{row['ID']}"):
                update_status(row['ID'], "retired")
                st.experimental_rerun()
        with col3:
            if st.button(f"Delete {row['ID']}", key=f"delete_{row['ID']}"):
                delete_project(row['ID'])
                st.experimental_rerun()

# ------------------------
# Public Dashboard
# ------------------------
def public_dashboard():
    st.subheader("Public Registry")
    df = get_all_projects()
    if df.empty:
        st.info("No projects available.")
    else:
        st.dataframe(df)

# ------------------------
# Main App
# ------------------------
def main():
    st.title("Blue Carbon Registry")

    if 'mode' not in st.session_state:
        st.session_state.mode = 'public'

    if st.session_state.mode == 'public':
        if st.button("Admin Login"):
            st.session_state.mode = 'login'
        public_dashboard()
    elif st.session_state.mode == 'login':
        password = st.text_input("Enter Admin Password", type="password")
        if st.button("Login"):
            if password == "admin123":  # change your admin password here
                st.session_state.mode = 'admin'
                st.experimental_rerun()
            else:
                st.error("Incorrect password!")
        if st.button("Back"):
            st.session_state.mode = 'public'
            st.experimental_rerun()
    elif st.session_state.mode == 'admin':
        if st.button("Logout"):
            st.session_state.mode = 'public'
            st.experimental_rerun()
        admin_dashboard()

# ------------------------
# Run App
# ------------------------
if __name__ == "__main__":
    main()
