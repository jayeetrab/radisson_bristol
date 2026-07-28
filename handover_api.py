from flask import Flask, render_template, request, jsonify, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import pymongo
from bson.objectid import ObjectId
from datetime import datetime, date, timedelta
import os
import logging

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.permanent_session_lifetime = timedelta(days=7)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB Configuration
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://jayeetrab:mGhnfdMwFeFZwx6L@cohortconnect.lcpylgn.mongodb.net/")
try:
    mongo_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_db = mongo_client["Reservations"]
    mongo_tasks = mongo_db["tasks"]
    mongo_users = mongo_db["users"]
    mongo_activity = mongo_db["activity"]
    try:
        mongo_tasks.create_index([("is_deleted", 1), ("task_date", 1)])
        mongo_tasks.create_index([("created_at", -1)])
    except Exception as idx_err:
        logger.warning(f"Task index creation notice: {idx_err}")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    mongo_tasks = None
    mongo_users = None
    mongo_activity = None

DEPARTMENTS = ["Maintenance", "Housekeeping", "Front Office", "Management", "F&B", "Finance", "Other"]
ROLES = ["normal", "supervisor", "manager", "admin"]
ROLE_RANK = {"normal": 1, "supervisor": 2, "manager": 3, "admin": 4}


def ensure_seed_admin():
    """Ensure the admin account defined by ADMIN_USERNAME / ADMIN_PASSWORD exists.
    Creates it if that username is missing; never overwrites an existing account, so a
    password changed in-app is preserved across deploys. Set these two vars in Vercel
    to control the super-admin login (the password is supplied by you via env, never
    stored in the codebase)."""
    if mongo_users is None:
        return
    try:
        admin_username = os.environ.get("ADMIN_USERNAME", "admin").strip().lower()
        if mongo_users.find_one({"username": admin_username}) is None:
            mongo_users.insert_one({
                "username": admin_username,
                "name": os.environ.get("ADMIN_NAME", "Administrator"),
                "password_hash": generate_password_hash(os.environ.get("ADMIN_PASSWORD", "admin123")),
                "role": "admin",
                "departments": ["Management"],
                "active": True,
                "must_change_password": False,
                "created_at": datetime.utcnow(),
            })
            logger.info(f"Seeded admin account '{admin_username}'.")
    except Exception as e:
        logger.error(f"Failed to seed admin: {e}")


ensure_seed_admin()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def current_user():
    if not session.get("uid"):
        return None
    return {
        "id": session.get("uid"),
        "name": session.get("name"),
        "username": session.get("username"),
        "role": session.get("role"),
        "departments": session.get("departments", []),
    }


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return wrapper


def rank(role):
    return ROLE_RANK.get(role, 0)


def can_edit_task(user, task):
    """Supervisor+ can edit any task; normal users can edit only tasks they created."""
    if rank(user["role"]) >= ROLE_RANK["supervisor"]:
        return True
    return (task.get("created_by_id") and task.get("created_by_id") == user["id"]) or (task.get("created_by") and task.get("created_by") == user["name"])


def resolve_task_id(task_id):
    if task_id.isdigit():
        return int(task_id)
    try:
        return ObjectId(task_id)
    except Exception:
        return task_id


def log_activity(action, target_type=None, target_id=None, target_title=None, task_departments=None, detail=""):
    """Record an auditable action. `depts` (actor's + target's departments) is what
    scopes visibility: managers see entries touching their department(s)."""
    if mongo_activity is None:
        return
    try:
        u = current_user() or {}
        actor_depts = u.get("departments", []) or []
        task_depts = task_departments or []
        if isinstance(task_depts, str):
            task_depts = [task_depts]
        depts = sorted(set([d for d in actor_depts if d] + [d for d in task_depts if d]))
        mongo_activity.insert_one({
            "ts": datetime.utcnow(),
            "user_id": u.get("id"),
            "user_name": u.get("name"),
            "user_role": u.get("role"),
            "user_departments": actor_depts,
            "action": action,
            "target_type": target_type,
            "target_id": str(target_id) if target_id is not None else None,
            "target_title": target_title,
            "task_departments": task_depts,
            "depts": depts,
            "detail": detail,
        })
    except Exception as e:
        logger.error(f"Activity log error: {e}")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    if not session.get("uid"):
        return redirect('/login')
    return render_template('handover.html')


