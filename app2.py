import streamlit as st
import pandas as pd
import io
import requests
import json
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from collections import defaultdict
import traceback

# ------------------------#
#     DATABASE SETTINGS   #
# ------------------------#
DB_HOST = "db.hrrmqkjxxyumemtowloy.supabase.co"
DB_PORT = 5432
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASS = "mahenoor123"

def get_db_connection() -> psycopg2.extensions.connection:
    """Establish and return a PostgreSQL connection."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            cursor_factory=RealDictCursor
        )
        return conn
    except psycopg2.Error as e:
        st.error(f"Error connecting to database: {e}")
        raise

# Initialize connection and cursor
conn = get_db_connection()
c = conn.cursor()

# ------------------------#
#      LLM SETTINGS       #
# ------------------------#
REPLICATE_API_TOKEN = "r8_H7Kmosw7cwXKNjMAvqbDJCj5Hm97FGp1hrNsj"
MODEL_VERSION_128K = "45ba1bd0a3cf3d5254becd00d937c4ba0c01b13fa1830818f483a76aa844205e"
ENDPOINT = "https://api.replicate.com/v1/predictions"
HEADERS = {
    "Authorization": f"Token {REPLICATE_API_TOKEN}",
    "Content-Type": "application/json"
}
LLM_CACHE = {}

def predict_carbon_llm(area: float) -> tuple:
    """
    Predict carbon using Phi-3 Mini 128k on Replicate API.
    Returns: (carbon_estimate, explanation)
    """
    if area in LLM_CACHE:
        return LLM_CACHE[area]

    try:
        data = {
            "version": MODEL_VERSION_128K,
            "input": {
                "messages": [
                    {"role": "system", "content": "You are a climate scientist."},
                    {"role": "user", "content": f"Estimate carbon in tonnes for {area} ha tidal marshes"}
                ]
            }
        }
        response = requests.post(ENDPOINT, headers=HEADERS, json=data)
        response.raise_for_status()
        result = response.json()
        carbon_estimate = None

        # Attempt to parse the model's output
        if 'output' in result and isinstance(result['output'], list) and len(result['output']) > 0:
            try:
                carbon_estimate = float(result['output'][0])
            except Exception as parse_err:
                st.warning(f"LLM output parse error: {parse_err}")
                carbon_estimate = area * 4.0  # Fallback default

        if carbon_estimate is None:
            carbon_estimate = area * 4.0
            explanation = f"Fallback: estimated carbon as {area} ha * 4.0 tCO₂/ha due to API output format"
        else:
            explanation = f"Phi-3 Mini predicted carbon as {carbon_estimate:.2f} tCO₂ for {area} ha"

        LLM_CACHE[area] = (carbon_estimate, explanation)
        return carbon_estimate, explanation
    except Exception as e:
        fallback_carbon = area * 4.0
        explanation = f"Fallback due to API error: {e}, estimated carbon {fallback_carbon:.2f} tCO₂"
        LLM_CACHE[area] = (fallback_carbon, explanation)
        st.error(f"LLM prediction failed: {traceback.format_exc()}")
        return fallback_carbon, explanation

# ------------------------#
#    DATA HELPER FUNCTIONS#
# ------------------------#
def calculate_credits(area: float, carbon: float) -> float:
    """Calculate credits based on area and carbon."""
    return round(area * 0.5 + carbon * 0.2, 2)

def add_project(
    name: str, 
    type_: str, 
    region: str, 
    area: float, 
    carbon: float, 
    explanation: str = ""
) -> None:
    """Insert new project into the DB."""
    try:
        credits = calculate_credits(area, carbon)
        created_at = datetime.now()
        c.execute('''
            INSERT INTO projects 
            (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (name, type_, region, area, carbon, credits, "Issued", created_at, explanation))
        conn.commit()
        st.success(f"Project '{name}' added successfully.")
    except Exception as e:
        st.error(f"DB Error: {e}")
        print(traceback.format_exc())

def delete_project(proj_id: int) -> None:
    """Delete project by ID."""
    try:
        c.execute('DELETE FROM projects WHERE id=%s', (proj_id,))
        conn.commit()
        st.info(f"Project ID {proj_id} deleted")
    except Exception as e:
        st.error(f"DB Error: {e}")
        print(traceback.format_exc())

def update_status(proj_id: int, status: str) -> None:
    """Update status for specific project."""
    try:
        c.execute('UPDATE projects SET status=%s WHERE id=%s', (status, proj_id))
        conn.commit()
        st.info(f"Project ID {proj_id} status updated to {status}")
    except Exception as e:
        st.error(f"DB Error: {e}")
        print(traceback.format_exc())

def get_all_projects() -> pd.DataFrame:
    """Fetch all projects, returning dataframe with standard columns."""
    try:
        c.execute("SELECT * FROM projects ORDER BY id DESC")
        data = c.fetchall()
        columns = [
            'ID','Name','Type','Region',
            'Area_ha','Carbon_tonnes','Credits',
            'Status','Created_at','Explanation'
        ]
        if data:
            df = pd.DataFrame(data, columns=columns)
        else:
            df = pd.DataFrame(columns=columns)
        return df
    except Exception as e:
        st.error(f"DB Error: {e}")
        print(traceback.format_exc())
        return pd.DataFrame()

def do_rerun() -> None:
    """Force a rerun so UI updates after DB changes."""
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.experimental_set_query_params(_=datetime.now().timestamp())

def show_expander_if_needed(carbon: float, explanation: str) -> None:
    """Show expander only if carbon prediction was missing and explanation available."""
    if carbon == 0:
        with st.expander("ℹ️ Explanation"):
            if explanation:
                st.write(explanation)
            else:
                st.write("No explanation available")

# ------------------------#
#      ADMIN DASHBOARD    #
# ------------------------#
def admin_dashboard():
    """Page for managing the registry: add, edit, delete, filter projects."""
    st.title("Admin Dashboard - Blue Carbon Registry")

    st.sidebar.subheader("Project Filters")
    status_filter = st.sidebar.multiselect("Status", ["Issued", "Retired"], default=["Issued", "Retired"])
    type_filter = st.sidebar.text_input("Type contains", "")
    region_filter = st.sidebar.text_input("Region contains", "")

    search_name = st.text_input("Search by Project Name", "")

    input_mode = st.radio("Input Mode", ["Manual Entry", "Bulk CSV Upload"])

    # ---------- Manual Project Entry ----------
    if input_mode == "Manual Entry":
        st.markdown("## Add New Project (Manual)")
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0, format="%.2f")
        carbon = st.number_input("Carbon Stored (tonnes)", min_value=0.0, format="%.2f")
        st.info("Leave carbon as 0 to auto-predict using Phi-3 Mini AI")

        if st.button("Add Project"):
            if name and type_ and region and area > 0:
                explanation = ""
                if carbon == 0.0:
                    carbon, explanation = predict_carbon_llm(area)
                add_project(name, type_, region, area, carbon, explanation)
                do_rerun()
            else:
                st.error("Please fill all required fields and make sure area > 0.")

    # ---------- Bulk CSV Upload ----------
    elif input_mode == "Bulk CSV Upload":
        st.markdown("## Bulk Upload Projects (CSV)")
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
        uploaded_files = st.file_uploader("Upload CSV file(s)", type=["csv"], accept_multiple_files=True)

        preview_dfs = []
        if uploaded_files:
            for file in uploaded_files:
                st.markdown(f"### 📂 {file.name}")
                try:
                    df = pd.read_csv(file)
                    st.dataframe(df.head())
                    preview_dfs.append(df)
                except Exception as e:
                    st.error(f"Error reading {file.name}: {e}")

            if st.button("Validate & Add All Projects"):
                for df in preview_dfs:
                    for _, row in df.iterrows():
                        name = str(row.get("name", ""))
                        type_ = str(row.get("type", ""))
                        region = str(row.get("region", ""))
                        area = row.get("area_ha", 0)
                        carbon = row.get("carbon_tonnes", 0)
                        explanation = ""

                        if pd.isna(area) or area <= 0:
                            st.warning(f"Skipping row '{name}': missing/invalid area")
                            continue
                        if pd.isna(carbon) or carbon == 0:
                            carbon, explanation = predict_carbon_llm(area)
                        add_project(name, type_, region, float(area), float(carbon), explanation)
                do_rerun()
                st.success("All uploaded projects imported.")

    # ---------- Projects Table ----------
    st.markdown("## Projects Overview / Edit / Delete")
    df = get_all_projects()

    # Apply filters & search
    if not df.empty:
        filtered_df = df[
            df['Status'].isin(status_filter)
        ]
        if type_filter:
            filtered_df = filtered_df[filtered_df['Type'].str.contains(type_filter, case=False, na=False)]
        if region_filter:
            filtered_df = filtered_df[filtered_df['Region'].str.contains(region_filter, case=False, na=False)]
        if search_name:
            filtered_df = filtered_df[filtered_df['Name'].str.contains(search_name, case=False, na=False)]

        # Summary stats
        st.markdown(f"- **Total Projects:** {len(filtered_df)}")
        st.markdown(f"- **Total Carbon:** {filtered_df['Carbon_tonnes'].sum():.2f} tCO₂")
        st.markdown(f"- **Total Credits:** {filtered_df['Credits'].sum():.2f}")
        status_counts = filtered_df['Status'].value_counts().to_dict()
        st.markdown(f"- **Status Breakdown:** {status_counts}")

        # Project rows
        for idx, row in filtered_df.iterrows():
            cols = st.columns([4,2,2])
            with cols[0]:
                st.markdown(f"**{row['Name']}** - Carbon: {row['Carbon_tonnes']} tCO₂")
                show_expander_if_needed(row['Carbon_tonnes'], row['Explanation'])
            with cols[1]:
                if st.button(f"Delete {row['ID']}", key=f"del_{row['ID']}"):
                    delete_project(row['ID'])
                    do_rerun()
            with cols[2]:
                if row['Status'] == "Issued":
                    if st.button(f"Retire {row['ID']}", key=f"ret_{row['ID']}"):
                        update_status(row['ID'], "Retired")
                        do_rerun()
                else:
                    if st.button(f"Issue {row['ID']}", key=f"iss_{row['ID']}"):
                        update_status(row['ID'], "Issued")
                        do_rerun()
    else:
        st.info("No projects yet! Use Manual or CSV to add new projects.")

# ------------------------#
#      PUBLIC DASHBOARD   #
# ------------------------#
def public_dashboard():
    """
    Public, read-only view of the registry.
    Project status, filtering, and detailed breakdown.
    """
    st.title("Public Registry - Verified Blue Carbon Projects")
    df = get_all_projects()

    # Sidebar filters
    st.sidebar.subheader("Project Filters")
    status_filter = st.sidebar.multiselect("Status", ["Issued", "Retired"], default=["Issued", "Retired"])
    type_filter = st.sidebar.text_input("Type contains", "")
    region_filter = st.sidebar.text_input("Region contains", "")
    search_name = st.sidebar.text_input("Search by Project Name", "")

    # Filter the dataframe
    filtered_df = df[
        df['Status'].isin(status_filter)
    ] if not df.empty else pd.DataFrame()

    if type_filter and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Type'].str.contains(type_filter, case=False, na=False)]
    if region_filter and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Region'].str.contains(region_filter, case=False, na=False)]
    if search_name and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Name'].str.contains(search_name, case=False, na=False)]

    if not filtered_df.empty:
        st.markdown("### Projects Table")
        st.dataframe(filtered_df[['ID', 'Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status']], width=1500)
        for idx, row in filtered_df.iterrows():
            status_color = "green" if row['Status'] == "Issued" else "red"
            cols = st.columns([6,2])
            with cols[0]:
                st.markdown(
                    f"**{row['Name']}** | {row['Type']} | {row['Region']} | "
                    f"{row['Area_ha']} ha | Carbon: {row['Carbon_tonnes']} tCO₂ | "
                    f"Credits: {row['Credits']} | Status: "
                    f"<span style='color:{status_color}'>{row['Status']}</span>",
                    unsafe_allow_html=True
                )
                show_expander_if_needed(row['Carbon_tonnes'], row['Explanation'])
    else:
        st.info("No projects currently match your filter.")

# ------------------------#
#         MAIN APP        #
# ------------------------#
def main():
    """Main entry for the Streamlit app; chooses dashboard mode."""
    st.sidebar.title("Carbon Registry System")
    mode = st.sidebar.selectbox(
        "Choose Mode",
        ["Public", "Admin"]
    )
    if mode == "Admin":
        password = st.sidebar.text_input("Admin Password", type="password")
        if password == "admin123":
            admin_dashboard()
        elif password:
            st.sidebar.error("Wrong password!")
    else:
        public_dashboard()

# ------------------------#
#          RUN APP        #
# ------------------------#
if __name__ == "__main__":
    main()

