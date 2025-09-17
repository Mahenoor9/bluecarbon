import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# ------------------------------
# Database Setup
# ------------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create table if not exists
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
# Helper Functions
# ------------------------------
def calculate_credits(area, carbon):
    # Simple formula for credits; can modify coefficient
    return area * carbon * 0.1

def add_project(name, type_, region, area, carbon):
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects (name, type, region, status, area_ha, carbon_tonnes, credits, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, 'Issued', area, carbon, credits, created_at))
    conn.commit()
    return credits

def get_all_projects():
    c.execute("SELECT * FROM projects")
    data = c.fetchall()
    df = pd.DataFrame(data, columns=['ID', 'Name', 'Type', 'Region', 'Status', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Created_at'])
    return df

def update_status(project_id, new_status):
    c.execute("UPDATE projects SET status=? WHERE project_id=?", (new_status, project_id))
    conn.commit()

def delete_project(project_id):
    c.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
    conn.commit()

# ------------------------------
# Admin Dashboard
# ------------------------------
def admin_dashboard():
    st.title("Admin Dashboard - Carbon Registry")

    st.subheader("Add New Project")
    with st.form("add_project_form"):
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0)
        carbon = st.number_input("Carbon Stock (tonnes)", min_value=0.0)
        submitted = st.form_submit_button("Add Project")
        if submitted:
            if name and type_ and region:
                credits = add_project(name, type_, region, area, carbon)
                st.success(f"Project added successfully! Calculated credits: {credits}")
            else:
                st.error("Please fill all the fields!")

    st.subheader("Project Dashboard")
    df = get_all_projects()
    if not df.empty:
        for index, row in df.iterrows():
            st.markdown(f"**{row['Name']}** | Type: {row['Type']} | Region: {row['Region']} | Status: {row['Status']} | Area: {row['Area_ha']} ha | Carbon: {row['Carbon_tonnes']} tonnes | Credits: {row['Credits']}")
            cols = st.columns(3)
            if cols[0].button("Issue", key=f"issue{row['ID']}"):
                update_status(row['ID'], "Issued")
                st.experimental_rerun()
            if cols[1].button("Retire", key=f"retire{row['ID']}"):
                update_status(row['ID'], "Retired")
                st.experimental_rerun()
            if cols[2].button("Delete", key=f"delete{row['ID']}"):
                delete_project(row['ID'])
                st.experimental_rerun()
    else:
        st.info("No projects available.")

# ------------------------------
# Public Dashboard
# ------------------------------
def public_dashboard():
    st.title("Public Dashboard - Carbon Registry")
    df = get_all_projects()
    if not df.empty:
        st.dataframe(df)
    else:
        st.info("No projects available for public view.")

# ------------------------------
# Main Function
# ------------------------------
def main():
    st.sidebar.title("Carbon Registry")
    mode = st.sidebar.selectbox("Select Mode", ["Public", "Admin"])
    
    if mode == "Admin":
        password = st.sidebar.text_input("Enter Admin Password", type="password")
        if password == "admin123":  # Set your admin password here
            admin_dashboard()
        elif password:
            st.sidebar.error("Incorrect password!")
    else:
        public_dashboard()

# ------------------------------
# Run App
# ------------------------------
if __name__ == "__main__":
    main()
