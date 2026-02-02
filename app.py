import os
from glob import glob
from datetime import date, datetime, timedelta
from io import BytesIO
import pandas as pd
import streamlit as st
import sqlite3
from contextlib import closing
import time


# Initialize database AFTER set_page_config in main()
db = None


def format_date(date_str):
    """Format date string, removing time portion"""
    if not date_str:
        return ''
    try:
        # Parse the datetime string
        dt = datetime.fromisoformat(str(date_str))
        # Return formatted date (e.g., "15 January 2026")
        return dt.strftime("%d %B %Y")
    except (ValueError, TypeError):
        # Fallback: just remove time if simple string
        return str(date_str).split()[0] if ' ' in str(date_str) else str(date_str)
    
    
def format_room_number(room_number):
    """Format room number, removing .0 decimals"""
    if not room_number:
        return ''
    try:
        num = float(room_number)
        if num.is_integer():
            return str(int(num))
        return str(num)
    except (ValueError, TypeError):
        return str(room_number)


def clean_numeric_columns(df: pd.DataFrame, cols: list):
    """Convert numeric columns to whole numbers for display"""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: int(float(x)) if pd.notna(x) and str(x) not in ['', 'None', 'nan'] else x
            )
    return df


# PostgreSQL configuration
TEST_MODE = False  # set False for live system

if TEST_MODE:
    DBPATH = "hotelfoTEST.db"
    ARRIVALS_ROOT = "data/arrivals-test"
else:
    DBPATH = "hotelfo.db"
    ARRIVALS_ROOT = "data/arrivals"

       

# Fixed room inventory blocks: inclusive ranges (whole numbers)
ROOM_BLOCKS = [
    (100, 115),
    (300, 313),
    (400, 413),
    (500, 513),
    (600, 613),
    (700, 709),
    (800, 809),
    (900, 909),
    (1000, 1009),
    (1100, 1109),
    (1200, 1209),
    (1300, 1309),
    (1400, 1409),
    (1500, 1509),
    (1600, 1609),
    (1700, 1705),
]


def clean_numeric_columns(df: pd.DataFrame, cols: list):
    """Convert numeric columns to whole numbers for display"""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: int(float(x)) if pd.notna(x) and str(x).strip() not in ['', 'None'] else x)
    return df

class FrontOfficeDB:
    def init_db(self):
            with closing(self.get_conn()) as conn, conn:
                c = conn.cursor()
                c.execute("""
                    CREATE TABLE IF NOT EXISTS reservations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        amount_pending REAL,
                        arrival_date TEXT,
                        depart_date TEXT,
                        room_number TEXT,
                        room_type_code TEXT,
                        adults INTEGER,
                        children INTEGER,
                        total_guests INTEGER,
                        reservation_no TEXT,
                        front_office_notes TEXT,
                        voucher TEXT,
                        related_reservation TEXT,
                        crs_code TEXT,
                        crs_name TEXT,
                        guest_id_raw TEXT,
                        guest_name TEXT,
                        vip_flag TEXT,
                        client_id TEXT,
                        main_client TEXT,
                        nights INTEGER,
                        meal_plan TEXT,
                        rate_code TEXT,
                        channel TEXT,
                        cancellation_policy TEXT,
                        main_remark TEXT,
                        contact_name TEXT,
                        contact_phone TEXT,
                        contact_email TEXT,
                        total_remarks TEXT,
                        source_of_business TEXT,
                        stay_option_desc TEXT,
                        remarks_by_chain TEXT,
                        reservation_group_id TEXT,
                        reservation_group_name TEXT,
                        company_name TEXT,
                        company_id_raw TEXT,
                        country TEXT,
                        reservation_status TEXT DEFAULT 'CONFIRMED',
                        created_at TEXT DEFAULT (datetime('now')),
                        updated_at TEXT DEFAULT (datetime('now'))
                    )
                """)

                c.execute("""
                    CREATE TABLE IF NOT EXISTS stays (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        reservation_id INTEGER,
                        room_number TEXT,
                        status TEXT DEFAULT 'EXPECTED',
                        checkin_planned TEXT,
                        checkout_planned TEXT,
                        checkin_actual TEXT,
                        checkout_actual TEXT,
                        breakfast_code TEXT,
                        comment TEXT,
                        parking_space TEXT,
                        parking_plate TEXT,
                        parking_notes TEXT,
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id)
                    )
                """)
                # Safe migration: add front_office_notes if missing
                try:
                    c.execute("ALTER TABLE reservations ADD COLUMN front_office_notes TEXT")
                except sqlite3.OperationalError:
                    # Column already exists
                    pass

                c.execute("""
                    CREATE TABLE IF NOT EXISTS rooms (
                        room_number TEXT PRIMARY KEY,
                        room_type TEXT,
                        floor INTEGER,
                        status TEXT DEFAULT 'VACANT',
                        is_twin INTEGER DEFAULT 0
                    )
                """)

                c.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_date TEXT,
                        title TEXT,
                        created_by TEXT,
                        assigned_to TEXT,
                        comment TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)

                c.execute("""
                    CREATE TABLE IF NOT EXISTS no_shows (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        arrival_date TEXT,
                        guest_name TEXT,
                        main_client TEXT,
                        charged INTEGER,
                        amount_charged REAL,
                        amount_pending REAL,
                        comment TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                
                c.execute('''
                    CREATE TABLE IF NOT EXISTS invoices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        invoice_no INTEGER UNIQUE,
                        reservation_id INTEGER,
                        guest_name TEXT,
                        room_number TEXT,
                        total_net REAL,
                        total_vat REAL,
                        total_amount REAL,
                        invoice_date TEXT,
                        created_at TEXT DEFAULT (datetime('now')),
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id)
                    )
                ''')


                # Safe migrations: add missing columns if DB is older
                try:
                    c.execute("ALTER TABLE no_shows ADD COLUMN amount_charged REAL")
                except sqlite3.OperationalError:
                    pass

                try:
                    c.execute("ALTER TABLE no_shows ADD COLUMN amount_pending REAL")
                except sqlite3.OperationalError:
                    pass

                c.execute("""
                    CREATE TABLE IF NOT EXISTS payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        reservation_id INTEGER,
                        guest_name TEXT,
                        amount REAL,
                        type TEXT,               -- PAYMENT or REFUND
                        method TEXT,             -- card / cash / etc.
                        reference TEXT,          -- PMS folio ref, POS ref
                        note TEXT,
                        created_at TEXT DEFAULT (datetime('now')),
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id)
                    )
                """)


                c.execute("""
                    CREATE TABLE IF NOT EXISTS spare_rooms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        target_date TEXT,
                        room_number TEXT
                    )
                """)
                c.execute("""
    CREATE TABLE IF NOT EXISTS hsk_task_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_date TEXT,
        room_number TEXT,
        task_type TEXT,
        status TEXT DEFAULT 'PENDING',
        notes TEXT,
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(task_date, room_number, task_type)
    )
