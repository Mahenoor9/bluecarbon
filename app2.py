# app.py
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import pandas as pd
import io
import requests
import json
import time

# -------------------
# SUPABASE POSTGRES CONNECTION
# -------------------
conn = psycopg2.connect(
    host="db.hrrmqkjxxyumemtowloy.supabase.co",
    port=5432,
    database="postgres",
    user="postgres",
    password="mahenoor123",
    cursor_factory=RealDictCursor
)
c = conn.cursor()

# -------------------
# PHI-3 MINI 128K SETTINGS
# -------------------
REPLICATE_API_TOKEN = "r8_GjvA1Mx65FbeviXgS9a7PdW2LA61s6n1euV5J"
MODEL_VERSION_128K = "45ba1bd0a3cf3d5254becd00d937c4ba0c01b13fa1830818f483a76aa844205e"
ENDPOINT = "https://api.replicate.com/v1/predictions"
HEADERS = {
    "Authorization": f"Token {REPLICATE_API_TOKEN}",
    "Content-Type": "application/json"
}

# -------------------
# CACHING DICTIONARY
# -------------------
phi3_cache = {}  # key: (area, type, region), value: (carbon, explanation)

# -------------------
# HELPER FUNCTIONS
# -------------------

def calculate_credits(area, carbon):
    """
    Calculate carbon credits based on area and carbon.
    Formula: credits = area * 0.5 + carbon * 0.2
    Returns rounded float.
    """
    return round(area * 0.5 + carbon * 0.2, 2)