@app.route('/login')
def login_page():
    if session.get("uid"):
        return redirect('/')
    return render_template('login.html')


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------
@app.route('/api/login', methods=['POST'])
def api_login():
    if mongo_users is None:
        return jsonify({"error": "Database connection failed"}), 500
    data = request.json or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    user = mongo_users.find_one({"username": username})
    if not user or not user.get("active", True) or not check_password_hash(user.get("password_hash", ""), password):
        return jsonify({"error": "Invalid username or password"}), 401
    session.permanent = True
    session["uid"] = str(user["_id"])
    session["name"] = user["name"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["departments"] = user.get("departments", [])
    session["must_change"] = user.get("must_change_password", False)
    log_activity("login", target_type="session", detail="Signed in")
    return jsonify({"success": True})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    log_activity("logout", target_type="session", detail="Signed out")
    session.clear()
    return jsonify({"success": True})


@app.route('/api/me', methods=['GET'])
@login_required
def api_me():
    u = current_user()
    u["departments_all"] = DEPARTMENTS
    u["can_view_activity"] = u["role"] in ("admin", "manager")
    u["can_manage_users"] = u["role"] in ("admin", "manager")
    u["must_change_password"] = session.get("must_change", False)
    return jsonify(u)


@app.route('/api/activity', methods=['GET'])
@login_required
def api_activity():
    """Admin (super-admin) sees every action. Managers see activity touching their
    department(s), plus their own. Supervisors and normal staff have no access."""
    if mongo_activity is None:
        return jsonify([])
    user = current_user()
    role = user["role"]
    if role == "admin":
        query = {}
    elif role == "manager":
        depts = user.get("departments", []) or []
        query = {"$or": [{"depts": {"$in": depts}}, {"user_id": user["id"]}]}
    else:
        return jsonify({"error": "You don't have access to activity logs"}), 403

    try:
        limit = min(int(request.args.get("limit", 300)), 1000)
    except ValueError:
        limit = 300

    entries = []
    for e in mongo_activity.find(query).sort("ts", -1).limit(limit):
        e.pop("_id", None)
        ts = e.get("ts")
        e["ts"] = ts.isoformat() if hasattr(ts, "isoformat") else ts
        entries.append(e)
    return jsonify(entries)


# ---------------------------------------------------------------------------
# User management
#   Super admin: full control over every account.
#   Department managers: create / reset-password / edit / remove the NORMAL and
#   SUPERVISOR staff of their own department(s) only.
# ---------------------------------------------------------------------------
MANAGER_MANAGEABLE_ROLES = ("normal", "supervisor")


def manager_or_admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ("admin", "manager"):
            return jsonify({"error": "Manager or admin access required"}), 403
        return f(*args, **kwargs)
    return wrapper


def manager_can_manage(actor, target_role, target_departments):
    """A manager may only manage normal/supervisor users whose department(s) all
    fall within the manager's own department(s)."""
    if actor["role"] == "admin":
        return True
    if actor["role"] != "manager":
        return False
    if target_role not in MANAGER_MANAGEABLE_ROLES:
        return False
    actor_depts = set(actor.get("departments", []) or [])
    tgt_depts = set(target_departments or [])
    return bool(tgt_depts) and tgt_depts.issubset(actor_depts)


@app.route('/api/users/list', methods=['GET'])
@login_required
def api_users_list():
    """Lightweight list for assignee dropdowns."""
    if mongo_users is None:
        return jsonify([])
    users = mongo_users.find({"active": True}, {"name": 1, "role": 1, "departments": 1})
    return jsonify([{"name": u["name"], "role": u.get("role", "normal"), "departments": u.get("departments", [])} for u in users])


@app.route('/api/me/password', methods=['POST'])
@login_required
def api_change_own_password():
    """Any signed-in user can change their own password."""
    data = request.json or {}
    current = data.get("current_password") or ""
    new = data.get("new_password") or ""
    if len(new) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400
    user = mongo_users.find_one({"_id": ObjectId(session["uid"])})
    if not user or not check_password_hash(user.get("password_hash", ""), current):
        return jsonify({"error": "Current password is incorrect"}), 400
    mongo_users.update_one({"_id": user["_id"]},
                           {"$set": {"password_hash": generate_password_hash(new), "must_change_password": False}})
    session["must_change"] = False
    log_activity("change_password", target_type="user", target_title=user.get("username"),
                 task_departments=user.get("departments", []), detail="Changed own password")
    return jsonify({"success": True})


@app.route('/api/users', methods=['GET'])
@manager_or_admin_required
def api_users():
    actor = current_user()
    if actor["role"] == "admin":
        cursor = mongo_users.find().sort("name", 1)
    else:
        depts = actor.get("departments", []) or []
        cursor = mongo_users.find({"departments": {"$in": depts}, "role": {"$ne": "admin"}}).sort("name", 1)
    users = []
    for u in cursor:
        users.append({
            "id": str(u["_id"]),
            "username": u.get("username"),
            "name": u.get("name"),
            "role": u.get("role"),
            "actual_role": u.get("actual_role", ""),
            "departments": u.get("departments", []),
            "active": u.get("active", True),
        })
    return jsonify(users)


@app.route('/api/users', methods=['POST'])
@manager_or_admin_required
def api_create_user():
    actor = current_user()
    data = request.json or {}
    username = (data.get("username") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""
    role = data.get("role", "normal")
    actual_role = data.get("actual_role", "")
    departments = data.get("departments", [])
    if not username or not name or not password:
        return jsonify({"error": "Username, name and password are required"}), 400
    if role not in ROLES:
        return jsonify({"error": "Invalid role"}), 400
    if not manager_can_manage(actor, role, departments):
        return jsonify({"error": "Managers can only create normal/supervisor staff within their own department(s)"}), 403
    if mongo_users.find_one({"username": username}):
        return jsonify({"error": "Username already exists"}), 409
    mongo_users.insert_one({
        "username": username,
        "name": name,
        "password_hash": generate_password_hash(password),
        "role": role,
        "actual_role": actual_role,
        "departments": departments,
        "active": True,
        "must_change_password": True,   # staff must replace the handed-out password on first login
        "created_at": datetime.utcnow(),
    })
    log_activity("create_user", target_type="user", target_title=username,
                 task_departments=departments, detail=f"Created user {name} ({role})")
    return jsonify({"success": True})


@app.route('/api/users/<user_id>', methods=['PUT'])
@manager_or_admin_required
def api_update_user(user_id):
    actor = current_user()
    target = mongo_users.find_one({"_id": ObjectId(user_id)})
    if not target:
        return jsonify({"error": "User not found"}), 404

    data = request.json or {}
    update = {}
    for field in ["name", "role", "actual_role", "departments", "active", "username"]:
        if field in data:
            if field == "username":
                new_username = data[field].strip().lower()
                if not new_username:
                    return jsonify({"error": "Username cannot be empty"}), 400
                if new_username != target.get("username"):
                    if mongo_users.find_one({"username": new_username}):
                        return jsonify({"error": "Username already exists"}), 409
                update[field] = new_username
            else:
                update[field] = data[field]
    if update.get("role") and update["role"] not in ROLES:
        return jsonify({"error": "Invalid role"}), 400

    # A manager may only touch manageable users in their department, and may not
    # promote anyone to manager/admin or move them outside their department.
    if actor["role"] != "admin":
        if not manager_can_manage(actor, target.get("role"), target.get("departments")):
            return jsonify({"error": "You can only manage staff in your own department"}), 403
        new_role = update.get("role", target.get("role"))
        new_depts = update.get("departments", target.get("departments"))
        if not manager_can_manage(actor, new_role, new_depts):
            return jsonify({"error": "Managers can only assign normal/supervisor roles within their own department(s)"}), 403

    if data.get("password"):
        update["password_hash"] = generate_password_hash(data["password"])
        # A reset password is temporary: the user must set their own on next login
        # (unless an admin is resetting their own account).
        if user_id != session.get("uid"):
            update["must_change_password"] = True

    # Guard against demoting / disabling yourself out of admin.
    if (update.get("role") and update["role"] != "admin") or (update.get("active") is False):
        if user_id == session.get("uid"):
            return jsonify({"error": "You cannot demote or deactivate your own account"}), 400

    if update:
        mongo_users.update_one({"_id": ObjectId(user_id)}, {"$set": update})
        refreshed = mongo_users.find_one({"_id": ObjectId(user_id)}) or {}
        detail = "Reset password for " + refreshed.get("name", user_id) if data.get("password") and len(update) == 1 else f"Updated user {refreshed.get('name', user_id)}"
        log_activity("edit_user", target_type="user", target_title=refreshed.get("username"),
                     task_departments=refreshed.get("departments", []), detail=detail)
    return jsonify({"success": True})


@app.route('/api/users/<user_id>', methods=['DELETE'])
@manager_or_admin_required
def api_delete_user(user_id):
    actor = current_user()
    if user_id == session.get("uid"):
        return jsonify({"error": "You cannot delete your own account"}), 400
    target = mongo_users.find_one({"_id": ObjectId(user_id)})
    if not target:
        return jsonify({"error": "User not found"}), 404
    if actor["role"] != "admin" and not manager_can_manage(actor, target.get("role"), target.get("departments")):
        return jsonify({"error": "You can only remove staff in your own department"}), 403
    mongo_users.delete_one({"_id": ObjectId(user_id)})
    log_activity("delete_user", target_type="user", target_title=target.get("username"),
                 task_departments=target.get("departments", []),
                 detail=f"Deleted user {target.get('name', user_id)}")
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Handovers
# ---------------------------------------------------------------------------
@app.route('/api/handovers', methods=['GET'])
@login_required
def get_handovers():
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500

    task_date_str = request.args.get('date', date.today().isoformat())
    include_overdue = request.args.get('include_overdue', 'false').lower() == 'true'

    try:
        if " to " in task_date_str:
            query_start, query_end = task_date_str.split(" to ")
        else:
            query_start = task_date_str
            query_end = task_date_str

        base_query = {
            "$or": [
                {"start_date": {"$lte": query_end}, "end_date": {"$gte": query_start}},
                {"task_date": {"$gte": query_start, "$lte": query_end} if " to " in task_date_str else task_date_str},
            ]
        }

        if include_overdue:
            overdue_query = {
                "status": {"$ne": "Completed"},
                "$or": [
                    {"end_date": {"$lt": query_start}},
                    {"task_date": {"$lt": query_start}, "end_date": {"$exists": False}},
                ],
            }
            query = {"$or": [base_query, overdue_query]}
        else:
            query = base_query
            
        view_deleted = request.args.get('view_deleted', 'false').lower() == 'true'
        if view_deleted:
            query["is_deleted"] = True
        else:
            query["is_deleted"] = {"$ne": True}

        tasks_cursor = mongo_tasks.find(query).sort("created_at", -1)
        tasks = []
        for t in tasks_cursor:
            t["id"] = str(t["_id"])
            t.pop("_id", None)
            t_end = t.get("end_date") or t.get("task_date", "")
            t["is_overdue"] = (t_end < query_start) and (t.get("status") != "Completed")
            tasks.append(t)
        return jsonify(tasks)
    except Exception as e:
        logger.error(f"MongoDB Fetch Error: {e}")
        return jsonify({"error": "Failed to fetch tasks"}), 500


@app.route('/api/handovers', methods=['POST'])
@login_required
def add_handover():
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500

    user = current_user()
    data = request.json
    task_date = data.get('task_date', date.today().isoformat())
    title = data.get('title')

    if " to " in task_date:
        start_date, end_date = task_date.split(" to ")
    else:
        start_date = task_date
        end_date = task_date

    if not title:
        return jsonify({"error": "Title is required"}), 400

    try:
        task = {
            "task_date": task_date,
            "start_date": start_date,
            "end_date": end_date,
            "title": title,
            "department": data.get("department"),
            "priority": data.get("priority", "Normal"),
            "status": data.get("status", "Pending"),
            "assigned_to": data.get("assigned_to"),
            "created_by": user["name"],        # authenticated author, not free text
            "created_by_id": user["id"],
            "completed_by": data.get("completed_by"),
            "comment": data.get("comment"),
            "photo": data.get("photo"),
            "comments": [],
            "created_at": datetime.utcnow(),
        }
        result = mongo_tasks.insert_one(task)
        log_activity("create_task", target_type="task", target_id=result.inserted_id,
                     target_title=title, task_departments=data.get("department"),
                     detail="Created handover")
        return jsonify({"success": True, "id": str(result.inserted_id)})
    except Exception as e:
        logger.error(f"Error inserting task: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/handovers/<task_id>', methods=['PUT'])
@login_required
def update_handover(task_id):
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500

    user = current_user()
    query_id = resolve_task_id(task_id)
    task = mongo_tasks.find_one({"_id": query_id}) or (mongo_tasks.find_one({"id": query_id}) if isinstance(query_id, int) else None)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    data = request.json or {}
    update_data = {}
    for field in ['task_date', 'title', 'created_by', 'assigned_to', 'comment', 'department', 'status', 'priority', 'completed_by', 'photo']:
        if field in data:
            update_data[field] = data[field]
            if field == 'task_date':
                if " to " in data[field]:
                    update_data['start_date'], update_data['end_date'] = data[field].split(" to ")
                else:
                    update_data['start_date'] = data[field]
                    update_data['end_date'] = data[field]

    if not update_data:
        return jsonify({"success": True})

    # A status-only change (the quick dropdown) is allowed for any logged-in user.
    # Broader edits require supervisor+ or being the task's creator.
    status_only = set(update_data.keys()) <= {"status", "completed_by", "start_date", "end_date"}
    if not status_only and not can_edit_task(user, task):
        return jsonify({"error": "You don't have permission to edit this task"}), 403

    # Never let a client overwrite the authenticated creator.
    update_data.pop("created_by", None)

    # Auto-stamp who completed it.
    if update_data.get("status") == "Completed" and not update_data.get("completed_by") and not task.get("completed_by"):
        update_data["completed_by"] = user["name"]

    try:
        result = mongo_tasks.update_one({"_id": query_id}, {"$set": update_data})
        if result.matched_count == 0 and isinstance(query_id, int):
            mongo_tasks.update_one({"id": query_id}, {"$set": update_data})

        if "status" in update_data and status_only:
            detail = f"Changed status to {update_data['status']}"
        elif "status" in update_data:
            detail = f"Edited handover (status → {update_data['status']})"
        else:
            detail = "Edited handover"
        log_activity("status_change" if status_only else "edit_task", target_type="task",
                     target_id=task_id, target_title=task.get("title"),
                     task_departments=update_data.get("department", task.get("department")),
                     detail=detail)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"MongoDB Update Error: {e}")
        return jsonify({"error": "Failed to update task"}), 500


@app.route('/api/handovers/<task_id>', methods=['DELETE'])
@login_required
def delete_handover(task_id):
    if rank(session.get("role")) < rank("supervisor"):
        return jsonify({"error": "Delete access required"}), 403
    
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500
    query_id = resolve_task_id(task_id)
    task = mongo_tasks.find_one({"_id": query_id}) or (mongo_tasks.find_one({"id": query_id}) if isinstance(query_id, int) else None)
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
        
    try:
        user = current_user()
        update_data = {
            "$set": {
                "is_deleted": True,
                "deleted_by": user["name"],
                "deleted_at": datetime.utcnow().isoformat()
            }
        }
        result = mongo_tasks.update_one({"_id": query_id}, update_data)
        if result.matched_count == 0 and isinstance(query_id, int):
            mongo_tasks.update_one({"id": query_id}, update_data)
            
        log_activity("delete_task", target_type="task", target_id=task_id,
                     target_title=(task or {}).get("title"), task_departments=(task or {}).get("department"),
                     detail="Deleted handover")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"MongoDB Delete Error: {e}")
        return jsonify({"error": "Failed to delete task"}), 500

@app.route('/api/handovers/<task_id>/undo-delete', methods=['POST'])
@login_required
def undo_delete_handover(task_id):
    if rank(session.get("role")) < rank("supervisor"):
        return jsonify({"error": "Access denied"}), 403
    
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500
    query_id = resolve_task_id(task_id)
    task = mongo_tasks.find_one({"_id": query_id}) or (mongo_tasks.find_one({"id": query_id}) if isinstance(query_id, int) else None)
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
        
    try:
        update_data = {
            "$unset": {
                "is_deleted": "",
                "deleted_by": "",
                "deleted_at": ""
            }
        }
        result = mongo_tasks.update_one({"_id": query_id}, update_data)
        if result.matched_count == 0 and isinstance(query_id, int):
            mongo_tasks.update_one({"id": query_id}, update_data)
            
        log_activity("undo_delete_task", target_type="task", target_id=task_id,
                     target_title=(task or {}).get("title"), task_departments=(task or {}).get("department"),
                     detail="Restored deleted handover")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"MongoDB Undo Delete Error: {e}")
        return jsonify({"error": "Failed to restore task"}), 500


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
@app.route('/api/handovers/<task_id>/comments', methods=['POST'])
@login_required
def add_comment(task_id):
    if mongo_tasks is None:
        return jsonify({"error": "DB not connected"}), 500
    try:
        user = current_user()
        data = request.json or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"error": "Text is required"}), 400
        new_comment = {
            "author": user["name"],
            "text": text,
            "timestamp": datetime.utcnow().isoformat(),
        }
        qid = resolve_task_id(task_id)
        task = mongo_tasks.find_one({"_id": qid})
        mongo_tasks.update_one({"_id": qid}, {"$push": {"comments": new_comment}})
        log_activity("comment", target_type="task", target_id=task_id,
                     target_title=(task or {}).get("title"), task_departments=(task or {}).get("department"),
                     detail=f"Commented: {text[:80]}")
        return jsonify(new_comment), 201
    except Exception as e:
        logger.error(f"Error adding comment: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/handovers/<task_id>/comments/<timestamp>', methods=['DELETE'])
@login_required
def delete_comment(task_id, timestamp):
    if mongo_tasks is None:
        return jsonify({"error": "DB not connected"}), 500
    try:
        user = current_user()
        obj_id = resolve_task_id(task_id)
        task = mongo_tasks.find_one({"_id": obj_id})
        comment = next((c for c in (task or {}).get("comments", []) if c.get("timestamp") == timestamp), None) if task else None
        if not comment:
            return jsonify({"error": "Comment not found"}), 404
        # Only the author or an admin may remove a comment.
        if user["role"] != "admin" and comment.get("author") != user["name"]:
            return jsonify({"error": "Not allowed"}), 403
        mongo_tasks.update_one({"_id": obj_id}, {"$pull": {"comments": {"timestamp": timestamp}}})
        return jsonify({"success": True}), 200
    except Exception as e:
        logger.error(f"Error deleting comment: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    if mongo_tasks is None:
        return jsonify([])
    try:
        pipeline = [
            {"$unwind": "$comments"},
            {"$sort": {"comments.timestamp": -1}},
            {"$limit": 30},
            {"$project": {
                "_id": 0,
                "task_id": {"$toString": "$_id"},
                "title": 1,
                "task_date": 1,
                "author": "$comments.author",
                "text": "$comments.text",
                "timestamp": "$comments.timestamp",
            }},
        ]
        return jsonify(list(mongo_tasks.aggregate(pipeline)))
    except Exception as e:
        logger.error(f"Error fetching notifications: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(port=5001, debug=True)
