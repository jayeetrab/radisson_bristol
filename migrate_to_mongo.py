import sqlite3
import pymongo
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    # Connect to MongoDB
    mongo_client = pymongo.MongoClient("mongodb+srv://jayeetrab:mGhnfdMwFeFZwx6L@cohortconnect.lcpylgn.mongodb.net/")
    db = mongo_client["Reservations"]
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect("hotel_fo.db")
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.cursor()
    
    tables = [
        "hsk_task_status", "payments", "spare_rooms",
        "invoices", "reservations", "stays",
        "no_shows", "rooms", "tasks"
    ]
    
    for table in tables:
        logger.info(f"Migrating table: {table}")
        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        
        if not rows:
            logger.info(f"Table {table} is empty, skipping.")
            continue
            
        docs = [dict(row) for row in rows]
        
        # Clear existing collection
        db[table].drop()
        
        # Insert all documents
        result = db[table].insert_many(docs)
        logger.info(f"Inserted {len(result.inserted_ids)} documents into {table}")

    sqlite_conn.close()
    logger.info("Migration complete!")

if __name__ == "__main__":
    migrate()
