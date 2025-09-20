# ----------------------------------------
# Imports and Library Setup
# ----------------------------------------

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

# ----------------------------------------
# Database Connection Settings 
# ----------------------------------------

DB_HOST = "db.hrrmqkjxxyumemtowloy.supabase.co"
DB_PORT = 5432
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASS = "mahenoor123"

def get_db_connection() -> psycopg2.extensions.connection:
    """
    Establish and return a PostgreSQL connection with RealDictCursor cursor factory,
    which returns rows as dictionaries for ease of access and consistency.
    
    Raises and surfaces any exceptions encountered.
    """
    try:
        connection = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            cursor_factory=RealDictCursor
        )
        return connection
    except psycopg2.Error as db_error:
        st.error(f"Database connection error: {db_error}")
        raise

# Create a persistent connection and cursor
conn = get_db_connection()
c = conn.cursor()

# ----------------------------------------
# LLM (Phi-3 Mini 128k) API Settings
# ----------------------------------------

# The Replicate API token for authentication (keep secure!)
REPLICATE_API_TOKEN = "r8_H7Kmosw7cwXKNjMAvqbDJCj5Hm97FGp1hrNsj"

# The model version identifier for Phi-3 Mini 128k instruct version
MODEL_VERSION_128K = "45ba1bd0a3cf3d5254becd00d937c4ba0c01b13fa1830818f483a76aa844205e"

# API endpoint for prediction calls
ENDPOINT = "https://api.replicate.com/v1/predictions"

# Cache dictionary to store predictions and avoid repeat API calls
LLM_CACHE = {}

def predict_carbon_llm(area: float) -> tuple:
    """
    Given an area in hectares, call the Phi-3 Mini 128k LLM hosted on Replicate API.
    This function sends a conversational prompt to estimate carbon storage (in tonnes)
    for tidal marshes of the given area.
    
    Returns a tuple:
        (estimated carbon value: float, explanation string)
    
    Implements caching to reduce redundant API usage.
    
    Handles API errors gracefully and falls back to a rule-of-thumb estimation.
    """
    if area in LLM_CACHE:
        # Return cached value to save API calls and reduce latency
        return LLM_CACHE[area]

    try:
        # Compose the message prompt for the LLM
        data_payload = {
            "version": MODEL_VERSION_128K,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a climate scientist."
                    },
                    {
                        "role": "user",
                        "content": f"Estimate carbon in tonnes for {area} ha tidal marshes"
                    }
                ]
            }
        }

        # Setup request headers using Bearer token authentication (required)
        HEADERS = {
            "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
            "Content-Type": "application/json"
        }

        # Perform the POST request to the Replicate API endpoint
        response = requests.post(ENDPOINT, headers=HEADERS, json=data_payload)

        # Raise exception for HTTP errors (including 401 Unauthorized)
        response.raise_for_status()

        # Parse JSON response
        result_json = response.json()

        # Initialize an estimate variable
        carbon_estimate = None

        # Check output format and extract carbon value safely
        if 'output' in result_json and isinstance(result_json['output'], list) and len(result_json['output']) > 0:
            try:
                carbon_estimate = float(result_json['output'][0])
            except Exception:
                # If parsing fails use fallback calculation
                carbon_estimate = area * 4.0

        # Fallback in case output is missing or badly formatted
        if carbon_estimate is None:
            carbon_estimate = area * 4.0
            explanation_text = f"Fallback: estimated carbon as {area} ha * 4.0 tCO₂/ha due to API output format"
        else:
            explanation_text = f"Phi-3 Mini predicted carbon as {carbon_estimate} tCO₂ for {area} ha"

        # Cache the result for this area
        LLM_CACHE[area] = (carbon_estimate, explanation_text)

        return carbon_estimate, explanation_text

    except Exception as ex:
        # On error, fallback estimation and explanation
        fallback_default = area * 4.0
        fallback_explanation = f"Fallback due to API error: {str(ex)}, estimated carbon {fallback_default} tCO₂"
        LLM_CACHE[area] = (fallback_default, fallback_explanation)

        # Streamlit error message for debugging
        st.error(f"LLM Prediction API call failed:\n{traceback.format_exc()}")

        return fallback_default, fallback_explanation

# ----------------------------------------
# Helper functions for database manipulation and business logic
# ----------------------------------------

def calculate_credits(area: float, carbon: float) -> float:
    """
    Simple credits calculation based on weighted sum:
    credits = (area * 0.5) + (carbon * 0.2)
    
    Returns the credits rounded to 2 decimal places.
    """
    return round(area * 0.5 + carbon * 0.2, 2)

