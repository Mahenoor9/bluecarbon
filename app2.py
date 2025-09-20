################################################################################
#                          BLUE CARBON REGISTRY APP                            #
#               Streamlit-based Admin & Public Dashboards                      #
################################################################################

# ---------------------------- IMPORTS -----------------------------------------

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

# --------------------------- DATABASE SETTINGS ---------------------------------

# PostgreSQL database connection details
DB_HOST = "db.hrrmqkjxxyumemtowloy.supabase.co"
DB_PORT = 5432
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASS = "mahenoor123"

def get_db_connection() -> psycopg2.extensions.connection:
    """
    Creates and returns a connection to the PostgreSQL database using psycopg2.
    Uses RealDictCursor for results as dictionaries instead of tuples.
    Raises psycopg2.Error if connection fails.
    """
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
        st.error(f"Database connection error: {e}")
        raise

# Initialize persistent connection and cursor which will be reused
conn = get_db_connection()
c = conn.cursor()

# ---------------------------- LLM (Phi-3 Mini) SETTINGS --------------------------

# API token for Replicate service
REPLICATE_API_TOKEN = "r8_H7Kmosw7cwXKNjMAvqbDJCj5Hm97FGp1hrNsj"

# Specific model version to call for carbon prediction
MODEL_VERSION_128K = "45ba1bd0a3cf3d5254becd00d937c4ba0c01b13fa1830818f483a76aa844205e"

# API endpoint URL for prediction calls
ENDPOINT = "https://api.replicate.com/v1/predictions"

# In-memory cache for repeated area predictions to minimize API calls
LLM_CACHE = {}

def predict_carbon_llm(area: float) -> tuple:
    """
    Makes an API call to Phi-3 Mini 128k model via Replicate to predict carbon storage.
    If prediction was done before for given area, returns cached result.
    Handles exceptions by falling back to a default estimate based on area.
    
    Args:
        area (float): Area in hectares (ha) to estimate carbon for.
    
    Returns:
        Tuple[float, str]: Predicted carbon tonnes, along with a textual explanation.
    """
    if area in LLM_CACHE:
        return LLM_CACHE[area]

    try:
        # Construct prompt messages for LLM API
        data_payload = {
            "version": MODEL_VERSION_128K,
            "input": {
                "messages": [
                    {"role": "system", "content": "You are a climate scientist."},
                    {"role": "user", "content": f"Estimate carbon in tonnes for {area} ha tidal marshes"}
                ]
            }
        }

        # Authentication header with Bearer token required by Replicate
        HEADERS = {
            "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
            "Content-Type": "application/json"
        }

        # Send POST request to prediction endpoint
        response = requests.post(ENDPOINT, headers=HEADERS, json=data_payload)

        # Raise error if HTTP status code indicates failure
        response.raise_for_status()

        # Parse response JSON
        result = response.json()

        carbon_estimate = None

        # The output is expected to be a list; handle parsing robustly
        if "output" in result and isinstance(result["output"], list) and len(result["output"]) > 0:
            try:
                carbon_estimate = float(result["output"][0])
            except Exception:
                # If output cannot be parsed, use fallback
                carbon_estimate = area * 4.0  # Default fallback value per ha

        if carbon_estimate is None:
            # Fallback in case of missing output
            carbon_estimate = area * 4.0
            explanation = f"Fallback: estimated carbon as {area} ha * 4.0 tCO₂/ha due to unexpected API output"
        else:
            explanation = f"Phi-3 Mini predicted carbon as {carbon_estimate:.2f} tCO₂ for {area} ha"

        # Cache and return results
        LLM_CACHE[area] = (carbon_estimate, explanation)
        return carbon_estimate, explanation

    except Exception as e:
        # Handle all exceptions robustly, fallback with explanation
        fallback_carbon = area * 4.0
        explanation = f"Fallback due to API error: {str(e)}, estimated carbon {fallback_carbon:.2f} tCO₂"
        LLM_CACHE[area] = (fallback_carbon, explanation)
        st.error(f"LLM prediction failed:\n{traceback.format_exc()}")
        return fallback_carbon, explanation

