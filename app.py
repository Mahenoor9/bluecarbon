import streamlit as st
import pandas as pd
import io
from datetime import datetime
from typing import Tuple, List, Dict
from supabase import create_client, Client


@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    client = create_client(url, key)
    return client

supabase = init_connection()


def do_rerun():
    """
    Provides compatibility with different Streamlit versions to trigger a rerun of the app.
    """
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.experimental_set_query_params(_=datetime.now().timestamp())


def calculate_credits(area: float, carbon: float) -> float:
    try:
        credits = 0.5 * area + 0.2 * carbon
        return round(credits, 4)
    except Exception as e:
        st.error(f"Error calculating credits: {e}")
        return 0.0


def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, status: str = "Draft") -> int:
    credits = calculate_credits(area or 0, carbon or 0)
    new_project = {
        "name": name,
        "type": type_,
        "region": region,
        "area_ha": area,
        "carbon_tonnes": carbon,
        "credits": credits,
        "status": status,
        "verified": "Unverified",
        "created_at": "now()",
        "updated_at": "now()"
    }
    try:
        response = supabase.table("projects").insert(new_project).execute()
        if hasattr(response, "status_code") and response.status_code != 201:
            st.error(f"Failed to add project: {response.error_message}")
            return -1
        return response.data[0]["id"]
    except Exception as e:
        st.error(f"Exception in adding project: {e}")
        return -1


def db_get_projects(limit: int = None, offset: int = 0) -> List[Dict]:
    query = supabase.table("projects").select("*").order("id", desc=True)
    if limit:
        query = query.limit(limit).offset(offset)
    try:
        response = query.execute()
        return getattr(response, "data", [])
    except Exception as e:
        st.error(f"Exception in retrieving projects: {e}")
        return []


def db_delete_project(proj_id: int) -> None:
    try:
        response = supabase.table("projects").delete().eq("id", proj_id).execute()
        if hasattr(response, "status_code") and response.status_code != 200:
            st.error(f"Error deleting project: {response.error_message}")
    except Exception as e:
        st.error(f"Exception in deleting project: {e}")


def db_update_status(proj_id: int, status: str) -> None:
    try:
        response = supabase.table("projects").update({"status": status, "updated_at": "now()"}).eq("id", proj_id).execute()
        if hasattr(response, "status_code") and response.status_code != 200:
            st.error(f"Error updating status: {response.error_message}")
    except Exception as e:
        st.error(f"Exception in updating status: {e}")


def db_update_project(proj_id: int, updates: Dict) -> None:
    try:
        updates["updated_at"] = "now()"
        response = supabase.table("projects").update(updates).eq("id", proj_id).execute()
        if hasattr(response, "status_code") and response.status_code != 200:
            st.error(f"Error updating project: {response.error_message}")
    except Exception as e:
        st.error(f"Exception in updating project: {e}")


def db_update_verified_status(proj_id: int, status: str) -> None:
    try:
        response = supabase.table("projects").update({
            "verified": status,
            "updated_at": "now()"
        }).eq("id", proj_id).execute()
        if hasattr(response, "error") and response.error:
            st.error(f"Error updating verified status: {response.error}")
    except Exception as e:
        st.error(f"Exception in updating verified status: {e}")


def make_csv_template() -> bytes:
    template = pd.DataFrame({
        "name": ["Project A"],
        "type": ["Afforestation"],
        "region": ["India"],
        "area_ha": [100],
        "carbon_tonnes": [400],
        "status": ["Draft"]
    })
    buf = io.BytesIO()
    template.to_csv(buf, index=False)
    return buf.getvalue()