def add_project(
    name: str,
    type_: str,
    region: str,
    area: float,
    carbon: float,
    explanation: str = ""
) -> None:
    """
    Inserts a new project record into the 'projects' table with all specified values.
    Sets initial status as "Issued" and logs current timestamp.
    
    Provides Streamlit success/error notifications on completion.
    """
    try:
        # Calculate credits before insertion
        credits = calculate_credits(area, carbon)

        # Capture current timestamp
        created_at = datetime.now()

        # SQL insert query
        insertion_query = '''
            INSERT INTO projects
            (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''

        # Execute insert query
        c.execute(insertion_query,
                  (name, type_, region, area, carbon, credits, "Issued", created_at, explanation))
        conn.commit()

        # Notify success in UI
        st.success(f"Project '{name}' added successfully.")

    except Exception as e:
        st.error(f"Database insertion failed: {str(e)}")
        print(traceback.format_exc())

def delete_project(proj_id: int) -> None:
    """
    Deletes a project from 'projects' table by project ID.
    
    Confirms deletion in notification or shows errors.
    """
    try:
        c.execute('DELETE FROM projects WHERE id = %s', (proj_id,))
        conn.commit()
        st.info(f"Project ID {proj_id} deleted.")
    except Exception as e:
        st.error(f"Error deleting project: {str(e)}")
        print(traceback.format_exc())

def update_status(proj_id: int, status: str) -> None:
    """
    Updates the status field of a project by ID.
    
    Shows status update notifications or errors in UI.
    """
    try:
        c.execute('UPDATE projects SET status = %s WHERE id = %s', (status, proj_id))
        conn.commit()
        st.info(f"Project ID {proj_id} status updated to '{status}'.")
    except Exception as e:
        st.error(f"Failed to update status: {str(e)}")
        print(traceback.format_exc())

def get_all_projects() -> pd.DataFrame:
    """
    Fetches all projects from the database ordered by descending ID.
    
    Returns a Pandas DataFrame with columns mapped explicitly.
    
    Returns empty DataFrame on error but shows UI notification.
    """
    try:
        c.execute("SELECT * FROM projects ORDER BY id DESC")
        rows = c.fetchall()
        columns = [
            'ID', 'Name', 'Type', 'Region',
            'Area_ha', 'Carbon_tonnes', 'Credits',
            'Status', 'Created_at', 'Explanation'
        ]
        if rows:
            df = pd.DataFrame(rows, columns=columns)
        else:
            df = pd.DataFrame(columns=columns)
        return df
    except Exception as e:
        st.error(f"Failed to fetch projects: {str(e)}")
        print(traceback.format_exc())
        return pd.DataFrame()

def do_rerun() -> None:
    """
    Forces Streamlit to rerun the app to pick up latest DB changes.
    Supports multiple Streamlit versions gracefully.
    """
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        # Experimental hack fallback
        st.experimental_set_query_params(_=datetime.now().timestamp())

def show_expander_if_needed(carbon: float, explanation: str) -> None:
    """
    Show an expandable info box only if carbon is zero (implying prediction was used)
    and an explanation text is available.
    """
    if carbon == 0:
        with st.expander("ℹ️ Explanation"):
            if explanation:
                st.write(explanation)
            else:
                st.write("No explanation available")

# ----------------------------------------
# Admin dashboard user interface and handlers
# ----------------------------------------

def admin_dashboard():
    """
    Provides the Admin dashboard with capability to:
    - Filter projects by status, type, region
    - Search by project name
    - Add projects manually or by bulk CSV upload
    - View, retire, issue, or delete projects
    """

    st.title("Admin Dashboard - Blue Carbon Registry")

    # Sidebar filters for projects
    st.sidebar.subheader("Filter Projects")
    status_filter = st.sidebar.multiselect("Status", options=["Issued", "Retired"], default=["Issued", "Retired"])
    type_filter = st.sidebar.text_input("Type contains")
    region_filter = st.sidebar.text_input("Region contains")

    # Text search by project name
    search_name = st.text_input("Search by Project Name")

    # Input method selector (manual or CSV)
    input_mode = st.radio("Choose Input Method", ["Manual Entry", "Bulk CSV Upload"])

    # ------- Manual Entry -------
    if input_mode == "Manual Entry":
        st.subheader("Add New Project")

        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0, format="%.2f")
        carbon = st.number_input("Carbon Stored (tonnes)", min_value=0.0, format="%.2f")

        st.markdown("Leave carbon as 0 to auto-predict using Phi-3 Mini")

        if st.button("Add Project"):
            if name and type_ and region and area > 0:
                explanation = ""
                if carbon == 0.0:
                    carbon, explanation = predict_carbon_llm(area)
                add_project(name, type_, region, area, carbon, explanation)
                do_rerun()
            else:
                st.error("Please fill all required fields and make sure area > 0!")

    # ------- Bulk CSV Upload -------
    elif input_mode == "Bulk CSV Upload":
        st.subheader("Upload CSV Files")

        # Template DataFrame to guide users on column structure
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
        parsed_dfs = []

        if uploaded_files:
            for file in uploaded_files:
                st.markdown(f"### 📂 {file.name}")
                try:
                    df = pd.read_csv(file)
                    st.dataframe(df.head())
                    parsed_dfs.append(df)
                except Exception as e:
                    st.error(f"Could not read {file.name}: {e}")

            if st.button("Validate and Add All Projects"):
                # Validate each row and insert projects
                for df in parsed_dfs:
                    for _, row in df.iterrows():
                        name = str(row.get("name", ""))
                        type_ = str(row.get("type", ""))
                        region = str(row.get("region", ""))
                        area = row.get("area_ha", 0)
                        carbon = row.get("carbon_tonnes", 0)
                        explanation = ""

                        if pd.isna(area) or area <= 0:
                            st.warning(f"Skipping '{name}': invalid or missing area")
                            continue
                        if pd.isna(carbon) or carbon == 0:
                            carbon, explanation = predict_carbon_llm(area)
                        add_project(name, type_, region, float(area), float(carbon), explanation)
                do_rerun()
                st.success("All uploaded projects imported successfully!")

    # ------- Projects Table -------
    st.subheader("Projects Overview")

    projects_df = get_all_projects()

    if projects_df.empty:
        st.info("No projects in the registry yet.")
        return

    # Apply filters and search
    filtered_df = projects_df[projects_df['Status'].isin(status_filter)]
    if type_filter:
        filtered_df = filtered_df[filtered_df['Type'].str.contains(type_filter, case=False, na=False)]
    if region_filter:
        filtered_df = filtered_df[filtered_df['Region'].str.contains(region_filter, case=False, na=False)]
    if search_name:
        filtered_df = filtered_df[filtered_df['Name'].str.contains(search_name, case=False, na=False)]

    # Summary statistics display
    total_projects = len(filtered_df)
    total_carbon = filtered_df['Carbon_tonnes'].sum()
    total_credits = filtered_df['Credits'].sum()
    status_counts = filtered_df['Status'].value_counts().to_dict()

    st.markdown(f"**Total Projects:** {total_projects} | **Total Carbon:** {total_carbon:.2f} tCO₂ | **Total Credits:** {total_credits:.2f}")
    st.markdown(f"**Status Breakdown:** {status_counts}")

    # Show project rows with Edit options
    for _, row in filtered_df.iterrows():
        cols = st.columns([4, 2, 2])
        with cols[0]:
            st.markdown(f"**{row['Name']}** — Carbon: {row['Carbon_tonnes']} tCO₂")
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

# ----------------------------------------
# Public dashboard for readonly project view
# ----------------------------------------

def public_dashboard():
    """
    Shows readonly public registry with filtering and search.
    Displays project status with color-coded visual cues.
    """

    st.title("Public Registry - Verified Blue Carbon Projects")

    projects_df = get_all_projects()

    st.sidebar.subheader("Filter Projects")

    status_filter = st.sidebar.multiselect("Status", ["Issued", "Retired"], default=["Issued", "Retired"])
    type_filter = st.sidebar.text_input("Type contains")
    region_filter = st.sidebar.text_input("Region contains")
    search_name = st.sidebar.text_input("Search by Project Name")

    filtered_df = projects_df[projects_df['Status'].isin(status_filter)] if not projects_df.empty else pd.DataFrame()

    if type_filter and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Type'].str.contains(type_filter, case=False, na=False)]

    if region_filter and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Region'].str.contains(region_filter, case=False, na=False)]

    if search_name and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Name'].str.contains(search_name, case=False, na=False)]

    if filtered_df.empty:
        st.info("No projects available matching the filters.")
        return

    # DataFrame view of projects for convenience
    st.markdown("### Projects Table")
    st.dataframe(filtered_df[['ID', 'Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status']], width=1500)

    # Detailed project list with colored status
    for _, row in filtered_df.iterrows():
        # Color "Issued" green and "Retired" red regardless of case
        status_color = "green" if row['Status'].lower() == "issued" else "red"
        cols = st.columns([6, 2])
        with cols[0]:
            st.markdown(
                f"**{row['Name']}** | {row['Type']} | {row['Region']} | {row['Area_ha']} ha | "
                f"Carbon: {row['Carbon_tonnes']} tCO₂ | Credits: {row['Credits']} | "
                f"Status: <span style='color:{status_color}'>{row['Status']}</span>",
                unsafe_allow_html=True
            )
            show_expander_if_needed(row['Carbon_tonnes'], row['Explanation'])

# ----------------------------------------
# Main Application Entry
# ----------------------------------------

def main():
    """
    Main Streamlit app entry.
    Provides sidebar mode selector for Public or Admin views.
    Admin mode requires a password.
    """

    st.sidebar.title("Carbon Registry System")
    mode = st.sidebar.selectbox("Select Mode", ["Public", "Admin"])

    if mode == "Admin":
        password = st.sidebar.text_input("Enter Admin Password", type="password")
        if password == "admin123":
            admin_dashboard()
        elif password:
            st.sidebar.error("Wrong password!")
    else:
        public_dashboard()

# ----------------------------------------
# Execute application
# ----------------------------------------

if __name__ == "__main__":
    main()
