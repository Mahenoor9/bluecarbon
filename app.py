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
              credits REAL,
              created_at TEXT)''')
conn.commit()

# ------------------------------
# Authentication (Admin Login)
# ------------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "bluecarbon123"

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# Login form
if not st.session_state.logged_in:
    st.title("🌍 BlueCarbon Registry")
    mode = st.radio("Choose Mode:", ["Public Mode", "Admin Login"])

    if mode == "Admin Login":
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                st.session_state.logged_in = True
                st.success("✅ Login successful! Welcome Admin.")
            else:
                st.error("❌ Invalid credentials")

# ------------------------------
# Public Mode (View only)
# ------------------------------
if not st.session_state.logged_in:
    st.subheader("📖 Public Registry View")
    projects = pd.read_sql("SELECT * FROM projects", conn)
    st.dataframe(projects)

# ------------------------------
# Admin Mode (Full Access)
# ------------------------------
if st.session_state.logged_in:
    st.sidebar.title("🔑 Admin Dashboard")
    st.sidebar.write(f"👤 Logged in as: {ADMIN_USERNAME}")
    if st.sidebar.button("🚪 Logout"):
        st.session_state.logged_in = False
        st.rerun()

    menu = st.sidebar.radio("Select Action:", ["View Projects", "Add Project", "Update Status", "Delete Project"])

    # View all projects
    if menu == "View Projects":
        st.subheader("📋 All Registered Projects")
        projects = pd.read_sql("SELECT * FROM projects", conn)
        st.dataframe(projects)

    # Add new project
    elif menu == "Add Project":
        st.subheader("➕ Add New Project")
        name = st.text_input("Project Name")
        type_ = st.selectbox("Project Type", ["Mangrove", "Industry", "Other"])
        region = st.text_input("Region")
        credits = st.number_input("Carbon Credits", min_value=0.0)
        if st.button("Add Project"):
            c.execute("INSERT INTO projects (name, type, region, status, credits, created_at) VALUES (?,?,?,?,?,?)",
                      (name, type_, region, "Issued", credits, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            st.success("✅ Project added successfully!")

    # Update project status
    elif menu == "Update Status":
        st.subheader("✏️ Update Project Status")
        projects = pd.read_sql("SELECT * FROM projects", conn)
        st.dataframe(projects)
        project_id = st.number_input("Enter Project ID to Update", min_value=1)
        new_status = st.selectbox("New Status", ["Issued", "Updated", "Retired", "Revoked"])
        if st.button("Update"):
            c.execute("UPDATE projects SET status=? WHERE project_id=?", (new_status, project_id))
            conn.commit()
            st.success("✅ Project status updated!")

    # Delete project
    elif menu == "Delete Project":
        st.subheader("🗑️ Delete Project")
        projects = pd.read_sql("SELECT * FROM projects", conn)
        st.dataframe(projects)
        project_id = st.number_input("Enter Project ID to Delete", min_value=1)
        if st.button("Delete"):
            c.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
            conn.commit()
            st.warning("⚠️ Project deleted successfully!")
