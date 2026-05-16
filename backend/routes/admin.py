import secrets
from flask import Blueprint, render_template, request, redirect, session, flash

from backend.config import Config
from backend.data.database import safe_int, ensure_admin_schema
from backend.services.auth import login_required, hash_password
from backend.services.clinic import get_queue_hot_clinics, get_queue_closed_busy
from backend.services.audit import log_action, get_recent_logs

admin_bp = Blueprint("admin", __name__)


def get_admin_stats():
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM doctors WHERE status = 'pending'")
    pending_doctors = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM patients")
    total_patients = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM clinics")
    total_clinics = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE status = 'waiting'")
    bookings_waiting = cursor.fetchone()["count"]

    doctor_query = """
        SELECT doctors.*, clinics.name as clinic_name
        FROM doctors
        LEFT JOIN clinics ON doctors.clinic_id = clinics.id
        WHERE 1=1
    """
    params = []
    filter_q = request.args.get("q", "").strip()
    filter_status = request.args.get("status", "all")
    if filter_q:
        doctor_query += " AND (doctors.name LIKE ? OR doctors.email LIKE ? OR clinics.name LIKE ?)"
        like = f"%{filter_q}%"
        params.extend([like, like, like])
    if filter_status != "all":
        doctor_query += " AND doctors.status = ?"
        params.append(filter_status)
    doctor_query += " ORDER BY doctors.id DESC"
    cursor.execute(doctor_query, params)
    doctors = cursor.fetchall()

    cursor.execute(
        """
        SELECT doctors.*, clinics.name as clinic_name
        FROM doctors
        LEFT JOIN clinics ON doctors.clinic_id = clinics.id
        WHERE doctors.status = 'pending'
        ORDER BY doctors.id DESC
    """
    )
    pending_list = cursor.fetchall()

    cursor.execute(
        """
        SELECT bookings.id, bookings.booked_at, bookings.status, bookings.arrived,
               patients.name, patients.email, patients.id as patient_id,
               clinics.name as clinic_name
        FROM bookings
        JOIN patients ON bookings.patient_id = patients.id
        JOIN clinics ON bookings.clinic_id = clinics.id
        ORDER BY bookings.booked_at DESC
        LIMIT 40
    """
    )
    recent_bookings = cursor.fetchall()

    conn.close()
    return {
        "doctors": doctors,
        "total_doctors": len(doctors),
        "pending_doctors": pending_doctors,
        "pending_list": pending_list,
        "total_patients": total_patients,
        "total_clinics": total_clinics,
        "bookings_waiting": bookings_waiting,
        "recent_bookings": recent_bookings,
        "filter_q": filter_q,
        "filter_status": filter_status,
    }


@admin_bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["password"] == Config.ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin")
        return render_template("admin_login.html", error="Wrong password!")
    return render_template("admin_login.html", error=None)


@admin_bp.route("/admin")
@login_required("admin")
def dashboard():
    ensure_admin_schema()
    stats = get_admin_stats()
    queue_hot = get_queue_hot_clinics()
    queue_closed_busy = get_queue_closed_busy()
    audit_log = get_recent_logs()

    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)

    return render_template(
        "admin.html",
        **stats,
        queue_hot=queue_hot,
        queue_closed_busy=queue_closed_busy,
        audit_log=audit_log,
        csrf_token=session.get("csrf_token", ""),
    )


@admin_bp.route("/admin/approve/<int:doctor_id>", methods=["GET", "POST"])
@login_required("admin")
def approve_doctor(doctor_id):
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    cursor.execute("UPDATE doctors SET status = 'approved' WHERE id = ?", (doctor_id,))
    cursor.execute(
        "UPDATE clinics SET is_open = 1 WHERE id = (SELECT clinic_id FROM doctors WHERE id = ?)",
        (doctor_id,),
    )
    conn.commit()
    conn.close()
    if doc:
        log_action("APPROVE", f"Approved doctor: {doc['name']} (id={doctor_id})")
    return redirect("/admin")


@admin_bp.route("/admin/reject/<int:doctor_id>", methods=["GET", "POST"])
@login_required("admin")
def reject_doctor(doctor_id):
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, clinic_id FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    if doc:
        cursor.execute("DELETE FROM clinics WHERE id = ?", (doc["clinic_id"],))
        log_action("REJECT", f"Rejected doctor: {doc['name']} (id={doctor_id})")
    cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")


@admin_bp.route("/admin/add_doctor", methods=["POST"])
@login_required("admin")
def add_doctor():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    phone = request.form.get("phone", "").strip()
    clinic_name = request.form.get("clinic_name", "").strip()
    specialty = request.form.get("specialty", "").strip()
    minutes_per_patient = safe_int(request.form.get("minutes_per_patient"), 15)
    address = request.form.get("address", "Cairo, Egypt").strip()
    latitude = request.form.get("latitude", "30.0444").strip()
    longitude = request.form.get("longitude", "31.2357").strip()

    if not name or not email or not password or not clinic_name or not specialty:
        flash("All required fields must be filled.", "error")
        return redirect("/admin")

    try:
        lat = float(latitude) if latitude else 30.0444
        lng = float(longitude) if longitude else 31.2357
    except ValueError:
        lat, lng = 30.0444, 31.2357

    hashed = hash_password(password)
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM doctors WHERE email = ?", (email,))
    if cursor.fetchone():
        flash(f"Email {email} already exists.", "error")
        conn.close()
        return redirect("/admin")

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
    flash(f"Doctor {name} and clinic {clinic_name} created successfully!", "success")
    return redirect("/admin")


@admin_bp.route("/admin/delete_doctor/<int:doctor_id>", methods=["POST"])
@login_required("admin")
def delete_doctor(doctor_id):
    conn = __import__("backend.data.database", fromlist=["get_db"]).get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, clinic_id FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    if doc:
        clinic_id = doc["clinic_id"]
        cursor.execute("DELETE FROM bookings WHERE clinic_id = ?", (clinic_id,))
        cursor.execute("DELETE FROM reviews WHERE clinic_id = ?", (clinic_id,))
        cursor.execute("DELETE FROM clinics WHERE id = ?", (clinic_id,))
        cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
        log_action("DELETE", f"Deleted doctor: {doc['name']} (id={doctor_id}) and clinic_id={clinic_id}")
    conn.commit()
    conn.close()
    flash("Doctor and clinic deleted.", "success")
    return redirect("/admin")


@admin_bp.route("/admin/logout")
def logout():
    session.pop("admin", None)
    return redirect("/")
