from flask import Blueprint, render_template, request, redirect, session

from backend.data.database import safe_int
from backend.services.auth import (
    login_required,
    hash_password,
    get_patient_by_email,
)
from backend.services.booking import (
    create_booking,
    get_booking_confirm_data,
    cancel_booking,
    get_patient_bookings,
    get_patient_active_bookings,
)
from backend.services.document import (
    upload_document,
    get_patient_documents,
    get_patient_pending_requests,
    respond_to_access_request,
)

patient_bp = Blueprint("patient", __name__)


@patient_bp.route("/patient/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        age = safe_int(request.form.get("age"), None)
        blood_type = request.form.get("blood_type", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not email or not password or age is None or not blood_type or not phone:
            return render_template("patient_register.html", error="All fields are required!")

        existing = get_patient_by_email(email)
        if existing:
            return render_template("patient_register.html", error="Email already registered!")

        hashed = hash_password(password)
        conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO patients (name, email, password, age, blood_type, phone) VALUES (?, ?, ?, ?, ?, ?)",
            (name, email, hashed, age, blood_type, phone),
        )
        conn.commit()
        patient_id = cursor.lastrowid
        conn.close()

        session["patient_id"] = patient_id
        session["patient_name"] = name
        return redirect("/patient/profile")

    return render_template("patient_register.html", error=None)


@patient_bp.route("/patient/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        from werkzeug.security import check_password_hash

        patient = get_patient_by_email(email)
        if patient and check_password_hash(patient["password"], password):
            session["patient_id"] = patient["id"]
            session["patient_name"] = patient["name"]
            return redirect("/patient/profile")
        else:
            return render_template("patient_login.html", error="Wrong email or password!")

    return render_template("patient_login.html", error=None)


@patient_bp.route("/patient/profile")
@login_required("patient")
def profile():
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (session["patient_id"],))
    patient = cursor.fetchone()
    conn.close()

    documents = get_patient_documents(session["patient_id"])
    bookings = get_patient_active_bookings(session["patient_id"])
    pending_requests = get_patient_pending_requests(session["patient_id"])

    return render_template(
        "patient_profile.html",
        patient=patient,
        documents=documents,
        success=None,
        bookings=bookings,
        pending_requests=pending_requests,
    )


@patient_bp.route("/patient/upload", methods=["POST"])
@login_required("patient")
def upload():
    description = request.form.get("description", "").strip()
    file = request.files.get("document")
    upload_document(file, description, session["patient_id"])
    return redirect("/patient/profile")


@patient_bp.route("/patient/approve_request/<int:request_id>", methods=["POST"])
@login_required("patient")
def approve_request(request_id):
    respond_to_access_request(request_id, session["patient_id"], "approved")
    return redirect("/patient/profile")


@patient_bp.route("/patient/reject_request/<int:request_id>", methods=["POST"])
@login_required("patient")
def reject_request(request_id):
    respond_to_access_request(request_id, session["patient_id"], "rejected")
    return redirect("/patient/profile")


@patient_bp.route("/patient/logout")
def logout():
    session.pop("patient_id", None)
    session.pop("patient_name", None)
    return redirect("/")


# --- Booking routes (patient-facing) ---


@patient_bp.route("/book/<int:clinic_id>")
@login_required("patient")
def book_clinic(clinic_id):
    result = create_booking(session["patient_id"], clinic_id)
    if result["already"]:
        return redirect(f"/booking/confirm/{clinic_id}?already=true")
    return redirect(f"/booking/confirm/{clinic_id}")


@patient_bp.route("/booking/confirm/<int:clinic_id>")
@login_required("patient")
def booking_confirm(clinic_id):
    already = request.args.get("already", False)
    clinic, patient, wait_time, queue_position = get_booking_confirm_data(
        clinic_id, session["patient_id"]
    )
    return render_template(
        "booking_confirm.html",
        clinic=clinic,
        patient=patient,
        wait_time=wait_time,
        queue_position=queue_position,
        already=already,
    )


@patient_bp.route("/cancel_booking/<int:booking_id>")
@login_required("patient")
def cancel(booking_id):
    cancel_booking(booking_id, session["patient_id"])
    return redirect("/my_bookings")


@patient_bp.route("/my_bookings")
@login_required("patient")
def my_bookings():
    bookings = get_patient_bookings(session["patient_id"])
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (session["patient_id"],))
    patient = cursor.fetchone()
    conn.close()
    return render_template("my_bookings.html", bookings=bookings, patient=patient)
