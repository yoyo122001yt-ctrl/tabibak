from datetime import datetime

from backend.data.database import get_db


def create_booking(patient_id, clinic_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM bookings WHERE patient_id = ? AND clinic_id = ? AND status = 'waiting'",
        (patient_id, clinic_id),
    )
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return {"already": True, "clinic_id": clinic_id}

    cursor.execute(
        "UPDATE clinics SET patients_waiting = patients_waiting + 1 WHERE id = ?", (clinic_id,)
    )
    cursor.execute(
        "INSERT INTO bookings (patient_id, clinic_id, booked_at, status) VALUES (?, ?, ?, 'waiting')",
        (patient_id, clinic_id, datetime.now()),
    )
    conn.commit()
    conn.close()
    return {"already": False, "clinic_id": clinic_id}


def get_booking_confirm_data(clinic_id, patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,))
    clinic = cursor.fetchone()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    patient = cursor.fetchone()
    cursor.execute(
        "SELECT COUNT(*) as count FROM bookings WHERE clinic_id = ? AND status = 'waiting'",
        (clinic_id,),
    )
    queue_position = cursor.fetchone()["count"]
    conn.close()

    wait_time = clinic["patients_waiting"] * clinic["minutes_per_patient"]
    return clinic, patient, wait_time, queue_position


def cancel_booking(booking_id, patient_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT clinic_id FROM bookings WHERE id = ? AND patient_id = ?",
        (booking_id, patient_id),
    )
    booking = cursor.fetchone()

    if booking:
        cursor.execute(
            "UPDATE clinics SET patients_waiting = MAX(0, patients_waiting - 1) WHERE id = ?",
            (booking["clinic_id"],),
        )
        cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        conn.commit()

    conn.close()


def get_patient_bookings(patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT bookings.id, bookings.patient_id, bookings.clinic_id,
               bookings.booked_at, bookings.status, bookings.arrived,
               clinics.name, clinics.doctor, clinics.patients_waiting,
               clinics.minutes_per_patient, clinics.latitude, clinics.longitude,
               bookings.reviewed
        FROM bookings
        JOIN clinics ON bookings.clinic_id = clinics.id
        WHERE bookings.patient_id = ? AND bookings.status IN ('waiting', 'completed')
        ORDER BY bookings.booked_at DESC
    """,
        (patient_id,),
    )
    bookings = cursor.fetchall()
    conn.close()
    return bookings


def get_patient_active_bookings(patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT bookings.*, clinics.name, clinics.doctor, clinics.patients_waiting, clinics.minutes_per_patient
        FROM bookings
        JOIN clinics ON bookings.clinic_id = clinics.id
        WHERE bookings.patient_id = ? AND bookings.status = 'waiting'
        ORDER BY bookings.booked_at DESC
    """,
        (patient_id,),
    )
    bookings = cursor.fetchall()
    conn.close()
    return bookings


def check_arrival(patient_id, patient_lat, patient_lng):
    from backend.data.database import get_distance_km

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT bookings.id, bookings.clinic_id, clinics.latitude, clinics.longitude, clinics.name
        FROM bookings
        JOIN clinics ON bookings.clinic_id = clinics.id
        WHERE bookings.patient_id = ? AND bookings.status = 'waiting' AND bookings.arrived = 0
    """,
        (patient_id,),
    )
    bookings = cursor.fetchall()

    arrived_clinics = []
    for booking in bookings:
        if booking["latitude"] is not None and booking["longitude"] is not None:
            distance = get_distance_km(
                patient_lat, patient_lng, booking["latitude"], booking["longitude"]
            )
            if distance <= 0.2:
                cursor.execute("UPDATE bookings SET arrived = 1 WHERE id = ?", (booking["id"],))
                arrived_clinics.append({
                    "clinic_id": booking["clinic_id"],
                    "clinic_name": booking["name"],
                    "distance_m": round(distance * 1000),
                })

    conn.commit()
    conn.close()
    return arrived_clinics


def get_waiting_arrived_patients(clinic_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT patients.name, patients.phone, patients.id as patient_id, bookings.booked_at
        FROM bookings
        JOIN patients ON bookings.patient_id = patients.id
        WHERE bookings.clinic_id = ? AND bookings.arrived = 1 AND bookings.status = 'waiting'
        ORDER BY bookings.booked_at ASC
    """,
        (clinic_id,),
    )
    patients = cursor.fetchall()
    conn.close()
    return patients


def get_queue_count(clinic_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as count FROM bookings WHERE clinic_id = ? AND status = 'waiting' AND arrived = 0",
        (clinic_id,),
    )
    count = cursor.fetchone()["count"]
    conn.close()
    return count


def call_next_patient(clinic_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id FROM bookings
        WHERE clinic_id = ? AND status = 'waiting' AND arrived = 1
        ORDER BY booked_at ASC LIMIT 1
    """,
        (clinic_id,),
    )
    booking = cursor.fetchone()

    if booking:
        cursor.execute("UPDATE bookings SET status = 'completed' WHERE id = ?", (booking["id"],))
        cursor.execute(
            "UPDATE clinics SET patients_waiting = MAX(0, patients_waiting - 1) WHERE id = ?",
            (clinic_id,),
        )
        conn.commit()

    conn.close()
