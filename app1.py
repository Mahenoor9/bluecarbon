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

# Ensure foreign key support
c.execute("PRAGMA foreign_keys = ON")

# Create projects table if it does not exist
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

def log_debug(msg):
    """Print debug messages to console."""
    print(f"[DEBUG] {datetime.now()} - {msg}")


def do_rerun():
    """Rerun Streamlit app safely."""
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        try:
            st.experimental_set_query_params(_=datetime.now().timestamp())
        except Exception:
            pass


def calculate_credits(area, carbon):
    """Calculate carbon credits based on area and carbon stored."""
    try:
        return round(area * 0.5 + carbon * 0.2, 2)
    except Exception as e:
        log_debug(f"Error calculating credits: {e}")
        return 0.0


def predict_carbon_llm(area, project_type="", region=""):
    """
    Placeholder for LLM-based carbon prediction.
    Currently returns area * 4 as default.
    """
    try:
        predicted = area * 4.0
        explanation = f"Predicted carbon based on area {area} ha: {predicted} tonnes."
        return predicted, explanation
    except Exception as e:
        log_debug(f"Error in LLM prediction: {e}")
        return 0.0, ""


def add_project(name, type_, region, area, carbon, explanation=""):
    """Add a new project to the database."""
    credits = calculate_credits(area, carbon)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO projects (name, type, region, area_ha, carbon_tonnes, credits, status, created_at, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, type_, region, area, carbon, credits, "Issued", created_at, explanation))
    conn.commit()
    log_debug(f"Added project: {name}, area: {area}, carbon: {carbon}")


def delete_project(proj_id):
    """Delete a project by ID."""
    try:
        c.execute('DELETE FROM projects WHERE id = ?', (proj_id,))
        conn.commit()
        log_debug(f"Deleted project ID: {proj_id}")
    except Exception as e:
        log_debug(f"Error deleting project {proj_id}: {e}")


def update_status(proj_id, status):
    """Update project status."""
    try:
        c.execute('UPDATE projects SET status=? WHERE id = ?', (status, proj_id))
        conn.commit()
        log_debug(f"Updated project {proj_id} status to {status}")
    except Exception as e:
        log_debug(f"Error updating status for project {proj_id}: {e}")


def get_all_projects():
    """Retrieve all projects as a DataFrame."""
    try:
        c.execute('SELECT * FROM projects')
        data = c.fetchall()
        columns = ['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation']
        if data:
            df = pd.DataFrame(data, columns=columns)
            return df
        else:
            return pd.DataFrame(columns=columns)
    except Exception as e:
        log_debug(f"Error fetching projects: {e}")
        return pd.DataFrame(columns=['ID','Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at','Explanation'])


# -------------------
# ADMIN DASHBOARD
# -------------------

def admin_dashboard():
    """Display the Admin dashboard with project management."""
    st.title("Admin Dashboard")

    # Input method selection
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
                # Use LLM prediction if carbon not provided
                if carbon == 0.0:
                    carbon, explanation = predict_carbon_llm(area, type_, region)
                else:
                    explanation = f"Carbon manually entered: {carbon} tonnes."
                add_project(name, type_, region, area, carbon, explanation)
                st.success("Project added successfully!")
                do_rerun()
            else:
                st.error("Fill all required fields and make sure area > 0!")

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
                        try:
                            name = row["name"]
                            type_ = row["type"]
                            region = row["region"]
                            area = row.get("area_ha")
                            carbon = row.get("carbon_tonnes")

                            if pd.isna(area) or area <= 0:
                                st.warning(f"Skipping row '{name}' because area is missing or zero!")
                                continue

                            if pd.isna(carbon):
                                carbon, explanation = predict_carbon_llm(area, type_, region)
                            else:
                                explanation = f"Carbon manually entered: {carbon} tonnes."

                            add_project(name, type_, region, float(area), float(carbon), explanation)
                        except Exception as e:
                            st.warning(f"Skipping row due to error: {e}")
                st.success("All uploaded projects imported successfully!")
                do_rerun()

    # -------------------
    # PROJECTS TABLE
    # -------------------
    st.subheader("Projects Overview")
    df = get_all_projects()
    if not df.empty:
        display_df = df[['Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at']]
        st.dataframe(display_df, use_container_width=True)

        st.subheader("Manage Projects")
        for _, row in df.iterrows():
            col1, col2, col3, col4 = st.columns([1,1,1,1])
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
            with col4:
                if row['Explanation']:
                    with st.expander(f"ℹ️ Explanation for {row['Name']}"):
                        st.write(row['Explanation'])


# -------------------
# PUBLIC DASHBOARD
# -------------------

def public_dashboard():
    """Display the public view of projects."""
    st.title("Public Registry")
    df = get_all_projects()

    if not df.empty:
        display_df = df[['Name','Type','Region','Area_ha','Carbon_tonnes','Credits','Status','Created_at']]
        st.dataframe(display_df, use_container_width=True)

        # ℹ️ Explanations for public
        for _, row in df.iterrows():
            if row['Explanation']:
                with st.expander(f"ℹ️ Explanation for {row['Name']}"):
                    st.write(row['Explanation'])
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
        if password == "admin123":  # change in production
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
