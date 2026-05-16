from datetime import datetime
from flask import Blueprint, request, jsonify

from backend.config import Config
from backend.data.database import get_db, safe_int
from backend.services.auth import hash_password, verify_password, get_doctor_by_email, get_patient_by_email
from backend.services.jwt import create_token, jwt_required
from backend.services.clinic import get_clinics, get_clinic_reviews_summary, get_clinic_by_id, update_clinic_status
from backend.services.booking import (
    create_booking, get_booking_confirm_data, cancel_booking,
    get_patient_bookings, get_waiting_arrived_patients,
    get_queue_count, call_next_patient, check_arrival,
)
from backend.services.document import (
    upload_document, get_patient_documents, request_document_access,
    get_document_access_status, respond_to_access_request,
)
from backend.services.review import submit_review
from backend.services.audit import log_action, get_recent_logs
from backend.services.queue_manager import publish_queue_update, get_cached_queue

api_v1_bp = Blueprint("api_v1", __name__)


def _json_clinic(row):
    return {k: row[k] for k in row.keys()}


def _json_booking(row):
    return {k: row[k] for k in row.keys()}


# ============ AUTH ============

@api_v1_bp.route("/api/v1/auth/patient/register", methods=["POST"])
def api_patient_register():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    age = safe_int(data.get("age"))
    blood_type = data.get("blood_type", "").strip()
    phone = data.get("phone", "").strip()

    if not name or not email or not password or age is None or not blood_type or not phone:
        return jsonify({"error": "All fields are required"}), 400

    existing = get_patient_by_email(email)
    if existing:
        return jsonify({"error": "Email already registered"}), 409

    hashed = hash_password(password)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO patients (name, email, password, age, blood_type, phone) VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, hashed, age, blood_type, phone),
    )
    patient_id = cursor.lastrowid
    conn.commit()
    conn.close()

    token = create_token(patient_id, "patient")
    return jsonify({"token": token, "user": {"id": patient_id, "name": name, "email": email}}), 201


@api_v1_bp.route("/api/v1/auth/patient/login", methods=["POST"])
def api_patient_login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    patient = get_patient_by_email(email)
    if not patient or not verify_password(password, patient["password"]):
        return jsonify({"error": "Wrong email or password"}), 401

    token = create_token(patient["id"], "patient")
    return jsonify({"token": token, "user": {"id": patient["id"], "name": patient["name"], "email": patient["email"]}})


@api_v1_bp.route("/api/v1/auth/doctor/login", methods=["POST"])
def api_doctor_login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    doctor = get_doctor_by_email(email)
    if not doctor or not verify_password(password, doctor["password"]):
        return jsonify({"error": "Wrong email or password"}), 401
    if doctor["status"] == "pending":
        return jsonify({"error": "Account pending approval"}), 403
    if doctor["status"] == "rejected":
        return jsonify({"error": "Account rejected"}), 403

    token = create_token(doctor["id"], "doctor")
    return jsonify({
        "token": token,
        "user": {"id": doctor["id"], "name": doctor["name"], "email": doctor["email"], "clinic_id": doctor["clinic_id"]},
    })