# --------------------------------- DATABASE HELPERS --------------------------------


def calculate_credits(area: float, carbon: float) -> float:
    """
    Compute carbon credit amount based on area and carbon stored.
    This formula uses a weighted sum:
        credits = 0.5 * area + 0.2 * carbon
    
    Args:
        area (float): Area in hectares (ha).
        carbon (float): Carbon stored in tonnes.

    Returns;
        float: Number of credits rounded to two decimals.
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
    Inserts a new project record into the 'projects' database table with given parameters,
    sets initial project status as 'Issued' and logs insertion time.
    Commits the transaction to persist changes.
    Handles exceptions by showing error message in Streamlit and printing stack trace.

    Args:
        name (str): Project name/title.
        type_ (str): Project type/category.
        region (str): Project location region.
        area (float): Area in hectares.
        carbon (float): Carbon stored in tonnes.
        explanation (str, optional): Text explanation or notes, default empty.
    """
    try:
        # Calculate carbon credits based on area and carbon
        credits = calculate_credits(area, carbon)

        # Current datetime for record insertion
        created_at = datetime.now()

        # SQL insertion query template
        insert_query = '''
            INSERT INTO projects 
            (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''

        # Execute the query with given parameters
        c.execute(insert_query, (name, type_, region, area, carbon, credits, "Issued", created_at, explanation))

        # Commit the transaction to DB
        conn.commit()

        # Inform the user of success
        st.success(f"Project '{name}' added successfully with Carbon: {carbon:.2f} tCO₂ and Credits: {credits:.2f}")

    except Exception as e:
        # Show error message and traceback for debugging
        st.error(f"Failed to add project to database: {str(e)}")
        print(traceback.format_exc())


def delete_project(proj_id: int) -> None:
    """
    Deletes a specific project by its ID from the 'projects' table.
    Commits changes and informs user.
    Handles any exceptions and displays an error message.

    Args:
        proj_id (int): ID of the project to delete.
    """
    try:
        c.execute('DELETE FROM projects WHERE id = %s', (proj_id,))
        conn.commit()
        st.info(f"Project ID {proj_id} deleted.")
    except Exception as e:
        st.error(f"Failed to delete project with ID {proj_id}: {str(e)}")


def update_status(proj_id: int, status: str) -> None:
    """
    Updates status column of a project in 'projects' table, e.g. from 'Issued' to 'Retired' or vice versa.
    Commits and informs the user of success or failure.

    Args:
        proj_id (int): ID of the project to update.
        status (str): New status (e.g. 'Issued', 'Retired').
    """
    try:
        c.execute('UPDATE projects SET status = %s WHERE id = %s', (status, proj_id))
        conn.commit()
        st.info(f"Project ID {proj_id} status updated to {status}.")
    except Exception as e:
        st.error(f"Failed to update status for project (ID {proj_id}): {str(e)}")


def get_all_projects() -> pd.DataFrame:
    """
    Queries and retrieves all project records ordered descending by ID.
    Converts them into a Pandas DataFrame for easier UI display and filtering.
    
    Returns an empty DataFrame on failure.

    Returns:
        pd.DataFrame: All projects with columns [ID, Name, Type, Region, Area_ha, Carbon_tonnes, Credits, Status, Created_at, Explanation].
    """
    try:
        c.execute("SELECT * FROM projects ORDER BY id DESC")
        projects = c.fetchall()
        columns = ['ID', 'Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status', 'Created_at', 'Explanation']
        if projects:
            return pd.DataFrame(projects, columns=columns)
        else:
            return pd.DataFrame(columns=columns)
    except Exception as e:
        st.error(f"Unable to fetch projects from database: {str(e)}")
        return pd.DataFrame()

def do_rerun() -> None:
    """
    Triggers Streamlit to immediately rerun the script, reflecting any database or UI changes.
    Uses multiple compatibility methods depending on Streamlit version.
    """
    if hasattr(st, 'rerun'):
        st.rerun()
    elif hasattr(st, 'experimental_rerun'):
        st.experimental_rerun()
    else:
        # As a last resort, set dummy query param to force rerun
        st.experimental_set_query_params(_=datetime.now().timestamp())


def show_expander_if_needed(carbon: float, explanation: str) -> None:
    """
    Displays a Streamlit expandable info box conditionally.
    Only shows if carbon was zero indicating AI prediction fallback was likely used.
    Provides explanation text if present.
    """
    if carbon == 0:
        with st.expander("ℹ️ Explanation"):
            if explanation:
                st.write(explanation)
            else:
                st.write("No explanation available.")


################################################################################
#                              ADMIN DASHBOARD                                 #
################################################################################

def admin_dashboard():
    """
    Displays the comprehensive Admin Dashboard with:
      - Filtering on Status, Type, Region
      - Searching by Project Name
      - Manual project addition form with AI prediction fallback
      - Bulk CSV upload and validation
      - Project list overview with options to delete, retire, or issue projects
    """
    st.title("Admin Dashboard - Blue Carbon Registry")

    # Sidebar filters for easy list filtering
    st.sidebar.subheader("Filter Projects")
    status_filter = st.sidebar.multiselect("Status", ["Issued", "Retired"], default=["Issued", "Retired"])
    type_filter = st.sidebar.text_input("Type contains")
    region_filter = st.sidebar.text_input("Region contains")

    # Search box for project name
    search_name = st.text_input("Search by Project Name")

    # Input method selection
    input_mode = st.radio("Choose Input Method", ["Manual Entry", "Bulk CSV Upload"])

    # ---------------------- Manual Entry ----------------------
    if input_mode == "Manual Entry":
        st.subheader("Add New Project")
        st.write("Fill in the project details. Leave 'Carbon Stored' as 0 to auto-predict using AI.")

        # Project details inputs
        name = st.text_input("Project Name")
        type_ = st.text_input("Project Type")
        region = st.text_input("Region")
        area = st.number_input("Area (ha)", min_value=0.0, format="%.2f")
        carbon = st.number_input("Carbon Stored (tonnes)", min_value=0.0, format="%.2f")

        # Add project button with validation and fallback prediction
        if st.button("Add Project"):
            if not name:
                st.error("Project Name is required.")
            elif not type_:
                st.error("Project Type is required.")
            elif not region:
                st.error("Region is required.")
            elif area <= 0:
                st.error("Area must be greater than 0.")
            else:
                explanation = ""
                try:
                    # Predict carbon if zero provided
                    if carbon == 0.0:
                        carbon, explanation = predict_carbon_llm(area)
                        if carbon is None or carbon == 0:
                            carbon = area * 4.0
                            explanation = f"Fallback applied: {area} ha * 4.0 tCO₂"
                except Exception as exc:
                    carbon = area * 4.0
                    explanation = f"Fallback due to prediction error: {exc}"
                    st.error(f"Prediction error fallback: {exc}")

                try:
                    credits = calculate_credits(area, carbon)
                except Exception as exc:
                    st.error(f"Credit calculation error: {exc}")
                    credits = 0.0

                try:
                    # Insert project in database
                    created_at = datetime.now()
                    c.execute('''
                        INSERT INTO projects 
                        (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (name, type_, region, area, carbon, credits, "Issued", created_at, explanation))
                    conn.commit()
                    st.success(f"Project '{name}' added successfully!")
                    do_rerun()
                except Exception as exc:
                    st.error(f"Failed to add project: {exc}")
                    print(traceback.format_exc())

    # ---------------------- Bulk CSV Upload ----------------------
    elif input_mode == "Bulk CSV Upload":
        st.subheader("Bulk Upload Projects via CSV")
        template_df = pd.DataFrame({
            "name": ["Example Project"],
            "type": ["Afforestation"],
            "region": ["India"],
            "area_ha": [100],
            "carbon_tonnes": [400]
        })
        buf = io.BytesIO()
        template_df.to_csv(buf, index=False)
        st.download_button("Download CSV Template", buf.getvalue(), "template.csv", "text/csv")

        # Allow multiple CSV file upload
        uploaded_files = st.file_uploader("Upload CSV file(s)", type=["csv"], accept_multiple_files=True)

        dataframes = []
        if uploaded_files:
            for uf in uploaded_files:
                st.markdown(f"### File: {uf.name}")
                try:
                    df = pd.read_csv(uf)
                    st.dataframe(df.head())
                    dataframes.append(df)
                except Exception as exc:
                    st.error(f"Error reading {uf.name}: {exc}")

            if st.button("Validate & Add All Projects"):
                for df in dataframes:
                    for _, row in df.iterrows():
                        name = str(row.get("name", ""))
                        type_ = str(row.get("type", ""))
                        region = str(row.get("region", ""))
                        area = row.get("area_ha", 0)
                        carbon = row.get("carbon_tonnes", 0)
                        explanation = ""

                        if pd.isna(area) or area <= 0:
                            st.warning(f"Skipping project '{name}' due to missing or invalid area")
                            continue
                        if pd.isna(carbon) or carbon == 0:
                            carbon, explanation = predict_carbon_llm(area)
                        add_project(name, type_, region, float(area), float(carbon), explanation)
                st.success("All uploaded projects imported successfully!")
                do_rerun()

    # ---------------------- Projects Overview ----------------------
    st.subheader("Projects Overview / Edit / Delete")

    projects_df = get_all_projects()

    if projects_df.empty:
        st.info("No projects available yet. Add some using the form or CSV upload!")
        return

    # Apply filtering based on sidebar input and search
    filtered_df = projects_df.query("Status in @status_filter")
    if type_filter:
        filtered_df = filtered_df[filtered_df['Type'].str.contains(type_filter, case=False, na=False)]
    if region_filter:
        filtered_df = filtered_df[filtered_df['Region'].str.contains(region_filter, case=False, na=False)]
    if search_name:
        filtered_df = filtered_df[filtered_df['Name'].str.contains(search_name, case=False, na=False)]

    st.markdown(f"**Total Projects:** {len(filtered_df)}")
    st.markdown(f"**Total Carbon:** {filtered_df['Carbon_tonnes'].sum():.2f} tCO₂")
    st.markdown(f"**Total Credits:** {filtered_df['Credits'].sum():.2f}")
    st.markdown(f"**Status Breakdown:** {filtered_df['Status'].value_counts().to_dict()}")

    # Show projects with action buttons in columns
    for _, row in filtered_df.iterrows():
        cols = st.columns([4, 2, 2])
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