""")
    def update_stay_comment(self, stay_id: int, comment: str):
        """Update in-house stay comment (front office notes)."""
        self.execute(
            "UPDATE stays SET comment = ? WHERE id = ?",
            (comment, stay_id),
        )

    def add_payment(self, reservation_id: int, guest_name: str, amount: float,
                    pay_type: str, method: str, reference: str, note: str):
        self.execute(
            """
            INSERT INTO payments (reservation_id, guest_name, amount, type, method, reference, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (reservation_id, guest_name, amount, pay_type, method, reference, note),
        )

    def is_room_clean(self, room_number: str) -> bool:
        """Return True if room exists and status is not DIRTY."""
        row = self.fetch_one(
            "SELECT status FROM rooms WHERE room_number = ?",
            (room_number.strip(),),
        )
        if not row:
            # if room not found, keep existing validation behaviour elsewhere
            return True
        return row["status"] != "DIRTY"

    def get_next_invoice_number(self) -> int:
        """Get next auto-incremented invoice number starting from 254000"""
        result = self.fetch_one("SELECT MAX(id) as max_id FROM invoices")
        if result and result['max_id']:
            return 254000 + result['max_id']
        return 254000
    
    def get_guests_for_date(self, d: date):
        """Get all guests with reservations for a specific date"""
        return self.fetch_all(
            """
            SELECT DISTINCT
                r.id,
                r.guest_name,
                r.room_number,
                r.reservation_no,
                r.arrival_date,
                r.depart_date,
                r.amount_pending
            FROM reservations r
            WHERE date(r.arrival_date) <= date(?)
            AND date(r.depart_date) > date(?)
            AND r.reservation_status NOT IN ('NO_SHOW', 'CANCELLED')
            ORDER BY r.guest_name
            """,
            (d.isoformat(), d.isoformat()),
        )

    def update_reservation_mealplan(self, reservation_id: int, meal_plan: str):
        """Update meal plan for a reservation (e.g., add breakfast)."""
        print(f"MEAL PLAN: {meal_plan}")
        self.execute(
            "UPDATE reservations SET meal_plan = ?, updated_at = datetime('now') WHERE id = ?",
            (meal_plan, reservation_id),
        )

    def get_reservation_by_guest_and_date(self, guest_name: str, d: date):
        """Get reservation details for a specific guest on a date"""
        return self.fetch_one(
            """
            SELECT *
            FROM reservations
            WHERE guest_name = ?
            AND date(arrival_date) <= date(?)
            AND date(depart_date) > date(?)
            AND reservation_status NOT IN ('NO_SHOW', 'CANCELLED')
            LIMIT 1
            """,
            (guest_name, d.isoformat(), d.isoformat()),
        )

    def get_payments_for_reservation(self, reservation_id: int):
        return self.fetch_all(
            """
            SELECT * FROM payments
            WHERE reservation_id = ?
            ORDER BY created_at DESC
            """,
            (reservation_id,),
        )

    def get_all_payments(self, limit: int = 500):
        return self.fetch_all(
            """
            SELECT p.*, r.arrival_date, r.depart_date, r.room_number, r.main_client
            FROM payments p
            LEFT JOIN reservations r ON p.reservation_id = r.id
            ORDER BY p.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def __init__(self, dbpath: str):
        self.dbpath = dbpath
        self.init_db()
        if self.reservations_empty():
            self.import_all_arrivals_from_fs()
            self.seed_rooms_from_blocks()
            self.sync_room_status_from_stays()
    def get_hsk_task_status(self, task_date: date, room_number: str, task_type: str):
        return self.fetch_one(
            "SELECT status, notes FROM hsk_task_status WHERE task_date = ? AND room_number = ? AND task_type = ?",
            (task_date.isoformat(), room_number, task_type)
        )
# helpers
    def move_checked_in_guest(self, stay_id: int, new_room: str):
        """Move a checked-in guest to a different room (updates stays, reservations, rooms)."""
        stay = self.fetch_one("SELECT * FROM stays WHERE id = ?", (stay_id,))
        if not stay:
            return False, "Stay not found"

        res = self.fetch_one("SELECT * FROM reservations WHERE id = ?", (stay["reservation_id"],))
        if not res:
            return False, "Reservation not found"

        old_room = stay["room_number"]

        isvalid, normalized = self.is_valid_room_number(new_room)
        if not isvalid:
            return False, normalized

        arr = datetime.fromisoformat(res["arrival_date"]).date()
        dep = datetime.fromisoformat(res["depart_date"]).date()

        available, msg = self.check_room_available_for_assignment(normalized, arr, dep, res["id"])
        if not available:
            return False, msg

        with closing(self.get_conn()) as conn, conn:
            c = conn.cursor()

            # Update stay
            c.execute(
                "UPDATE stays SET room_number = ? WHERE id = ?",
                (normalized, stay["id"]),
            )

            # Update reservation
            c.execute(
                "UPDATE reservations SET room_number = ?, updated_at = datetime('now') WHERE id = ?",
                (normalized, res["id"]),
            )

            # Free old room, occupy new room
            c.execute("UPDATE rooms SET status = 'VACANT' WHERE room_number = ?", (old_room,))
            c.execute("INSERT OR IGNORE INTO rooms (room_number, status) VALUES (?, 'OCCUPIED')", (normalized,))
            c.execute("UPDATE rooms SET status = 'OCCUPIED' WHERE room_number = ?", (normalized,))

        return True, f"Guest moved from {old_room} to {normalized}"

    def update_reservation_notes(self, reservation_id: int, main_remark: str, total_remarks: str = ""):
        """Update Front Office notes for a reservation."""
        self.execute(
            """
            UPDATE reservations
            SET main_remark = ?,
                total_remarks = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (main_remark, total_remarks, reservation_id),
        )


    def mark_reservation_as_no_show(
        self,
        reservation_id: int,
        arrival_date: date,
        guest_name: str,
        main_client: str,
        charged: bool = False,
        amount_charged: float = 0.0,
        amount_pending: float = 0.0,
        comment: str = "",
    ):
        charged_int = 1 if charged else 0
        amount_charged = amount_charged or 0.0
        amount_pending = amount_pending or 0.0

        # 1) Upsert into no_shows
        self.execute(
            """
            INSERT INTO no_shows (
                arrival_date,
                guest_name,
                main_client,
                charged,
                amount_charged,
                amount_pending,
                comment
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                arrival_date.isoformat(),
                guest_name,
                main_client,
                charged_int,
                amount_charged,
                amount_pending,
                comment,
            ),
        )

        # 2) Mark reservation as NO_SHOW so it is excluded from arrivals
        self.execute(
            """
            UPDATE reservations
            SET reservation_status = 'NO_SHOW',
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (reservation_id,),
        )

    def update_hsk_task_status(self, task_date: date, room_number: str, task_type: str, status: str, notes: str = ""):
        self.execute(
            """
            INSERT INTO hsk_task_status (task_date, room_number, task_type, status, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(task_date, room_number, task_type)
            DO UPDATE SET status = ?, notes = ?, updated_at = datetime('now')
            """,
            (task_date.isoformat(), room_number, task_type, status, notes, status, notes)
        )
    def search_reservations_by_room_number(self, room_number: str):
        return self.fetch_all(
            """
            SELECT *
            FROM reservations
            WHERE room_number = ?
            ORDER BY arrival_date DESC
            LIMIT 500
            """,
            (room_number.strip(),),
        )



    def get_potential_no_shows(self, d: date):
        """Get arrivals who didn't check in - potential no-shows"""
        return self.fetch_all(
            """
            SELECT r.id, r.guest_name, r.reservation_no, r.main_client, r.room_number
            FROM reservations r
            WHERE date(r.arrival_date) = date(?)
            AND NOT EXISTS (
                SELECT 1 FROM stays s
                WHERE s.reservation_id = r.id
                    AND s.status = 'CHECKED_IN'
            )
            ORDER BY r.guest_name
            """,
            (d.isoformat(),),
        )


    def get_conn(self):
            conn = sqlite3.connect(self.dbpath, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

    def execute(self, query, params=None):
        with closing(self.get_conn()) as conn, conn:
            c = conn.cursor()
            if params is None:
                c.execute(query)
            else:
                c.execute(query, params)
            return c

    def fetch_all(self, query, params=None):
        with closing(self.get_conn()) as conn:
            c = conn.cursor()
            if params is None:
                c.execute(query)
            else:
                c.execute(query, params)
            rows = c.fetchall()
            return [dict(row) for row in rows]

    def fetch_one(self, query, params=None):
        with closing(self.get_conn()) as conn:
            c = conn.cursor()
            if params is None:
                c.execute(query)
            else:
                c.execute(query, params)
            row = c.fetchone()
            return dict(row) if row else None


    def get_breakfast_list_for_date(self, target_date: date):
        return self.fetch_all(
            """
            SELECT
                s.room_number      AS room_number,
                r.guest_name       AS guest_name,
                r.adults          AS adults,
                r.children        AS children,
                r.total_guests     AS total_guests,
                r.meal_plan        AS meal_plan
            FROM stays AS s
            JOIN reservations AS r
            ON r.id = s.reservation_id
            WHERE s.status = 'CHECKED_IN'
            AND date(s.checkin_planned) <= date(?)
            AND date(s.checkout_planned) >= date(?)
            AND r.room_number IS NOT NULL
            AND r.room_number != ''
            AND (
                r.meal_plan = 'BB'
                OR r.meal_plan LIKE '%BB%'
                OR lower(r.meal_plan) LIKE '%breakfast%'
            )
            ORDER BY CAST(s.room_number AS INTEGER)
            """,
            (target_date.isoformat(), target_date.isoformat()),
        )



    def generate_hsk_tasks_for_date(self, target_date: date):
        """Auto-generate housekeeping tasks for the day"""
        tasks = []
        
        conn = self.get_conn()
        c = conn.cursor()
        
        try:
            # Use LIKE to match the date portion of timestamp
            target_str = target_date.isoformat()  # e.g., "2026-08-16"
            
            # 1. Checkouts
            # 1. Checkouts - ALL guests departing today (checked in OR checked out)
            c.execute("""
                SELECT s.room_number, r.guest_name, r.main_remark, r.total_remarks, s.status
                FROM stays s
                JOIN reservations r ON r.id = s.reservation_id
                WHERE s.checkout_planned LIKE ?
                AND s.room_number IS NOT NULL AND s.room_number != ''
                ORDER BY 
                    CASE WHEN s.status = 'CHECKED_OUT' THEN 0 ELSE 1 END,
                    CAST(s.room_number AS INTEGER)
            """, (f"{target_date.isoformat()}%",))

            checkouts = c.fetchall()

            for co in checkouts:
                co_dict = dict(co)
                room = co_dict["room_number"]
                guest = co_dict["guest_name"]
                
                # Mark already checked-out rooms as URGENT
                if co_dict.get("status") == "CHECKED_OUT":
                    priority = "URGENT"
                else:
                    priority = "HIGH"
                
                task = {
                    "room": room,
                    "tasktype": "CHECKOUT",
                    "priority": priority,
                    "description": f"Clean room {room} - {guest} checkout",
                    "notes": []
                }
                
                remarks = f"{co_dict.get('main_remark') or ''} {co_dict.get('total_remarks') or ''}".lower()
                if '2t' in remarks:
                    task["notes"].append("2 TWIN BEDS")
                if 'vip' in remarks or 'birthday' in remarks:
                    task["priority"] = "URGENT"
                    task["notes"].append("VIP/SPECIAL")
                
                # Add note if already checked out
                if co_dict.get("status") == "CHECKED_OUT":
                    task["notes"].append("✓ CHECKED OUT - CLEAN NOW")
                
                tasks.append(task)

            
            # 2. Stayovers
            c.execute("""
                SELECT DISTINCT s.room_number, r.guest_name
                FROM stays s
                JOIN reservations r ON r.id = s.reservation_id
                WHERE s.status = 'CHECKED_IN'
                AND s.checkin_planned LIKE ?
                AND s.checkout_planned LIKE ?
                ORDER BY CAST(s.room_number AS INTEGER)
            """, (f"%{target_str.split('-')[0]}-{target_str.split('-')[1]}%", 
                f"%{target_str.split('-')[0]}-{target_str.split('-')[1]}%"))
            
            stayovers = c.fetchall()
            
            for so in stayovers:
                so_dict = dict(so)
                tasks.append({
                    "room": so_dict["room_number"],
                    "tasktype": "STAYOVER",
                    "priority": "MEDIUM",
                    "description": f"Refresh room {so_dict['room_number']} - {so_dict['guest_name']} stayover",
                    "notes": []
                })
            
            # 3. Arrivals
            c.execute("""
                SELECT r.room_number, r.guest_name, r.main_remark, r.total_remarks
                FROM reservations r
                WHERE r.arrival_date LIKE ?
                AND r.room_number IS NOT NULL AND r.room_number != ''
                ORDER BY CAST(r.room_number AS INTEGER)
            """, (f"{target_str}%",))
            
            arrivals = c.fetchall()
            
            for arr in arrivals:
                arr_dict = dict(arr)
                room = arr_dict["room_number"]
                guest = arr_dict["guest_name"]
                
                task = {
                    "room": room,
                    "tasktype": "ARRIVAL",
                    "priority": "HIGH",
                    "description": f"Prepare room {room} for {guest} arrival",
                    "notes": []
                }
                
                remarks = f"{arr_dict.get('main_remark') or ''} {arr_dict.get('total_remarks') or ''}".lower()
                if '2t' in remarks:
                    task["notes"].append("2 TWIN BEDS")
                if 'accessible' in remarks or 'disabled' in remarks:
                    task["notes"].append("ACCESSIBLE ROOM")
                
                tasks.append(task)
        
        finally:
            conn.close()
        
        return tasks


    def cancel_checkin(self, stay_id: int):
        stay = self.fetch_one("SELECT * FROM stays WHERE id = ?", (stay_id,))
        if not stay:
            return False, "Stay not found"
        
        self.execute("DELETE FROM stays WHERE id = ?", (stay_id,))
        self.execute(
            "UPDATE rooms SET status = 'VACANT' WHERE room_number = ?",
            (stay["room_number"],),
        )
        return True, "Check-in cancelled successfully"


    def cancel_checkout(self, stay_id: int):
        stay = self.fetch_one("SELECT * FROM stays WHERE id = ?", (stay_id,))
        if not stay:
            return False, "Stay not found"
        if stay["status"] != "CHECKED_OUT":
            return False, "Not checked out"
        
        self.execute("UPDATE stays SET status = 'CHECKED_IN', checkout_actual = NULL WHERE id = ?", (stay_id,))
        self.execute("UPDATE rooms SET status = 'OCCUPIED' WHERE room_number = ?", (stay["room_number"],))
        return True, f"Check-out cancelled - room {stay['room_number']} back to in-house"



    def is_valid_room_number(self, room_number: str) -> tuple[bool, str]:
        """Check if room number is valid (integer within ROOM_BLOCKS)"""
        if not room_number or not room_number.strip():
            return False, "Room number cannot be empty"
        
        # Try to parse as integer (reject decimals)
        try:
            # First check if it contains a decimal point
            if '.' in room_number.strip():
                return False, "Room number cannot have decimals. Use whole numbers only"
            
            room_int = int(room_number.strip())
        except:
            return False, "Room number must be a valid whole number"
        
        # Check if it's in valid ranges
        for start, end in ROOM_BLOCKS:
            if start <= room_int <= end:
                return True, str(room_int)
        
        # Not in any valid range
        valid_ranges = ", ".join([f"{s}-{e}" for s, e in ROOM_BLOCKS])
        return False, f"Room {room_int} not in valid ranges: {valid_ranges}"

    def check_room_available_for_assignment(self, room_number: str, arrival_date: date, depart_date: date, exclude_reservation_id: int = None):
        if not room_number or not room_number.strip():
            return True, ""
        try:
            rn = str(int(float(room_number.strip())))
        except:
            return False, "Invalid room number format"
        
        params = [rn, depart_date.isoformat(), arrival_date.isoformat()]
        sql = """
            SELECT r.id, r.guest_name, r.arrival_date, r.depart_date, r.reservation_no
            FROM reservations r
            WHERE r.room_number = ?
            AND r.arrival_date < ?
            AND r.depart_date > ?
        """

        if exclude_reservation_id is not None:
            sql += " AND r.id != ?"
            params.append(exclude_reservation_id)

        conflict = self.fetch_one(sql, tuple(params))
       
        if conflict:
            return False, f"Room {rn} occupied by {conflict['guest_name']} (Res #{conflict['reservation_no']})"
        return True, ""


   
    def reservations_empty(self):
        result = self.fetch_one("SELECT COUNT(*) as cnt FROM reservations")
        return result["cnt"] == 0 if result else True


    def build_reservations_from_df(self, df: pd.DataFrame):
           df.columns = [str(c).strip() for c in df.columns]
           
           # Simple mapping - keep everything as strings initially
           df_clean = pd.DataFrame({
               "arrival_date": pd.to_datetime(df.get("Arrival Date"), errors='coerce'),
               "depart_date": pd.to_datetime(df.get("Depart"), errors='coerce'),
               "room_number": df.get("Room"),
               "room_type_code": df.get("Room type"),
               "adults": pd.to_numeric(df.get("AD"), errors='coerce').fillna(1).astype(int),
               "children": 0,
               "total_guests": pd.to_numeric(df.get("Tot. guests"), errors='coerce').fillna(1).astype(int),
               "reservation_no": df.get("Reservation No.").astype(str),
               "voucher": df.get("Voucher").astype(str) if "Voucher" in df.columns else None,
               "guest_name": df.get("Guest or Group's name"),
               "main_client": df.get("Main client"),
               "nights": pd.to_numeric(df.get("Nights"), errors='coerce'),
               "meal_plan": df.get("Meal Plan"),
               "rate_code": df.get("Rate"),
               "channel": df.get("Chanl"),
               "main_remark": df.get("Main Rem."),
               "contact_name": df.get("Contact person"),
               "contact_email": df.get("E-mail"),
               "source_of_business": df.get("Source of Business"),
           })
           
           # Drop rows with invalid dates
           df_clean = df_clean.dropna(subset=["arrival_date", "depart_date"])
           
           # Replace remaining NaT/NaN with None
           df_clean = df_clean.where(pd.notna(df_clean), None)
           
           return df_clean



    def import_arrivals_file(self, path: str):
        try:
            df = pd.read_excel(path)
            df_db = self.build_reservations_from_df(df)
            from contextlib import closing
            with closing(self.get_conn()) as conn:
                df_db.to_sql("reservations", conn, if_exists="append", index=False)
            return len(df_db)
        except Exception as e:
            st.error(f"Import error: {e}")
            return 0



    def import_all_arrivals_from_fs(self) -> int:
        pattern = os.path.join(ARRIVALS_ROOT, "**", "Arrivals *.XLSX")
        files = sorted(glob(pattern, recursive=True))
        total = 0
        for path in files:
            total += self.import_arrivals_file(path)
        return total

    def get_arrivals_for_date(self, d: date):
        return self.fetch_all(
            """
            SELECT r.*
            FROM reservations AS r
            WHERE date(r.arrival_date) = date(?)
            AND r.reservation_status NOT IN ('CHECKED_IN', 'CHECKED_OUT', 'NO_SHOW')
            AND NOT EXISTS (
                SELECT 1
                FROM stays AS s
                WHERE s.reservation_id = r.id
                    AND s.status IN ('CHECKED_IN', 'CHECKED_OUT')
            )
            ORDER BY COALESCE(r.room_number, ''), r.guest_name
            """,
            (d.isoformat(),),
        )




    def update_reservation_room(self, resid: int, room_number: str):
        if not room_number or not room_number.strip():
            return False, "Room number cannot be empty"

        isvalid, result = self.is_valid_room_number(room_number)
        if not isvalid:
            return False, result

        # NEW: block dirty rooms
        if not self.is_room_clean(room_number):
            return False, "Room is marked DIRTY. Please choose a clean room."

        with closing(self.get_conn()) as conn:
            c = conn.cursor()
            c.execute("SELECT arrival_date, depart_date FROM reservations WHERE id = ?", (resid,))
            res = c.fetchone()
            if not res:
                return False, "Reservation not found"

            arr = datetime.fromisoformat(res["arrival_date"]).date()
            dep = datetime.fromisoformat(res["depart_date"]).date()

        available, msg = self.check_room_available_for_assignment(room_number, arr, dep, resid)
        if not available:
            return False, msg

        with closing(self.get_conn()) as conn, conn:
            c = conn.cursor()
            c.execute(
                "UPDATE reservations SET room_number = ?, updated_at = datetime('now') WHERE id = ?",
                (room_number, resid),
            )
        return True, f"Room {room_number} assigned successfully"




    
    def get_checked_out_for_date(self, d: date):
        return self.fetch_all(
            """
            SELECT s.*, r.guest_name, r.reservation_no
            FROM stays s
            JOIN reservations r ON r.id = s.reservation_id
            WHERE s.status = 'CHECKED_OUT'
            AND date(s.checkout_actual) = date(?)
            ORDER BY CAST(s.room_number AS INTEGER)
            """,
            (d.isoformat(),),
        )



    def set_room_status(self, room_number: str, status: str):
        """Set room status manually (e.g. CLEAN, DIRTY)."""
        if not room_number:
            return False, "Room number required"
        status = status.upper().strip()
        if status not in ["CLEAN", "DIRTY", "VACANT", "OCCUPIED"]:
            return False, "Invalid status. Use CLEAN, DIRTY, VACANT or OCCUPIED."

        self.execute(
            "UPDATE rooms SET status = ? WHERE room_number = ?",
            (status, room_number.strip()),
        )
        return True, f"Room {room_number} set to {status}"

    # ---- rooms / stays ----

    def ensure_room_exists(self, room_number: str):
        if not room_number:
            return
        self.execute("""
            INSERT INTO rooms (room_number, status) VALUES (:room, 'VACANT')
            ON CONFLICT (room_number) DO NOTHING
        """, {"room": room_number.strip()})

    def check_room_conflict(self, room_number: str, d: date):
    # This method is no longer needed - already handled by check_room_available_for_assignment
        return []


    def checkin_reservation(self, res_id: int):
        res = self.fetch_one("SELECT * FROM reservations WHERE id = ?", (res_id,))

        if not res:
            return False, "Reservation not found"
        if not res["room_number"]:
            return False, "Assign a room first"
        
        is_valid, result = self.is_valid_room_number(res["room_number"])
        if not is_valid:
            return False, result
        
        # if res["arrival_date"] < date.today():
        #     return False, f"Cannot check in for past date"
        
        self.ensure_room_exists(result)
        
        self.execute("""
            INSERT INTO stays (reservation_id, room_number, status, checkin_planned, checkout_planned, checkin_actual)
            VALUES (:res_id, :room, 'CHECKED_IN', :arr, :dep, CURRENT_TIMESTAMP)
        """, {"res_id": res_id, "room": result, "arr": res["arrival_date"], "dep": res["depart_date"]})
        
        self.execute(
    "UPDATE rooms SET status = 'OCCUPIED' WHERE room_number = ?",
    (result,),
)

        return True, "Checked in successfully"
    
    def checkout_stay(self, stay_id: int):
        # Try to find existing stay by stay_id
        stay = self.fetch_one("SELECT * FROM stays WHERE id = ?", (stay_id,))
        
        if stay:
            # Existing stay: mark as checked out
            self.execute(
                "UPDATE stays SET status = 'CHECKED_OUT', checkout_actual = datetime('now') WHERE id = ?",
                (stay_id,),
            )
            self.execute(
                "UPDATE rooms SET status = 'VACANT' WHERE room_number = ?",
                (stay["room_number"],),
            )
        else:
            # No stay row: treat stay_id as reservation_id
            res = self.fetch_one("SELECT * FROM reservations WHERE id = ?", (stay_id,))
            if not res or not res["room_number"]:
                return False, "Reservation not found or no room assigned"
            
            self.execute(
                """
                INSERT INTO stays (
                    reservation_id, room_number, status,
                    checkin_planned, checkout_planned,
                    checkin_actual, checkout_actual
                )
                VALUES (?, ?, 'CHECKED_OUT', ?, ?, datetime('now'), datetime('now'))
                """,
                (stay_id, res["room_number"], res["arrival_date"], res["depart_date"]),
            )
            self.execute(
                "UPDATE rooms SET status = 'VACANT' WHERE room_number = ?",
                (res["room_number"],),
            )

        return True, "Checked out successfully"





    def get_inhouse(self, target_date: date = None):
        """Get only CHECKED_IN guests who are actually in the hotel."""
        if not target_date:
            target_date = date.today()

        return self.fetch_all(
            """
            SELECT
                s.id AS stay_id,
                s.reservation_id AS id,
                r.reservation_no,
                r.guest_name,
                s.room_number,
                s.checkin_planned,
                s.checkout_planned,
                r.meal_plan      AS breakfast_code,
                r.main_remark    AS main_remark,
                r.total_remarks  AS total_remarks,
                s.comment        AS comment,
                COALESCE(s.parking_space, '') AS parking_space,
                COALESCE(s.parking_plate, '') AS parking_plate,
                s.status
            FROM stays s
            JOIN reservations r ON r.id = s.reservation_id
            WHERE s.status = 'CHECKED_IN'
            AND date(s.checkin_planned) <= date(?)
            AND date(s.checkout_planned) > date(?)
            ORDER BY s.room_number
            """,
            (target_date.isoformat(), target_date.isoformat()),
        )







    def get_departures_for_date(self, d: date):
        return self.fetch_all(
            """
            SELECT s.id AS stay_id, r.id, r.reservation_no, r.guest_name, s.room_number,
                s.checkin_planned, s.checkout_planned, s.status
            FROM stays s
            JOIN reservations r ON r.id = s.reservation_id
            WHERE s.status = 'CHECKED_IN'
            AND date(s.checkout_planned) = date(?)
            ORDER BY CAST(s.room_number AS INTEGER)
            """,
            (d.isoformat(),),
        )




    def checkout_stay(self, stay_id: int):
        """Checkout a guest - handles both stay IDs and reservation IDs"""
    
        # Try to find existing stay
        stay = self.fetch_one("SELECT * FROM stays WHERE id = ?", (stay_id,))
        
        if stay:
            # Actual stay exists - update it
            self.execute(
            "UPDATE stays SET status = 'CHECKED_OUT', checkout_actual = datetime('now') WHERE id = ?",
            (stay_id,),
        )
            self.execute(
            "UPDATE rooms SET status = 'VACANT' WHERE room_number = ?",
            (stay["room_number"],),
)
        else:
            # No stay exists - create one as checked out
            res = self.fetch_one("SELECT * FROM reservations WHERE id = ?", (stay_id,))

            
            if not res or not res["room_number"]:
                return False, "Reservation not found or no room assigned"
            
            self.execute("""
                INSERT INTO stays (reservation_id, room_number, status, 
                                checkin_planned, checkout_planned, 
                                checkin_actual, checkout_actual)
                VALUES (:res_id, :room, 'CHECKED_OUT', :arr, :dep, 
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, {
                "res_id": stay_id, 
                "room": res["room_number"], 
                "arr": res["arrival_date"], 
                "dep": res["depart_date"]
            })
            
            self.execute(
    "UPDATE rooms SET status = 'VACANT' WHERE room_number = ?",
    (res["room_number"],),
)

        
        return True, "Checked out successfully"



    from contextlib import closing

    def seed_rooms_from_blocks(self):
        with closing(self.get_conn()) as conn, conn:
            c = conn.cursor()
            for start, end in ROOM_BLOCKS:
                for rn in range(start, end + 1):
                    c.execute(
                        "INSERT OR IGNORE INTO rooms (room_number, status) VALUES (?, 'VACANT')",
                        (str(rn),),
                    )


    def sync_room_status_from_stays(self):
        self.execute("UPDATE rooms SET status = 'VACANT'")
        occupied = self.fetch_all("SELECT DISTINCT room_number FROM stays WHERE status = 'CHECKED_IN'")
        for row in occupied:
            self.execute(
    "UPDATE rooms SET status = 'OCCUPIED' WHERE room_number = ?",
    (row["room_number"],),
)

    
    def update_parking_for_stay(self, stay_id: int, space: str, plate: str, notes: str):
        self.execute(
    """
    UPDATE stays
    SET parking_space = ?, parking_plate = ?, parking_notes = ?
    WHERE id = ?
    """,
    (space, plate, notes, stay_id),
)

    # ---- parking helpers ----

    def get_parking_overview_for_date(self, target_date: date):
        return self.fetchall(
            """
            SELECT
                s.id,
                s.reservation_id,
                s.room_number,
                s.status,
                s.checkin_planned,
                s.check_out_planned,
                s.check_in_actual,
                s.check_out_actual,
                s.parking_space,
                s.parking_plate,
                s.parking_notes,
                r.guest_name
            FROM stays AS s
            JOIN reservations AS r
            ON r.id = s.reservation_id
            WHERE s.status = 'CHECKED_IN'
            AND date(s.checkin_planned) <= date(?)
            AND date(s.check_out_planned) > date(?)
            AND (
                s.parking_space IS NOT NULL
                OR s.parking_plate IS NOT NULL
            )
            ORDER BY
                s.parking_space,
                CAST(s.room_number AS INTEGER)
            """,
            (target_date.isoformat(),),
        )





    def add_task(self, task_date: date, title: str, created_by: str, assigned_to: str, comment: str):
        self.execute("""
            INSERT INTO tasks (task_date, title, created_by, assigned_to, comment)
            VALUES (:date, :title, :by, :to, :comment)
        """, {"date": task_date, "title": title, "by": created_by, "to": assigned_to, "comment": comment})
    
    def get_tasks_for_date(self, d: date):
        return self.fetch_all("SELECT * FROM tasks WHERE task_date = :date ORDER BY created_at", {"date": d})
    
    def add_no_show(
        self,
        arrival_date: date,
        guest_name: str,
        main_client: str,
        charged: bool,
        amount_charged: float,
        amount_pending: float,
        comment: str,
    ):
        existing = self.fetch_one(
            """
            SELECT id
            FROM no_shows
            WHERE guest_name = ?
            AND date(arrival_date) = date(?)
            """,
            (guest_name, arrival_date.isoformat()),
        )

        charged_int = 1 if charged else 0
        amount_charged = amount_charged or 0.0
        amount_pending = amount_pending or 0.0

        if existing:
            self.execute(
                """
                UPDATE no_shows
                SET main_client   = ?,
                    charged       = ?,
                    amount_charged = ?,
                    amount_pending = ?,
                    comment       = ?
                WHERE id = ?
                """,
                (
                    main_client,
                    charged_int,
                    amount_charged,
                    amount_pending,
                    comment,
                    existing["id"],
                ),
            )
        else:
            self.execute(
                """
                INSERT INTO no_shows (
                    arrival_date,
                    guest_name,
                    main_client,
                    charged,
                    amount_charged,
                    amount_pending,
                    comment
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    arrival_date.isoformat(),
                    guest_name,
                    main_client,
                    charged_int,
                    amount_charged,
                    amount_pending,
                    comment,
                ),
            )


    def get_no_shows_for_date(self, target_date: date):
        return self.fetch_all(
            """
            SELECT *
            FROM no_shows
            WHERE date(arrival_date) = date(?)
            ORDER BY created_at
            """,
            (target_date.isoformat(),),
        )

    
    def get_twin_rooms(self):
        rows = self.fetch_all("SELECT room_number FROM rooms WHERE is_twin = 1 ORDER BY CAST(room_number AS INTEGER)")
        return [r["room_number"] for r in rows]
    
    def get_all_rooms(self):
        rows = self.fetch_all("SELECT room_number FROM rooms ORDER BY CAST(room_number AS INTEGER)")
        return [r["room_number"] for r in rows]
    
    def set_spare_rooms_for_date(self, target_date: date, rooms: list):
        self.execute("DELETE FROM spare_rooms WHERE target_date = :date", {"date": target_date})
        for rn in rooms:
            self.execute("INSERT INTO spare_rooms (target_date, room_number) VALUES (:date, :room)", 
                         {"date": target_date, "room": rn})
    
    def get_spare_rooms_for_date(self, target_date: date):
        rows = self.fetch_all("""
            SELECT room_number FROM spare_rooms WHERE target_date = :date
            ORDER BY CAST(room_number AS INTEGER)
        """, {"date": target_date})
        return [r["room_number"] for r in rows]
    
    def search_reservations(self, q: str):
        like_pattern = f"%{q}%"
        return self.fetch_all(
            """
            SELECT * FROM reservations
            WHERE guest_name LIKE ?
            OR room_number LIKE ?
            OR reservation_no LIKE ?
            OR main_client LIKE ?
            OR channel LIKE ?
            ORDER BY arrival_date DESC
            LIMIT 500
            """,
            (like_pattern, like_pattern, like_pattern, like_pattern, like_pattern),
        )

    
    def read_table(self, name: str):
        from contextlib import closing
        with closing(self.get_conn()) as conn:
            return pd.read_sql_query(f"SELECT * FROM {name}", conn)



    def export_arrivals_excel(self, d: date):
        rows = self.get_arrivals_for_date(d)
        if not rows:
            return None
        df = pd.DataFrame([dict(r) for r in rows])
        preferred_order = [
            "amount_pending", "arrival_date", "room_number", "room_type_code",
            "adults", "total_guests", "reservation_no", "voucher",
            "related_reservation", "crs_code", "crs_name", "guest_id_raw",
            "guest_name", "vip_flag", "client_id", "main_client", "nights",
            "depart_date", "meal_plan", "rate_code", "channel",
            "cancellation_policy", "main_remark", "contact_name",
            "contact_phone", "contact_email", "total_remarks",
            "source_of_business", "stay_option_desc", "remarks_by_chain"
        ]
        cols = [c for c in preferred_order if c in df.columns] + [
            c for c in df.columns if c not in preferred_order
        ]
        df = df[cols]
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Arrivals")
        output.seek(0)
        return output

    def export_inhouse_excel(self, d: date):
        inhouse_rows = self.get_inhouse()
        dep_rows = self.get_departures_for_date(d)
        df_inhouse = pd.DataFrame([dict(r) for r in inhouse_rows]) if inhouse_rows else pd.DataFrame()
        df_dep = pd.DataFrame([dict(r) for r in dep_rows]) if dep_rows else pd.DataFrame()
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df_inhouse.to_excel(writer, index=False, sheet_name="InHouse")
            df_dep.to_excel(writer, index=False, sheet_name="Departures")
        output.seek(0)
        return output


# =========================
# Streamlit UI
# =========================

db = None  # Will be initialized in main()
 # Use cached connection
from datetime import date  # make sure this is imported at top of file

def page_payments():
    st.header("Payments / Refunds")

    # --- NEW: date + guest dropdown (like invoice tab) ---
    col1, col2 = st.columns(2)
    with col1:
        pay_date = st.date_input("Payment Date", value=date.today(), key="payment_date")
    with col2:
        st.write("")  # spacer

    guests_for_date = db.get_guests_for_date(pay_date)
    guest_options = [
        f"{g['guest_name']} (Room {g['room_number']})"
        for g in guests_for_date
    ]

    if not guest_options:
        st.warning("No guests for this date. Please select another date.")
        return

    selected_guest_str = st.selectbox(
        "Select Guest",
        guest_options,
        key="payment_guest_selector",
    )

    selected_guest_name = selected_guest_str.split(" (Room")[0]

    # get reservation for that guest/date
    res_data = db.get_reservation_by_guest_and_date(selected_guest_name, pay_date)
    if not res_data:
        st.error("Could not load reservation data for this guest/date.")
        return

    reservation_id = res_data.get("id", None)
    guest_name = res_data.get("guest_name", "")
    room_no = res_data.get("room_number", "")

    st.info(f"✓ Selected: {guest_name} | Room: {room_no} | Res ID: {reservation_id}")

    # --- OLD amount/type/method block stays the same ---
    col3, col4, col5 = st.columns(3)
    with col3:
        amount = st.number_input("Amount (£)", min_value=0.0, step=0.01, format="%.2f")
    with col4:
        pay_type = st.selectbox("Type", ["PAYMENT", "REFUND"])
    with col5:
        method = st.selectbox("Method", ["CARD", "CASH", "BANK", "OTHER"])

    reference = st.text_input("Reference (folio, POS ref, etc.)")
    note = st.text_area("Note")

    # --- UPDATED: no manual res_id / guest_name, use selected ones ---
    if st.button("Add entry", type="primary", use_container_width=True):
        if amount <= 0:
            st.error("Amount must be greater than 0.")
        else:
            db.add_payment(
                int(reservation_id) if reservation_id is not None else None,
                guest_name,
                amount,
                pay_type,
                method,
                reference,
                note,
            )
            st.success("Payment/refund recorded.")

    st.divider()
    st.subheader("Recent payments / refunds")

    rows = db.get_all_payments()
    if not rows:
        st.info("No payments recorded yet.")
    else:
        df = pd.DataFrame(rows)
        df = clean_numeric_columns(df, ["reservation_id"])
        st.dataframe(
            df[
                [
                    "created_at",
                    "reservation_id",
                    "guest_name",
                    "amount",
                    "type",
                    "method",
                    "reference",
                    "note",
                    "room_number",
                    "arrival_date",
                    "depart_date",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )



def page_breakfast():
    st.header("Breakfast List")
    today = st.date_input("Date", value=date.today(), key="breakfast_date")
    
    breakfast_rows = db.get_breakfast_list_for_date(today)
    
    if not breakfast_rows:
        st.info("No guests with breakfast for this date.")
        return
    
    df_breakfast = pd.DataFrame([dict(r) for r in breakfast_rows])
    
    # Calculate totals
    total_rooms = len(df_breakfast)
    total_adults = df_breakfast["adults"].sum()
    total_children = df_breakfast["children"].sum()
    total_guests = total_adults + total_children
    
    # Summary at top
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Rooms", total_rooms)
    col2.metric("Adults", int(total_adults))
    col3.metric("Children", int(total_children))
    col4.metric("Total Guests", int(total_guests))
    
    st.subheader(f"Breakfast for {today}")
    
    # Prepare display
    df_display = df_breakfast[
        ["room_number", "guest_name", "adults", "children", "total_guests", "meal_plan"]
    ].copy()
    df_display = clean_numeric_columns(
        df_display, ["room_number", "adults", "children", "total_guests"]
    )
    df_display.columns = ["Room", "Guest Name", "Adults", "Children", "Total", "Meal Plan"]
    df_display.insert(0, "#", range(1, len(df_display) + 1))
    df_display = clean_numeric_columns(df_display, ["Room"])

    edited = st.data_editor(
        df_display,
        use_container_width=True,
        hide_index=True,
        disabled=["#", "Guest Name"],
        column_config={
            "Adults": st.column_config.NumberColumn(min_value=0, step=1),
            "Children": st.column_config.NumberColumn(min_value=0, step=1),
            "Meal Plan": st.column_config.TextColumn(),
        },
    )

    if st.button("Save breakfast adjustments", type="primary", use_container_width=True):
        # optional: write back to reservations table by room + date
        for _, row in edited.iterrows():
            room = str(row["Room"]).strip()
            adults = int(row["Adults"])
            children = int(row["Children"])
            meal_plan = row["Meal Plan"]

            db.execute(
                """
                UPDATE reservations
                SET adults = ?, total_guests = ?, meal_plan = ?
                WHERE room_number = ?
                  AND date(arrival_date) <= date(?)
                  AND date(depart_date) >= date(?)
                """,
                (
                    adults,
                    adults + children,
                    meal_plan,
                    room,
                    today.isoformat(),
                    today.isoformat(),
                ),
            )
        st.success("Breakfast data updated.")
        st.rerun()

def page_housekeeping():
    st.header("Housekeeping Task List")
    today = st.date_input("Date", value=date.today(), key="hsk_date")
    
    tasks = db.generate_hsk_tasks_for_date(today)
    
    if not tasks:
        st.info("No housekeeping tasks for this date.")
        return
    
    # Get existing statuses and merge with tasks
    for task in tasks:
        status_data = db.get_hsk_task_status(today, task["room"], task["tasktype"])
        if status_data:
            task["Status"] = status_data["status"]
            task["HSK Notes"] = status_data["notes"] or ""
        else:
            task["Status"] = "PENDING"
            task["HSK Notes"] = ""
    
    # Summary metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Tasks", len(tasks))
    col2.metric("Checkouts", len([t for t in tasks if t['tasktype'] == 'CHECKOUT']))
    col3.metric("Stayovers", len([t for t in tasks if t['tasktype'] == 'STAYOVER']))
    col4.metric("Arrivals", len([t for t in tasks if t['tasktype'] == 'ARRIVAL']))
    completed_count = len([t for t in tasks if t.get('Status') == 'DONE'])
    col5.metric("Completed", completed_count)
    
    # Create editable DataFrame
    df_tasks = pd.DataFrame([
        {
            "#": idx,
            "Room": format_room_number(t["room"]),
            "Type": t["tasktype"],
            "Priority": t["priority"],
            "Task": t["description"],
            "Notes": " | ".join(t["notes"]) if t["notes"] else "",
            "Status": t["Status"],
            "HSK Notes": t["HSK Notes"]
        }
        for idx, t in enumerate(tasks, 1)
    ])
    
    # Display editable table
    st.subheader("Task Tracking")
    edited_df = st.data_editor(
        df_tasks,
        use_container_width=True,
        hide_index=True,
        disabled=["#", "Room", "Type", "Priority", "Task", "Notes"],  # Only Status and HSK Notes are editable
        column_config={
            "Status": st.column_config.SelectboxColumn(
                "Status",
                options=["PENDING", "DONE"],
                required=True
            ),
            "HSK Notes": st.column_config.TextColumn(
                "HSK Notes",
                help="Add notes here (e.g., 'Cleaned', 'Extra towels needed')",
                max_chars=200
            )
        }
    )
    
    # Save button
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("Save", type="primary", use_container_width=True):
            # Save each task status
             for idx, row in edited_df.iterrows():
                original_task = tasks[idx]
                db.update_hsk_task_status(
                    today,
                    original_task["room"],
                    original_task["tasktype"],
                    row["Status"],
                    row["HSK Notes"],
                )

                # If checkout cleaning task is DONE, mark room as CLEAN
                if original_task["tasktype"] == "CHECKOUT" and row["Status"] == "DONE":
                    db.set_room_status(original_task["room"], "CLEAN")

    
    # Download CSV
    csv = edited_df.to_csv(index=False)
    st.download_button(
        label="Download HSK List",
        data=csv,
        file_name=f"HSK_{today.strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )
    
    # Summary
    pending = len(edited_df[edited_df["Status"] == "PENDING"])
    completed = len(edited_df[edited_df["Status"] == "DONE"])
    st.caption(f"Total: {len(tasks)} tasks | ✅ Completed: {completed} | ⏳ Pending: {pending}")


def page_arrivals():
    st.header("Arrivals")
    d = st.date_input("Arrival date", value=date.today(), key="arrivals_date")
    
    rows = db.get_arrivals_for_date(d)
    if not rows:
        st.info("No arrivals for this date.")
        return
    
    st.subheader(f"Arrivals list ({len(rows)} reservations)")
    
    for idx, r in enumerate(rows, 1):
        res_no = int(float(r['reservation_no'])) if r.get('reservation_no') and str(r['reservation_no']) not in ['None', ''] else r.get('reservation_no', '')
        with st.expander(f"{idx} - {r['guest_name']} |  Reservation No.: {res_no}", expanded=True):
            # Add check-in/checkout dates at top
            col1, col2, col3, col4 = st.columns(4)
            col1.write(f"Arrival: {format_date(r['arrival_date'])}")
            col2.write(f"Departure: {format_date(r['depart_date'])}")

            col3.write(f"**Nights:** {r.get('nights', '')}")
            col4.write(f"**Guests:** {r.get('total_guests', '')}")
            
            col1, col2, col3 = st.columns(3)
            col1.write(f"**Room type:** {r['room_type_code']}")
            col2.write(f"**Channel:** {r['channel']}")
            col3.write(f"**Meal Plan:** {r.get('meal_plan', 'RO')}")

            # Front Office notes (editable)
            main_note = st.text_area(
                "Front Office Note",
                value=r.get("main_remark") or "",
                key=f"fo_main_{r['id']}",
                height=80,
            )
            # extra_note = st.text_area(
            #     "Extra Notes (optional)",
            #     value=r.get("total_remarks") or "",
            #     key=f"fo_extra_{r['id']}",
            #     height=80,
            # )

            if st.button("Save Notes", key=f"save_notes_{r['id']}", use_container_width=True):
                db.update_reservation_notes(r["id"], main_note)
                st.success("Notes saved.")
                st.rerun()

            current_room = r["room_number"] or ""
            room = st.text_input(
                "Room Number",
                value=current_room,
                key=f"room_{r['id']}", 
                placeholder="Enter room number",
            )
            
            colbtn1, colbtn2, colbtn3 = st.columns(3)

            with colbtn1:
                if st.button(
                    "Save Room",
                    key=f"save_{r['id']}",
                    type="primary",
                    use_container_width=True,
                ):
                    if room and room.strip():
                        success, msg = db.update_reservation_room(r['id'], room)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
                    else:
                        st.warning("Please enter a room number.")

            with colbtn2:
                if st.button(
                    "Check-in",
                    key=f"checkin_{r['id']}",
                    type="secondary",
                    use_container_width=True,
                ):
                    success, msg = db.checkin_reservation(r['id'])
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            with colbtn3:
                if st.button(
                    "Add No-show",
                    key=f"noshow_{r['id']}",
                    type="secondary",
                    use_container_width=True,
                ):
                    db.mark_reservation_as_no_show(
                        reservation_id=r['id'],
                        arrival_date=datetime.fromisoformat(r["arrival_date"]).date(),
                        guest_name=r["guest_name"],
                        main_client=r.get("main_client") or "",
                        charged=False,
                        amount_charged=0.0,
                        amount_pending=0.0,
                        comment=main_note or r.get("main_remark") or "",
                    )
                    st.success("Marked as no-show and removed from arrivals.")
                    st.rerun()


def page_inhouse_list():
    st.header("In-House List")
    today = st.date_input("Date", value=date.today(), key="inhouse_list_date")
    
    st.subheader(f"Guests in hotel on {today.strftime('%d %B %Y')}")
    inhouse_rows = db.get_inhouse(today)
    
    if not inhouse_rows:
        st.info("No guests scheduled for this date.")
        return

    # Build DataFrame with reservation_id for updating mealplan
    df_inhouse = pd.DataFrame([
        {
            "reservation_id": r["id"],          # r.reservationid AS id in get_inhouse [file:1]
            "Room": r["room_number"],
            "Guest Name": r["guest_name"],
            "Status": r["status"],
            "Arrival": r["checkin_planned"],
            "Departure": r["checkout_planned"],
            "Meal Plan": r.get("meal_plan") or r.get("breakfast_code") or "",
            "Parking": r["parking_space"] if r["parking_space"] else "",
            "Notes": " | ".join(
                part
                for part in [
                    r.get("main_remark") or "",
                    r.get("total_remarks") or "",
                    r.get("comment") or "",
                ]
                if part
            ),
        }
        for r in inhouse_rows
    ])

    df_inhouse = clean_numeric_columns(df_inhouse, ["reservation_id", "Room"])

    st.subheader("In-house guests")

    edited_df = st.data_editor(
        df_inhouse,
        use_container_width=True,
        hide_index=True,
        column_config={
            "reservation_id": st.column_config.NumberColumn("reservation_id", disabled=True),
            "Room": st.column_config.TextColumn("Room", disabled=True),
            "Guest Name": st.column_config.TextColumn("Guest Name", disabled=True),
            "Status": st.column_config.TextColumn("Status", disabled=True),
            "Arrival": st.column_config.TextColumn("Arrival", disabled=True),
            "Departure": st.column_config.TextColumn("Departure", disabled=True),
            "Meal Plan": st.column_config.TextColumn(
                "Meal Plan",
                help="Change to BB / HB / RO+BB etc. to control breakfast eligibility",
            ),
            "Parking": st.column_config.TextColumn("Parking", disabled=True),
            "Notes": st.column_config.TextColumn("Notes", disabled=True),
        },
    )

    if st.button("Save meal plans", type="primary", use_container_width=True):
        for _, row in edited_df.iterrows():
            reservation_id = int(row["reservation_id"])
            mealplan = row["Meal Plan"] or ""
            db.update_reservation_mealplan(reservation_id, mealplan)
        st.success("Meal plans updated.")
        st.rerun()

    # Cancel check-in section (unchanged)
    checked_in_guests = [dict(r) for r in inhouse_rows if r["status"] == "CHECKED_IN"]
    
    if checked_in_guests:
        st.divider()
        st.subheader("Cancel check-in")
        for idx, guest in enumerate(checked_in_guests, 1):
            col1, col2 = st.columns([4, 1])
            col1.write(f"**{idx}.** Room {guest['room_number']} - {guest['guest_name']}")
            if col2.button("Cancel", key=f"cancel_{idx}_{guest['stay_id']}", use_container_width=True):
                success, msg = db.cancel_checkin(guest["stay_id"])
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    if checked_in_guests:
        st.divider()
        st.subheader("Change room for checked-in guests")
        for idx, guest in enumerate(checked_in_guests, 1):
            with st.expander(f"{idx}. Room {guest['room_number']} - {guest['guest_name']}", expanded=False):
                new_room = st.text_input(
                    "New Room Number",
                    key=f"move_room_{guest['stay_id']}",
                    placeholder="Enter new room",
                )
                if st.button("Move", key=f"move_btn_{guest['stay_id']}", use_container_width=True):
                    if not new_room.strip():
                        st.warning("Enter a room number.")
                    else:
                        success, msg = db.move_checked_in_guest(guest["stay_id"], new_room)
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)



def page_checkout_list():
    st.header("Check-out List")
    today = st.date_input("Date", value=date.today(), key="checkout_date")
    
    st.subheader(f"Guests checking out on {today.strftime('%d %B %Y')}")
    dep_rows = db.get_departures_for_date(today)
    
    if not dep_rows:
        st.info("No departures scheduled for this date.")
    else:
        st.caption(f"{len(dep_rows)} departures scheduled")
        df_dep = pd.DataFrame([{
            "Room": r["room_number"],
            "Guest Name": r["guest_name"],
            "Arrival": r["checkin_planned"],
            "Departure": r["checkout_planned"],
            "Status": r["status"]
        } for r in dep_rows])
        df_dep = clean_numeric_columns(df_dep, ["Room"])
        st.dataframe(df_dep, use_container_width=True, hide_index=True)
        
        st.subheader("Quick checkout")
        for idx, row_data in enumerate(dep_rows, 1):
            row_dict = dict(row_data)
            
            # Create a bordered card for each guest
            with st.container():
                col1, col2 = st.columns([5, 1])
                
                with col1:
                    st.markdown(f"""
                    <div style="
                        border: 2px solid #e0e0e0; 
                        border-radius: 8px; 
                        padding: 12px; 
                        background-color: #f9f9f9;
                        margin-bottom: 8px;
                    ">
                        <strong style="font-size: 16px;">{idx}. Room {format_room_number(row_dict['room_number'])} - {row_dict['guest_name']}</strong>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    if st.button("Check-out", key=f"co_{idx}_{row_dict['stay_id']}", use_container_width=True):
                        success, msg = db.checkout_stay(int(row_dict["stay_id"]))
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

                
            
    st.divider()
    st.subheader(f"Already checked out on {today.strftime('%d %B %Y')}")
    checkout_rows = db.get_checked_out_for_date(today)
    
    if not checkout_rows:
        st.info("No check-outs completed for this date.")
    else:
        df_checkout = pd.DataFrame([{
            "Room": r["room_number"],
            "Guest Name": r["guest_name"],
            "Planned": r["checkout_planned"],
            "Actual": r["checkout_actual"]
        } for r in checkout_rows])
        df_checkout = clean_numeric_columns(df_checkout, ["Room"])
        st.dataframe(df_checkout, use_container_width=True, hide_index=True)
        st.caption(f"{len(df_checkout)} completed check-outs")
        
        st.subheader("Cancel check-out")
        for idx, row_data in enumerate(checkout_rows, 1):
            row_dict = dict(row_data)
            col1, col2 = st.columns([4, 1])
            col1.write(f"**{idx}.** Room {row_dict['room_number']} - {row_dict['guest_name']}")
            if col2.button("Undo", key=f"undo_{row_dict['id']}", use_container_width=True):
                success, msg = db.cancel_checkout(row_dict["id"])
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)



def page_tasks_handover():
    st.header("Handover")
    d = st.date_input("Date", value=date.today(), key="tasks_date")

    st.subheader("Add task")
    col1, col2 = st.columns(2)
    title = col1.text_input("Task")
    created_by = col2.text_input("By")
    assigned_to = col1.text_input("To")
    comment = col2.text_input("Comment")
    if st.button("Add Handover"):
        if title:
            db.add_task(d, title, created_by, assigned_to, comment)
            st.success("Handover added.")
        else:
            st.error("Handover title required.")

        st.subheader("Handover for this date")
    rows = db.get_tasks_for_date(d)
    df = pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
    if df.empty:
        st.info("No Handovers.")
    else:
        df_edit = st.data_editor(
            df[["id", "task_date", "title", "created_by", "assigned_to", "comment"]],
            hide_index=True,
            disabled=["id", "task_date"],
            use_container_width=True,
        )

        if st.button("Save changes", type="primary"):
            for _, row in df_edit.iterrows():
                db.execute(
                    """
                    UPDATE tasks
                    SET title = ?, created_by = ?, assigned_to = ?, comment = ?
                    WHERE id = ?
                    """,
                    (
                        row["title"],
                        row["created_by"],
                        row["assigned_to"],
                        row["comment"],
                        row["id"],
                    ),
                )
            st.success("Handover updated.")
            st.rerun()


def page_no_shows():
    st.header("No Shows")
    d = st.date_input("Arrival date", value=date.today(), key="no_show_date")
    
    st.subheader("Add no-show")
    
    # Get potential no-shows
    potential = db.get_potential_no_shows(d)
    
    with st.form("no_show_form", clear_on_submit=True):
        if potential:
            guest_options = ["Select a guest..."] + [
                f"{g['guest_name']} (Res {g['reservation_no']}) - {g.get('main_client', '')}" 
                for g in potential
            ]
            
            selected_idx = st.selectbox("Guest who didn't show up", options=range(len(guest_options)),
                                       format_func=lambda x: guest_options[x])
            
            if selected_idx > 0:
                guest_data = potential[selected_idx - 1]
                guest_name = guest_data['guest_name']
                main_client = guest_data.get('main_client', '')
                # st.info(f"Selected: {guest_name}")
            else:
                guest_name = st.text_input("Guest Name (manual-optional)")
                main_client = st.text_input("Main Client")
        else:
            st.info("No expected arrivals for this date")
            guest_name = st.text_input("Guest Name")
            main_client = st.text_input("Main Client")
        
        col1, col2 = st.columns(2)
        amount_charged = col1.number_input("Amount Charged (£)", min_value=0.0, step=0.01, format="%.2f")
        amount_pending = col2.number_input("Amount Pending (£)", min_value=0.0, step=0.01, format="%.2f")
        
        charged = st.checkbox("Payment Received")
        comment = st.text_area("Comment")
        
        submitted = st.form_submit_button("Add No-Show", type="primary", use_container_width=True)
        
        if submitted and guest_name:
            # Add to database
            db.add_no_show(d, guest_name, main_client, charged, amount_charged, amount_pending, comment)
            st.success(f"✓ No-show added: {guest_name}")
    
    st.divider()
    st.subheader(f"No-shows for {d.strftime('%d %B %Y')}")
    rows = db.get_no_shows_for_date(d)
    
    if not rows:
        st.info("No no-shows recorded.")
    else:
        df = pd.DataFrame([{
            "Guest": r["guest_name"],
            "Client": r["main_client"] if r.get("main_client") else "",
            "Charged": f"£{float(r['amount_charged']):.2f}" if r.get('amount_charged') is not None else "£0.00",
            "Pending": f"£{float(r['amount_pending']):.2f}" if r.get('amount_pending') is not None else "£0.00",
            "Paid": "✓" if r["charged"] else "✗",
            "Comment": r.get("comment", "")
        } for r in rows])
        
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(rows)} no-shows")



def page_search():
    st.header("Search Reservations")
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        search_type = st.selectbox(
            "Search by",
            [
                
                "Room Number",
                "Guest Name",
                "Reservation No",
                "Main Client",
                "Channel",
                "All Fields"
            ]
        )
    
    with col2:
        q = st.text_input(
            "Search term",
            placeholder=f"Enter {search_type.lower()}...",
            key="search_input"
        )
    
    if not q:
        st.info("Enter a search term to find reservations.")
        return
    
    # Build query based on search type
    like_pattern = f"%{q}%"
    
    if search_type == "Room Number":
        room_number = q.strip()
        rows = db.search_reservations_by_room_number(room_number)

    elif search_type == "Guest Name":
        rows = db.fetch_all(
            """
            SELECT * FROM reservations
            WHERE guest_name LIKE ?
            ORDER BY arrival_date DESC
            LIMIT 500
            """,
            (like_pattern,),
        )
    elif search_type == "Reservation No":
        rows = db.fetch_all(
            """
            SELECT * FROM reservations
            WHERE reservation_no LIKE ?
            ORDER BY arrival_date DESC
            LIMIT 500
            """,
            (like_pattern,),
        )
    elif search_type == "Main Client":
        rows = db.fetch_all(
            """
            SELECT * FROM reservations
            WHERE main_client LIKE ?
            ORDER BY arrival_date DESC
            LIMIT 500
            """,
            (like_pattern,),
        )
    elif search_type == "Channel":
        rows = db.fetch_all(
            """
            SELECT * FROM reservations
            WHERE channel LIKE ?
            ORDER BY arrival_date DESC
            LIMIT 500
            """,
            (like_pattern,),
        )
    else:  # All Fields
        rows = db.search_reservations(q)
    
    # Display results
    if not rows:
        st.warning(f"No reservations found matching '{q}' in {search_type}.")
        return
    
    st.success(f"Found {len(rows)} reservation(s)")
    
    # Create display DataFrame
    df = pd.DataFrame([dict(r) for r in rows])
    df_clean = clean_numeric_columns(df, ["room_number", "reservation_no"])
    
    # Select and format columns for display
    display_cols = [
        "arrival_date", "depart_date", "guest_name", "room_number",
        "reservation_no", "channel", "rate_code", "main_client", "main_remark"
    ]
    
    # Only show columns that exist
    display_cols = [col for col in display_cols if col in df_clean.columns]
    
    st.dataframe(
        df_clean[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "arrival_date": st.column_config.TextColumn("Arrival"),
            "depart_date": st.column_config.TextColumn("Departure"),
            "guest_name": st.column_config.TextColumn("Guest Name"),
            "room_number": st.column_config.TextColumn("Room"),
            "reservation_no": st.column_config.TextColumn("Res No"),
            "channel": st.column_config.TextColumn("Channel"),
            "rate_code": st.column_config.TextColumn("Rate"),
            "main_client": st.column_config.TextColumn("Client"),
            "main_remark": st.column_config.TextColumn("Remarks"),
        }
    )
    
    # Show detailed view option
    with st.expander("📋 View Full Details"):
        for idx, row in enumerate(rows, 1):
            with st.container():
                st.markdown(f"### {idx}. {row['guest_name']} - Room {format_room_number(row.get('room_number', 'Not assigned'))}")
                
                col1, col2, col3, col4 = st.columns(4)
                col1.write(f"**Arrival:** {format_date(row['arrival_date'])}")
                col2.write(f"**Departure:** {format_date(row['depart_date'])}")
                col3.write(f"**Nights:** {row.get('nights', 'N/A')}")
                col4.write(f"**Guests:** {row.get('total_guests', 'N/A')}")
                
                col1, col2, col3 = st.columns(3)
                col1.write(f"**Res No:** {row.get('reservation_no', 'N/A')}")
                col2.write(f"**Channel:** {row.get('channel', 'N/A')}")
                col3.write(f"**Meal Plan:** {row.get('meal_plan', 'N/A')}")
                
                if row.get('main_remark'):
                    st.info(f"📝 {row['main_remark']}")
                
                if row.get('main_client'):
                    st.caption(f"Client: {row['main_client']}")
                
                st.divider()

def page_room_list():
    st.header("Room List")
    st.caption("Manage room inventory and room status (CLEAN / DIRTY / VACANT / OCCUPIED)")

    df = db.read_table("rooms")
    if df.empty:
        st.info("No rooms yet (should have been seeded).")
        return

    df_display = df[["room_number", "status"]].copy()
    df_display = df_display.sort_values(
        by="room_number", key=lambda s: pd.to_numeric(s, errors="coerce")
    )
    df_display.columns = ["Room", "Status"]

    st.subheader("Rooms")

    edited = st.data_editor(
        df_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Status": st.column_config.SelectboxColumn(
                "Status",
                options=["VACANT", "OCCUPIED", "CLEAN", "DIRTY"],
            )
        },
    )

    if st.button("Save room statuses", type="primary", use_container_width=True):
        for _, row in edited.iterrows():
            rn = str(row["Room"]).strip()
            status = row["Status"]
            db.set_room_status(rn, status)
        st.success("Room statuses updated.")
        st.rerun()

    st.caption(f"Total: {len(df)} rooms")


def page_spare_rooms():
    st.header("Spare Twin rooms")
    st.caption("Mark rooms as spare twins for a specific date (e.g. Spare Twin List).")

    target = st.date_input("Date", value=date.today(), key="spare_date")

    all_rooms = db.get_all_rooms()
    if not all_rooms:
        st.info("No rooms in inventory yet. Fill the Room list first.")
        return

    current_spare = db.get_spare_rooms_for_date(target)
    twin_rooms = set(db.get_twin_rooms())

    st.subheader("Select spare twins rooms")
    selected = st.multiselect(
        "spare twins rooms for this date",
        options=all_rooms,
        default=current_spare,
        help="Include twin and non-twin rooms; twin rooms are listed below.",
    )

    if twin_rooms:
        st.caption(
            "Twin rooms (for reference): " +
            ", ".join(sorted(twin_rooms, key=int))
        )

    if st.button("Save spare twins rooms"):
        db.set_spare_rooms_for_date(target, selected)
        st.success(f"Saved {len(selected)} spare twins rooms for {target}.")

    saved = db.get_spare_rooms_for_date(target)
    st.subheader("Saved spare twins rooms")
    if not saved:
        st.info("No spare twins rooms saved for this date.")
    else:
        st.write(", ".join(saved))


def page_parking():
    st.header("Parking Overview")
    today = st.date_input("Date", value=date.today(), key="parking_date")
    
    inhouse = db.get_inhouse(today)
    
    if not inhouse:
        st.info("No in-house guests for this date.")
        return
    
    inhouse_dicts = [dict(r) for r in inhouse]
    
    # Filter: has parking_space OR "parking" mentioned in notes
    guests_with_parking = [r for r in inhouse_dicts if r.get("parking_space") or (r.get("comment") and ("parking" in r.get("comment", "").lower() or "poa" in r.get("comment", "").lower()))]
    guests_without_parking = [r for r in inhouse_dicts if r not in guests_with_parking]
    
    col1, col2 = st.columns(2)
    col1.metric("Total In-House", len(inhouse_dicts))
    col2.metric("With Parking", len(guests_with_parking))
    
    if guests_with_parking:
        st.subheader("Parking Assigned")
        df_parking = pd.DataFrame([{
            "Space": r.get("parking_space", "See notes"),
            "Room": r["room_number"],
            "Guest Name": r["guest_name"],
            "Plate": r.get("parking_plate", ""),
            "Notes": r.get("comment", "") or r.get("parking_notes", "")
        } for r in guests_with_parking])
        df_parking = clean_numeric_columns(df_parking, ["Room"]) 
        st.dataframe(df_parking, use_container_width=True, hide_index=True)
    else:
        st.info("No parking spaces assigned yet.")
    
    if guests_without_parking:
        st.divider()
        st.subheader("Guests without parking")
        
        for idx, guest in enumerate(guests_without_parking, 1):
            with st.expander(f"{idx}. Room {guest['room_number']} - {guest['guest_name']}", expanded=False):
                col1, col2, col3 = st.columns(3)
                space = col1.text_input("Space", key=f"space_{guest['stay_id']}")
                plate = col2.text_input("Plate", key=f"plate_{guest['stay_id']}")
                notes = col3.text_input("Notes", key=f"notes_{guest['stay_id']}")
                
                if st.button("Assign Parking", key=f"assign_{guest['stay_id']}"):
                    if space:
                        db.update_parking_for_stay(guest["stay_id"], space, plate, notes)
                        st.success(f"Parking {space} assigned to room {guest['room_number']}")
                        st.rerun()
                    else:
                        st.warning("Enter parking space number")


def page_db_viewer():
    

    st.header("Database Viewer")
    
    
    # Database statistics
    st.subheader("Database Overview")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    reservations_count = db.fetch_one("SELECT COUNT(*) as cnt FROM reservations")
    stays_count = db.fetch_one("SELECT COUNT(*) as cnt FROM stays")
    rooms_count = db.fetch_one("SELECT COUNT(*) as cnt FROM rooms")
    tasks_count = db.fetch_one("SELECT COUNT(*) as cnt FROM tasks")
    no_shows_count = db.fetch_one("SELECT COUNT(*) as cnt FROM no_shows")
    spare_count = db.fetch_one("SELECT COUNT(*) as cnt FROM spare_rooms")
    
    col1.metric("Reservations", reservations_count['cnt'])
    col2.metric("Stays", stays_count['cnt'])
    col3.metric("Rooms", rooms_count['cnt'])
    col4.metric("Tasks", tasks_count['cnt'])
    col5.metric("No Shows", no_shows_count['cnt'])
    col6.metric("Spare Rooms", spare_count['cnt'])
    
    st.divider()
    
    # Table viewer with filters
    st.subheader("View & Search Tables")
    
    col_table, col_limit = st.columns([3, 1])
    table = col_table.selectbox("Select table", 
                                ["reservations", "stays", "rooms", "tasks", "no_shows", "spare_rooms"])
    limit = col_limit.number_input("Rows to show", min_value=10, max_value=1000, value=100, step=10)
    
    # Search box
    search = st.text_input(f"Search in {table}", placeholder="Enter search term...")
    
    # Fetch data
    if search:
        # Simple search across all text columns
        df = db.read_table(table)
        mask = df.astype(str).apply(lambda row: row.str.contains(search, case=False).any(), axis=1)
        df = df[mask].head(limit)
    else:
        df = db.read_table(table)
        if limit:
            df = df.head(limit)

    
    if df.empty:
        st.info(f"No rows in {table}")
    else:
        # Clean numeric columns
        if table == "reservations":
            df = clean_numeric_columns(df, ["id", "reservation_no", "adults", "children", "total_guests", "nights"])
        elif table == "stays":
            df = clean_numeric_columns(df, ["id", "reservation_id"])
        elif table == "tasks":
            df = clean_numeric_columns(df, ["id"])
        elif table == "no_shows":
            df = clean_numeric_columns(df, ["id"])
        
        st.caption(f"Showing {len(df)} of {reservations_count['cnt'] if table == 'reservations' else '...'} total rows")
        st.dataframe(df, use_container_width=True, height=500)
        
        # Export button
        csv = df.to_csv(index=False)
        st.download_button(
            f"Download {table} as CSV",
            data=csv,
            file_name=f"{table}_{date.today().isoformat()}.csv",
            mime="text/csv"
        )
    
    DB_PATH = "hotel_fo.db"  # or hotel_fo_TEST.db
    
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'rb') as f:
            backup_data = f.read()
        
        st.download_button(
            "⬇ DOWNLOAD LIVE DATABASE NOW",
            data=backup_data,
            file_name=f"hotel_PRODUCTION_{datetime.now().strftime('%Y%m%d_%H%M')}.db",
            mime="application/octet-stream",
            type="primary"
        )
        st.success(f"Database size: {len(backup_data)/1024:.1f} KB")
        
def page_invoices():
    """
    Invoice generation page matching exact Excel template format.
    Features:
    - Auto-increment invoice number (starting 254000)
    - Date selector with guest dropdown
    - Multiple line items (multi-day stays)
    - PDF export
    """
    st.header("📋 Invoice Generation")
    
    # Get next invoice number
    next_inv = db.get_next_invoice_number()
    
    col1, col2 = st.columns([3, .5], gap="large")
    
    with col1:
        st.subheader("Invoice Details")
        
        # Invoice Number (auto-increment)
        invoice_no = st.number_input(
            "Invoice Number",
            value=next_inv,
            step=1,
            min_value=254000,
            format="%d"
        )
        
        # Invoice Date
        invoice_date = st.date_input("Invoice Date")
        
        st.divider()
        st.write("**Guest Information**")
        
        # Date-based guest selection
        guests_for_date = db.get_guests_for_date(invoice_date)
        guest_options = [f"{g['guest_name']} (Room {g['room_number']})" for g in guests_for_date]
        
        if not guest_options:
            st.warning("No guests for this date. Please select another date.")
            return
        
        selected_guest_str = st.selectbox(
            "Select Guest",
            guest_options,
            key="guest_selector"
        )
        
        # Extract guest name from selection
        selected_guest_name = selected_guest_str.split(" (Room")[0]
        
        # Get full reservation data
        res_data = db.get_reservation_by_guest_and_date(selected_guest_name, invoice_date)
        
        if res_data:
            guest_name = res_data.get("guest_name", "")
            room_no = res_data.get("room_number", "")
            reservation_id = res_data.get("id", "")
        else:
            st.error("Could not load guest data.")
            return
        
        # Display selected guest info
        st.info(f"✓ Selected: {guest_name} | Room: {room_no}")
        
        st.divider()
        st.write("**Billing Information**")
        
        # Line items approach - multiple dates for multi-day stays
        st.write("**Add Line Items**")

        # NEW: tax box
        tax_rate = st.number_input(
            "VAT rate (%)",
            min_value=0.0,
            max_value=100.0,
            value=20.0,
            step=0.5,
            key="invoice_tax_rate",
        )
        tax_factor = 1 + (tax_rate / 100.0)

        
        col_date, col_qty, col_price = st.columns(3)
        with col_date:
            line_date = st.date_input("Item Date", value=invoice_date, key="line_date")
        with col_qty:
            line_qty = st.number_input("Qty", value=1, min_value=1, step=1, key="line_qty")
        with col_price:
            line_price = st.number_input("Price per Unit (£)", value=119.00, step=0.01, key="line_price")
        
        line_desc = st.text_input(
            "Description",
            value="Bed and Breakfast",
            key="line_desc"
        )
        
        # Initialize session state for line items if not exists
        if "invoice_items" not in st.session_state:
            st.session_state.invoice_items = []
        
        col_add, col_clear = st.columns(2)
        with col_add:
            if st.button("+ Add Item", use_container_width=True):
                # use selected VAT rate
                net_price = line_price / tax_factor
                vat = line_price - net_price
                st.session_state.invoice_items.append({
                    "date": line_date,
                    "qty": line_qty,
                    "price_per_unit": line_price,
                    "description": line_desc,
                    "net_price": net_price,
                    "vat": vat,
                    "total": line_price
                })
                st.rerun()
        
        with col_clear:
            if st.button("Clear All", use_container_width=True):
                st.session_state.invoice_items = []
                st.rerun()
        
        # Show added items
        if st.session_state.invoice_items:
            st.divider()
            st.write("**Line Items Added:**")
            for idx, item in enumerate(st.session_state.invoice_items):
                col_remove, col_info = st.columns([0.5, 3])
                with col_remove:
                    if st.button("❌", key=f"remove_{idx}", use_container_width=True):
                        st.session_state.invoice_items.pop(idx)
                        st.rerun()
                with col_info:
                    st.caption(f"{item['date']} - {item['description']} - £{item['total']:.2f}")
            
            # Calculate totals
            total_net = sum(item['net_price'] for item in st.session_state.invoice_items)
            total_vat = sum(item['vat'] for item in st.session_state.invoice_items)
            total_amount = sum(item['total'] for item in st.session_state.invoice_items)
            
            st.divider()
            st.metric("Total Amount", f"£{total_amount:.2f}")
            
            # PDF Export button
            if st.button("📥 Download as PDF", use_container_width=True, type="primary"):
                pdf_bytes = generate_invoice_pdf(
                    invoice_no=invoice_no,
                    invoice_date=invoice_date,
                    guest_name=guest_name,
                    room_no=room_no,
                    items=st.session_state.invoice_items,
                    total_net=total_net,
                    total_vat=total_vat,
                    total_amount=total_amount
                )
                
                st.download_button(
                    "⬇️ Click to Download PDF",
                    data=pdf_bytes,
                    file_name=f"Invoice_{invoice_no}_{guest_name}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
        else:
            st.warning("⚠️ Add at least one line item to generate invoice")


def render_exact_invoice_preview(invoice_no, invoice_date, guest_name, room_no, 
                                 items, total_net, total_vat, total_amount):
    """
    Render invoice preview in EXACT Excel template format.
    NO HTML code visible - pure formatted display.
    """
    
    # Create HTML that matches Excel layout exactly
    items_html = ""
    for item in items:
        items_html += f"""
        <tr style="border: 1px solid #ccc; height: 20px;">
            <td style="padding: 1px; border: 1px solid #ccc; width: 15%; font-size: 12px;">{item['date'].strftime('%d/%m/%Y')}</td>
            <td style="padding: 1px; border: 1px solid #ccc; text-align: center; width: 8%; font-size: 12px;">{item['qty']}</td>
            <td style="padding: 1px; border: 1px solid #ccc; text-align: right; width: 15%; font-size: 12px;">£ {item['price_per_unit']:>9.2f}</td>
            <td style="padding: 1px; border: 1px solid #ccc; width: 25%; font-size: 12px;">{item['description']}</td>
            <td style="padding: 1px; border: 1px solid #ccc; text-align: right; width: 12%; font-size: 12px;">£ {item['net_price']:>9.2f}</td>
            <td style="padding: 1px; border: 1px solid #ccc; text-align: right; width: 12%; font-size: 12px;">£ {item['vat']:>9.2f}</td>
            <td style="padding: 1px; border: 1px solid #ccc; text-align: right; width: 13%; font-size: 12px; font-weight: bold;">£ {item['total']:>9.2f}</td>
        </tr>
        """
    
    html = f"""
    <style>
        .invoice-container {{ font-family: 'Arial', sans-serif; background: white; padding: 30px; line-height: 1.4; }}
        .header-title {{ font-size: 18px; font-weight: bold; color: #333; margin-bottom: 20px; }}
        .section-label {{ font-size: 11px; font-weight: bold; margin-top: 15px; margin-bottom: 8px; }}
        .guest-info {{ font-size: 11px; line-height: 1.6; margin-bottom: 20px; }}
        .invoice-meta {{ display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 15px; }}
        th {{ background-color: #f0f0f0; border: 1px solid #ccc; padding: 8px; text-align: left; font-weight: bold; font-size: 11px; }}
        td {{ border: 1px solid #ccc; padding: 8px; }}
        .totals-section {{ background-color: #f9f9f9; padding: 15px; margin-bottom: 15px; border: 1px solid #ccc; }}
        .total-row {{ display: flex; justify-content: space-between; font-size: 12px; padding: 8px 0; border-bottom: 1px solid #ddd; }}
        .total-row-bold {{ display: flex; justify-content: space-between; font-size: 12px; padding: 8px 0; font-weight: bold; background-color: #003366; color: white; padding: 12px; }}
        .vat-breakdown {{ background-color: #f0f0f0; padding: 12px; margin-bottom: 15px; border: 1px solid #ccc; }}
        .vat-row {{ display: flex; justify-content: space-between; font-size: 11px; padding: 6px 0; }}
        .payment-section {{ font-size: 10px; line-height: 1.8; }}
        .bank-table {{ width: 100%; font-size: 10px; margin: 10px 0; }}
        .bank-table td {{ border: none; padding: 4px 0; }}
    </style>
    
    <div class="invoice-container">
        
        <!-- Header -->
        <div class="header-title">INVOICE</div>
        
        <!-- Supplier Section -->
        <div class="section-label">Supplier</div>
        <div class="guest-info" style="margin-left: 20px;">
            <strong>St Wulfstan ltd</strong><br>
            T/A Radisson BLU Hotel, Bristol<br>
            Broad Quay<br>
            Bristol<br>
            BS1 4BY
        </div>
        
        <!-- Invoice To Section -->
        <div class="section-label">Invoice to:</div>
        <div class="guest-info" style="margin-left: 20px;">
            <strong>{guest_name}</strong><br>
            Room {room_no}
        </div>
        
        <!-- Invoice Meta -->
        <div class="invoice-meta">
        Invoice number:
            <div>
                <strong>{invoice_no}</strong>
            </div>
            <div>
                <span class="section-label">Date :</span>
                <strong>{invoice_date.strftime('%d/%m/%Y')}</strong>
            </div>
        </div>
        
        <!-- Items Table -->
        <table>
            <thead>
                <tr>
                    <th style="width: 15%;">Date</th>
                    <th style="width: 8%; text-align: center;">Qty</th>
                    <th style="width: 15%; text-align: right;">Price Gross/unit</th>
                    <th style="width: 25%;">Description</th>
                    <th style="width: 12%; text-align: right;">Net Price</th>
                    <th style="width: 12%; text-align: right;">VAT</th>
                    <th style="width: 13%; text-align: right;">Total Price</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
                <tr style="border: 1px solid #ccc; background-color: #f9f9f9; font-weight: bold; height: 22px;">
                    <td colspan="4" style="border: 1px solid #ccc; text-align: right; padding: 8px;">Total</td>
                    <td style="border: 1px solid #ccc; text-align: right; padding: 8px;">£ {total_net:>9.2f}</td>
                    <td style="border: 1px solid #ccc; text-align: right; padding: 8px;">£ {total_vat:>9.2f}</td>
                    <td style="border: 1px solid #ccc; text-align: right; padding: 8px;">£ {total_amount:>9.2f}</td>
                </tr>
            </tbody>
        </table>
        
        <!-- VAT Breakdown -->
        <div class="vat-breakdown">
            <div class="section-label" style="margin-top: 0;">VAT Breakdown</div>
            <div class="vat-row">
                <span>Vatable Amount (excl VAT)</span>
                <span>£ {total_net:>15.2f}</span>
            </div>
            <div class="vat-row">
                <span>Non Vatable Amount</span>
                <span>£ {0:>15.2f}</span>
            </div>
            <div class="vat-row" style="font-weight: bold; border-top: 1px solid #ccc; padding-top: 8px;">
                <span>VAT @ 20.00%</span>
                <span>£ {total_vat:>15.2f}</span>
            </div>
            <div class="vat-row" style="font-weight: bold; background-color: #003366; color: white; margin-top: 8px; padding: 8px; margin-left: -12px; margin-right: -12px; margin-bottom: -12px;">
                <span>TOTAL BILL</span>
                <span>£ {total_amount:>15.2f}</span>
            </div>
        </div>
        
        <!-- Payment Details -->
        <div class="payment-section">
            <p><strong>Please pay to St Wulfstan LTD "Radisson BLU Hotel Bristol" account</strong></p>
            
            <p style="margin-top: 12px;"><strong>Our bank account details for CHAPS and BACS payments are:</strong></p>
            
            <table class="bank-table">
                <tr>
                    <td style="width: 30%;"><strong>Account name:</strong></td>
                    <td>St Wulfstan ltd</td>
                </tr>
                <tr>
                    <td><strong>Account number:</strong></td>
                    <td>36744760</td>
                    <td style="padding-left: 40px;"><strong>Sort code:</strong></td>
                    <td>30-65-41</td>
                </tr>
                <tr>
                    <td><strong>IBAN Code:</strong></td>
                    <td colspan="3">GB98 LOYD 3065 4136 7447 60</td>
                </tr>
                <tr>
                    <td><strong>BIC Code:</strong></td>
                    <td colspan="3">LOYDGB21682</td>
                </tr>
            </table>
            
            <div style="border-top: 1px solid #ccc; padding-top: 8px; margin-top: 8px; font-size: 9px;">
                <p style="margin: 4px 0;">Company Reg. No: 6824436</p>
                <p style="margin: 4px 0;">VAT Reg. No: 979243179</p>
            </div>
        </div>
        
    </div>
    """
    
    st.markdown(html, unsafe_allow_html=True)


def generate_invoice_pdf(invoice_no, invoice_date, guest_name, room_no, 
                        items, total_net, total_vat, total_amount):
    """
    Generate PDF invoice matching exact Excel template format.
    Uses reportlab for PDF generation.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm, mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        from reportlab.lib import colors
        
        buffer = BytesIO()
        
        # Create PDF
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, 
                               leftMargin=15*mm, rightMargin=15*mm)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#003366'),
            spaceAfter=6,
            alignment=TA_CENTER
        )
        
        label_style = ParagraphStyle(
            'Label',
            parent=styles['Normal'],
            fontSize=10,
            fontName='Helvetica-Bold',
            spaceAfter=4
        )
        
        # Title
        title = Paragraph("INVOICE", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.3*cm))
        
        # Supplier
        supplier = Paragraph("<b>Supplier</b>", label_style)
        elements.append(supplier)
        supplier_text = Paragraph(
            "St Wulfstan ltd<br/>T/A Radisson BLU Hotel, Bristol<br/>"
            "Broad Quay<br/>Bristol<br/>BS1 4BY",
            styles['Normal']
        )
        elements.append(supplier_text)
        elements.append(Spacer(1, 0.3*cm))
        
        # Invoice To
        inv_to = Paragraph("<b>Invoice to:</b>", label_style)
        elements.append(inv_to)
        inv_to_text = Paragraph(
            f"<b>{guest_name}</b><br/>Room {room_no}",
            styles['Normal']
        )
        elements.append(inv_to_text)
        elements.append(Spacer(1, 0.3*cm))
        
        # Invoice Meta
                # Invoice Meta
        meta_data = [
            [
                Paragraph(f"<b>Invoice number :</b><br/>{invoice_no}", styles['Normal']),
                Paragraph(f"<b>Date :</b><br/>{invoice_date.strftime('%d/%m/%Y')}", styles['Normal'])
            ]
        ]
        meta_table = Table(meta_data, colWidths=[9.5*cm, 6.5*cm])
        meta_table.setStyle(TableStyle([
            ('ALIGN', (-1, 0), (0, -1), 'LEFT'),    # left cell (invoice no)
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),    # date cell, still left-aligned
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))

        elements.append(meta_table)
        elements.append(Spacer(1, 0.3*cm))
        
        # Items Table Data
        table_data = [
            ['Date', 'Qty', 'Price Gross/unit', 'Description', 'Net Price', 'VAT', 'Total Price']
        ]
        
        for item in items:
            table_data.append([
                item['date'].strftime('%d/%m/%Y'),
                str(item['qty']),
                f"£ {item['price_per_unit']:.2f}",
                item['description'],
                f"£ {item['net_price']:.2f}",
                f"£ {item['vat']:.2f}",
                f"£ {item['total']:.2f}"
            ])
        
        # Add totals row
        table_data.append([
            '', '', '', 'Total',
            f"£ {total_net:.2f}",
            f"£ {total_vat:.2f}",
            f"£ {total_amount:.2f}"
        ])
        
        # Create table
                # Create table
        items_table = Table(
            table_data,
            colWidths=[
                2.2*cm,   # Date  (slightly wider, but not huge)
                1.0*cm,   # Qty
                3.0*cm,   # Price Gross per Unit
                5.0*cm,   # Description
                2.2*cm,   # Net Price
                2.2*cm,   # VAT
                2.4*cm,   # Total Price
            ],
        )
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            # Left-align first 4 columns, right-align numeric ones
            ('ALIGN', (0, 0), (3, -1), 'LEFT'),
            ('ALIGN', (4, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f9f9f9')),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Slightly reduce side padding so text doesn’t crowd into next column
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))

        elements.append(items_table)
        elements.append(Spacer(1, 0.3*cm))
        
        # VAT Breakdown
        vat_header = Paragraph("<b>VAT Breakdown</b>", label_style)
        elements.append(vat_header)
        
        vat_data = [
            [Paragraph("Vatable Amount (excl VAT)", styles['Normal']), Paragraph(f"£ {total_net:.2f}", styles['Normal'])],
            [Paragraph("Non Vatable Amount", styles['Normal']), Paragraph(f"£ 0.00", styles['Normal'])],
            [Paragraph("<b>VAT @ 20.00%</b>", styles['Normal']), Paragraph(f"<b>£ {total_vat:.2f}</b>", styles['Normal'])],
            [Paragraph("<b>TOTAL BILL</b>", ParagraphStyle('Bold', parent=styles['Normal'], textColor=colors.white, fontName='Helvetica-Bold')), 
             Paragraph(f"<b>£ {total_amount:.2f}</b>", ParagraphStyle('Bold', parent=styles['Normal'], textColor=colors.white, fontName='Helvetica-Bold'))]
        ]
        
        vat_table = Table(vat_data, colWidths=[12*cm, 3*cm])
        vat_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 0), (-1, 2), [colors.white, colors.white, colors.white]),
            ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#003366')),
            ('TEXTCOLOR', (0, 3), (-1, 3), colors.white),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(vat_table)
        elements.append(Spacer(1, 0.5*cm))
        
        # Payment Details
        payment_header = Paragraph("<b>Please pay to St Wulfstan LTD \"Radisson BLU Hotel Bristol\" account</b>", 
                                 ParagraphStyle('PaymentHeader', parent=styles['Normal'], fontSize=9, spaceAfter=6))
        elements.append(payment_header)
        
        bank_header = Paragraph("<b>Our bank account details for CHAPS and BACS payments are:</b>", 
                              ParagraphStyle('BankHeader', parent=styles['Normal'], fontSize=9, spaceAfter=6))
        elements.append(bank_header)
        
        bank_data = [
            [Paragraph("<b>Account name:</b>", styles['Normal']), "St Wulfstan ltd"],
            [Paragraph("<b>Account number:</b>", styles['Normal']), "36744760", Paragraph("<b>Sort code:</b>", styles['Normal']), "30-65-41"],
            [Paragraph("<b>IBAN Code:</b>", styles['Normal']), "GB98 LOYD 3065 4136 7447 60"],
            [Paragraph("<b>BIC Code:</b>", styles['Normal']), "LOYDGB21682"],
        ]
        
        bank_table = Table(bank_data)
        bank_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(bank_table)
        elements.append(Spacer(1, 0.3*cm))
        
        # Company Info
        company_info = Paragraph(
            "Company Reg. No: 6824436<br/>VAT Reg. No: 979243179",
            ParagraphStyle('CompanyInfo', parent=styles['Normal'], fontSize=8)
        )
        elements.append(company_info)
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()
        
    except ImportError:
        st.error("⚠️ reportlab not installed. Install with: pip install reportlab")
        return None
    except Exception as e:
        st.error(f"⚠️ Error generating PDF: {str(e)}")
        return None

# def render_invoice_preview(invoice_no, invoice_date, guest_name, room_no, 
#                           net_amount, tax_rate, tax_amount, total_amount, 
#                           service_desc, quantity):
#     """
#     Display invoice in Streamlit using styled HTML/CSS
#     Matches Radisson BLU template format
#     """
    
#     # Radisson BLU styling
#     html_content = f"""
#     <div style="background: white; padding: 40px; font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; border: 1px solid #ddd;">
        
#         <!-- Header -->
#         <div style="text-align: center; margin-bottom: 30px; border-bottom: 3px solid #003366; padding-bottom: 20px;">
#             <h1 style="color: #003366; margin: 0; font-size: 28px;">INVOICE</h1>
#             <p style="color: #666; margin: 5px 0; font-size: 12px;">Radisson BLU Hotel, Bristol</p>
#         </div>
        
#         <!-- Invoice To Section -->
#         <div style="margin-bottom: 30px;">
#             <div style="font-weight: bold; margin-bottom: 5px;">Invoice to:</div>
#             <div style="margin-left: 20px; line-height: 1.8;">
#                 <div><strong>{guest_name}</strong></div>
#                 <div>Room: {room_no}</div>
#                 <div style="margin-top: 15px; font-size: 12px; color: #666;">
#                     <div>St Wulfstan ltd</div>
#                     <div>T/A Radisson BLU Hotel, Bristol</div>
#                     <div>Broad Quay</div>
#                     <div>Bristol</div>
#                     <div>BS1 4BY</div>
#                 </div>
#             </div>
#         </div>
        
#         <!-- Invoice Details -->
#         <div style="display: flex; justify-content: space-between; margin-bottom: 30px; font-size: 14px;">
#             <div>
#                 <div style="color: #666;">Invoice number:</div>
#                 <div style="font-weight: bold; font-size: 16px;">{invoice_no}</div>
#             </div>
#             <div>
#                 <div style="color: #666;">Date:</div>
#                 <div style="font-weight: bold; font-size: 16px;">{invoice_date.strftime('%d %b %Y')}</div>
#             </div>
#         </div>
        
#         <!-- Items Table -->
#         <div style="margin-bottom: 30px;">
#             <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
#                 <thead>
#                     <tr style="background-color: #f0f0f0; border: 1px solid #ccc;">
#                         <th style="padding: 10px; text-align: left; border: 1px solid #ccc;">Date</th>
#                         <th style="padding: 10px; text-align: center; border: 1px solid #ccc;">Qty</th>
#                         <th style="padding: 10px; text-align: right; border: 1px solid #ccc;">Price per Unit</th>
#                         <th style="padding: 10px; text-align: left; border: 1px solid #ccc;">Description</th>
#                         <th style="padding: 10px; text-align: right; border: 1px solid #ccc;">Net Price</th>
#                         <th style="padding: 10px; text-align: right; border: 1px solid #ccc;">VAT</th>
#                         <th style="padding: 10px; text-align: right; border: 1px solid #ccc;">Total</th>
#                     </tr>
#                 </thead>
#                 <tbody>
#                     <tr style="border: 1px solid #ccc;">
#                         <td style="padding: 10px; border: 1px solid #ccc;">{invoice_date.strftime('%Y-%m-%d')}</td>
#                         <td style="padding: 10px; text-align: center; border: 1px solid #ccc;">{quantity}</td>
#                         <td style="padding: 10px; text-align: right; border: 1px solid #ccc;">£{(net_amount/quantity):.2f}</td>
#                         <td style="padding: 10px; border: 1px solid #ccc;">{service_desc}</td>
#                         <td style="padding: 10px; text-align: right; border: 1px solid #ccc;">£{net_amount:.2f}</td>
#                         <td style="padding: 10px; text-align: right; border: 1px solid #ccc;">£{tax_amount:.2f}</td>
#                         <td style="padding: 10px; text-align: right; border: 1px solid #ccc; font-weight: bold;">£{(net_amount + tax_amount):.2f}</td>
#                     </tr>
#                 </tbody>
#             </table>
#         </div>
        
#         <!-- Totals Section -->
#         <div style="background-color: #f9f9f9; padding: 20px; border: 1px solid #ccc; margin-bottom: 30px;">
#             <table style="width: 100%; font-size: 14px;">
#                 <tr>
#                     <td style="text-align: right; padding: 8px; width: 50%;">Subtotal (Net):</td>
#                     <td style="text-align: right; padding: 8px; font-weight: bold;">£{net_amount:.2f}</td>
#                 </tr>
#                 <tr>
#                     <td style="text-align: right; padding: 8px;">VAT @ {tax_rate}%:</td>
#                     <td style="text-align: right; padding: 8px; font-weight: bold;">£{tax_amount:.2f}</td>
#                 </tr>
#                 <tr style="background-color: #003366; color: white; font-size: 16px;">
#                     <td style="text-align: right; padding: 12px; font-weight: bold;">TOTAL BILL:</td>
#                     <td style="text-align: right; padding: 12px; font-weight: bold;">£{total_amount:.2f}</td>
#                 </tr>
#             </table>
#         </div>
        
#         <!-- VAT Breakdown -->
#         <div style="background-color: #f0f0f0; padding: 15px; border: 1px solid #ccc; margin-bottom: 20px; font-size: 13px;">
#             <div style="font-weight: bold; margin-bottom: 10px;">VAT Breakdown</div>
#             <table style="width: 100%; font-size: 12px;">
#                 <tr>
#                     <td style="padding: 5px;">Vatable Amount (excl VAT):</td>
#                     <td style="text-align: right; padding: 5px;">£{net_amount:.2f}</td>
#                 </tr>
#                 <tr>
#                     <td style="padding: 5px;">Non Vatable Amount:</td>
#                     <td style="text-align: right; padding: 5px;">£0.00</td>
#                 </tr>
#                 <tr style="font-weight: bold;">
#                     <td style="padding: 5px;">VAT @ {tax_rate}%:</td>
#                     <td style="text-align: right; padding: 5px;">£{tax_amount:.2f}</td>
#                 </tr>
#             </table>
#         </div>
        
#         <!-- Payment Details -->
#         <div style="font-size: 12px; line-height: 1.6; color: #333;">
#             <p style="margin: 10px 0; font-weight: bold;">Please pay to St Wulfstan LTD "Radisson BLU Hotel Bristol" account</p>
            
#             <p style="margin: 15px 0; font-weight: bold;">Our bank account details for CHAPS and BACS payments are:</p>
            
#             <table style="font-size: 12px; width: 100%; margin-bottom: 15px;">
#                 <tr>
#                     <td style="padding: 5px; width: 40%; font-weight: bold;">Account name:</td>
#                     <td style="padding: 5px;">St Wulfstan ltd</td>
#                 </tr>
#                 <tr>
#                     <td style="padding: 5px; font-weight: bold;">Account number:</td>
#                     <td style="padding: 5px;">36744760</td>
#                     <td style="padding: 5px; font-weight: bold;">Sort code:</td>
#                     <td style="padding: 5px;">30-65-41</td>
#                 </tr>
#                 <tr>
#                     <td style="padding: 5px; font-weight: bold;">IBAN Code:</td>
#                     <td colspan="3" style="padding: 5px;">GB98 LOYD 3065 4136 7447 60</td>
#                 </tr>
#                 <tr>
#                     <td style="padding: 5px; font-weight: bold;">BIC Code:</td>
#                     <td colspan="3" style="padding: 5px;">LOYDGB21682</td>
#                 </tr>
#             </table>
            
#             <div style="border-top: 1px solid #ccc; padding-top: 10px; margin-top: 10px;">
#                 <div>Company Reg. No: 6824436</div>
#                 <div>VAT Reg. No: 979243179</div>
#             </div>
#         </div>
        
#     </div>
#     """
    
#     st.markdown(html_content, unsafe_allow_html=True)


def generate_invoice_html(invoice_no, invoice_date, guest_name, room_no, 
                         net_amount, tax_rate, tax_amount, total_amount, 
                         service_desc, quantity):
    """
    Generate complete printable HTML invoice with all styling
    """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Invoice {invoice_no}</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: Arial, sans-serif;
                background: #f5f5f5;
                padding: 20px;
            }}
            
            .invoice-container {{
                background: white;
                padding: 50px;
                max-width: 900px;
                margin: 0 auto;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
            }}
            
            .header {{
                text-align: center;
                margin-bottom: 40px;
                border-bottom: 3px solid #003366;
                padding-bottom: 20px;
            }}
            
            .header h1 {{
                color: #003366;
                font-size: 32px;
                margin-bottom: 5px;
            }}
            
            .header p {{
                color: #666;
                font-size: 12px;
            }}
            
            .invoice-to {{
                margin-bottom: 30px;
            }}
            
            .invoice-to label {{
                font-weight: bold;
                display: block;
                margin-bottom: 8px;
            }}
            
            .invoice-to-content {{
                margin-left: 20px;
                line-height: 1.8;
            }}
            
            .invoice-to-content strong {{
                display: block;
                font-size: 14px;
            }}
            
            .company-details {{
                font-size: 11px;
                color: #666;
                margin-top: 10px;
            }}
            
            .invoice-meta {{
                display: flex;
                justify-content: space-between;
                margin-bottom: 30px;
                font-size: 13px;
            }}
            
            .invoice-meta div {{
                color: #666;
            }}
            
            .invoice-meta strong {{
                display: block;
                font-size: 16px;
                color: #333;
                margin-top: 3px;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 20px;
                font-size: 13px;
            }}
            
            thead {{
                background-color: #f0f0f0;
            }}
            
            th, td {{
                border: 1px solid #ccc;
                padding: 12px;
                text-align: left;
            }}
            
            th {{
                font-weight: bold;
                background-color: #f0f0f0;
            }}
            
            td.number {{
                text-align: right;
            }}
            
            .totals {{
                background-color: #f9f9f9;
                padding: 20px;
                border: 1px solid #ccc;
                margin-bottom: 20px;
            }}
            
            .totals-table {{
                width: 100%;
                font-size: 13px;
            }}
            
            .totals-table tr {{
                border: none;
            }}
            
            .totals-table td {{
                border: none;
                padding: 8px;
            }}
            
            .totals-table td:first-child {{
                text-align: right;
                width: 60%;
            }}
            
            .totals-table td:last-child {{
                text-align: right;
                font-weight: bold;
            }}
            
            .total-row {{
                background-color: #003366 !important;
                color: white !important;
                font-size: 16px;
                font-weight: bold;
            }}
            
            .vat-breakdown {{
                background-color: #f0f0f0;
                padding: 15px;
                border: 1px solid #ccc;
                margin-bottom: 20px;
                font-size: 12px;
            }}
            
            .vat-breakdown h4 {{
                font-weight: bold;
                margin-bottom: 10px;
                font-size: 13px;
            }}
            
            .payment-details {{
                font-size: 11px;
                line-height: 1.6;
                color: #333;
            }}
            
            .payment-details p {{
                margin: 10px 0;
            }}
            
            .payment-details strong {{
                font-weight: bold;
            }}
            
            .bank-details {{
                font-size: 11px;
                margin: 15px 0;
            }}
            
            .company-reg {{
                border-top: 1px solid #ccc;
                padding-top: 10px;
                margin-top: 10px;
                font-size: 11px;
            }}
            
            @media print {{
                body {{
                    background: white;
                    padding: 0;
                }}
                .invoice-container {{
                    box-shadow: none;
                    max-width: 100%;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="invoice-container">
            
            <!-- Header -->
            <div class="header">
                <h1>INVOICE</h1>
                <p>Radisson BLU Hotel, Bristol</p>
            </div>
            
            <!-- Invoice To -->
            <div class="invoice-to">
                <label>Invoice to:</label>
                <div class="invoice-to-content">
                    <strong>{guest_name}</strong>
                    <div>Room: {room_no}</div>
                    <div class="company-details">
                        <div>St Wulfstan ltd</div>
                        <div>T/A Radisson BLU Hotel, Bristol</div>
                        <div>Broad Quay</div>
                        <div>Bristol</div>
                        <div>BS1 4BY</div>
                    </div>
                </div>
            </div>
            
            <!-- Invoice Meta -->
            <div class="invoice-meta">
                <div>
                    Invoice number:
                    <strong>{invoice_no}</strong>
                </div>
                <div>
                    Date:
                    <strong>{invoice_date.strftime('%d %b %Y')}</strong>
                </div>
            </div>
            
            <!-- Items Table -->
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th style="text-align: center;">Qty</th>
                        <th style="text-align: right;">Price per Unit</th>
                        <th>Description</th>
                        <th style="text-align: right;">Net Price</th>
                        <th style="text-align: right;">VAT</th>
                        <th style="text-align: right;">Total</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>{invoice_date.strftime('%Y-%m-%d')}</td>
                        <td style="text-align: center;">{quantity}</td>
                        <td class="number">£{(net_amount/quantity):.2f}</td>
                        <td>{service_desc}</td>
                        <td class="number">£{net_amount:.2f}</td>
                        <td class="number">£{tax_amount:.2f}</td>
                        <td class="number"><strong>£{(net_amount + tax_amount):.2f}</strong></td>
                    </tr>
                </tbody>
            </table>
            
            <!-- Totals -->
            <div class="totals">
                <table class="totals-table">
                    <tr>
                        <td>Subtotal (Net):</td>
                        <td>£{net_amount:.2f}</td>
                    </tr>
                    <tr>
                        <td>VAT @ {tax_rate}%:</td>
                        <td>£{tax_amount:.2f}</td>
                    </tr>
                    <tr class="total-row">
                        <td>TOTAL BILL:</td>
                        <td>£{total_amount:.2f}</td>
                    </tr>
                </table>
            </div>
            
            <!-- VAT Breakdown -->
            <div class="vat-breakdown">
                <h4>VAT Breakdown</h4>
                <table class="totals-table">
                    <tr>
                        <td>Vatable Amount (excl VAT):</td>
                        <td>£{net_amount:.2f}</td>
                    </tr>
                    <tr>
                        <td>Non Vatable Amount:</td>
                        <td>£0.00</td>
                    </tr>
                    <tr>
                        <td><strong>VAT @ {tax_rate}%:</strong></td>
                        <td><strong>£{tax_amount:.2f}</strong></td>
                    </tr>
                </table>
            </div>
            
            <!-- Payment Details -->
            <div class="payment-details">
                <p><strong>Please pay to St Wulfstan LTD "Radisson BLU Hotel Bristol" account</strong></p>
                
                <p><strong>Our bank account details for CHAPS and BACS payments are:</strong></p>
                
                <div class="bank-details">
                    <p><strong>Account name:</strong> St Wulfstan ltd</p>
                    <p><strong>Account number:</strong> 36744760 <span style="margin-left: 40px;"><strong>Sort code:</strong> 30-65-41</span></p>
                    <p><strong>IBAN Code:</strong> GB98 LOYD 3065 4136 7447 60</p>
                    <p><strong>BIC Code:</strong> LOYDGB21682</p>
                </div>
                
                <div class="company-reg">
                    <p>Company Reg. No: 6824436</p>
                    <p>VAT Reg. No: 979243179</p>
                </div>
            </div>
            
        </div>
    </body>
    </html>
    """
    
    return html    
def page_admin_upload():
    st.header("Admin: Upload Database Data")
    
    # Add password protection
    password = st.text_input("Admin Password", type="password")
    if password != st.secrets.get("ADMIN_PASSWORD", "Raddison2025#"):
        st.warning("Enter admin password to access this page")
        return
    
    tab1, tab2, tab3 = st.tabs(["Upload Full DB", "Upload Stays CSV", "Download DB"])
    
    with tab1:
        st.subheader("Replace Entire Database")
        st.warning("⚠️ This will replace the entire database file")
        
        uploaded_db = st.file_uploader("Upload SQLite database (.db)", type=['db'], key="db_upload")
        
        if uploaded_db:
            st.info(f"File size: {uploaded_db.size / 1024:.1f} KB")
            
            if st.button("Replace Database", type="primary"):
                try:
                    # Backup current DB first
                    import shutil
                    backup_path = DBPATH + ".backup"
                    shutil.copy2(DBPATH, backup_path)
                    
                    # Replace with uploaded
                    with open(DBPATH, 'wb') as f:
                        f.write(uploaded_db.getbuffer())
                    
                    st.success("✅ Database replaced successfully!")
                    st.info("Reloading app...")
                    time.sleep(1)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Error: {str(e)}")
    
    with tab2:
        st.subheader("Import Stays from CSV")
        
        uploaded_csv = st.file_uploader("Upload stays CSV", type=['csv'], key="csv_upload")
        
        if uploaded_csv:
            import pandas as pd
            df = pd.read_csv(uploaded_csv)
            
            st.write(f"**Preview:** {len(df)} rows")
            st.dataframe(df.head(10))
            
            st.write("**Expected columns:** `id, reservation_id, room_number, status, checkin_planned, checkout_planned, checkin_actual, checkout_actual, parking_space, parking_plate, parking_notes`")
            
            if st.button("Import Stays", type="primary"):
                try:
                    with st.spinner("Importing stays..."):
                        count = 0
                        for _, row in df.iterrows():
                            db.execute(
                                """
                                INSERT OR REPLACE INTO stays (
                                    id, reservation_id, room_number, status,
                                    checkin_planned, checkout_planned,
                                    checkin_actual, checkout_actual,
                                    parking_space, parking_plate, parking_notes
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    row.get("id"),
                                    row.get("reservation_id"),
                                    row.get("room_number"),
                                    row.get("status", "CHECKED_IN"),
                                    row.get("checkin_planned"),
                                    row.get("checkout_planned"),
                                    row.get("checkin_actual"),
                                    row.get("checkout_actual"),
                                    row.get("parking_space", ""),
                                    row.get("parking_plate", ""),
                                    row.get("parking_notes", ""),
                                ),
                            )
                            count += 1
                        
                        st.success(f"✅ Imported {count} stays")
                    
                    # 1. Update room statuses based on stays
                    with st.spinner("Syncing room statuses..."):
                        db.sync_room_status_from_stays()
                        st.success("✅ Room statuses synced")
                    
                    # 2. Verify linkage between stays and reservations
                    with st.spinner("Verifying data linkage..."):
                        orphaned = db.fetch_one("""
                            SELECT COUNT(*) as cnt FROM stays s
                            LEFT JOIN reservations r ON s.reservation_id = r.id
                            WHERE r.id IS NULL
                        """)
                        
                        if orphaned['cnt'] > 0:
                            st.warning(f"⚠️ Found {orphaned['cnt']} stays without matching reservations")
                        else:
                            st.success("✅ All stays linked to reservations")
                    
                    # 3. Show summary by status
                    with st.spinner("Verifying data..."):
                        checked_in = db.fetch_one(
                            "SELECT COUNT(*) as cnt FROM stays WHERE status = 'CHECKED_IN'"
                        )
                        checked_out = db.fetch_one(
                            "SELECT COUNT(*) as cnt FROM stays WHERE status = 'CHECKED_OUT'"
                        )
                        occupied = db.fetch_one(
                            "SELECT COUNT(*) as cnt FROM rooms WHERE status = 'OCCUPIED'"
                        )
                        
                        # Check departures for today
                        today = date.today()
                        departures_today = db.fetch_one(
                            """
                            SELECT COUNT(*) as cnt
                            FROM reservations r
                            LEFT JOIN stays s ON s.reservation_id = r.id
                            WHERE date(r.depart_date) = date(?)
                            AND (s.status IS NULL OR s.status != 'CHECKED_OUT')
                            """,
                            (today.isoformat(),)
                        )
                        
                        st.info(f"""
                        **Data Summary:**
                        - Checked-in guests: {checked_in['cnt']}
                        - Already checked out: {checked_out['cnt']}
                        - Occupied rooms: {occupied['cnt']}
                        - Departures today: {departures_today['cnt']}
                        """)
                    
                    st.success("🎉 Stays imported successfully!")
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error importing: {str(e)}")
                    st.exception(e)
    with tab3:
        st.subheader("Download Live Database")
        st.info("Downloads a ZIP file containing the database file and CSV exports of all tables")
        
        if st.button("Generate Download Package", type="primary"):
            try:
                import zipfile
                import io
                import pandas as pd
                
                with st.spinner("Creating download package..."):
                    zip_buffer = io.BytesIO()
                    
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        # 1. Add database file
                        with open(DBPATH, 'rb') as db_file:
                            zip_file.writestr("hotelfo.db", db_file.read())
                        
                        # 2. Export tables to CSV
                        tables = ['reservations', 'stays', 'rooms', 'no_shows', 'spare_rooms', 'tasks']
                        
                        for table_name in tables:
                            try:
                                rows = db.fetch_all(f"SELECT * FROM {table_name}")
                                
                                if rows:
                                    df = pd.DataFrame([dict(row) for row in rows])
                                    csv_buffer = io.StringIO()
                                    df.to_csv(csv_buffer, index=False)
                                    zip_file.writestr(f"{table_name}.csv", csv_buffer.getvalue())
                                    st.success(f"✅ Exported {table_name}: {len(rows)} rows")
                                else:
                                    st.info(f"ℹ️ {table_name}: empty")
                                    
                            except Exception as e:
                                st.warning(f"⚠️ Could not export {table_name}: {str(e)}")
                    
                    zip_buffer.seek(0)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"hotelfo_backup_{timestamp}.zip"
                    
                    st.download_button(
                        label="⬇️ Download Database Package",
                        data=zip_buffer,
                        file_name=filename,
                        mime="application/zip",
                        use_container_width=True,
                    )
                    
                    st.success("🎉 Download package ready!")
                    
            except Exception as e:
                st.error(f"❌ Error creating download: {str(e)}")
                st.exception(e)
        st.divider()
        st.subheader("Database Viewer")
        page_db_viewer()



def main():
    st.set_page_config(
        page_title="Not-Radisson",
        page_icon="🏨",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    menu_options = {
    "Arrivals": page_arrivals,
    "In-House List": page_inhouse_list,
    "Checkout List": page_checkout_list,
    # ... other pages
    "Admin Upload": page_admin_upload,  # Add this
}

    # Initialize database here (after set_page_config)
    global db
    db = FrontOfficeDB(DBPATH)




    with st.sidebar:
        st.title("YesWeCan! Bristol")
        mode = "NEW LIVE MODE"
        st.markdown(f"**{mode}**")
        page = st.radio(
            "Navigate",
            [
                "Arrivals",
                "In-House List",
                "Check-out List",
                "Housekeeping Task-List",
                "Breakfast List",
                "Search",
                "Handover",
                "No Shows",
                "Room list",
                "Spare Twin rooms",
                "Parking",
                "Payments",
                "Invoices",        # ← ADD THIS
                "Admin",
            ],
        )





        st.markdown("---")
        st.caption("Welcome to YesWeCan! v1.0")

    if page == "Arrivals":
        page_arrivals()
    elif page == "In-House List":
        page_inhouse_list()
    elif page == "Check-out List":
        page_checkout_list()
    elif page == "Housekeeping Task-List":
        page_housekeeping()
    elif page == "Breakfast List":
        page_breakfast()
    elif page == "Search":
        page_search()
    elif page == "Handover":
        page_tasks_handover()
    elif page == "Payments":
        page_payments()
    elif page == "Invoices":
        page_invoices()


    elif page == "No Shows":
        page_no_shows()
    elif page == "Room list":
        page_room_list()
    elif page == "Spare Twin rooms":
        page_spare_rooms()
    elif page == "Parking":
        page_parking()
    elif page == "Admin":
        page_admin_upload()


if __name__ == "__main__":
    main()