def predict_carbon_phi3_128k(area, project_type="Afforestation", region="India"):
    """
    Call Phi-3 Mini 128K to estimate carbon for a project.
    Returns (carbon_estimate, explanation)
    Uses caching to prevent repeated API calls.
    """
    cache_key = (area, project_type, region)
    if cache_key in phi3_cache:
        return phi3_cache[cache_key]

    prompt = f"Estimate carbon stored (tonnes) for a {area} ha {project_type} project in {region}. Provide numeric value and explanation."
    data = {
        "version": MODEL_VERSION_128K,
        "input": {
            "messages": [
                {"role": "system", "content": "You are a climate scientist."},
                {"role": "user", "content": prompt}
            ]
        }
    }
    try:
        response = requests.post(ENDPOINT, headers=HEADERS, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()
        explanation_raw = str(result.get("output")[0])
        # Extract numeric value for carbon
        carbon_estimate = float([word for word in explanation_raw.split() if word.replace('.','',1).isdigit()][0])
        explanation = explanation_raw
    except Exception as e:
        carbon_estimate = area * 4.0
        explanation = f"Fallback due to API error: {e}, estimated carbon {carbon_estimate} tCO2"

    phi3_cache[cache_key] = (carbon_estimate, explanation)
    return carbon_estimate, explanation

def do_rerun():
    """Force Streamlit to rerun app."""
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.experimental_set_query_params(_=datetime.now().timestamp())

def validate_project_data(name, type_, region, area):
    """Validate input data for a project."""
    if not name or not type_ or not region:
        return False
    if area <= 0:
        return False
    return True

def create_csv_template():
    """Create a CSV template for bulk upload."""
    template = pd.DataFrame({
        "name": ["Project A"],
        "type": ["Afforestation"],
        "region": ["India"],
        "area_ha": [100],
        "carbon_tonnes": [400]
    })
    buffer = io.BytesIO()
    template.to_csv(buffer, index=False)
    return buffer

# -------------------
# DATABASE FUNCTIONS
# -------------------

def add_project(name, type_, region, area, carbon, explanation=""):
    """Insert new project into Supabase Postgres."""
    credits = calculate_credits(area, carbon)
    c.execute("""
        INSERT INTO projects (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
    """, (name, type_, region, area, carbon, credits, "Issued", explanation))
    conn.commit()

def delete_project(proj_id):
    """Delete project by ID"""
    c.execute("DELETE FROM projects WHERE id=%s", (proj_id,))
    conn.commit()

def update_status(proj_id, status):
    """Update project status (Issued/Retired)"""
    c.execute("UPDATE projects SET status=%s WHERE id=%s", (status, proj_id))
    conn.commit()

def get_all_projects():
    """Retrieve all projects from DB as DataFrame"""
    c.execute("SELECT * FROM projects ORDER BY id DESC;")
    rows = c.fetchall()
    if rows:
        return pd.DataFrame(rows)
    else:
        return pd.DataFrame(columns=['id','name','type','region','area_ha','carbon_tonnes','credits','status','created_at','explanation'])

# -------------------
# ADMIN DASHBOARD
# -------------------

def admin_dashboard():
    """Admin dashboard for managing projects."""
    st.title("Admin Dashboard")
    st.markdown("---")
    input_mode = st.radio("Choose Input Method", ["Manual Entry", "Bulk CSV Upload"])
    
    # Manual Entry
    if input_mode == "Manual Entry":
        st.subheader("Add New Project")
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0)
        carbon = st.number_input("Carbon Stored (tonnes)", min_value=0.0)
        st.write("Leave carbon as 0 to auto-predict using Phi-3 Mini")

        if st.button("Add Project"):
            if validate_project_data(name, type_, region, area):
                if carbon == 0.0:
                    carbon, explanation = predict_carbon_phi3_128k(area, type_, region)
                else:
                    explanation = ""
                add_project(name, type_, region, area, carbon, explanation)
                st.success("Project added successfully!")
                do_rerun()
            else:
                st.error("Please fill all fields and make sure area > 0!")

    # Bulk CSV Upload
    elif input_mode == "Bulk CSV Upload":
        st.subheader("Upload CSV Files")
        buffer = create_csv_template()
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
                    for _, row in df.iterrows():
                        name = row.get("name")
                        type_ = row.get("type")
                        region = row.get("region")
                        area = row.get("area_ha")
                        carbon = row.get("carbon_tonnes")
                        if pd.isna(area) or area <= 0:
                            st.warning(f"Skipping row '{name}': missing area")
                            continue
                        if pd.isna(carbon):
                            carbon, explanation = predict_carbon_phi3_128k(area, type_, region)
                        else:
                            explanation = ""
                        add_project(name, type_, region, float(area), float(carbon), explanation)
                st.success("All uploaded projects imported successfully!")
                do_rerun()

    # Projects Table
    st.markdown("## Projects Overview")
    df = get_all_projects()
    if not df.empty:
        for _, row in df.iterrows():
            st.markdown(f"**{row['name']}** - Carbon: {row['carbon_tonnes']} tCO₂ - Status: {row['status']}")
            with st.expander("ℹ️ Explanation"):
                st.write(row['explanation'] if row['explanation'] else "No explanation available")
            
            col1, col2, col3 = st.columns([1,1,1])
            with col1:
                if st.button("Delete", key=f"del_{row['id']}"):
                    delete_project(row['id'])
                    do_rerun()
            with col2:
                if st.button("Retire", key=f"ret_{row['id']}"):
                    update_status(row['id'], "Retired")
                    do_rerun()
            with col3:
                if st.button("Issue", key=f"iss_{row['id']}"):
                    update_status(row['id'], "Issued")
                    do_rerun()
    else:
        st.info("No projects yet!")

# -------------------
# PUBLIC DASHBOARD
# -------------------

def public_dashboard():
    """Public view of all projects."""
    st.title("Public Registry")
    df = get_all_projects()
    if not df.empty:
        st.dataframe(df[['name','type','region','area_ha','carbon_tonnes','credits','status','created_at']])
        for _, row in df.iterrows():
            with st.expander(f"{row['name']} - ℹ️ Explanation"):
                st.write(row['explanation'] if row['explanation'] else "No explanation available")
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
