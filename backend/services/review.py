from datetime import datetime

from backend.data.database import get_db


def get_reviewable_booking(booking_id, patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM bookings WHERE id = ? AND patient_id = ? AND status = 'completed' AND reviewed = 0",
        (booking_id, patient_id),
    )
    booking = cursor.fetchone()
    conn.close()
    return booking


def submit_review(clinic_id, booking_id, patient_id, rating, comment):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM bookings WHERE id = ? AND patient_id = ? AND status = 'completed' AND reviewed = 0",
        (booking_id, patient_id),
    )
    booking = cursor.fetchone()
    if not booking or booking["clinic_id"] != clinic_id:
        conn.close()
        return False

    cursor.execute(
        "INSERT INTO reviews (patient_id, clinic_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?)",
        (patient_id, clinic_id, rating, comment, datetime.now()),
    )
    cursor.execute("UPDATE bookings SET reviewed = 1 WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()
    return True
