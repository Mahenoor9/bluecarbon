import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# -------------------------------
# Database Setup
# -------------------------------
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()

# Create projects table if it doesn't exist
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

# -------------------------------
# Helper Functions
# -------------------------------
def add_project(name, type_, region, area_ha, carbon_tonnes):
    # Automatic credit calculation
    credits = area_ha * carbon_tonnes * 0.5
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects (name, type, region, status, area_ha, carbon_tonnes, credits, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, 'Issued', area_ha, carbon_tonnes, credits, created_at))
    conn.commit()
    return credits

def get_all_projects():
    c.execute("SELECT * FROM projects")
    data = c.fetchall()
    if data:
        df = pd.DataFrame(data, columns=['ID','Name','Type','Region','Status','Area_ha','Carbon_tonnes','Credits','Created_at'])
        return df
    else:
        return pd.DataFrame(columns=['ID','Name','Type','Region','Status','Area_ha','Carbon_tonnes','Credits','Created_at'])

def delete_project(project_id):
    c.execute("DELETE FROM projects WHERE id=?", (project_id,))
    conn.commit()

def update_status(project_id, new_status):
    c.execute("UPDATE projects SET status=? WHERE id=?", (new_status, project_id))
    conn.commit()

# -------------------------------
# Admin Dashboard
# -------------------------------
def admin_dashboard():
    st.subheader("Admin Dashboard")
    menu = ["Add Project", "Manage Projects", "Bulk Upload CSV"]
    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Add Project":
        st.write("Add a New Project")
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area_ha = st.number_input("Area (ha)", min_value=0.0)
        carbon_tonnes = st.number_input("Carbon Stock (tonnes)", min_value=0.0)
        if st.button("Add Project"):
            credits = add_project(name, type_, region, area_ha, carbon_tonnes)
            st.success(f"Project added successfully! Credits calculated: {credits:.2f}")

    elif choice == "Manage Projects":
        df = get_all_projects()
        st.write("Manage Projects")
        if not df.empty:
            for idx, row in df.iterrows():
                st.write(f"**{row['Name']}** ({row['Type']}) - Status: {row['Status']}")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button(f"Delete {row['ID']}"):
                        delete_project(row['ID'])
                        st.experimental_rerun()
                with col2:
                    if st.button(f"Issue {row['ID']}"):
                        update_status(row['ID'], "Issued")
                        st.experimental_rerun()
                with col3:
                    if st.button(f"Retire {row['ID']}"):
                        update_status(row['ID'], "Retired")
                        st.experimental_rerun()
        else:
            st.info("No projects found.")

    elif choice == "Bulk Upload CSV":
        st.write("Upload CSV File")
        uploaded_file = st.file_uploader("Choose a CSV", type="csv")
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            for _, row in df.iterrows():
                add_project(row['Name'], row['Type'], row['Region'], row['Area_ha'], row['Carbon_tonnes'])
            st.success("CSV uploaded successfully!")

# -------------------------------
# Public Dashboard
# -------------------------------
def public_dashboard():
    st.subheader("Public Dashboard")
    df = get_all_projects()
    if not df.empty:
        st.dataframe(df)
        st.write("Summary:")
        st.write(f"Total Projects: {len(df)}")
        st.write(f"Total Credits: {df['Credits'].sum():.2f}")
        status_counts = df['Status'].value_counts()
        st.bar_chart(status_counts)
    else:
        st.info("No projects available.")

# -------------------------------
# Main App
# -------------------------------
def main():
    st.title("Blue Carbon Registry")

    # Initialize session state for login
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False

    menu = ["Public View", "Admin Login"]
    choice = st.sidebar.selectbox("Select Mode", menu)

    if choice == "Public View":
        public_dashboard()

    elif choice == "Admin Login":
        if not st.session_state.logged_in:
            st.subheader("Admin Login")
            password = st.text_input("Enter Admin Password", type="password")
            if st.button("Login"):
                if password == "admin123":
                    st.session_state.logged_in = True
                    st.success("Login Successful!")
                else:
                    st.error("Wrong Password!")
        else:
            admin_dashboard()

if __name__ == "__main__":
    main()

