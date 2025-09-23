import streamlit as st
import pandas as pd
import io
from datetime import datetime
from typing import Tuple, List, Dict
from supabase import create_client


# ----- CUSTOM SUPER-3D/GLASS STYLE -----
st.set_page_config(page_title="Cloud Registry 3D", layout="wide")
st.markdown("""
<style>
body {
    background: linear-gradient(240deg, #45e8f8 3%, #40c9ff 45%, #ffde7d 100%);
    font-family: 'Montserrat', Arial, sans-serif ;
}
.stApp { background: transparent; }
.registry-glass {
    background: rgba(245, 245, 255, .16);
    box-shadow: 0 16px 40px 0 #51cbee29, 0 2px 4px #0002;
    border-radius: 14px;
    padding: 2.7rem 2.1rem 1.6rem 2.1rem;
    margin-bottom: 1.5rem;
    border: 1.4px solid #94ffd14c;
    backdrop-filter: blur(8px) brightness(1.11);
    transition: 0.24s all cubic-bezier(.4,2.4,.3,1);
    position: relative;
}
.registry-glass:hover {
    box-shadow: 0 28px 80px 0 #51cbee72, 0 8px 24px #0005;
    transform: translateY(-2px) scale(1.03) rotateY(4deg);
}
.registry-badge {
    border-radius:2em;
    background:linear-gradient(90deg,#33e8bd,#11b9f1 90%);
    color:#fff!important;
    font-size:0.95rem;padding:0.35em 1.2em;
    display:inline-block;
    margin:0.35em 0.7em 0.4em 0;letter-spacing:0.1em;
    box-shadow:0 3px 16px -3px #15604790;
}
.status-icon {
    display: inline-block;
    vertical-align: middle;
    margin-right: 2px;
}
.status-Draft {
    background: linear-gradient(90deg,#fbbf24 60%,#f59e0b 100%);
}
.status-Issued {
    background: linear-gradient(90deg,#38d46c 80%,#16a34a 100%);
}
.status-Retired {
    background: linear-gradient(90deg,#e84d4a 65%,#b91c1c 100%);
}
.animated-toast {
    animation: popin 0.9s cubic-bezier(0.16,1,0.3,1.01);
}
@keyframes popin {
    from { opacity:.4; transform: translateY(60px) scale(.85);}
    to   { opacity:1; transform: translateY(0) scale(1);}
}
.matrix-bg {
    pointer-events: none; z-index:0; position:fixed;top:0;left:0;right:0;bottom:0;
    opacity:0.16;
    filter: blur(2.5px) contrast(1.05);
}
</style>
""", unsafe_allow_html=True)


st.markdown("""<svg class="matrix-bg" width="100vw" height="100vh"><defs><linearGradient id="G" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#30fac1"/><stop offset="1" stop-color="#00cdac" /></linearGradient></defs>
<g>
<rect x="0" y="0" width="100%" height="100%" fill="url(#G)" opacity="0.12"></rect>
</g></svg>
""", unsafe_allow_html=True)


@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    client = create_client(url, key)
    return client
supabase = init_connection()


def do_rerun():
    if hasattr(st, "rerun"): st.rerun()
    elif hasattr(st, "experimental_rerun"): st.experimental_rerun()
    else: st.experimental_set_query_params(_=datetime.now().timestamp())


def calculate_credits(area: float, carbon: float) -> float:
    try: return round(0.5 * area + 0.2 * carbon, 4)
    except Exception as e:
        st.error(f"Error calculating credits: {e}")
        return 0.0


