import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd

# ----------------------------
# Database setup
# ----------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create table if it doesn't exist
c.execute('''
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

# ----------------------------
# Helper functions
# ----------------------------
def calculate_credits(area, carbon):
    # Example formula: credits = area_ha * carbon_tonnes * 0.5
    return area * carbon * 0.5

def add_project(name, type_, region, area, carbon):
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects (name, type, region, status, area_ha, carbon_tonnes, credits, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, "Issued", area, carbon, credits, created_at))
    conn.commit()
    return credits

def delete_project(project_id):
    c.execute('DELETE FROM projects WHERE id=?', (project_id,))
    conn.commit()

def get_all_projects():
    c.execute('SELECT * FROM projects')
    data = c.fetchall()
    df = pd.DataFrame(data, columns=['ID','Name','Type','Region','Status','Area_ha','Carbon_tonnes','Credits','Created_at'])
    return df

# ----------------------------
# Admin dashboard
# ----------------------------
def admin_dashboard():
    st.title("Admin Dashboard")
    st.subheader("Add a new project")

    with st.form("add_project_form"):
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0)
        carbon = st.number_input("Carbon Emission (tonnes)", min_value=0.0)
        submitted = st.form_submit_button("Add Project")
        if submitted:
            credits = add_project(name, type_, region, area, carbon)
            st.success(f"Project added! Credits calculated: {credits:.2f}")
            st.session_state["refresh"] = True  # trigger refresh

    st.subheader("All Projects")
    df = get_all_projects()
    st.dataframe(df)

    st.subheader("Delete a project")
    project_ids = df['ID'].tolist()
    delete_id = st.selectbox("Select Project ID to delete", [0]+project_ids, format_func=lambda x: "Select" if x==0 else x)
    if st.button("Delete Project") and delete_id != 0:
        delete_project(delete_id)
        st.success(f"Project ID {delete_id} deleted")
        st.session_state["refresh"] = True  # trigger refresh

# ----------------------------
# Public dashboard
# ----------------------------
def public_dashboard():
    st.title("Public View of Registry")
    df = get_all_projects()
    st.dataframe(df)

# ----------------------------
# Main function
# ----------------------------
def main():
    if "refresh" not in st.session_state:
        st.session_state["refresh"] = False

    st.sidebar.title("Blue Carbon Registry")
    mode = st.sidebar.radio("Select Mode", ["Public", "Admin"])

    if mode == "Admin":
        password = st.sidebar.text_input("Enter admin password", type="password")
        if password == "admin123":  # change this password as needed
            admin_dashboard()
        elif password:
            st.sidebar.error("Wrong password")
    else:
        public_dashboard()

    # Handle refresh
    if st.session_state["refresh"]:
        st.session_state["refresh"] = False
        st.experimental_rerun()  # This line can be replaced in future Streamlit versions

# ----------------------------
# Run the app
# ----------------------------
if __name__ == "__main__":
    main()
