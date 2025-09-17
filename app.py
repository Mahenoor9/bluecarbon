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
              area_ha REAL,
              carbon_tonnes REAL,
              credits REAL,
              status TEXT,
              created_at TEXT)''')
conn.commit()

# ------------------------------
# Session state initialization
# ------------------------------
if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False

if "admin_password" not in st.session_state:
    st.session_state.admin_password = "Admin@123"  # Change this to your desired password

# ------------------------------
# Utility functions
# ------------------------------
def calculate_credits(area, carbon_tonnes):
    # Simple formula: 1 credit per tonne of carbon * area factor
    # You can change this formula as per your rules
    return carbon_tonnes * area * 0.1

def add_project_to_db(name, type_, region, area, carbon, status="Issued"):
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO projects 
                 (name, type, region, area_ha, carbon_tonnes, credits, status, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (name, type_, region, area, carbon, credits, status, created_at))
    conn.commit()
    return credits

def load_projects():
    df = pd.read_sql_query("SELECT * FROM projects", conn)
    return df

# ------------------------------
# Admin login page
# ------------------------------
def admin_login():
    st.title("Admin Login")
    password_input = st.text_input("Enter admin password", type="password")

    if st.button("Login"):
        if password_input == st.session_state.admin_password:
            st.session_state.admin_logged_in = True
            st.success("Logged in successfully!")
        else:
            st.error("Wrong password! Try again.")

# ------------------------------
# Admin dashboard
# ------------------------------
def admin_dashboard():
    st.title("Admin Dashboard - Blue Carbon Registry")

    st.subheader("Add New Project")
    name = st.text_input("Project Name")
    type_ = st.selectbox("Project Type", ["Forestry", "Mangrove", "Wetland", "Other"])
    region = st.text_input("Region")
    area = st.number_input("Area (ha)", min_value=0.0, step=0.1)
    carbon = st.number_input("Carbon Stock (tonnes)", min_value=0.0, step=0.1)

    if st.button("Add Project"):
        if name and region and area > 0 and carbon > 0:
            credits = add_project_to_db(name, type_, region, area, carbon)
            st.success(f"Project added! Credits generated: {credits:.2f}")
        else:
            st.error("Please fill all fields correctly.")

    st.subheader("Uploaded Projects")
    projects_df = load_projects()
    st.dataframe(projects_df)

# ------------------------------
# Public view
# ------------------------------
def public_view():
    st.title("Public Blue Carbon Registry")
    st.subheader("View Projects")

    projects_df = load_projects()
    st.dataframe(projects_df)

    st.subheader("Upload CSV File")
    uploaded_file = st.file_uploader("Upload CSV (Region, Area_ha, Carbon_Stock_tonnes, Type, Status)", type=["csv"])
    if uploaded_file is not None:
        try:
            csv_data = pd.read_csv(uploaded_file)
            for idx, row in csv_data.iterrows():
                add_project_to_db(
                    name=row.get("Project_Name", f"Project_{idx+1}"),
                    type_=row.get("Type", "Other"),
                    region=row.get("Region", "Unknown"),
                    area=float(row.get("Area_ha", 0)),
                    carbon=float(row.get("Carbon_Stock_tonnes", 0)),
                    status=row.get("Status", "Issued")
                )
            st.success("CSV uploaded and projects added successfully!")
        except Exception as e:
            st.error(f"Error processing CSV: {e}")

# ------------------------------
# Main
# ------------------------------
def main():
    st.sidebar.title("Navigation")
    mode = st.sidebar.selectbox("Choose Mode", ["Public", "Admin"])

    if mode == "Admin":
        if st.session_state.admin_logged_in:
            admin_dashboard()
        else:
            admin_login()
    else:
        public_view()

if __name__ == "__main__":
    main()
