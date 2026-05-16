from datetime import datetime
import os

from flask import session
from werkzeug.utils import secure_filename

from backend.data.database import get_db, allowed_file
from backend.config import Config


def upload_document(file, description, patient_id):
    if not file or file.filename == "":
        return False

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{patient_id}_{timestamp}_{filename}"
        file_path = os.path.join(Config.UPLOAD_FOLDER, unique_filename)
        file.save(file_path)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO medical_documents (patient_id, filename, description, uploaded_at) VALUES (?, ?, ?, ?)",
            (patient_id, unique_filename, description, datetime.now()),
        )
        conn.commit()
        conn.close()
        return True
    return False


def get_patient_documents(patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medical_documents WHERE patient_id = ?", (patient_id,))
    documents = cursor.fetchall()
    conn.close()
    return documents


def request_document_access(doctor_id, patient_id, clinic_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM bookings WHERE patient_id = ? AND clinic_id = ?", (patient_id, clinic_id)
    )
    if not cursor.fetchone():
        conn.close()
        return False

    cursor.execute(
        "SELECT * FROM document_access_requests WHERE doctor_id = ? AND patient_id = ? AND status = 'pending'",
        (doctor_id, patient_id),
    )
    existing = cursor.fetchone()

    if not existing:
        cursor.execute(
            "INSERT INTO document_access_requests (doctor_id, patient_id, clinic_id, status, requested_at) VALUES (?, ?, ?, 'pending', ?)",
            (doctor_id, patient_id, clinic_id, datetime.now()),
        )
        conn.commit()

    conn.close()
    return True


def get_document_access_status(doctor_id, patient_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM document_access_requests
        WHERE doctor_id = ? AND patient_id = ? AND status = 'approved'
        ORDER BY responded_at DESC LIMIT 1
    """,
        (doctor_id, patient_id),
    )
    access_granted = cursor.fetchone()

    cursor.execute(
        """
        SELECT * FROM document_access_requests
        WHERE doctor_id = ? AND patient_id = ? AND status = 'pending'
        ORDER BY requested_at DESC LIMIT 1
    """,
        (doctor_id, patient_id),
    )
    pending_request = cursor.fetchone()

    cursor.execute(
        """
        SELECT * FROM document_access_requests
        WHERE doctor_id = ? AND patient_id = ? AND status = 'rejected'
        ORDER BY responded_at DESC, requested_at DESC LIMIT 1
    """,
        (doctor_id, patient_id),
    )
    rejected_request = cursor.fetchone()

    conn.close()
    return access_granted, pending_request, rejected_request


def get_patient_pending_requests(patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT dar.*, doctors.name as doctor_name, clinics.name as clinic_name
        FROM document_access_requests dar
        JOIN doctors ON dar.doctor_id = doctors.id
        JOIN clinics ON dar.clinic_id = clinics.id
        WHERE dar.patient_id = ? AND dar.status = 'pending'
        ORDER BY dar.requested_at DESC
    """,
        (patient_id,),
    )
    requests = cursor.fetchall()
    conn.close()
    return requests


def respond_to_access_request(request_id, patient_id, status):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM document_access_requests WHERE id = ? AND patient_id = ? AND status = 'pending'",
        (request_id, patient_id),
    )
    request_data = cursor.fetchone()

    if request_data:
        cursor.execute(
            "UPDATE document_access_requests SET status = ?, responded_at = ? WHERE id = ?",
            (status, datetime.now(), request_id),
        )
        conn.commit()
        conn.close()
        return True

    conn.close()
    return False
