import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import io

# -------------------
# DATABASE SETUP
# -------------------
# Connect to SQLite database
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()
c.execute("PRAGMA foreign_keys = ON")

# Drop old table to ensure fresh start
c.execute('DROP TABLE IF EXISTS projects')
conn.commit()

# Create new projects table with all necessary columns
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
    created_at TEXT,
    explanation TEXT
)
''')
conn.commit()

# -------------------
# HELPER FUNCTIONS
# -------------------

def calculate_credits(area, carbon):
    """
    Calculate carbon credits based on area and carbon.
    Formula: credits = area * 0.5 + carbon * 0.2
    Args:
        area (float): Project area in hectares
        carbon (float): Carbon stored in tonnes
    Returns:
        float: Calculated carbon credits
    """
    return round(area * 0.5 + carbon * 0.2, 2)

def predict_carbon_llm(area):
    """
    Placeholder function for LLM prediction of carbon.
    Args:
        area (float): Project area in hectares
    Returns:
        carbon_estimate (float): Estimated carbon
        explanation (str): Explanation string for LLM prediction
    """
    carbon_estimate = area * 4.0
    explanation = f"Carbon estimated as {area} ha * 4.0 tCO₂/ha"
    return carbon_estimate, explanation

def add_project(name, type_, region, area, carbon, explanation=""):
    """
    Add a new project to the database.
    Calculates credits automatically.
    Args:
        name (str): Project name
        type_ (str): Project type
        region (str): Region name
        area (float): Area in hectares
        carbon (float): Carbon stored in tonnes
        explanation (str): Explanation of how carbon was determined
    """
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects 
        (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, area, carbon, credits, "Issued", created_at, explanation))
    conn.commit()

def delete_project(proj_id):
    """
    Delete a project from the database using its ID.
    Args:
        proj_id (int): Project ID
    """
    c.execute('DELETE FROM projects WHERE id=?', (proj_id,))
    conn.commit()

def update_status(proj_id, status):
    """
    Update the status of a project.
    Args:
        proj_id (int): Project ID
        status (str): New status (e.g., "Retired", "Issued")
    """
    c.execute('UPDATE projects SET status=? WHERE id=?', (status, proj_id))
    conn.commit()

def get_all_projects():
    """
    Retrieve all projects from the database.
    Returns:
        pd.DataFrame: Dataframe containing all projects
    """
    c.execute("SELECT * FROM projects")
    data = c.fetchall()
    columns = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation']
    df = pd.DataFrame(data, columns=columns)
    return df

def do_rerun():
    """
    Force Streamlit to rerun the app.
    Handles multiple Streamlit versions.
    """
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.experimental_set_query_params(_=datetime.now().timestamp())

# -------------------
# ADMIN DASHBOARD
# -------------------

def admin_dashboard():
    """
    Admin dashboard to manage projects.
    Includes manual entry and CSV bulk upload.
    Displays project table and controls.
    """
    st.title("Admin Dashboard")
    
    # Select input mode
    input_mode = st.radio("Choose Input Method", ["Manual Entry", "Bulk CSV Upload"])
    
    # -------------------
    # MANUAL ENTRY
    # -------------------
    if input_mode == "Manual Entry":
        st.subheader("Add New Project")
        
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0)
        carbon = st.number_input("Carbon Stored (tonnes)", min_value=0.0)
        
        if st.button("Add Project"):
            if name and type_ and region and area > 0:
                if carbon == 0.0:
                    carbon, explanation = predict_carbon_llm(area)
                else:
                    explanation = ""
                
                add_project(name, type_, region, area, carbon, explanation)
                st.success("Project added successfully!")
                do_rerun()
            else:
                st.error("Please fill all required fields and make sure area > 0!")

    # -------------------
    # BULK CSV UPLOAD
    # -------------------
    elif input_mode == "Bulk CSV Upload":
        st.subheader("Upload CSV Files")
        
        # CSV template download
        template = pd.DataFrame({
            "name": ["Project A"],
            "type": ["Afforestation"],
            "region": ["India"],
            "area_ha": [100],
            "carbon_tonnes": [400]
        })
        buffer = io.BytesIO()
        template.to_csv(buffer, index=False)
        st.download_button("Download CSV Template", buffer.getvalue(), "template.csv", "text/csv")
        
        # File uploader
        uploaded_files = st.file_uploader("Upload CSV files", type=["csv"], accept_multiple_files=True)
        all_dfs = []
        if uploaded_files:
            for file in uploaded_files:
                st.markdown(f"### 📂 {file.name}")
                df = pd.read_csv(file)
                st.dataframe(df.head())
                all_dfs.append(df)
            
            if st.button("Add All Projects"):
                for df in all_dfs:
                    for _, row in df.iterrows():
                        name = row.get("name")
                        type_ = row.get("type")
                        region = row.get("region")
                        area = row.get("area_ha")
                        carbon = row.get("carbon_tonnes")
                        
                        # Skip invalid rows
                        if pd.isna(area) or area <= 0:
                            st.warning(f"Skipping row '{name}': missing area")
                            continue
                        
                        if pd.isna(carbon):
                            carbon, explanation = predict_carbon_llm(area)
                        else:
                            explanation = ""
                        
                        add_project(name, type_, region, float(area), float(carbon), explanation)
                
                st.success("All uploaded projects imported successfully!")
                do_rerun()
    
    # -------------------
    # PROJECTS TABLE
    # -------------------
    st.subheader("Projects Overview")
    df = get_all_projects()
    
    if not df.empty:
        # Display table with explanations in expanders
        for i, row in df.iterrows():
            cols = st.columns([3,1])
            with cols[0]:
                st.markdown(f"**{row['Name']}** - Carbon: {row['Carbon_tonnes']} tonnes")
            with cols[1]:
                with st.expander("ℹ️ Explanation"):
                    if row['Explanation']:
                        st.write(row['Explanation'])
                    else:
                        st.write("No explanation available")
        
        # Manage project buttons
        for _, row in df.iterrows():
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button(f"Delete {row['ID']}", key=f"del_{row['ID']}"):
                    delete_project(row['ID'])
                    do_rerun()
            with col2:
                if st.button(f"Retire {row['ID']}", key=f"ret_{row['ID']}"):
                    update_status(row['ID'], "Retired")
                    do_rerun()
            with col3:
                if st.button(f"Issue {row['ID']}", key=f"iss_{row['ID']}"):
                    update_status(row['ID'], "Issued")
                    do_rerun()
    else:
        st.info("No projects yet!")

# -------------------
# PUBLIC DASHBOARD
# -------------------

def public_dashboard():
    """
    Public dashboard to view all projects.
    Includes explanations in expanders.
    """
    st.title("Public Registry")
    df = get_all_projects()
    
    if not df.empty:
        st.dataframe(df[['Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status']])
        
        # Show explanations for each project
        for i, row in df.iterrows():
            with st.expander(f"{row['Name']} - ℹ️ Explanation"):
                if row['Explanation']:
                    st.write(row['Explanation'])
                else:
                    st.write("No explanation available")
    else:
        st.info("No projects available.")

# -------------------
# MAIN APP
# -------------------

def main():
    st.sidebar.title("Carbon Registry")
    mode = st.sidebar.selectbox("Select Mode", ["Public", "Admin"])
    
    if mode == "Admin":
        password = st.sidebar.text_input("Enter Admin Password", type="password")
        if password == "admin123":
            admin_dashboard()
        elif password:
            st.sidebar.error("Wrong password!")
    else:
        public_dashboard()

# -------------------
# RUN APP
# -------------------
if __name__ == "__main__":
    main()
