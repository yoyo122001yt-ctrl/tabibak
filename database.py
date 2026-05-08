import sqlite3

conn = sqlite3.connect("tabibak.db")
cursor = conn.cursor()

# Create clinics table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS clinics (
        id INTEGER PRIMARY KEY,
        name TEXT,
        doctor TEXT,
        specialty TEXT,
        patients_waiting INTEGER,
        minutes_per_patient INTEGER,
        is_open INTEGER
    )
""")

# Create doctors table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS doctors (
        id INTEGER PRIMARY KEY,
        name TEXT,
        email TEXT,
        password TEXT,
        clinic_id INTEGER,
        is_arrived INTEGER
    )
""")

# Clear old data
cursor.execute("DELETE FROM clinics")
cursor.execute("DELETE FROM doctors")

# Add clinics
cursor.execute("INSERT INTO clinics VALUES (1, 'Clinic Youssef', 'Dr. Ahmed', 'General', 3, 15, 1)")
cursor.execute("INSERT INTO clinics VALUES (2, 'Nile Medical', 'Dr. Sara', 'Cardiology', 6, 20, 1)")
cursor.execute("INSERT INTO clinics VALUES (3, 'October Clinic', 'Dr. Mona', 'Pediatrics', 2, 10, 0)")

# Add doctors
cursor.execute("INSERT INTO doctors VALUES (1, 'Dr. Ahmed', 'ahmed@tabibak.com', 'ahmed123', 1, 0)")
cursor.execute("INSERT INTO doctors VALUES (2, 'Dr. Sara', 'sara@tabibak.com', 'sara123', 2, 0)")
cursor.execute("INSERT INTO doctors VALUES (3, 'Dr. Mona', 'mona@tabibak.com', 'mona123', 3, 0)")

conn.commit()
print("✅ Database updated with doctors!")
conn.close()