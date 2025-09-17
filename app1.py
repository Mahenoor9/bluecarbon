import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd

# ------------------------------
# Database setup
# ------------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create projects table
c.execute('''
    CREATE TABLE IF NOT EXISTS projects (
        project_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        type TEXT,
        region TEXT,
        status TEXT,
        area_ha REAL,
        carbon_tonnes REAL,
        credits REAL,
        created_at TEXT
    )
''')
conn.commit()

# ------------------------------
# Helper functions
# ------------------------------
def calculate_credits(area, carbon):
    """Simple formula: 1 credit = 1 hectare * 0.5 * carbon tonnes"""
    return round(area * carbon * 0.5, 2)

def add_project(name, type_, region, area, carbon):
    credits = calculate_credits(area, carbon)
    c.execute('''
        INSERT INTO projects (name, type, region, status, area_ha, carbon_tonnes, credits, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, "Issued", area, carbon, credits, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    return credits

def get_all_projects():
    c.execute('SELECT * FROM projects')
    data = c.fetchall()
    df = pd.DataFrame(data, columns=[
        'ID', 'Name', 'Type', 'Region', 'Status', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Created_at'
    ])
    return df

def delete_project(project_id):
    c.execute('DELETE FROM projects WHERE project_id=?', (project_id,))
    conn.commit()

# ------------------------------
# Admin Dashboard
# ------------------------------
def admin_dashboard():
    st.title("Admin Dashboard")
    
    st.subheader("Add New Project")
    name = st.text_input("Project Name")
    type_ = st.text_input("Project Type")
    region = st.text_input("Region")
    area = st.number_input("Area (ha)", min_value=0.0, step=0.1)
    carbon = st.number_input("Carbon Stock (tonnes)", min_value=0.0, step=0.1)
    
    if st.button("Add Project"):
        if name and type_ and region:
            credits = add_project(name, type_, region, area, carbon)
            st.success(f"Project added successfully! Credits: {credits}")
        else:
            st.error("Please fill all fields!")

    st.subheader("All Projects")
    df = get_all_projects()
    st.dataframe(df)

    st.subheader("Delete Project")
    delete_id = st.number_input("Enter Project ID to delete", min_value=1, step=1)
    if st.button("Delete Project"):
        delete_project(delete_id)
        st.success(f"Project {delete_id} deleted successfully!")

# ------------------------------
# Public Dashboard
# ------------------------------
def public_dashboard():
    st.title("Public Dashboard")
    st.subheader("All Projects")
    df = get_all_projects()
    st.dataframe(df)

# ------------------------------
# Main app
# ------------------------------
def main():
    st.sidebar.title("Blue Carbon Registry")
    mode = st.sidebar.selectbox("Select Mode", ["Public", "Admin"])
    
    if mode == "Admin":
        password = st.sidebar.text_input("Enter Admin Password", type="password")
        if st.sidebar.button("Login"):
            if password == "admin123":  # Change this password as needed
                st.success("Login Successful!")
                admin_dashboard()
            else:
                st.error("Incorrect Password!")
    else:
        public_dashboard()

if __name__ == "__main__":
    main()
