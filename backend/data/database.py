import sqlite3
import os
import math
from datetime import datetime
from werkzeug.security import generate_password_hash

from backend.config import Config


def get_db():
    if Config.DB_ENGINE == "postgres":
        return _get_postgres_conn()
    return _get_sqlite_conn()


def _get_sqlite_conn():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _get_postgres_conn():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(
        host=Config.POSTGRES_HOST,
        port=Config.POSTGRES_PORT,
        dbname=Config.POSTGRES_DB,
        user=Config.POSTGRES_USER,
        password=Config.POSTGRES_PASSWORD,
        cursor_factory=RealDictCursor,
    )
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clinics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            doctor TEXT,
            specialty TEXT,
            patients_waiting INTEGER DEFAULT 0,
            minutes_per_patient INTEGER DEFAULT 15,
            is_open INTEGER DEFAULT 0,
            latitude REAL DEFAULT 0,
            longitude REAL DEFAULT 0,
            address TEXT DEFAULT ''
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT,
            clinic_id INTEGER,
            is_arrived INTEGER DEFAULT 0,
            phone TEXT,
            specialty TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT,
            age INTEGER,
            blood_type TEXT,
            phone TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medical_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            filename TEXT,
            description TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            clinic_id INTEGER,
            booked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'waiting',
            arrived INTEGER DEFAULT 0,
            reviewed INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            clinic_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            clinic_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMP,
            FOREIGN KEY (doctor_id) REFERENCES doctors(id),
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (clinic_id) REFERENCES clinics(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialized successfully!")


def seed_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM clinics")
    if cursor.fetchone()[0] > 0:
        conn.close()
        print("Database already has data — skipping sample data!")
        return

    print("Adding sample data...")
    cursor.execute(
        "INSERT INTO clinics (id, name, doctor, specialty, patients_waiting, minutes_per_patient, is_open, latitude, longitude, address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "Clinic Youssef", "Dr. Ahmed", "General", 3, 15, 1, 30.0444, 31.2357, "Cairo, Egypt"),
    )
    cursor.execute(
        "INSERT INTO clinics (id, name, doctor, specialty, patients_waiting, minutes_per_patient, is_open, latitude, longitude, address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (2, "Nile Medical", "Dr. Sara", "Cardiology", 6, 20, 1, 30.0626, 31.2497, "Heliopolis, Cairo"),
    )
    cursor.execute(
        "INSERT INTO clinics (id, name, doctor, specialty, patients_waiting, minutes_per_patient, is_open, latitude, longitude, address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (3, "October Clinic", "Dr. Mona", "Pediatrics", 2, 10, 0, 29.9792, 30.9256, "6th of October, Giza"),
    )

    ahmed_pw = generate_password_hash("ahmed123")
    sara_pw = generate_password_hash("sara123")
    mona_pw = generate_password_hash("mona123")

    cursor.execute(
        "INSERT INTO doctors (id, name, email, password, clinic_id, is_arrived, phone, specialty, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "Dr. Ahmed", "ahmed@tabibak.com", ahmed_pw, 1, 0, "01000000001", "General", "approved"),
    )
    cursor.execute(
        "INSERT INTO doctors (id, name, email, password, clinic_id, is_arrived, phone, specialty, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (2, "Dr. Sara", "sara@tabibak.com", sara_pw, 2, 0, "01000000002", "Cardiology", "approved"),
    )
    cursor.execute(
        "INSERT INTO doctors (id, name, email, password, clinic_id, is_arrived, phone, specialty, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (3, "Dr. Mona", "mona@tabibak.com", mona_pw, 3, 0, "01000000003", "Pediatrics", "approved"),
    )

    conn.commit()
    conn.close()
    print("Sample data added!")


def safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def allowed_file(filename):
    return filename and "." in filename and filename.rsplit(".", 1)[1].lower() in {"png", "jpg", "jpeg", "pdf"}


def get_distance_km(lat1, lng1, lat2, lng2):
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return 999
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def ensure_admin_schema():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
