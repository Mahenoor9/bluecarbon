import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd

# ------------------------------
# Database setup
# ------------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create table if it doesn't exist
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
# Function to add project
# ------------------------------
def add_project_to_db(name, type_, region, area, carbon):
    # Simple formula for credits
    credits = area * carbon  # You can change formula if needed
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "issued"

    c.execute('''
    INSERT INTO projects (name, type, region, status, area, carbon, credits, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, status, area, carbon, credits, created_at))
    conn.commit()
    return credits

# ------------------------------
# Function to fetch all projects
# ------------------------------
def get_all_projects():
    c.execute("SELECT * FROM projects")
    data = c.fetchall()
    df = pd.DataFrame(data, columns=['ID', 'Name', 'Type', 'Region', 'Status', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Created_at'])
    return df

# ------------------------------
# Admin Dashboard
# ------------------------------
def admin_dashboard():
    st.subheader("Admin Dashboard - Add New Project")
    
    with st.form(key="admin_form"):
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0, step=0.01)
        carbon = st.number_input("Carbon Stock (tonnes)", min_value=0.0, step=0.01)
        submit_button = st.form_submit_button(label="Add Project")

        if submit_button:
            if name and type_ and region:
                credits = add_project_to_db(name, type_, region, area, carbon)
                st.success(f"Project '{name}' added successfully! Calculated Credits: {credits}")
            else:
                st.error("Please fill in all fields.")

    st.subheader("All Projects")
    df = get_all_projects()
    st.dataframe(df)

# ------------------------------
# Public View
# ------------------------------
def public_dashboard():
    st.subheader("Public View - Carbon Projects")
    df = get_all_projects()
    if not df.empty:
        st.dataframe(df[['Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status']])
    else:
        st.info("No projects available yet.")

# ------------------------------
# Main App
# ------------------------------
def main():
    st.title("Blue Carbon Registry")

    menu = ["Public", "Admin"]
    choice = st.sidebar.selectbox("Choose Mode", menu)

    if choice == "Admin":
        st.subheader("Admin Login")
        password = st.text_input("Enter Admin Password", type="password")
        login_button = st.button("Login")
        if login_button:
            if password == "admin123":  # You can change password here
                st.success("Logged in as Admin")
                admin_dashboard()
            else:
                st.error("Incorrect password. Try again.")
    else:
        public_dashboard()

if __name__ == "__main__":
    main()