def db_add_project(name: str, type_: str, region: str, area: float, carbon: float, status: str = "Draft") -> int:
    credits = calculate_credits(area or 0, carbon or 0)
    new_project = {
        "name": name,"type": type_,"region": region,
        "area_ha": area, "carbon_tonnes": carbon, "credits": credits,
        "status": status, "verified": "Unverified",
        "created_at": "now()","updated_at": "now()"
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
    if limit: query = query.limit(limit).offset(offset)
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
    except Exception as e: st.error(f"Exception in deleting project: {e}")


def db_update_status(proj_id: int, status: str) -> None:
    try:
        response = supabase.table("projects").update({"status": status, "updated_at": "now()"}).eq("id", proj_id).execute()
        if hasattr(response, "status_code") and response.status_code != 200:
            st.error(f"Error updating status: {response.error_message}")
    except Exception as e: st.error(f"Exception in updating status: {e}")


def db_update_project(proj_id: int, updates: Dict) -> None:
    try:
        updates["updated_at"] = "now()"
        response = supabase.table("projects").update(updates).eq("id", proj_id).execute()
        if hasattr(response, "status_code") and response.status_code != 200:
            st.error(f"Error updating project: {response.error_message}")
    except Exception as e: st.error(f"Exception in updating project: {e}")


def db_update_verified_status(proj_id: int, status: str) -> None:
    try:
        response = supabase.table("projects").update({ "verified": status, "updated_at": "now()" }).eq("id", proj_id).execute()
        if hasattr(response, "error") and response.error:
            st.error(f"Error updating verified status: {response.error}")
    except Exception as e: st.error(f"Exception in updating verified status: {e}")


def make_csv_template() -> bytes:
    template = pd.DataFrame({
        "name": ["Project A"], "type": ["Afforestation"], "region": ["India"],
        "area_ha": [100],"carbon_tonnes": [400],"status": ["Draft"]
    })
    buf = io.BytesIO(); template.to_csv(buf, index=False)
    return buf.getvalue()


def validate_csv_df(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    errors = []; required = ["name", "type", "region", "area_ha"]
    for col in required:
        if col not in df.columns: errors.append(f"Missing required column: {col}")
    if errors: return pd.DataFrame(), errors
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
                errors.append(f"Row {idx}: missing required text fields"); continue
            if area <= 0: errors.append(f"Row {idx}: area_ha must be > 0"); continue
            cleaned.append({"name": name,"type": type_,"region": region,"area": area,"carbon": carbon,"status": status})
        except Exception as e: errors.append(f"Row {idx}: parsing error: {e}")
    clean_df = pd.DataFrame(cleaned)
    return clean_df, errors


def pretty_timestamp(ts):
    try:
        if ts is None: return ""
        return pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception: return str(ts)


def status_badge(status: str) -> str:
    color = "#aaa"
    icon = '<svg class="status-icon" width="16" height="16">' if status == "Draft" else ''
    if status == "Issued": color = "#11c964"; icon = '<svg class="status-icon" width="16" height="16"><circle r="7" cx="8" cy="8" fill="#11c964"/></svg>'
    if status == "Retired": color = "#e84d4a"; icon = '<svg class="status-icon" width="16" height="16"><circle r="7" cx="8" cy="8" fill="#e84d4a"/></svg>'
    if status == "Draft": color = "#f59e0b"; icon = '<svg class="status-icon" width="16" height="16"><circle r="7" cx="8" cy="8" fill="#fbbf24"/></svg>'
    return f'{icon}<span class="registry-badge status-{status}">{status}</span>'


def admin_dashboard():
    st.markdown('<div class="registry-glass"><h1>👑 Admin Dashboard — Cloud Registry 3D</h1><p>Manage all projects. Beautiful, glassmorphism design, animated badges. </p></div>', unsafe_allow_html=True)
    df_all = pd.DataFrame(db_get_projects())
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="registry-glass registry-badge" style="background:#00cdac2c;">Total projects<br><b>{len(df_all)}</b></div>',unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="registry-glass registry-badge" style="background:#097b92b0;">Total carbon<br><b>{round(float(df_all["carbon_tonnes"].sum()) if not df_all.empty else 0.0, 4)} tCO₂</b></div>',unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="registry-glass registry-badge" style="background:#70f6b7bb;">Total credits<br><b>{round(float(df_all["credits"].sum()) if not df_all.empty else 0.0, 4)}</b></div>',unsafe_allow_html=True)
    with col4:
        if st.button("🔄 Refresh"): do_rerun()

    st.markdown('<div class="registry-glass"><h4>Manual Entry</h4>', unsafe_allow_html=True)
    c1, c2, c3= st.columns([4,3,3])
    with c1:
        name = st.text_input("Project name", key="manual_name")
        type_ = st.text_input("Project type", key="manual_type")
        region = st.text_input("Region", key="manual_region")
    with c2:
        area = st.number_input("Area (ha)", min_value=0.0, format="%.2f", key="manual_area")
        carbon = st.number_input("Carbon stored (tonnes) — optional", min_value=0.0, format="%.2f", key="manual_carbon")
        status_select = st.selectbox("Initial status", ["Draft", "Issued", "Retired"])
    with c3:
        st.write("CSV Upload:")
        template_bytes = make_csv_template()
        st.download_button("Download CSV template", template_bytes, "projects_template.csv", "text/csv")
        uploaded_files = st.file_uploader("CSV files", accept_multiple_files=True, type=["csv"])
    st.markdown('</div>', unsafe_allow_html=True)

    colb1, colb2 = st.columns([6,4])
    with colb1:
        if st.button("Add project (manual)"):
            if not name or not type_ or not region:
                st.toast('Name, type, region required', icon="❗", key="errorm")
            elif area <= 0:
                st.toast('Area must be > 0', icon="⚠️", key="aream")
            else:
                proj_id = db_add_project(name=name, type_=type_, region=region, area=area, carbon=carbon or 0, status=status_select)
                if proj_id != -1:
                    st.success(f"Project added (ID {proj_id}) 🎉", icon="✅")
                    do_rerun()
    with colb2:
        if uploaded_files:
            all_errors = []
            preview_frames = []
            for uploaded in uploaded_files:
                try:
                    df = pd.read_csv(uploaded)
                    clean_df, errors = validate_csv_df(df)
                    if errors: st.error(f"{uploaded.name}: " + ", ".join(errors), icon="🚫")
                    if not clean_df.empty:
                        st.write(f"[{uploaded.name}]")
                        st.dataframe(clean_df)
                        preview_frames.append((uploaded.name, clean_df))
                except Exception as e:
                    st.error(f"could not read CSV {uploaded.name}: {e}")
            if preview_frames and st.button("Confirm & Import all valid rows"):
                for fname, cdf in preview_frames:
                    for _, r in cdf.iterrows():
                        try:
                            db_add_project(r["name"], r["type"], r["region"], float(r["area"]), float(r["carbon"]), r.get("status", "Draft"))
                        except Exception as e: st.error(f"Failed import: {e}")
                st.toast("All valid rows imported!", icon="✅"); do_rerun()

    st.markdown("---")
    st.markdown('<div class="registry-glass"><h3>Manage Projects</h3>', unsafe_allow_html=True)
    df = pd.DataFrame(db_get_projects())
    status_filter = st.multiselect("Status", ["Draft", "Issued", "Retired"], default=["Draft", "Issued", "Retired"])
    df = df[df["status"].isin(status_filter)] if status_filter else df
    per_page = st.selectbox("Rows per page", [10, 20, 50, 100], index=1)
    page_num = st.number_input("Page number (1-indexed)", min_value=1, value=1, step=1)
    total_pages = max(1, ((len(df) + per_page - 1) // per_page))
    if page_num > total_pages: page_num = total_pages
    start_idx = (page_num - 1) * per_page
    end_idx = start_idx + per_page
    df_page = df.iloc[start_idx:end_idx]

    for idx, row in df_page.iterrows():
        st.markdown(f'''<div class="registry-glass animated-toast">
            <b>{row['name']}</b> — {row['type']} — {row['region']}
            <br>Area: <b>{row['area_ha']}</b> ha | Carbon: <b>{row['carbon_tonnes']}</b> tCO₂ | Credits: <b>{row['credits']}</b>
            <br>Status: {status_badge(row['status'])} Verified: <span class="registry-badge">{row.get('verified','Unverified')}</span>
            <br>Created: {pretty_timestamp(row.get('created_at'))} | Updated: {pretty_timestamp(row.get('updated_at'))}
            </div>''', unsafe_allow_html=True)
        cc1, cc2, cc3, cc4 = st.columns([2,2,2,3])
        with cc1:
            new_status = st.selectbox("Change status", ["Draft","Issued","Retired"], index=["Draft","Issued","Retired"].index(row['status']), key=f"status_{row['id']}")
            if new_status != row["status"] and st.button("Apply", key=f"apply_{row['id']}"):
                db_update_status(row['id'], new_status)
                st.toast(f"Status updated to {new_status}!", icon="✏️")
                do_rerun()
        with cc2:
            if st.button("Delete", key=f"del_{row['id']}"):
                db_delete_project(row['id'])
                st.toast("Project deleted.", icon="🗑")
                do_rerun()
        with cc3:
            if st.button("Edit", key=f"edit_{row['id']}"):
                with st.expander("Edit details", expanded=True):
                    edit_name = st.text_input("Name", value=row['name'], key=f"ename_{row['id']}")
                    edit_type = st.text_input("Type", value=row['type'], key=f"etype_{row['id']}")
                    edit_region = st.text_input("Region", value=row['region'], key=f"eregion_{row['id']}")
                    edit_area = st.number_input("Area (ha)", value=float(row['area_ha']), key=f"earea_{row['id']}")
                    edit_carbon = st.number_input("Carbon (t)", value=float(row['carbon_tonnes']), key=f"ecarbon_{row['id']}")
                    if st.button("Save changes", key=f"save_{row['id']}"):
                        db_update_project(row['id'], {
                            "name": edit_name, "type": edit_type, "region": edit_region, "area_ha": edit_area,
                            "carbon_tonnes": edit_carbon, "credits": calculate_credits(edit_area, edit_carbon)
                        })
                        st.toast("Saved!", icon="💾")
                        do_rerun()
        with cc4:
            if st.button("Mark Verified", key=f"verify_btn_{row['id']}"):
                db_update_verified_status(row['id'], "Verified")
                st.toast("Marked as Verified", icon="✅")
                do_rerun()
            if st.button("Mark Unverified", key=f"unverify_btn_{row['id']}"):
                db_update_verified_status(row['id'], "Unverified")
                st.toast("Marked as Unverified", icon="⛔")
                do_rerun()


def verifier_dashboard():
    st.title("✅ Verifier Dashboard — Carbon Registry (3D)")
    st.markdown('<div class="registry-glass">Inspect and mark projects Verified or Unverified. This view is for third-party auditors only.</div>', unsafe_allow_html=True)
    projects = db_get_projects()
    if not projects:
        st.info("No projects available.")
        return

    df = pd.DataFrame(projects)
    if 'verified' not in df.columns:
        df['verified'] = 'Unverified'

    for idx, row in df.iterrows():
        st.markdown(f'''<div class="registry-glass animated-toast" style="margin-bottom:1rem;">
            <b>{row['name']}</b> — {row['type']} — {row['region']}
            <br>Area: <b>{row['area_ha']}</b> ha | Carbon: <b>{row['carbon_tonnes']}</b> tCO₂ | Credits: <b>{row['credits']}</b>
            <br>Status: {status_badge(row['status'])} Verified: <span class="registry-badge">{row.get('verified','Unverified')}</span>
            <br>Created: {pretty_timestamp(row.get('created_at'))} | Updated: {pretty_timestamp(row.get('updated_at'))}
            </div>''', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button(f"✅ Mark as Verified (ID {row['id']})", key=f"verify_{row['id']}"):
                db_update_verified_status(row['id'], 'Verified')
                st.toast("Marked as Verified", icon="✅")
                do_rerun()
        with col2:
            if st.button(f"❌ Mark as Unverified (ID {row['id']})", key=f"unverify_{row['id']}"):
                db_update_verified_status(row['id'], 'Unverified')
                st.toast("Marked as Unverified", icon="✖️")
                do_rerun()


def main():
    st.sidebar.markdown('<h2 style="margin-bottom:0.5em;">🌤️ Carbon Registry <span class="registry-badge">3D</span></h2>', unsafe_allow_html=True)
    page = st.sidebar.radio("Navigate", ["Public", "Verifier", "Admin", "About"])
    if page == "Admin":
        password = st.sidebar.text_input("Admin password", type="password")
        if password.strip() == "" and "password" not in st.session_state:
            st.sidebar.info("Enter admin password."); return
        if password == "admin123" or st.session_state.get("is_admin"):
            st.session_state["is_admin"] = True
            admin_dashboard()
        else:
            st.sidebar.error("Wrong password.")
    elif page == "Public":
        st.title("🌏 Public Cloud Registry")
        st.markdown('<div class="registry-glass"><b>Use the filters on the left to explore all projects in stunning 3D—cards, glass, and colors included! (View Only)</b></div>', unsafe_allow_html=True)
        projects = db_get_projects()
        if not projects:
            st.info("No projects available.")
        else:
            df = pd.DataFrame(projects)
            status_filter = st.sidebar.multiselect("Status", options=["Draft", "Issued", "Retired"], default=["Draft", "Issued", "Retired"])
            type_filter = st.sidebar.text_input("Type contains")
            region_filter = st.sidebar.text_input("Region contains")
            name_search = st.sidebar.text_input("Search name contains")
            if status_filter:
                df = df[df["status"].isin(status_filter)]
            if type_filter:
                df = df[df["type"].str.contains(type_filter, case=False, na=False)]
            if region_filter:
                df = df[df["region"].str.contains(region_filter, case=False, na=False)]
            if name_search:
                df = df[df["name"].str.contains(name_search, case=False, na=False)]
            st.markdown("---")
            st.markdown(f"**Total projects:** {len(df)} — **Total carbon:** {round(df['carbon_tonnes'].sum(), 4)} tCO₂ — **Total credits:** {round(df['credits'].sum(), 4)}")
            st.markdown("---")
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
            st.dataframe(view_df, use_container_width=True)
    elif page == "Verifier":
        verifier_dashboard()
    else:
        st.title("ℹ️ About — Carbon Registry (3D+)")
        st.markdown('''<div class="registry-glass">
        Beautifully animated, interactive, and visually striking, this registry combines a powerful backend with <b>cutting-edge frontend</b> design.<hr>
        <i>All logic is original—only the frontend is supercharged. Copy & use freely!</i><hr>
        </div>''', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
