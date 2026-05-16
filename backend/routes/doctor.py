from flask import Blueprint, render_template, request, redirect, session

from backend.data.database import safe_int, ensure_admin_schema
from backend.services.auth import (
    login_required,
    hash_password,
    get_doctor_by_email,
)
from backend.services.clinic import update_clinic_status
from backend.services.booking import (
    get_waiting_arrived_patients,
    get_queue_count,
    call_next_patient,
)
from backend.services.document import (
    get_document_access_status,
    get_patient_documents,
    request_document_access,
)
from backend.services.audit import log_action

doctor_bp = Blueprint("doctor", __name__)


@doctor_bp.route("/doctor/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        clinic_name = request.form.get("clinic_name", "").strip()
        specialty = request.form.get("specialty", "").strip()
        minutes_per_patient = safe_int(request.form.get("minutes_per_patient"), 15)

        if not name or not email or not password or not clinic_name or not specialty:
            return render_template("doctor_register.html", error="All fields are required.", success=False)

        if minutes_per_patient <= 0:
            minutes_per_patient = 15

        existing = get_doctor_by_email(email)
        if existing:
            return render_template("doctor_register.html", error="Email already registered!", success=False)

        hashed = hash_password(password)
        conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO clinics (name, doctor, specialty, patients_waiting, minutes_per_patient, is_open) VALUES (?, ?, ?, 0, ?, 0)",
            (clinic_name, name, specialty, minutes_per_patient),
        )
        clinic_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO doctors (name, email, password, clinic_id, is_arrived, phone, specialty, status) VALUES (?, ?, ?, ?, 0, ?, ?, 'pending')",
            (name, email, hashed, clinic_id, phone, specialty),
        )
        conn.commit()
        conn.close()
        return render_template("doctor_register.html", error=None, success=True)

    return render_template("doctor_register.html", error=None, success=False)


@doctor_bp.route("/doctor/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        from werkzeug.security import check_password_hash

        doctor = get_doctor_by_email(email)
        if doctor and check_password_hash(doctor["password"], password):
            if doctor["status"] == "pending":
                return render_template("doctor_login.html", error="Your account is still pending approval. Please wait.")
            elif doctor["status"] == "rejected":
                return render_template("doctor_login.html", error="Your account has been rejected. Contact support.")

            session["doctor_id"] = doctor["id"]
            session["doctor_name"] = doctor["name"]
            session["clinic_id"] = doctor["clinic_id"]
            return redirect("/doctor/dashboard")
        else:
            return render_template("doctor_login.html", error="Wrong email or password!")

    return render_template("doctor_login.html", error=None)


@doctor_bp.route("/doctor/dashboard")
@login_required("doctor")
def dashboard():
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (session["clinic_id"],))
    clinic = cursor.fetchone()

    cursor.execute(
        """
        SELECT DISTINCT patients.* FROM patients
        JOIN bookings ON bookings.patient_id = patients.id
        WHERE bookings.clinic_id = ?
    """,
        (session["clinic_id"],),
    )
    patients = cursor.fetchall()
    conn.close()

    arrived_patients = get_waiting_arrived_patients(session["clinic_id"])
    queue_count = get_queue_count(session["clinic_id"])

    return render_template(
        "doctor_dashboard.html",
        doctor=session["doctor_name"],
        clinic=clinic,
        patients=patients,
        arrived_patients=arrived_patients,
        queue_count=queue_count,
    )


@doctor_bp.route("/doctor/patient/<int:patient_id>")
@login_required("doctor")
def view_patient(patient_id):
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT patients.* FROM patients
        JOIN bookings ON bookings.patient_id = patients.id
        WHERE patients.id = ? AND bookings.clinic_id = ?
    """,
        (patient_id, session["clinic_id"]),
    )
    patient = cursor.fetchone()
    if not patient:
        conn.close()
        return redirect("/doctor/dashboard")

    conn.close()

    access_granted, pending_request, rejected_request = get_document_access_status(
        session["doctor_id"], patient_id
    )

    documents = []
    if access_granted:
        documents = get_patient_documents(patient_id)

    return render_template(
        "doctor_view_patient.html",
        patient=patient,
        documents=documents,
        access_granted=access_granted,
        pending_request=pending_request,
        rejected_request=rejected_request,
    )


@doctor_bp.route("/doctor/arrive")
@login_required("doctor")
def arrive():
    update_clinic_status(session["clinic_id"], 1)
    return redirect("/doctor/dashboard")


@doctor_bp.route("/doctor/leave")
@login_required("doctor")
def leave():
    update_clinic_status(session["clinic_id"], 0)
    return redirect("/doctor/dashboard")


@doctor_bp.route("/doctor/next")
@login_required("doctor")
def next_patient():
    call_next_patient(session["clinic_id"])
    return redirect("/doctor/dashboard")


@doctor_bp.route("/doctor/request_documents/<int:patient_id>", methods=["POST"])
@login_required("doctor")
def request_documents(patient_id):
    request_document_access(session["doctor_id"], patient_id, session["clinic_id"])
    return redirect(f"/doctor/patient/{patient_id}")


@doctor_bp.route("/doctor/logout")
def logout():
    session.pop("doctor_id", None)
    session.pop("doctor_name", None)
    session.pop("clinic_id", None)
    return redirect("/")
