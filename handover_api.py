from flask import Flask, render_template, request, jsonify
import pymongo
from bson.objectid import ObjectId
from datetime import datetime, date
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB Configuration
MONGO_URI = "mongodb+srv://jayeetrab:mGhnfdMwFeFZwx6L@cohortconnect.lcpylgn.mongodb.net/"
try:
    mongo_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_db = mongo_client["Reservations"]
    mongo_tasks = mongo_db["tasks"]
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    mongo_tasks = None

def get_mongo_id(task_id_str):
    try:
        return ObjectId(task_id_str)
    except:
        return task_id_str

@app.route('/')
def index():
    return render_template('handover.html')

@app.route('/api/handovers', methods=['GET'])
def get_handovers():
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500

    task_date_str = request.args.get('date', date.today().isoformat())
    
    try:
        if " to " in task_date_str:
            start_date, end_date = task_date_str.split(" to ")
            query = {"task_date": {"$gte": start_date, "$lte": end_date}}
        else:
            query = {"task_date": task_date_str}

        tasks_cursor = mongo_tasks.find(query).sort("created_at", -1)
        tasks = []
        for t in tasks_cursor:
            # Map ObjectId to string
            t["id"] = str(t["_id"])
            t.pop("_id", None)
            tasks.append(t)
        return jsonify(tasks)
    except Exception as e:
        logger.error(f"MongoDB Fetch Error: {e}")
        return jsonify({"error": "Failed to fetch tasks"}), 500

@app.route('/api/handovers', methods=['POST'])
def add_handover():
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500

    data = request.json
    task_date = data.get('task_date', date.today().isoformat())
    title = data.get('title')
    created_by = data.get('created_by', '')
    assigned_to = data.get('assigned_to', '')
    comment = data.get('comment', '')
    department = data.get('department', 'Other')
    status = data.get('status', 'Pending')
    priority = data.get('priority', 'Normal')
    completed_by = data.get('completed_by', '')
    
    if not title:
        return jsonify({"error": "Title is required"}), 400
        
    try:
        result = mongo_tasks.insert_one({
            "task_date": task_date,
            "title": title,
            "created_by": created_by,
            "assigned_to": assigned_to,
            "comment": comment,
            "department": department,
            "status": status,
            "priority": priority,
            "completed_by": completed_by,
            "created_at": datetime.now().isoformat()
        })
        task_id = str(result.inserted_id)
        return jsonify({"success": True, "id": task_id})
    except Exception as e:
        logger.error(f"MongoDB Insert Error: {e}")
        return jsonify({"error": "Failed to insert task"}), 500

@app.route('/api/handovers/<task_id>', methods=['PUT'])
def update_handover(task_id):
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500

    data = request.json
    
    # Check if task_id is a legacy integer or an ObjectId
    query_id = None
    if task_id.isdigit():
        query_id = int(task_id)
    else:
        query_id = get_mongo_id(task_id)
        
    update_data = {}
    for field in ['title', 'created_by', 'assigned_to', 'comment', 'department', 'status', 'priority', 'completed_by']:
        if field in data:
            update_data[field] = data[field]
            
    if not update_data:
        return jsonify({"success": True})
        
    try:
        # Fallback check for legacy 'id' field if ObjectId fails
        result = mongo_tasks.update_one(
            {"_id": query_id},
            {"$set": update_data}
        )
        if result.matched_count == 0 and type(query_id) == int:
            # Maybe it's stored with field 'id' instead of _id
            mongo_tasks.update_one({"id": query_id}, {"$set": update_data})
            
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"MongoDB Update Error: {e}")
        return jsonify({"error": "Failed to update task"}), 500

@app.route('/api/handovers/<task_id>', methods=['DELETE'])
def delete_handover(task_id):
    if mongo_tasks is None:
        return jsonify({"error": "Database connection failed"}), 500

    query_id = None
    if task_id.isdigit():
        query_id = int(task_id)
    else:
        query_id = get_mongo_id(task_id)
        
    try:
        result = mongo_tasks.delete_one({"_id": query_id})
        if result.deleted_count == 0 and type(query_id) == int:
            mongo_tasks.delete_one({"id": query_id})
            
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"MongoDB Delete Error: {e}")
        return jsonify({"error": "Failed to delete task"}), 500

if __name__ == '__main__':
    app.run(port=5001, debug=True)
