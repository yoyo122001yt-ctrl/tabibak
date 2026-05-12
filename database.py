import sqlite3
import os

conn = sqlite3.connect("tabibak.db")
cursor = conn.cursor()

# Clinics table with GPS
cursor.execute("""
    CREATE TABLE IF NOT EXISTS clinics (
        id INTEGER PRIMARY KEY,
        name TEXT,
        doctor TEXT,
        specialty TEXT,
        patients_waiting INTEGER,
        minutes_per_patient INTEGER,
        is_open INTEGER,
        latitude REAL DEFAULT 0,
        longitude REAL DEFAULT 0,
        address TEXT DEFAULT ''
    )
""")

# Doctors table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS doctors (
        id INTEGER PRIMARY KEY,
        name TEXT,
        email TEXT,
        password TEXT,
        clinic_id INTEGER,
        is_arrived INTEGER,
        phone TEXT,
        specialty TEXT,
        status TEXT DEFAULT 'pending'
    )
""")

# Patients table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY,
        name TEXT,
        email TEXT,
        password TEXT,
        age INTEGER,
        blood_type TEXT,
        phone TEXT
    )
""")

# Medical documents table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS medical_documents (
        id INTEGER PRIMARY KEY,
        patient_id INTEGER,
        filename TEXT,
        description TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Bookings table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY,
        patient_id INTEGER,
        clinic_id INTEGER,
        booked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'waiting',
        arrived INTEGER DEFAULT 0,
        reviewed INTEGER DEFAULT 0
    )
""")

# Reviews table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY,
        patient_id INTEGER,
        clinic_id INTEGER,
        rating INTEGER,
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Admin audit log (optional; app also creates via ensure_admin_schema)
cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        detail TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Add columns if they don't exist
for col, table, definition in [
    ("latitude", "clinics", "REAL DEFAULT 0"),
    ("longitude", "clinics", "REAL DEFAULT 0"),
    ("address", "clinics", "TEXT DEFAULT ''"),
    ("arrived", "bookings", "INTEGER DEFAULT 0"),
    ("reviewed", "bookings", "INTEGER DEFAULT 0"),
]:
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
        print(f"✅ Added {col} column to {table}!")
    except:
        pass

# Update existing clinics with GPS coordinates
cursor.execute("UPDATE clinics SET latitude = 30.0444, longitude = 31.2357, address = 'Cairo, Egypt' WHERE id = 1")
cursor.execute("UPDATE clinics SET latitude = 30.0626, longitude = 31.2497, address = 'Heliopolis, Cairo' WHERE id = 2")
cursor.execute("UPDATE clinics SET latitude = 29.9792, longitude = 30.9256, address = '6th of October, Giza' WHERE id = 3")

# Only add sample data if clinics table is empty
cursor.execute("SELECT COUNT(*) FROM clinics")
count = cursor.fetchone()[0]

if count == 0:
    print("Adding sample data...")
    cursor.execute("INSERT INTO clinics VALUES (1, 'Clinic Youssef', 'Dr. Ahmed', 'General', 3, 15, 1, 30.0444, 31.2357, 'Cairo, Egypt')")
    cursor.execute("INSERT INTO clinics VALUES (2, 'Nile Medical', 'Dr. Sara', 'Cardiology', 6, 20, 1, 30.0626, 31.2497, 'Heliopolis, Cairo')")
    cursor.execute("INSERT INTO clinics VALUES (3, 'October Clinic', 'Dr. Mona', 'Pediatrics', 2, 10, 0, 29.9792, 30.9256, '6th of October, Giza')")
    cursor.execute("INSERT INTO doctors VALUES (1, 'Dr. Ahmed', 'ahmed@tabibak.com', 'ahmed123', 1, 0, '01000000001', 'General', 'approved')")
    cursor.execute("INSERT INTO doctors VALUES (2, 'Dr. Sara', 'sara@tabibak.com', 'sara123', 2, 0, '01000000002', 'Cardiology', 'approved')")
    cursor.execute("INSERT INTO doctors VALUES (3, 'Dr. Mona', 'mona@tabibak.com', 'mona123', 3, 0, '01000000003', 'Pediatrics', 'approved')")
    print("✅ Sample data added!")
else:
    print("✅ Database already has data — skipping sample data!")

conn.commit()
print("✅ Database updated!")

os.makedirs("static/uploads", exist_ok=True)
print("✅ Uploads folder ready!")

conn.close()