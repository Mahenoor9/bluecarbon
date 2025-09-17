import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd

# -------------------
# Database Setup
# -------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create table if not exists
c.execute('''
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    type TEXT,
    region TEXT,
    area_ha REAL,
    carbon_tonnes REAL,
    credits REAL,
    status TEXT,
    created_at TEXT
)
''')
conn.commit()

# -------------------
# Helper Functions
# -------------------

def calculate_credits(area, carbon):
    # Example formula: 1 ha stores 0.5 tonnes carbon = 0.5 credits
    return round(area * 0.5 + carbon * 0.2, 2)

def add_project(name, type_, region, area, carbon):
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects (name, type, region, area_ha, carbon_tonnes, credits, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, area, carbon, credits, "Issued", created_at))
    conn.commit()

def delete_project(proj_id):
    c.execute('DELETE FROM projects WHERE id=?', (proj_id,))
    conn.commit()

def update_status(proj_id, status):
    c.execute('UPDATE projects SET status=? WHERE id=?', (status, proj_id))
    conn.commit()

def get_all_projects():
    c.execute('SELECT * FROM projects')
    data = c.fetchall()
    if data:
        df = pd.DataFrame(data, columns=['ID', 'Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status', 'Created_at'])
        return df
    else:
        return pd.DataFrame(columns=['ID', 'Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status', 'Created_at'])

# -------------------
# Admin Dashboard
# -------------------

def admin_dashboard():
    st.title("Admin Dashboard")
    st.subheader("Add New Project")
    
    name = st.text_input("Project Name")
    type_ = st.text_input("Project Type")
    region = st.text_input("Region")
    area = st.number_input("Area (ha)", min_value=0.0)
    carbon = st.number_input("Carbon Stored (tonnes)", min_value=0.0)
    
    if st.button("Add Project"):
        if name and type_ and region:
            add_project(name, type_, region, area, carbon)
            st.success("Project added successfully!")
        else:
            st.error("Fill all required fields!")

    st.subheader("Projects Overview")
    df = get_all_projects()
    if not df.empty:
        st.dataframe(df)

        st.subheader("Manage Projects")
        for i, row in df.iterrows():
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button(f"Delete {row['ID']}", key=f"del_{row['ID']}"):
                    delete_project(row['ID'])
                    st.experimental_rerun()
            with col2:
                if st.button(f"Retire {row['ID']}", key=f"ret_{row['ID']}"):
                    update_status(row['ID'], "Retired")
                    st.experimental_rerun()
            with col3:
                if st.button(f"Issue {row['ID']}", key=f"iss_{row['ID']}"):
                    update_status(row['ID'], "Issued")
                    st.experimental_rerun()
    else:
        st.info("No projects yet!")

# -------------------
# Public Dashboard
# -------------------

def public_dashboard():
    st.title("Public Registry")
    df = get_all_projects()
    if not df.empty:
        st.dataframe(df)
    else:
        st.info("No projects available.")

# -------------------
# Main App
# -------------------

def main():
    st.sidebar.title("Carbon Registry")
    mode = st.sidebar.selectbox("Select Mode", ["Public", "Admin"])

    if mode == "Admin":
        password = st.sidebar.text_input("Enter Admin Password", type="password")
        if password == "admin123":  # set your admin password here
            admin_dashboard()
        elif password:
            st.sidebar.error("Wrong password!")
    else:
        public_dashboard()

if __name__ == "__main__":
    main()