################################################################################
#                           PUBLIC DASHBOARD                                 #
################################################################################

def public_dashboard():
    """
    Read-only dashboard showing all projects available publicly,
    with filtering and search options and status coloration.
    """
    st.title("Public Registry - Verified Blue Carbon Projects")

    projects_df = get_all_projects()

    st.sidebar.subheader("Filter Projects")
    status_filter = st.sidebar.multiselect("Status", ["Issued", "Retired"], default=["Issued", "Retired"])
    type_filter = st.sidebar.text_input("Type contains")
    region_filter = st.sidebar.text_input("Region contains")
    search_name = st.sidebar.text_input("Search by Project Name")

    filtered_df = projects_df.query("Status in @status_filter") if not projects_df.empty else pd.DataFrame()

    if type_filter and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Type'].str.contains(type_filter, case=False, na=False)]
    if region_filter and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Region'].str.contains(region_filter, case=False, na=False)]
    if search_name and not filtered_df.empty:
        filtered_df = filtered_df[filtered_df['Name'].str.contains(search_name, case=False, na=False)]

    if filtered_df.empty:
        st.info("No projects currently match the filter criteria.")
        return

    st.markdown("### Projects Table")
    st.dataframe(filtered_df[['ID', 'Name', 'Type', 'Region', 'Area_ha', 'Carbon_tonnes', 'Credits', 'Status']], width=1500)

    # Display each project with color-coded project status
    for _, row in filtered_df.iterrows():
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

################################################################################
#                                MAIN ENTRYPOINT                                #
################################################################################

def main():
    """
    Main entrypoint of the Streamlit app.
    Selects between Public and Admin dashboards,
    requires password authentication for Admin.
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

################################################################################
#                                RUN APP                                      #
################################################################################

if __name__ == "__main__":
    main()