def validate_csv_df(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    errors = []
    required = ["name", "type", "region", "area_ha"]
    for col in required:
        if col not in df.columns:
            errors.append(f"Missing required column: {col}")
    if errors:
        return pd.DataFrame(), errors
    cleaned = []
    for idx, row in df.iterrows():
        try:
            name = str(row.get("name", "")).strip()
            type_ = str(row.get("type", "")).strip()
            region = str(row.get("region", "")).strip()
            area = float(row.get("area_ha", 0) or 0)
            carbon = float(row.get("carbon_tonnes", 0) or 0)
            status = row.get("status", "Draft") or "Draft"
            if not name or not type_ or not region:
                errors.append(f"Row {idx}: missing required text fields")
                continue
            if area <= 0:
                errors.append(f"Row {idx}: area_ha must be > 0")
                continue
            cleaned.append({
                "name": name,
                "type": type_,
                "region": region,
                "area": area,
                "carbon": carbon,
                "status": status
            })
        except Exception as e:
            errors.append(f"Row {idx}: parsing error: {e}")
    clean_df = pd.DataFrame(cleaned)
    return clean_df, errors


def status_badge(status: str) -> str:
    s = str(status or "").lower()
    color = "#6c757d"
    if s == "issued":
        color = "#16a34a"
    elif s == "retired":
        color = "#dc2626"
    elif s == "draft":
        color = "#f59e0b"
    return f"<span style='background:{color};color:white;padding:4px 8px;border-radius:6px;font-size:12px'>{status}</span>"


def pretty_timestamp(ts):
    try:
        if ts is None:
            return ""
        return pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def admin_dashboard():
    st.title("Admin Dashboard — Cloud Registry")
    st.markdown("Use this dashboard to add projects (manually or via CSV), manage them, and inspect stats.")
    st.markdown("---")

    df_all = pd.DataFrame(db_get_projects())
    total_projects = len(df_all)
    total_carbon = round(float(df_all['carbon_tonnes'].sum()) if not df_all.empty else 0.0, 4)
    total_credits = round(float(df_all['credits'].sum()) if not df_all.empty else 0.0, 4)

    col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
    with col1:
        st.metric("Total projects", total_projects)
    with col2:
        st.metric("Total carbon (tCO₂)", total_carbon)
    with col3:
        st.metric("Total credits", total_credits)
    with col4:
        st.button("Refresh", on_click=do_rerun)

    st.markdown("---")
    left, right = st.columns([2, 3])
    with left:
        st.header("Manual Entry")
        name = st.text_input("Project name", key="manual_name")
        type_ = st.text_input("Project type", key="manual_type")
        region = st.text_input("Region", key="manual_region")
        area = st.number_input("Area (ha)", min_value=0.0, format="%.2f", key="manual_area")
        carbon = st.number_input("Carbon stored (tonnes) — optional", min_value=0.0, format="%.2f", key="manual_carbon")
        status_select = st.selectbox("Initial status", ["Draft", "Issued", "Retired"])
        st.markdown("If carbon is left blank or 0, it will be stored as 0. No AI/LLM is used in this version.")
        if st.button("Add project (manual)"):
            if not name or not type_ or not region:
                st.error("Name, type, and region are required.")
            elif area <= 0:
                st.error("Area must be > 0.")
            else:
                proj_id = db_add_project(name=name, type_=type_, region=region, area=area, carbon=carbon or 0, status=status_select)
                if proj_id:
                    st.success(f"Project added (ID {proj_id})")
                    do_rerun()

    with right:
        st.header("Bulk CSV Upload")
        st.markdown("Upload CSV files containing columns: `name,type,region,area_ha,carbon_tonnes (optional),status (optional)`")
        template_bytes = make_csv_template()
        st.download_button("Download CSV template", template_bytes, "projects_template.csv", "text/csv")
        uploaded_files = st.file_uploader("Upload CSV files (you can upload multiple)", accept_multiple_files=True, type=["csv"])
        if uploaded_files:
            preview_frames = []
            all_errors = []
            for uploaded in uploaded_files:
                try:
                    df = pd.read_csv(uploaded)
                    st.markdown(f"**Preview — {uploaded.name}**")
                    st.dataframe(df.head(5))
                    clean_df, errors = validate_csv_df(df)
                    if errors:
                        all_errors.extend([f"{uploaded.name}: {err}" for err in errors])
                    preview_frames.append((uploaded.name, clean_df))
                except Exception as e:
                    all_errors.append(f"{uploaded.name}: could not read CSV ({e})")

            if all_errors:
                st.warning("Validation issues detected. See details below.")
                for e in all_errors:
                    st.write("- " + e)

            if preview_frames:
                st.info("Preview valid rows and click 'Confirm & Import' to insert into the cloud DB.")
                for fname, cdf in preview_frames:
                    st.subheader(f"Valid rows from {fname}")
                    st.dataframe(cdf)
                if st.button("Confirm & Import all valid rows"):
                    imported = 0
                    for _, cdf in preview_frames:
                        for _, r in cdf.iterrows():
                            try:
                                name = r["name"]
                                type_v = r["type"]
                                region_v = r["region"]
                                area_v = float(r["area"])
                                carbon_v = float(r["carbon"])
                                status_v = r.get("status", "Draft") or "Draft"
                                db_add_project(name=name, type_=type_v, region=region_v, area=area_v, carbon=carbon_v, status=status_v)
                                imported += 1
                            except Exception as e:
                                st.error(f"Failed to import row: {e}")
                    st.success(f"Imported {imported} rows.")
                    do_rerun()

    st.markdown("---")
    st.header("Manage Projects")
    st.markdown("Filter, search, and perform bulk actions on existing projects.")
    filter_cols = st.columns(4)
    with filter_cols[0]:
        status_filter = st.multiselect("Status", options=["Draft", "Issued", "Retired"], default=["Draft", "Issued", "Retired"])
    with filter_cols[1]:
        type_filter = st.text_input("Type contains")
    with filter_cols[2]:
        region_filter = st.text_input("Region contains")
    with filter_cols[3]:
        name_search = st.text_input("Search name contains")
    per_page = st.selectbox("Rows per page", [10, 20, 50, 100], index=1)
    page_num = st.number_input("Page number (1-indexed)", min_value=1, value=1, step=1)

    df = pd.DataFrame(db_get_projects())
    if df.empty:
        st.info("No projects in the registry yet.")
        return

    if status_filter:
        df = df[df["status"].isin(status_filter)]
    if type_filter:
        df = df[df["type"].str.contains(type_filter, case=False, na=False)]
    if region_filter:
        df = df[df["region"].str.contains(region_filter, case=False, na=False)]
    if name_search:
        df = df[df["name"].str.contains(name_search, case=False, na=False)]

    st.markdown("#### Filtered summary")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.write(f"Projects (filtered): {len(df)}")
    with col_b:
        st.write(f"Carbon (filtered): {round(df['carbon_tonnes'].sum(),4)} tCO₂")
    with col_c:
        st.write(f"Credits (filtered): {round(df['credits'].sum(),4)}")

    total_rows = len(df)
    total_pages = max(1, (total_rows + per_page - 1) // per_page)
    if page_num > total_pages:
        page_num = total_pages

    start_idx = (page_num - 1) * per_page
    end_idx = start_idx + per_page
    df_page = df.iloc[start_idx:end_idx]

    st.markdown(f"Showing page {page_num} of {total_pages}")
    for idx, row in df_page.iterrows():
        st.markdown("---")
        c1, c2, c3 = st.columns([4, 2, 2])
        with c1:
            created_at = row.get('created_at', None)
            updated_at = row.get('updated_at', None)
            st.markdown(f"**{row['name']}** — {row['type']} — {row['region']}")
            st.write(f"Area: {row['area_ha']} ha | Carbon: {row['carbon_tonnes']} tCO₂ | Credits: {row['credits']}")
            st.write(f"Created: {pretty_timestamp(created_at)} | Updated: {pretty_timestamp(updated_at)}")
            st.write(f"Status: {row['status']} — Verified: {row.get('verified', 'Unverified')}")
        with c2:
            st.markdown(status_badge(row['status']), unsafe_allow_html=True)
            status_options = ["Draft", "Issued", "Retired"]
            current_status = row['status']
            default_index = status_options.index(current_status) if current_status in status_options else 0

            new_status = st.selectbox(f"Change status (ID {row['id']})",
                                     status_options, index=default_index, key=f"status_{row['id']}")

            if new_status != current_status:
                if st.button(f"Apply status {new_status} (ID {row['id']})", key=f"apply_{row['id']}"):
                    db_update_status(row['id'], new_status)
                    st.success(f"Status updated to {new_status}")
                    do_rerun()
        with c3:
            if st.button("Delete", key=f"del_{row['id']}"):
                db_delete_project(row['id'])
                st.success("Deleted")
                do_rerun()
            if st.button("Edit", key=f"edit_{row['id']}"):
                with st.expander(f"Edit project ID {row['id']}", expanded=True):
                    edit_name = st.text_input("Name", value=row['name'], key=f"ename_{row['id']}")
                    edit_type = st.text_input("Type", value=row['type'], key=f"etype_{row['id']}")
                    edit_region = st.text_input("Region", value=row['region'], key=f"eregion_{row['id']}")
                    edit_area = st.number_input("Area (ha)", value=float(row['area_ha'] or 0.0), key=f"earea_{row['id']}")
                    edit_carbon = st.number_input("Carbon (t)", value=float(row['carbon_tonnes'] or 0.0), key=f"ecarbon_{row['id']}")
                    if st.button("Save changes", key=f"save_{row['id']}"):
                        new_credits = calculate_credits(edit_area, edit_carbon)
                        db_update_project(row['id'], {
                            "name": edit_name,
                            "type": edit_type,
                            "region": edit_region,
                            "area_ha": edit_area,
                            "carbon_tonnes": edit_carbon,
                            "credits": new_credits
                        })
                        st.success("Saved")
                        do_rerun()


def public_dashboard():
    st.title("Public Registry — Cloud Projects")
    st.markdown("Public table of projects stored in the cloud. Use filters on the left to refine view.")
    st.markdown("---")

    st.sidebar.header("Public filters")
    status_filter = st.sidebar.multiselect("Status", ["Draft", "Issued", "Retired"], default=["Draft", "Issued", "Retired"])
    type_filter = st.sidebar.text_input("Type contains (public)")
    region_filter = st.sidebar.text_input("Region contains (public)")
    name_search = st.sidebar.text_input("Search name contains (public)")

    rows = db_get_projects()
    if not rows:
        st.info("No projects available.")
        return
    df = pd.DataFrame(rows)

    if status_filter:
        df = df[df["status"].isin(status_filter)]
    if type_filter:
        df = df[df["type"].str.contains(type_filter, case=False, na=False)]
    if region_filter:
        df = df[df["region"].str.contains(region_filter, case=False, na=False)]
    if name_search:
        df = df[df["name"].str.contains(name_search, case=False, na=False)]

    total_projects = len(df)
    total_carbon = round(df['carbon_tonnes'].sum(), 4) if not df.empty else 0.0
    total_credits = round(df['credits'].sum(), 4) if not df.empty else 0.0

    st.markdown(f"**Total projects:** {total_projects} — **Total carbon:** {total_carbon} tCO₂ — **Total credits:** {total_credits}")
    st.markdown("---")

    if not df.empty:
        view_df = df[["id", "name", "type", "region", "area_ha", "carbon_tonnes",
                      "credits", "status", "verified", "created_at"]].copy()
        view_df.rename(columns={
            "id": "ID",
            "name": "Name",
            "type": "Type",
            "region": "Region",
            "area_ha": "Area_ha",
            "carbon_tonnes": "Carbon_tonnes",
            "credits": "Credits",
            "status": "Status",
            "verified": "Verified",
            "created_at": "Created_at"
        }, inplace=True)
        view_df["Created_at"] = view_df["Created_at"].apply(pretty_timestamp)
        st.dataframe(view_df)
    else:
        st.info("No projects match your filters.")


def verifier_dashboard():
    st.title("Verifier Dashboard — Carbon Registry")
    st.markdown("View projects and mark as Verified or Unverified.")

    projects = db_get_projects()
    if not projects:
        st.info("No projects available.")
        return

    df = pd.DataFrame(projects)
    if 'verified' not in df.columns:
        df['verified'] = 'Unverified'

    for idx, row in df.iterrows():
        st.markdown("---")
        st.write(f"**{row['name']}** — Credits: {row.get('credits', 0)}")
        st.write(f"Status: {row['status']} | Verified: {row['verified']}")
        col1, col2 = st.columns(2)

        with col1:
            if st.button(f"Verify (ID {row['id']})", key=f"verify_{row['id']}"):
                db_update_verified_status(row['id'], 'Verified')
                st.success("Marked as Verified")
                do_rerun()

        with col2:
            if st.button(f"Unverify (ID {row['id']})", key=f"unverify_{row['id']}"):
                db_update_verified_status(row['id'], 'Unverified')
                st.success("Marked as Unverified")
                do_rerun()


def main():
    st.set_page_config(page_title="Carbon Registry (Cloud)", layout="wide", initial_sidebar_state="auto")
    st.sidebar.title("Carbon Registry")
    st.sidebar.markdown("Select view and actions")
    page = st.sidebar.radio("Navigate", ["Public", "Verifier", "Admin", "About"])

    if page == "Admin":
        st.sidebar.markdown("---")
        password = st.sidebar.text_input("Admin password", type="password")
        if password.strip() == "" and "password" not in st.session_state:
            st.sidebar.info("Enter admin password to continue.")
            public_dashboard()
            return

        if password == "admin123" or st.session_state.get("is_admin"):
            st.session_state["is_admin"] = True
            admin_dashboard()
        else:
            st.sidebar.error("Wrong password.")
            public_dashboard()

    elif page == "Verifier":
        # No password authentication for verifier since blockchain handles verification externally
        verifier_dashboard()

    elif page == "Public":
        public_dashboard()

    else:
        st.title("About — Carbon Registry (Cloud)")
        st.markdown("""
        This app stores project data (area, carbon, credits, status) in a cloud PostgreSQL database (Supabase).

        Features:
        - Admin: add projects (manual or CSV), manage status, edit, delete.
        - Verifier: view projects, mark Verified/Unverified.
        - Public: view projects in tabular format with filters.
        - No LLMs or external AI calls in this version (cloud-only registry).

        Notes:
        - DB credentials are read from Streamlit secrets or environment variables for safety.
        - Replace the admin password and secure the app before production.
        """)
        st.markdown("### Current DB connection info (for debugging)")
        st.write({
            "host": "hidden for security"
        })


if __name__ == "__main__":
    main()
