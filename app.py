import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# ------------------------------
# Database setup
# ------------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create table if it does not exist
c.execute('''
CREATE TABLE IF NOT EXISTS projects (
    project_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    type TEXT,
    region TEXT,
    status TEXT,
    area REAL,
    carbon REAL,
    credits REAL,
    created_at TEXT
)
''')
conn.commit()

# ------------------------------
# Session state for admin login
# ------------------------------
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False

# ------------------------------
# Function to calculate credits
# ------------------------------
def calculate_credits(area_ha, carbon_tonnes):
    # Example formula: credits = carbon * area / 10
    return round(carbon_tonnes * area_ha / 10, 2)

# ------------------------------
# Add project to database
# ------------------------------
def add_project_to_db(name, type_, region, area, carbon):
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "Issued"
    c.execute('''
        INSERT INTO projects (name, type, region, status, area, carbon, credits, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, status, area, carbon, credits, created_at))
    conn.commit()
    return credits

# ------------------------------
# Get all projects from database
# ------------------------------
def get_all_projects():
    c.execute("SELECT * FROM projects")
    data = c.fetchall()
    if data:
        df = pd.DataFrame(data, columns=['ID', 'Name', 'Type', 'Region', 'Status', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Created_at'])
        return df
    else:
        return pd.DataFrame(columns=['ID', 'Name', 'Type', 'Region', 'Status', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Created_at'])

# ------------------------------
# Admin login
# ------------------------------
def admin_login():
    st.subheader("Admin Login")
    password = st.text_input("Enter admin password", type="password")
    login_button = st.button("Login")

    if login_button:
        if password == "admin123":  # set your admin password here
            st.session_state.admin_logged_in = True
        else:
            st.error("Wrong password")

# ------------------------------
# Admin dashboard
# ------------------------------
def admin_dashboard():
    st.subheader("Admin Dashboard")
    
    # Project input form
    st.write("Add New Project")
    name = st.text_input("Project Name")
    type_ = st.selectbox("Project Type", ["Forestry", "Wetlands", "Coastal", "Other"])
    region = st.text_input("Region")
    area = st.number_input("Area (ha)", min_value=0.0, step=0.1)
    carbon = st.number_input("Carbon Stock (tonnes)", min_value=0.0, step=0.1)
    
    if st.button("Add Project"):
        if name and type_ and region and area > 0 and carbon > 0:
            credits = add_project_to_db(name, type_, region, area, carbon)
            st.success(f"Project added! Credits generated: {credits}")
        else:
            st.error("Please fill all fields correctly")
    
    # Show all projects
    st.write("All Projects")
    df = get_all_projects()
    st.dataframe(df)

# ------------------------------
# Public dashboard
# ------------------------------
def public_dashboard():
    st.subheader("Public View")
    st.write("View all registered carbon projects")
    df = get_all_projects()
    st.dataframe(df)

# ------------------------------
# Main function
# ------------------------------
def main():
    st.title("Blue Carbon Registry")
    
    mode = st.radio("Choose mode:", ["Public", "Admin"])
    
    if mode == "Admin":
        if not st.session_state.admin_logged_in:
            admin_login()
        else:
            admin_dashboard()
    else:
        public_dashboard()

if __name__ == "__main__":
    main()
