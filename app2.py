import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import io
import requests

# -----------------------------
# DATABASE SETUP
# -----------------------------
# Connect to SQLite database
conn = sqlite3.connect("registry.db", check_same_thread=False)
c = conn.cursor()
c.execute("PRAGMA foreign_keys = ON")

# Create projects table if it doesn't exist
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

# -----------------------------
# PHI-3 MINI CONFIGURATION
# -----------------------------
REPLICATE_API_TOKEN = "YOUR_REPLICATE_API_TOKEN_HERE"
MODEL_VERSION = "YOUR_MODEL_VERSION_HERE"
ENDPOINT = "https://api.replicate.com/v1/predictions"
HEADERS = {
    "Authorization": f"Token {REPLICATE_API_TOKEN}",
    "Content-Type": "application/json",
}

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------

def calculate_credits(area, carbon):
    """
    Calculate carbon credits for a project.
    Formula: credits = area * 0.5 + carbon * 0.2
    """
    credits = area * 0.5 + carbon * 0.2
    return round(credits, 2)

@st.cache_data
def predict_carbon_llm(area, project_type="Unknown", region="Unknown"):
    """
    Calls Phi-3 Mini LLM to predict carbon stored for a project.
    Returns carbon_estimate and detailed explanation.
    """
    prompt = f"Estimate carbon stored (in tonnes) for a {area} hectare {project_type} project in {region}. Provide numeric estimate and explanation."
    data = {
        "version": MODEL_VERSION,
        "input": {
            "messages": [
                {"role": "system", "content": "You are a climate scientist and carbon accounting expert."},
                {"role": "user", "content": prompt}
            ]
        }
    }
    try:
        response = requests.post(ENDPOINT, headers=HEADERS, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        if "output" in result and len(result["output"]) > 0:
            explanation = result["output"][0]["text"]
            try:
                carbon_estimate = float(explanation.split()[0])
            except:
                carbon_estimate = area * 4.0
        else:
            carbon_estimate = area * 4.0
            explanation = f"Fallback: Carbon estimated as {area} ha * 4 tCO2/ha"
    except Exception as e:
        carbon_estimate = area * 4.0
        explanation = f"Fallback due to API error: {str(e)} | Carbon estimated as {area} ha * 4 tCO2/ha"
    return carbon_estimate, explanation

def add_project(name, type_, region, area, carbon, explanation=""):
    """
    Adds a new project to the SQLite database.
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
    Deletes a project by its ID from the database.
    """
    c.execute('DELETE FROM projects WHERE id=?', (proj_id,))
    conn.commit()

def update_status(proj_id, status):
    """
    Updates a project's status (Issued or Retired).
    """
    c.execute('UPDATE projects SET status=? WHERE id=?', (status, proj_id))
    conn.commit()

def get_all_projects():
    """
    Returns all projects as a Pandas DataFrame.
    """
    c.execute("SELECT * FROM projects")
    data = c.fetchall()
    columns = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation']
    df = pd.DataFrame(data, columns=columns)
    return df

def do_rerun():
    """
    Forces Streamlit to rerun the app.
    """
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.experimental_set_query_params(_=datetime.now().timestamp())

# -----------------------------
# FILTERING FUNCTIONS
# -----------------------------

def filter_projects(df, type_filter=None, region_filter=None, status_filter=None):
    """
    Filters projects by type, region, and status.
    """
    filtered = df.copy()
    if type_filter and type_filter != "All":
        filtered = filtered[filtered['Type'] == type_filter]
    if region_filter and region_filter != "All":
        filtered = filtered[filtered['Region'] == region_filter]
    if status_filter and status_filter != "All":
        filtered = filtered[filtered['Status'] == status_filter]
    return filtered

# -----------------------------
# ADMIN DASHBOARD
# -----------------------------
def admin_dashboard():
    st.title("Admin Dashboard")
    
    # -----------------------------
    # FILTERS
    # -----------------------------
    df_all = get_all_projects()
    types = ["All"] + sorted(df_all['Type'].dropna().unique().tolist())
    regions = ["All"] + sorted(df_all['Region'].dropna().unique().tolist())
    statuses = ["All"] + ["Issued","Retired"]
    
    st.subheader("Filter Projects")
    col1, col2, col3 = st.columns(3)
    with col1:
        type_filter = st.selectbox("Filter by Type", types)
    with col2:
        region_filter = st.selectbox("Filter by Region", regions)
    with col3:
        status_filter = st.selectbox("Filter by Status", statuses)
    
    df_filtered = filter_projects(df_all, type_filter, region_filter, status_filter)
    
    st.write(f"Total projects: {len(df_filtered)}")
    st.write(f"Total carbon (tonnes): {df_filtered['Carbon_tonnes'].sum()}")
    st.write(f"Total credits: {df_filtered['Credits'].sum()}")

    # -----------------------------
    # INPUT MODE
    # -----------------------------
    input_mode = st.radio("Choose Input Method", ["Manual Entry", "Bulk CSV Upload"])
    
    # -----------------------------
    # MANUAL ENTRY
    # -----------------------------
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
                    carbon, explanation = predict_carbon_llm(area, type_, region)
                else:
                    explanation = ""
                add_project(name, type_, region, area, carbon, explanation)
                st.success("Project added successfully!")
                do_rerun()
            else:
                st.error("Please fill all required fields and ensure area > 0!")

    # -----------------------------
    # BULK CSV UPLOAD
    # -----------------------------
    elif input_mode == "Bulk CSV Upload":
        st.subheader("Upload CSV Files")
        # CSV Template
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
                    for idx, row in df.iterrows():
                        name = row.get("name")
                        type_ = row.get("type")
                        region = row.get("region")
                        area = row.get("area_ha")
                        carbon = row.get("carbon_tonnes")
                        if pd.isna(area) or area <= 0:
                            st.warning(f"Skipping row '{name}' ({idx}): missing or invalid area")
                            continue
                        if pd.isna(carbon):
                            carbon, explanation = predict_carbon_llm(area, type_, region)
                        else:
                            explanation = ""
                        add_project(name, type_, region, float(area), float(carbon), explanation)
                st.success("All uploaded projects imported successfully!")
                do_rerun()
    
    # -----------------------------
    # PROJECT CARDS
    # -----------------------------
    st.subheader("Projects Overview")
    if not df_filtered.empty:
        for _, row in df_filtered.iterrows():
            with st.expander(f"{row['Name']} ({row['Type']}, {row['Region']}) - Status: {row['Status']}"):
                st.write(f"**Area (ha):** {row['Area_ha']}")
                st.write(f"**Carbon Stored (t):** {row['Carbon_tonnes']}")
                st.write(f"**Credits:** {row['Credits']}")
                st.write(f"**Created At:** {row['Created_at']}")
                st.write(f"**Explanation:** {row['Explanation'] if row['Explanation'] else 'No explanation available'}")
                
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
        st.info("No projects to display for the selected filters.")
        
# -----------------------------
# PUBLIC DASHBOARD
# -----------------------------
def public_dashboard():
    st.title("Public Registry")
    
    df_all = get_all_projects()
    types = ["All"] + sorted(df_all['Type'].dropna().unique().tolist())
    regions = ["All"] + sorted(df_all['Region'].dropna().unique().tolist())
    statuses = ["All"] + ["Issued","Retired"]
    
    st.subheader("Filter Projects")
    col1, col2, col3 = st.columns(3)
    with col1:
        type_filter = st.selectbox("Filter by Type", types)
    with col2:
        region_filter = st.selectbox("Filter by Region", regions)
    with col3:
        status_filter = st.selectbox("Filter by Status", statuses)
    
    df_filtered = filter_projects(df_all, type_filter, region_filter, status_filter)
    
    st.write(f"Total projects: {len(df_filtered)}")
    st.write(f"Total carbon (tonnes): {df_filtered['Carbon_tonnes'].sum()}")
    st.write(f"Total credits: {df_filtered['Credits'].sum()}")

    if not df_filtered.empty:
        for _, row in df_filtered.iterrows():
            with st.expander(f"{row['Name']} ({row['Type']}, {row['Region']}) - Status: {row['Status']}"):
                st.write(f"**Area (ha):** {row['Area_ha']}")
                st.write(f"**Carbon Stored (t):** {row['Carbon_tonnes']}")
                st.write(f"**Credits:** {row['Credits']}")
                st.write(f"**Created At:** {row['Created_at']}")
                st.write(f"**Explanation:** {row['Explanation'] if row['Explanation'] else 'No explanation available'}")
    else:
        st.info("No projects to display for the selected filters.")

# -----------------------------
# MAIN APP
# -----------------------------
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

if __name__ == "__main__":
    main()