@api_v1_bp.route("/api/v1/auth/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json() or {}
    if data.get("password", "") == Config.ADMIN_PASSWORD:
        token = create_token(0, "admin")
        return jsonify({"token": token})
    return jsonify({"error": "Wrong password"}), 401


# ============ CLINICS ============

@api_v1_bp.route("/api/v1/clinics", methods=["GET"])
def api_clinics():
    clinics = get_clinics()
    reviews = get_clinic_reviews_summary()
    result = []
    for c in clinics:
        row = _json_clinic(c)
        row["reviews"] = reviews.get(c["id"], {"avg": 0, "count": 0})
        result.append(row)
    return jsonify(result)


@api_v1_bp.route("/api/v1/clinics/<int:clinic_id>", methods=["GET"])
def api_clinic_detail(clinic_id):
    clinic = get_clinic_by_id(clinic_id)
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404
    return jsonify(_json_clinic(clinic))


# ============ PATIENT ============

@api_v1_bp.route("/api/v1/patient/profile", methods=["GET"])
@jwt_required(role="patient")
def api_patient_profile():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, age, blood_type, phone FROM patients WHERE id = ?", (request.user_id,))
    patient = cursor.fetchone()
    conn.close()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    return jsonify(_json_clinic(patient))


@api_v1_bp.route("/api/v1/patient/bookings", methods=["GET"])
@jwt_required(role="patient")
def api_patient_bookings():
    bookings = get_patient_bookings(request.user_id)
    return jsonify([_json_booking(b) for b in bookings])


@api_v1_bp.route("/api/v1/patient/book/<int:clinic_id>", methods=["POST"])
@jwt_required(role="patient")
def api_book_clinic(clinic_id):
    result = create_booking(request.user_id, clinic_id)
    if result.get("already"):
        return jsonify({"message": "Already booked", "clinic_id": clinic_id}), 200
    return jsonify({"message": "Booked successfully", "clinic_id": clinic_id}), 201


@api_v1_bp.route("/api/v1/patient/cancel/<int:booking_id>", methods=["POST"])
@jwt_required(role="patient")
def api_cancel_booking(booking_id):
    cancel_booking(booking_id, request.user_id)
    return jsonify({"message": "Cancelled"}), 200


@api_v1_bp.route("/api/v1/patient/documents", methods=["GET"])
@jwt_required(role="patient")
def api_patient_documents():
    docs = get_patient_documents(request.user_id)
    return jsonify([_json_clinic(d) for d in docs])


@api_v1_bp.route("/api/v1/patient/documents/upload", methods=["POST"])
@jwt_required(role="patient")
def api_upload_document():
    file = request.files.get("document")
    description = request.form.get("description", "").strip()
    if not file or file.filename == "":
        return jsonify({"error": "No file provided"}), 400
    success = upload_document(file, description, request.user_id)
    if success:
        return jsonify({"message": "Uploaded"}), 201
    return jsonify({"error": "Invalid file type"}), 400


@api_v1_bp.route("/api/v1/patient/check_arrival", methods=["POST"])
@jwt_required(role="patient")
def api_check_arrival():
    data = request.get_json() or {}
    lat = data.get("lat")
    lng = data.get("lng")
    if lat is None or lng is None:
        return jsonify({"error": "Location required"}), 400
    arrived = check_arrival(request.user_id, lat, lng)
    return jsonify({"arrived": arrived})


@api_v1_bp.route("/api/v1/patient/approve_document/<int:request_id>", methods=["POST"])
@jwt_required(role="patient")
def api_approve_document(request_id):
    success = respond_to_access_request(request_id, request.user_id, "approved")
    return jsonify({"success": success}), 200 if success else 404


@api_v1_bp.route("/api/v1/patient/reject_document/<int:request_id>", methods=["POST"])
@jwt_required(role="patient")
def api_reject_document(request_id):
    success = respond_to_access_request(request_id, request.user_id, "rejected")
    return jsonify({"success": success}), 200 if success else 404


@api_v1_bp.route("/api/v1/patient/review", methods=["POST"])
@jwt_required(role="patient")
def api_submit_review():
    data = request.get_json() or {}
    clinic_id = safe_int(data.get("clinic_id"))
    booking_id = safe_int(data.get("booking_id"))
    rating = safe_int(data.get("rating"))
    comment = data.get("comment", "").strip()
    if not clinic_id or not booking_id or not rating:
        return jsonify({"error": "Missing required fields"}), 400
    success = submit_review(clinic_id, booking_id, request.user_id, rating, comment)
    if success:
        return jsonify({"message": "Review submitted"}), 201
    return jsonify({"error": "Cannot review this booking"}), 400


# ============ DOCTOR ============

@api_v1_bp.route("/api/v1/doctor/dashboard", methods=["GET"])
@jwt_required(role="doctor")
def api_doctor_dashboard():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT doctors.*, clinics.name as clinic_name FROM doctors JOIN clinics ON doctors.clinic_id = clinics.id WHERE doctors.id = ?", (request.user_id,))
    doctor = cursor.fetchone()
    if not doctor:
        conn.close()
        return jsonify({"error": "Doctor not found"}), 404
    clinic_id = doctor["clinic_id"]
    conn.close()

    clinic = get_clinic_by_id(clinic_id)
    arrived = get_waiting_arrived_patients(clinic_id)
    queue_count = get_queue_count(clinic_id)

    return jsonify({
        "doctor": {"id": doctor["id"], "name": doctor["name"], "email": doctor["email"], "phone": doctor["phone"]},
        "clinic": _json_clinic(clinic),
        "arrived_patients": [_json_clinic(p) for p in arrived],
        "queue_count": queue_count,
    })


@api_v1_bp.route("/api/v1/doctor/arrive", methods=["POST"])
@jwt_required(role="doctor")
def api_doctor_arrive():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT clinic_id FROM doctors WHERE id = ?", (request.user_id,))
    doc = cursor.fetchone()
    conn.close()
    if not doc:
        return jsonify({"error": "Doctor not found"}), 404
    update_clinic_status(doc["clinic_id"], 1)
    return jsonify({"message": "Clinic opened"}), 200


@api_v1_bp.route("/api/v1/doctor/leave", methods=["POST"])
@jwt_required(role="doctor")
def api_doctor_leave():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT clinic_id FROM doctors WHERE id = ?", (request.user_id,))
    doc = cursor.fetchone()
    conn.close()
    if not doc:
        return jsonify({"error": "Doctor not found"}), 404
    update_clinic_status(doc["clinic_id"], 0)
    return jsonify({"message": "Clinic closed"}), 200


@api_v1_bp.route("/api/v1/doctor/next", methods=["POST"])
@jwt_required(role="doctor")
def api_doctor_next():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT clinic_id FROM doctors WHERE id = ?", (request.user_id,))
    doc = cursor.fetchone()
    conn.close()
    if not doc:
        return jsonify({"error": "Doctor not found"}), 404
    call_next_patient(doc["clinic_id"])
    return jsonify({"message": "Next patient called"}), 200


@api_v1_bp.route("/api/v1/doctor/patients", methods=["GET"])
@jwt_required(role="doctor")
def api_doctor_patients():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT clinic_id FROM doctors WHERE id = ?", (request.user_id,))
    doc = cursor.fetchone()
    if not doc:
        conn.close()
        return jsonify({"error": "Doctor not found"}), 404
    cursor.execute("""
        SELECT DISTINCT patients.id, patients.name, patients.email, patients.phone
        FROM patients
        JOIN bookings ON bookings.patient_id = patients.id
        WHERE bookings.clinic_id = ?
    """, (doc["clinic_id"],))
    patients = cursor.fetchall()
    conn.close()
    return jsonify([_json_clinic(p) for p in patients])


@api_v1_bp.route("/api/v1/doctor/patient/<int:patient_id>", methods=["GET"])
@jwt_required(role="doctor")
def api_doctor_view_patient(patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT clinic_id FROM doctors WHERE id = ?", (request.user_id,))
    doc = cursor.fetchone()
    if not doc:
        conn.close()
        return jsonify({"error": "Doctor not found"}), 404
    cursor.execute("""
        SELECT patients.* FROM patients
        JOIN bookings ON bookings.patient_id = patients.id
        WHERE patients.id = ? AND bookings.clinic_id = ?
    """, (patient_id, doc["clinic_id"]))
    patient = cursor.fetchone()
    conn.close()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    access_granted, pending, rejected = get_document_access_status(request.user_id, patient_id)
    documents = []
    if access_granted:
        documents = [dict(d) for d in get_patient_documents(patient_id)]

    return jsonify({
        "patient": {"id": patient["id"], "name": patient["name"], "email": patient["email"],
                     "phone": patient["phone"], "age": patient["age"], "blood_type": patient["blood_type"]},
        "documents": documents,
        "access_granted": bool(access_granted),
        "pending_request": bool(pending),
        "rejected_request": bool(rejected),
    })


@api_v1_bp.route("/api/v1/doctor/patient/<int:patient_id>/request_documents", methods=["POST"])
@jwt_required(role="doctor")
def api_doctor_request_documents(patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT clinic_id FROM doctors WHERE id = ?", (request.user_id,))
    doc = cursor.fetchone()
    conn.close()
    if not doc:
        return jsonify({"error": "Doctor not found"}), 404
    success = request_document_access(request.user_id, patient_id, doc["clinic_id"])
    if not success:
        return jsonify({"error": "Patient has not booked this clinic"}), 400
    return jsonify({"message": "Request sent"}), 200


# ============ ADMIN ============

@api_v1_bp.route("/api/v1/admin/dashboard", methods=["GET"])
@jwt_required(role="admin")
def api_admin_dashboard():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM doctors WHERE status = 'pending'")
    pending_doctors = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM patients")
    total_patients = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM clinics")
    total_clinics = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE status = 'waiting'")
    bookings_waiting = cursor.fetchone()["count"]
    conn.close()

    return jsonify({
        "pending_doctors": pending_doctors,
        "total_patients": total_patients,
        "total_clinics": total_clinics,
        "bookings_waiting": bookings_waiting,
    })


@api_v1_bp.route("/api/v1/admin/doctors", methods=["GET"])
@jwt_required(role="admin")
def api_admin_doctors():
    conn = get_db()
    cursor = conn.cursor()
    filter_q = request.args.get("q", "").strip()
    filter_status = request.args.get("status", "all")
    query = """
        SELECT doctors.*, clinics.name as clinic_name
        FROM doctors
        LEFT JOIN clinics ON doctors.clinic_id = clinics.id
        WHERE 1=1
    """
    params = []
    if filter_q:
        query += " AND (doctors.name LIKE ? OR doctors.email LIKE ? OR clinics.name LIKE ?)"
        like = f"%{filter_q}%"
        params.extend([like, like, like])
    if filter_status != "all":
        query += " AND doctors.status = ?"
        params.append(filter_status)
    query += " ORDER BY doctors.id DESC"
    cursor.execute(query, params)
    doctors = cursor.fetchall()
    conn.close()
    return jsonify([_json_clinic(d) for d in doctors])


@api_v1_bp.route("/api/v1/admin/doctors/pending", methods=["GET"])
@jwt_required(role="admin")
def api_admin_pending_doctors():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT doctors.*, clinics.name as clinic_name
        FROM doctors LEFT JOIN clinics ON doctors.clinic_id = clinics.id
        WHERE doctors.status = 'pending' ORDER BY doctors.id DESC
    """)
    doctors = cursor.fetchall()
    conn.close()
    return jsonify([_json_clinic(d) for d in doctors])


@api_v1_bp.route("/api/v1/admin/doctors/approve/<int:doctor_id>", methods=["POST"])
@jwt_required(role="admin")
def api_admin_approve_doctor(doctor_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    if not doc:
        conn.close()
        return jsonify({"error": "Doctor not found"}), 404
    cursor.execute("UPDATE doctors SET status = 'approved' WHERE id = ?", (doctor_id,))
    cursor.execute("UPDATE clinics SET is_open = 1 WHERE id = (SELECT clinic_id FROM doctors WHERE id = ?)", (doctor_id,))
    conn.commit()
    conn.close()
    log_action("APPROVE", f"Approved doctor: {doc['name']} (id={doctor_id})")
    return jsonify({"message": f"Doctor {doc['name']} approved"}), 200


@api_v1_bp.route("/api/v1/admin/doctors/reject/<int:doctor_id>", methods=["POST"])
@jwt_required(role="admin")
def api_admin_reject_doctor(doctor_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, clinic_id FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    if not doc:
        conn.close()
        return jsonify({"error": "Doctor not found"}), 404
    cursor.execute("DELETE FROM clinics WHERE id = ?", (doc["clinic_id"],))
    cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    conn.commit()
    conn.close()
    log_action("REJECT", f"Rejected doctor: {doc['name']} (id={doctor_id})")
    return jsonify({"message": f"Doctor {doc['name']} rejected"}), 200


@api_v1_bp.route("/api/v1/admin/doctors", methods=["POST"])
@jwt_required(role="admin")
def api_admin_add_doctor():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    phone = data.get("phone", "").strip()
    clinic_name = data.get("clinic_name", "").strip()
    specialty = data.get("specialty", "").strip()
    minutes_per_patient = safe_int(data.get("minutes_per_patient"), 15)
    address = data.get("address", "Cairo, Egypt").strip()
    lat = safe_int(data.get("latitude"), 30.0444)
    lng = safe_int(data.get("longitude"), 31.2357)

    if not name or not email or not password or not clinic_name or not specialty:
        return jsonify({"error": "All required fields must be filled"}), 400

    existing = get_doctor_by_email(email)
    if existing:
        return jsonify({"error": "Email already exists"}), 409

    hashed = hash_password(password)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO clinics (name, doctor, specialty, patients_waiting, minutes_per_patient, is_open, latitude, longitude, address) VALUES (?, ?, ?, 0, ?, 1, ?, ?, ?)",
        (clinic_name, name, specialty, minutes_per_patient, lat, lng, address),
    )
    clinic_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO doctors (name, email, password, clinic_id, is_arrived, phone, specialty, status) VALUES (?, ?, ?, ?, 0, ?, ?, 'approved')",
        (name, email, hashed, clinic_id, phone, specialty),
    )
    conn.commit()
    conn.close()
    log_action("ADD_DOCTOR", f"Added doctor: {name} ({email}) with clinic: {clinic_name}")
    return jsonify({"message": f"Doctor {name} created", "doctor_id": cursor.lastrowid}), 201


@api_v1_bp.route("/api/v1/admin/doctors/<int:doctor_id>", methods=["DELETE"])
@jwt_required(role="admin")
def api_admin_delete_doctor(doctor_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, clinic_id FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    if not doc:
        conn.close()
        return jsonify({"error": "Doctor not found"}), 404
    cid = doc["clinic_id"]
    cursor.execute("DELETE FROM bookings WHERE clinic_id = ?", (cid,))
    cursor.execute("DELETE FROM reviews WHERE clinic_id = ?", (cid,))
    cursor.execute("DELETE FROM clinics WHERE id = ?", (cid,))
    cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    conn.commit()
    conn.close()
    log_action("DELETE", f"Deleted doctor: {doc['name']} (id={doctor_id})")
    return jsonify({"message": "Doctor deleted"}), 200


@api_v1_bp.route("/api/v1/admin/audit_log", methods=["GET"])
@jwt_required(role="admin")
def api_admin_audit_log():
    logs = get_recent_logs(limit=50)
    return jsonify([_json_clinic(l) for l in logs])


@api_v1_bp.route("/api/v1/admin/bookings", methods=["GET"])
@jwt_required(role="admin")
def api_admin_bookings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT bookings.id, bookings.booked_at, bookings.status, bookings.arrived,
               patients.name, patients.email, patients.id as patient_id,
               clinics.name as clinic_name
        FROM bookings
        JOIN patients ON bookings.patient_id = patients.id
        JOIN clinics ON bookings.clinic_id = clinics.id
        ORDER BY bookings.booked_at DESC LIMIT 40
    """)
    bookings = cursor.fetchall()
    conn.close()
    return jsonify([_json_clinic(b) for b in bookings])


# ============ QUEUE ============

@api_v1_bp.route("/api/v1/queue/<int:clinic_id>", methods=["GET"])
def api_queue_status(clinic_id):
    cached = get_cached_queue(clinic_id)
    if cached:
        return jsonify(cached)

    clinic = get_clinic_by_id(clinic_id)
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 404

    queue_count = get_queue_count(clinic_id)
    data = {
        "clinic_id": clinic_id,
        "clinic_name": clinic["name"],
        "patients_waiting": clinic["patients_waiting"],
        "queue_count": queue_count,
        "is_open": bool(clinic["is_open"]),
        "minutes_per_patient": clinic["minutes_per_patient"],
        "est_wait_minutes": clinic["patients_waiting"] * clinic["minutes_per_patient"],
    }
    return jsonify(data)
