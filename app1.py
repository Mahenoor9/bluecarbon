# ------------------------------
# Imports
# ------------------------------
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# ------------------------------
# Database setup
# ------------------------------

# Connect to local SQLite database
# A file called registry.db will be created in your folder if it doesn’t exist
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create the main projects table
c.execute(
    '''
    CREATE TABLE IF NOT EXISTS projects (
        project_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        type TEXT,
        region TEXT,
        area_ha REAL,
        carbon_stock REAL,
        credits REAL,
        status TEXT,
        created_at TEXT
    )
    '''
)
conn.commit()

# ------------------------------
# Helper functions
# ------------------------------

def add_project(name, ptype, region, area, carbon_stock, credits, status="Pending"):
    """
    Insert a new project entry into the database.
    Each project will be assigned a unique project_id.
    """
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        '''
        INSERT INTO projects 
        (name, type, region, area_ha, carbon_stock, credits, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (name, ptype, region, area, carbon_stock, credits, status, created_at)
    )
    conn.commit()


def get_all_projects():
    """
    Retrieve all project records from the database.
    Returns a Pandas DataFrame for easy visualization.
    """
    query = "SELECT * FROM projects"
    df = pd.read_sql(query, conn)
    return df


def update_status(project_id, new_status):
    """
    Update the status of a project (Pending, Issued, Retired).
    """
    c.execute("UPDATE projects SET status=? WHERE project_id=?", (new_status, project_id))
    conn.commit()


# ------------------------------
# Streamlit UI setup
# ------------------------------

st.set_page_config(
    page_title="Blue Carbon Registry",
    layout="wide"
)

# App Title
st.title("🌱 Blue Carbon MRV & Registry System")

# Sidebar menu
menu = st.sidebar.selectbox(
    "Navigate",
    ["Upload Project", "Admin Panel", "Public Ledger", "Dashboard"]
)

# ------------------------------
# Upload Project Page
# ------------------------------
if menu == "Upload Project":

    st.header("📤 Submit New Project / Industry Data")
    st.write("Fill out the form below to register a new project or industry offset activity.")

    with st.form("project_form", clear_on_submit=True):
        # Input fields
        name = st.text_input("Project / Industry Name")
        ptype = st.selectbox("Type of Project", ["Mangrove Restoration", "Seagrass", "Industry Offset"])
        region = st.text_input("Geographical Region")
        area = st.number_input("Area (ha)", min_value=0.0, step=0.1, format="%.2f")
        carbon_stock = st.number_input("Carbon Stock (tonnes)", min_value=0.0, step=0.1, format="%.2f")

        # Submit button
        submitted = st.form_submit_button("Submit Project")

        # Processing logic
        if submitted:
            if name and region and area > 0 and carbon_stock > 0:
                credits = carbon_stock * 0.9   # Example credit calculation: 90% of carbon stock
                add_project(name, ptype, region, area, carbon_stock, credits)
                st.success(f"✅ Project '{name}' submitted successfully!")
                st.info(f"Estimated Carbon Credits = **{credits:.2f}**")
            else:
                st.error("⚠️ Please fill in all fields correctly before submitting.")


# ------------------------------
# Admin Panel Page
# ------------------------------
elif menu == "Admin Panel":

    st.header("🛠 Admin Panel")
    st.write("View submitted projects and update their verification status.")

    df = get_all_projects()

    if not df.empty:
        st.subheader("All Projects in Registry")
        st.dataframe(df, use_container_width=True)

        # Select a project to update
        project_ids = df["project_id"].tolist()
        selected_id = st.selectbox("Select Project ID to Update", project_ids)

        # Status options
        new_status = st.radio("New Status", ["Pending", "Issued", "Retired"], horizontal=True)

        if st.button("Update Status"):
            update_status(selected_id, new_status)
            st.success(f"✅ Status updated for Project ID {selected_id} → {new_status}")

    else:
        st.info("No projects found in the registry yet.")


# ------------------------------
# Public Ledger Page
# ------------------------------
elif menu == "Public Ledger":

    st.header("📖 Public Carbon Credit Ledger")
    st.write("A transparent view of all registered projects and their issued credits.")

    df = get_all_projects()

    if not df.empty:
        # Show selected fields only
        ledger_df = df[["project_id", "name", "region", "credits", "status", "created_at"]]
        st.dataframe(ledger_df, use_container_width=True)
    else:
        st.info("Ledger is empty. No projects registered yet.")


# ------------------------------
# Dashboard Page
# ------------------------------
elif menu == "Dashboard":

    st.header("📊 Registry Dashboard")
    st.write("Summary of carbon projects, credits, and status.")

    df = get_all_projects()

    if not df.empty:
        # Metrics
        col1, col2, col3 = st.columns(3)
        total_projects = len(df)
        total_credits = round(df["credits"].sum(), 2)
        verified_projects = len(df[df["status"] == "Issued"])

        col1.metric("🌍 Total Projects", total_projects)
        col2.metric("🌱 Total Credits", total_credits)
        col3.metric("✅ Verified Projects", verified_projects)

        # Bar chart: credits by status
        st.subheader("Credits by Status")
        credits_by_status = df.groupby("status")["credits"].sum()
        st.bar_chart(credits_by_status)

        # Optional table for insights
        st.subheader("Project Summary Table")
        st.dataframe(df, use_container_width=True)

    else:
        st.info("No data available for dashboard.")
