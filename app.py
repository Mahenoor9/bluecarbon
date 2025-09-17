import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# ------------------------------
# Database setup
# ------------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create projects table if not exists
c.execute('''CREATE TABLE IF NOT EXISTS projects
             (project_id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT,
              type TEXT,
              region TEXT,
              status TEXT,
              area_ha REAL,
              carbon_stock_tonnes REAL,
              credits REAL,
              created_on TEXT)''')
conn.commit()

# ------------------------------
# Helper functions
# ------------------------------

def calculate_credits(area, carbon_stock):
    """
    Formula for calculating credits:
    Example: 1 credit = 1 tonne CO2 equivalent
    Modify this formula as needed
    """
    # Simple example: credits proportional to carbon_stock
    credits = carbon_stock  
    return credits

def add_project(name, type_, region, status, area, carbon_stock):
    credits = calculate_credits(area, carbon_stock)
    created_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO projects
                 (name, type, region, status, area_ha, carbon_stock_tonnes, credits, created_on)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (name, type_, region, status, area, carbon_stock, credits, created_on))
    conn.commit()

def get_all_projects():
    c.execute("SELECT * FROM projects")
    rows = c.fetchall()
    df = pd.DataFrame(rows, columns=[
        "Project ID", "Name", "Type", "Region", "Status",
        "Area (ha)", "Carbon Stock (tonnes)", "Credits", "Created On"
    ])
    return df

# ------------------------------
# Streamlit UI
# ------------------------------

st.title("🌱 Blue Carbon Registry")

# Mode selection
mode = st.sidebar.selectbox("Select Mode", ["Public", "Admin"])

# Admin password
ADMIN_PASSWORD = "admin123"  # change this password

if mode == "Admin":
    password = st.sidebar.text_input("Enter Admin Password", type="password")
    if password == ADMIN_PASSWORD:
        st.subheader("Admin Dashboard")

        # Create new project
        st.markdown("### Create New Project")
        with st.form("add_project_form"):
            name = st.text_input("Project Name")
            type_ = st.selectbox("Project Type", ["Reforestation", "Afforestation", "Mangrove"])
            region = st.text_input("Region")
            status = st.selectbox("Status", ["Issued", "Updated", "Retired", "Revoked"])
            area = st.number_input("Area (ha)", min_value=0.0)
            carbon_stock = st.number_input("Carbon Stock (tonnes)", min_value=0.0)
            submitted = st.form_submit_button("Add Project")
            if submitted:
                if name and region:
                    add_project(name, type_, region, status, area, carbon_stock)
                    st.success(f"Project '{name}' added successfully!")
                else:
                    st.error("Project Name and Region are required!")

        # View all projects
        st.markdown("### All Projects")
        df = get_all_projects()
        st.dataframe(df)

    else:
        st.error("🔒 Incorrect password. Access denied.")

else:  # Public mode
    st.subheader("Public View")
    st.markdown("You can view all registered projects below:")
    df = get_all_projects()
    st.dataframe(df)
