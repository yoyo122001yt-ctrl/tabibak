from backend.data.database import get_db


def get_clinics():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics")
    clinics = cursor.fetchall()
    conn.close()
    return clinics


def get_clinic_by_id(clinic_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,))
    clinic = cursor.fetchone()
    conn.close()
    return clinic


def update_clinic_status(clinic_id, is_open):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE clinics SET is_open = ? WHERE id = ?", (is_open, clinic_id))
    conn.commit()
    conn.close()


def get_clinic_reviews_summary():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT clinic_id,
               ROUND(AVG(rating), 1) as avg_rating,
               COUNT(*) as review_count
        FROM reviews
        GROUP BY clinic_id
    """)
    data = cursor.fetchall()
    conn.close()
    reviews = {}
    for r in data:
        reviews[r["clinic_id"]] = {"avg": r["avg_rating"], "count": r["review_count"]}
    return reviews


def get_queue_hot_clinics():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, doctor, patients_waiting, minutes_per_patient,
               patients_waiting * minutes_per_patient as est_wait, is_open
        FROM clinics
        WHERE is_open = 1 AND (patients_waiting >= 10 OR patients_waiting * minutes_per_patient >= 120)
    """)
    hot = cursor.fetchall()
    conn.close()
    return hot


def get_queue_closed_busy():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, doctor, patients_waiting, minutes_per_patient,
               patients_waiting * minutes_per_patient as est_wait, is_open
        FROM clinics
        WHERE is_open = 0 AND patients_waiting > 0
    """)
    busy = cursor.fetchall()
    conn.close()
    return busy
