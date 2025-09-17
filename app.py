import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# -----------------------------------------
# DATABASE SETUP
# -----------------------------------------
# Connect to SQLite database (auto-creates if not exist)
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create table for projects
c.execute('''
CREATE TABLE IF NOT EXISTS projects (
    project_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    type TEXT,
    region TEXT,
    area_ha REAL,
    carbon_stock_tonnes REAL,
    credits REAL,
    status TEXT,
    created_at TEXT
)
''')
conn.commit()

# -----------------------------------------
# ADMIN SETTINGS
# -----------------------------------------
ADMIN_PASSWORD = "admin123"  # change this to your desired password

# -----------------------------------------
# UTILITY FUNCTIONS
# -----------------------------------------
def add_project(name, ptype, region, area, carbon_stock):
    """Add project to database with automatic credit calculation."""
    credits = area * carbon_stock  # simple formula: area * carbon stock
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects (name, type, region, area_ha, carbon_stock_tonnes, credits, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, ptype, region, area, carbon_stock, credits, "Issued", created_at))
    conn.commit()
    return credits

def get_projects(status=None):
    """Fetch projects from database. Optionally filter by status."""
    if status:
        c.execute("SELECT * FROM projects WHERE status=?", (status,))
    else:
        c.execute("SELECT * FROM projects")
    rows = c.fetchall()
    columns = [desc[0] for desc in c.description]
    return pd.DataFrame(rows, columns=columns)

def update_status(project_id, new_status):
    """Update project status."""
    c.execute("UPDATE projects SET status=? WHERE project_id=?", (new_status, project_id))
    conn.commit()

# -----------------------------------------
# STREAMLIT APP
# -----------------------------------------
st.title("🌱 Blue Carbon Registry")

# Mode selection
mode = st.selectbox("Select Mode:", ["Public", "Admin"])

if mode == "Admin":
    # Admin login section
    password = st.text_input("Enter admin password:", type="password")
    if st.button("Login"):
        if password == ADMIN_PASSWORD:
            st.success("✅ Welcome, Admin!")
            
            # Tabs for admin functions
            tabs = st.tabs(["Dashboard", "Add Project", "Upload CSV", "Manage Projects"])
            
            # -----------------------
            # Dashboard Tab
            # -----------------------
            with tabs[0]:
                st.header("Admin Dashboard")
                all_projects = get_projects()
                if all_projects.empty:
                    st.info("No projects in registry yet.")
                else:
                    st.dataframe(all_projects)
                    total_credits = all_projects['credits'].sum()
                    st.metric("Total Carbon Credits Issued", total_credits)
            
            # -----------------------
            # Add Project Tab
            # -----------------------
            with tabs[1]:
                st.header("Add Single Project")
                name = st.text_input("Project Name")
                ptype = st.selectbox("Project Type", ["Reforestation", "Afforestation", "Blue Carbon"])
                region = st.text_input("Region")
                area = st.number_input("Area (ha)", min_value=0.0, step=0.1)
                carbon_stock = st.number_input("Carbon Stock (tonnes/ha)", min_value=0.0, step=0.1)
                
                if st.button("Add Project"):
                    if name and region and area > 0 and carbon_stock > 0:
                        credits = add_project(name, ptype, region, area, carbon_stock)
                        st.success(f"Project added! Calculated credits: {credits}")
                    else:
                        st.error("Please fill all fields with valid values.")
            
            # -----------------------
            # Upload CSV Tab
            # -----------------------
            with tabs[2]:
                st.header("Upload Projects via CSV")
                st.info("CSV must include columns: name, type, region, area_ha, carbon_stock_tonnes")
                uploaded_file = st.file_uploader("Choose CSV", type="csv")
                
                if uploaded_file:
                    df = pd.read_csv(uploaded_file)
                    if set(["name","type","region","area_ha","carbon_stock_tonnes"]).issubset(df.columns):
                        for _, row in df.iterrows():
                            add_project(row["name"], row["type"], row["region"], row["area_ha"], row["carbon_stock_tonnes"])
                        st.success("All projects from CSV added successfully!")
                    else:
                        st.error("CSV missing required columns.")
            
            # -----------------------
            # Manage Projects Tab
            # -----------------------
            with tabs[3]:
                st.header("Manage Projects Status")
                df_projects = get_projects()
                if not df_projects.empty:
                    for idx, row in df_projects.iterrows():
                        st.write(f"Project: {row['name']} | Status: {row['status']}")
                        new_status = st.selectbox(f"Update Status for {row['name']}", ["Issued", "Updated", "Retired", "Revoked"], key=row['project_id'])
                        if st.button(f"Update {row['name']}", key=f"btn_{row['project_id']}"):
                            update_status(row['project_id'], new_status)
                            st.success(f"Status updated to {new_status}")
                else:
                    st.info("No projects to manage.")
            
        else:
            st.error("❌ Wrong password! Please try again.")

# -----------------------
# Public Mode
# -----------------------
else:
    st.info("You are in Public Mode. Viewing all issued projects.")
    public_projects = get_projects()
    if not public_projects.empty:
        st.dataframe(public_projects)
        st.metric("Total Carbon Credits Issued", public_projects['credits'].sum())
    else:
        st.info("No projects issued yet.")
