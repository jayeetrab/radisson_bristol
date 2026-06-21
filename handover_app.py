import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
import pymongo
import logging

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Handover Dashboard", layout="wide", page_icon="🤝")

# Modern CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        margin-bottom: 16px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    }
    .card-title {
        font-size: 1.25rem;
        font-weight: 600;
        color: #0f172a;
        margin-bottom: 8px;
    }
    .card-meta {
        font-size: 0.85rem;
        color: #64748b;
        margin-bottom: 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .card-body {
        font-size: 1rem;
        color: #334155;
        white-space: pre-wrap;
    }
    .dept-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .dept-Maintenance { background-color: #fee2e2; color: #991b1b; }
    .dept-Housekeeping { background-color: #e0e7ff; color: #3730a3; }
    .dept-FrontOffice { background-color: #dcfce3; color: #166534; }
    .dept-Management { background-color: #fef3c7; color: #92400e; }
    .dept-Other { background-color: #f1f5f9; color: #475569; }
    
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-left: 8px;
    }
    .status-Pending { background-color: #fef08a; color: #854d0e; border: 1px solid #fde047; }
    .status-InProgress { background-color: #bfdbfe; color: #1e3a8a; border: 1px solid #93c5fd; }
    .status-Completed { background-color: #bbf7d0; color: #14532d; border: 1px solid #86efac; }
    
    .card-footer {
        margin-top: 12px;
        padding-top: 12px;
        border-top: 1px solid #e2e8f0;
        font-size: 0.85rem;
        color: #64748b;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
</style>
""", unsafe_allow_html=True)

# Function to get current DB path based on config if we were to parse it, but for standalone we'll just check if TEST is needed or just use hotelfo.db
DBPATH = "hotelfo.db"

# MongoDB Configuration
MONGO_URI = "mongodb+srv://jayeetrab:mGhnfdMwFeFZwx6L@cohortconnect.lcpylgn.mongodb.net/"
try:
    mongo_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_db = mongo_client["Reservations"]
    mongo_tasks = mongo_db["tasks"]
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    mongo_tasks = None

def get_db_connection():
    conn = sqlite3.connect(DBPATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def add_handover(task_date, title, created_by, assigned_to, comment, department, status="Pending", completed_by=""):
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO tasks (task_date, title, created_by, assigned_to, comment, department, status, completed_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (task_date.isoformat(), title, created_by, assigned_to, comment, department, status, completed_by))
        conn.commit()
        task_id = cursor.lastrowid
        
    if mongo_tasks is not None:
        try:
            mongo_tasks.insert_one({
                "id": task_id,
                "task_date": task_date.isoformat(),
                "title": title,
                "created_by": created_by,
                "assigned_to": assigned_to,
                "comment": comment,
                "department": department,
                "status": status,
                "completed_by": completed_by,
                "created_at": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"MongoDB Sync Error (Insert): {e}")

def get_handovers(task_date):
    with get_db_connection() as conn:
        cursor = conn.execute("""
            SELECT * FROM tasks WHERE task_date = ? ORDER BY id DESC
        """, (task_date.isoformat(),))
        return cursor.fetchall()

def update_handover(task_id, title, created_by, assigned_to, comment, department, status, completed_by):
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE tasks
            SET title = ?, created_by = ?, assigned_to = ?, comment = ?, department = ?, status = ?, completed_by = ?
            WHERE id = ?
        """, (title, created_by, assigned_to, comment, department, status, completed_by, task_id))
        conn.commit()
        
    if mongo_tasks is not None:
        try:
            mongo_tasks.update_one(
                {"id": task_id},
                {"$set": {
                    "title": title,
                    "created_by": created_by,
                    "assigned_to": assigned_to,
                    "comment": comment,
                    "department": department,
                    "status": status,
                    "completed_by": completed_by
                }},
                upsert=True
            )
        except Exception as e:
            logger.error(f"MongoDB Sync Error (Update): {e}")

def update_handover_status(task_id, status):
    with get_db_connection() as conn:
        conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        conn.commit()
    if mongo_tasks is not None:
        try:
            mongo_tasks.update_one({"id": task_id}, {"$set": {"status": status}})
        except Exception as e:
            logger.error(f"MongoDB Sync Error (Status Update): {e}")

def delete_handover(task_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        
    if mongo_tasks is not None:
        try:
            mongo_tasks.delete_one({"id": task_id})
        except Exception as e:
            logger.error(f"MongoDB Sync Error (Delete): {e}")

st.title("🤝 Handover Dashboard")
st.markdown("Modern Handover Management for Maintenance, Housekeeping, and Front Office.")

d = st.date_input("Select Date", value=date.today())

with st.expander("➕ Add New Handover", expanded=False):
    with st.form("add_handover_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        title = col1.text_input("Task / Title*", placeholder="e.g. Broken AC in Room 102")
        department = col2.selectbox("Department", ["Maintenance", "Housekeeping", "Front Office", "Management", "Other"])
        
        col3, col4 = st.columns(2)
        created_by = col3.text_input("Created By", placeholder="e.g. John Doe")
        assigned_to = col4.text_input("Assigned To (Optional)", placeholder="e.g. Jane Smith")
        
        status = st.selectbox("Status", ["Pending", "In Progress", "Completed"])
        
        comment = st.text_area("Additional Comments", placeholder="Add any details here...")
        
        submitted = st.form_submit_button("Submit Handover", type="primary", use_container_width=True)
        if submitted:
            if title:
                add_handover(d, title, created_by, assigned_to, comment, department, status)
                st.success("✅ Handover added successfully.")
                st.rerun()
            else:
                st.error("❌ Title is required.")

# Fetch Handovers
rows = get_handovers(d)

if not rows:
    st.info("No handovers found for this date.")
else:
    # Separate by department
    departments = ["All", "Maintenance", "Housekeeping", "Front Office", "Management", "Other"]
    tabs = st.tabs(departments)
    
    for i, tab in enumerate(tabs):
        dept_name = departments[i]
        with tab:
            if dept_name == "All":
                filtered_rows = rows
            else:
                filtered_rows = [r for r in rows if (r["department"] == dept_name) or (dept_name == "Other" and r["department"] not in departments)]
            
            if not filtered_rows:
                st.caption(f"No handovers for {dept_name}.")
            else:
                for row in filtered_rows:
                    row_dict = dict(row)
                    dept_display = row_dict["department"] or "Other"
                    dept_class = dept_display.replace(" ", "")
                    if dept_class not in ["Maintenance", "Housekeeping", "FrontOffice", "Management"]:
                        dept_class = "Other"
                    
                    status_val = row_dict.get("status") or "Pending"
                    status_class = status_val.replace(" ", "")
                    completed_by_text = f"✓ Completed by: {row_dict.get('completed_by')}" if status_val == "Completed" and row_dict.get("completed_by") else ""
                    
                    with st.container(border=True):
                        c_main, c_stat = st.columns([3, 1])
                        with c_main:
                            st.markdown(f"**{row['title']}**")
                            st.markdown(f"<span class='dept-badge dept-{dept_class}'>{dept_display}</span>", unsafe_allow_html=True)
                            if completed_by_text:
                                st.markdown(f"<small style='color:green;'>{completed_by_text}</small>", unsafe_allow_html=True)
                        
                        with c_stat:
                            status_options = ["Pending", "In Progress", "Completed"]
                            try:
                                status_idx = status_options.index(status_val)
                            except ValueError:
                                status_idx = 0
                                
                            new_status = st.selectbox(
                                "Status", 
                                status_options, 
                                index=status_idx,
                                key=f"quick_status_{dept_name}_{row['id']}",
                                label_visibility="collapsed"
                            )
                            if new_status != status_val:
                                update_handover_status(row['id'], new_status)
                                st.rerun()

                        with st.expander("View Details & Edit"):
                            st.markdown(f"**By:** {row_dict['created_by'] or 'N/A'} &nbsp;➔&nbsp; **To:** {row_dict['assigned_to'] or 'N/A'}")
                            st.markdown(f"**Notes:**\n\n{row_dict['comment'] or 'No additional comments.'}")
                            
                            st.divider()
                            st.caption("Edit Task")
                            with st.form(f"edit_form_{dept_name}_{row['id']}"):
                                edit_title = st.text_input("Title", value=row["title"])
                                
                                # Safely find index for selectbox
                                dept_options = ["Maintenance", "Housekeeping", "Front Office", "Management", "Other"]
                                try:
                                    default_idx = dept_options.index(row["department"]) if row["department"] else 4
                                except ValueError:
                                    default_idx = 4
                                edit_dept = st.selectbox("Department", dept_options, index=default_idx)
                                
                                status_options = ["Pending", "In Progress", "Completed"]
                                try:
                                    status_idx = status_options.index(status_val)
                                except ValueError:
                                    status_idx = 0
                                edit_status = st.selectbox("Status", status_options, index=status_idx)
                                
                                col_c1, col_c2 = st.columns(2)
                                edit_created = col_c1.text_input("Created By", value=row_dict["created_by"] or "")
                                edit_assigned = col_c2.text_input("Assigned To", value=row_dict["assigned_to"] or "")
                                
                                edit_completed = st.text_input("Completed By", value=row_dict.get("completed_by") or "")
                                edit_comment = st.text_area("Comment", value=row_dict["comment"] or "")
                                
                                col_save, col_del = st.columns(2)
                                with col_save:
                                    if st.form_submit_button("Save changes", type="primary", use_container_width=True):
                                        update_handover(row["id"], edit_title, edit_created, edit_assigned, edit_comment, edit_dept, edit_status, edit_completed)
                                        st.success("Updated.")
                                        st.rerun()
                                with col_del:
                                    if st.form_submit_button("Delete", use_container_width=True):
                                        delete_handover(row["id"])
                                        st.success("Deleted.")
                                        st.rerun()
