from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
import sqlite3
import os
import math
import secrets
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "tabibak_secret_123"


def delete_doctor_and_clinic(cursor, doctor_id):
    """Remove doctor row and their clinic; clears bookings and reviews for that clinic."""
    cursor.execute("SELECT clinic_id FROM doctors WHERE id = ?", (doctor_id,))
    row = cursor.fetchone()
    if not row or row[0] is None:
        cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
        return True
    clinic_id = row[0]
    cursor.execute("DELETE FROM bookings WHERE clinic_id = ?", (clinic_id,))
    cursor.execute("DELETE FROM reviews WHERE clinic_id = ?", (clinic_id,))
    cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    cursor.execute("DELETE FROM clinics WHERE id = ?", (clinic_id,))
    return True


def ensure_admin_schema(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def log_admin_action(cursor, action, detail=""):
    ensure_admin_schema(cursor)
    d = (detail or "")[:2000]
    cursor.execute("INSERT INTO admin_audit_log (action, detail) VALUES (?, ?)", (action, d))


def admin_csrf_valid():
    return request.form.get("csrf_token") == session.get("admin_csrf")


def admin_redirect_after_mutation():
    q = request.form.get("return_q", "").strip()
    st = request.form.get("return_status", "").strip()
    params = {}
    if q:
        params["q"] = q
    if st and st != "all":
        params["status"] = st
    return redirect(url_for("admin", **params))


UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_clinics():
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics")
    clinics = cursor.fetchall()
    conn.close()
    return clinics

def get_doctor_by_email(email):
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE email = ?", (email,))
    doctor = cursor.fetchone()
    conn.close()
    return doctor

def update_clinic_status(clinic_id, is_open):
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clinics SET is_open = ? WHERE id = ?", (is_open, clinic_id))
    conn.commit()
    conn.close()

def get_distance_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# ─── MAIN PAGES ───────────────────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/clinics")
def clinics():
    data = get_clinics()
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT clinic_id,
               ROUND(AVG(rating), 1) as avg_rating,
               COUNT(*) as review_count
        FROM reviews
        GROUP BY clinic_id
    """)
    reviews_data = cursor.fetchall()
    conn.close()
    reviews = {}
    for r in reviews_data:
        reviews[r[0]] = {"avg": r[1], "count": r[2]}
    return render_template("clinics.html", clinics=data, reviews=reviews)

# ─── BOOKING ROUTES ───────────────────────────────────────
@app.route("/book/<int:clinic_id>")
def book_clinic(clinic_id):
    if "patient_id" not in session:
        return redirect("/patient/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE patient_id = ? AND clinic_id = ? AND status = 'waiting'",
                  (session["patient_id"], clinic_id))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return redirect(f"/booking/confirm/{clinic_id}?already=true")
    cursor.execute("UPDATE clinics SET patients_waiting = patients_waiting + 1 WHERE id = ?", (clinic_id,))
    cursor.execute("INSERT INTO bookings (patient_id, clinic_id) VALUES (?, ?)",
                  (session["patient_id"], clinic_id))
    conn.commit()
    conn.close()
    return redirect(f"/booking/confirm/{clinic_id}")

@app.route("/booking/confirm/<int:clinic_id>")
def booking_confirm(clinic_id):
    if "patient_id" not in session:
        return redirect("/patient/login")
    already = request.args.get("already", False)
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,))
    clinic = cursor.fetchone()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (session["patient_id"],))
    patient = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM bookings WHERE clinic_id = ? AND status = 'waiting'", (clinic_id,))
    queue_position = cursor.fetchone()[0]
    conn.close()
    wait_time = clinic[4] * clinic[5]
    return render_template("booking_confirm.html",
        clinic=clinic,
        patient=patient,
        wait_time=wait_time,
        queue_position=queue_position,
        already=already)

# ─── AUTO ARRIVE ──────────────────────────────────────────
@app.route("/api/check_arrival", methods=["POST"])
def check_arrival():
    if "patient_id" not in session:
        return jsonify({"error": "not logged in"}), 401

    data = request.get_json() or {}
    patient_lat = data.get("lat")
    patient_lng = data.get("lng")

    if patient_lat is None or patient_lng is None:
        return jsonify({"error": "no location"}), 400
    try:
        patient_lat = float(patient_lat)
        patient_lng = float(patient_lng)
    except (TypeError, ValueError):
        return jsonify({"error": "no location"}), 400

    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()

    # Get patient's active bookings
    cursor.execute("""
        SELECT bookings.id, bookings.clinic_id, clinics.latitude, clinics.longitude, clinics.name
        FROM bookings
        JOIN clinics ON bookings.clinic_id = clinics.id
        WHERE bookings.patient_id = ? AND bookings.status = 'waiting' AND bookings.arrived = 0
    """, (session["patient_id"],))
    bookings = cursor.fetchall()

    arrived_clinics = []
    for booking in bookings:
        booking_id, clinic_id, clinic_lat, clinic_lng, clinic_name = booking
        if clinic_lat and clinic_lng:
            distance = get_distance_km(patient_lat, patient_lng, clinic_lat, clinic_lng)
            # If within 200 meters
            if distance <= 0.2:
                cursor.execute("UPDATE bookings SET arrived = 1 WHERE id = ?", (booking_id,))
                arrived_clinics.append({
                    "clinic_id": clinic_id,
                    "clinic_name": clinic_name,
                    "distance_m": round(distance * 1000)
                })

    conn.commit()
    conn.close()

    return jsonify({"arrived": arrived_clinics})

@app.route("/my_bookings")
def my_bookings():
    if "patient_id" not in session:
        return redirect("/patient/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("""
    SELECT bookings.id, bookings.patient_id, bookings.clinic_id,
           bookings.booked_at, bookings.status, bookings.arrived,
           clinics.name, clinics.doctor, clinics.patients_waiting,
           clinics.minutes_per_patient, clinics.latitude, clinics.longitude,
           bookings.reviewed
    FROM bookings
    JOIN clinics ON bookings.clinic_id = clinics.id
    WHERE bookings.patient_id = ? AND bookings.status = 'waiting'
    ORDER BY bookings.booked_at DESC
""", (session["patient_id"],))
    bookings = cursor.fetchall()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (session["patient_id"],))
    patient = cursor.fetchone()
    conn.close()
    return render_template("my_bookings.html", bookings=bookings, patient=patient)

# ─── DOCTOR ROUTES ────────────────────────────────────────
@app.route("/doctor/register", methods=["GET", "POST"])
def doctor_register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        phone = request.form["phone"]
        clinic_name = request.form["clinic_name"]
        specialty = request.form["specialty"]
        minutes_per_patient = request.form["minutes_per_patient"]
        conn = sqlite3.connect("tabibak.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM doctors WHERE email = ?", (email,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return render_template("doctor_register.html", error="Email already registered!", success=False)
        cursor.execute("INSERT INTO clinics (name, doctor, specialty, patients_waiting, minutes_per_patient, is_open) VALUES (?, ?, ?, 0, ?, 0)",
                      (clinic_name, name, specialty, minutes_per_patient))
        clinic_id = cursor.lastrowid
        cursor.execute("INSERT INTO doctors (name, email, password, clinic_id, is_arrived, phone, specialty, status) VALUES (?, ?, ?, ?, 0, ?, ?, 'pending')",
                      (name, email, password, clinic_id, phone, specialty))
        conn.commit()
        conn.close()
        return render_template("doctor_register.html", error=None, success=True)
    return render_template("doctor_register.html", error=None, success=False)

@app.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        doctor = get_doctor_by_email(email)
        if doctor and doctor[3] == password:
            if doctor[8] == "pending":
                return render_template("doctor_login.html", error="Your account is still pending approval. Please wait 24 hours.")
            session["doctor_id"] = doctor[0]
            session["doctor_name"] = doctor[1]
            session["clinic_id"] = doctor[4]
            return redirect("/doctor/dashboard")
        else:
            return render_template("doctor_login.html", error="Wrong email or password!")
    return render_template("doctor_login.html", error=None)

@app.route("/doctor/dashboard")
def doctor_dashboard():
    if "doctor_id" not in session:
        return redirect("/doctor/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (session["clinic_id"],))
    clinic = cursor.fetchone()
    conn.close()
    return render_template("doctor_dashboard.html",
        doctor=session["doctor_name"],
        clinic=clinic)

@app.route("/doctor/patient/<int:patient_id>")
def doctor_view_patient(patient_id):
    if "doctor_id" not in session:
        return redirect("/doctor/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1 FROM bookings
        WHERE patient_id = ? AND clinic_id = ?
        LIMIT 1
        """,
        (patient_id, session["clinic_id"]),
    )
    if not cursor.fetchone():
        conn.close()
        return redirect("/doctor/dashboard")
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    patient = cursor.fetchone()
    if not patient:
        conn.close()
        return redirect("/doctor/dashboard")
    cursor.execute("SELECT * FROM medical_documents WHERE patient_id = ?", (patient_id,))
    documents = cursor.fetchall()
    conn.close()
    return render_template("doctor_view_patient.html", patient=patient, documents=documents)

@app.route("/doctor/arrive")
def doctor_arrive():
    if "doctor_id" not in session:
        return redirect("/doctor/login")
    update_clinic_status(session["clinic_id"], 1)
    return redirect("/doctor/dashboard")

@app.route("/doctor/leave")
def doctor_leave():
    if "doctor_id" not in session:
        return redirect("/doctor/login")
    update_clinic_status(session["clinic_id"], 0)
    return redirect("/doctor/dashboard")

@app.route("/doctor/next")
def next_patient():
    if "doctor_id" not in session:
        return redirect("/doctor/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clinics SET patients_waiting = MAX(0, patients_waiting - 1) WHERE id = ?", (session["clinic_id"],))
    conn.commit()
    conn.close()
    return redirect("/doctor/dashboard")

@app.route("/doctor/logout")
def doctor_logout():
    session.clear()
    return redirect("/")

# ─── PATIENT ROUTES ───────────────────────────────────────
@app.route("/patient/register", methods=["GET", "POST"])
def patient_register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        age = request.form["age"]
        blood_type = request.form["blood_type"]
        phone = request.form["phone"]
        conn = sqlite3.connect("tabibak.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM patients WHERE email = ?", (email,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return render_template("patient_register.html", error="Email already registered!")
        cursor.execute("INSERT INTO patients (name, email, password, age, blood_type, phone) VALUES (?, ?, ?, ?, ?, ?)",
                      (name, email, password, age, blood_type, phone))
        conn.commit()
        patient_id = cursor.lastrowid
        conn.close()
        session["patient_id"] = patient_id
        session["patient_name"] = name
        return redirect("/patient/profile")
    return render_template("patient_register.html", error=None)

@app.route("/patient/login", methods=["GET", "POST"])
def patient_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        conn = sqlite3.connect("tabibak.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM patients WHERE email = ? AND password = ?", (email, password))
        patient = cursor.fetchone()
        conn.close()
        if patient:
            session["patient_id"] = patient[0]
            session["patient_name"] = patient[1]
            return redirect("/patient/profile")
        else:
            return render_template("patient_login.html", error="Wrong email or password!")
    return render_template("patient_login.html", error=None)

@app.route("/patient/profile")
def patient_profile():
    if "patient_id" not in session:
        return redirect("/patient/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (session["patient_id"],))
    patient = cursor.fetchone()
    cursor.execute("SELECT * FROM medical_documents WHERE patient_id = ?", (session["patient_id"],))
    documents = cursor.fetchall()
    cursor.execute("""
        SELECT bookings.*, clinics.name, clinics.doctor, clinics.patients_waiting, clinics.minutes_per_patient
        FROM bookings
        JOIN clinics ON bookings.clinic_id = clinics.id
        WHERE bookings.patient_id = ? AND bookings.status = 'waiting'
        ORDER BY bookings.booked_at DESC
    """, (session["patient_id"],))
    bookings = cursor.fetchall()
    conn.close()
    return render_template("patient_profile.html", patient=patient, documents=documents, success=None, bookings=bookings)

@app.route("/patient/upload", methods=["POST"])
def patient_upload():
    if "patient_id" not in session:
        return redirect("/patient/login")
    description = request.form["description"]
    file = request.files["document"]
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{session['patient_id']}_{filename}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], unique_filename))
        conn = sqlite3.connect("tabibak.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO medical_documents (patient_id, filename, description) VALUES (?, ?, ?)",
                      (session["patient_id"], unique_filename, description))
        conn.commit()
        conn.close()
    return redirect("/patient/profile")

@app.route("/patient/logout")
def patient_logout():
    session.clear()
    return redirect("/")

# ─── ADMIN ROUTES ─────────────────────────────────────────
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form["password"] == "tabibak_admin_2026":
            session["admin"] = True
            session["admin_csrf"] = secrets.token_urlsafe(32)
            return redirect("/admin")
        return render_template("admin_login.html", error="Wrong password!")
    return render_template("admin_login.html", error=None)

@app.route("/admin")
def admin():
    if session.get("admin") != True:
        return redirect("/admin/login")
    if not session.get("admin_csrf"):
        session["admin_csrf"] = secrets.token_urlsafe(32)

    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "all").strip().lower()
    if status_filter not in ("all", "pending", "approved"):
        status_filter = "all"

    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    ensure_admin_schema(cursor)

    cursor.execute("""
        SELECT doctors.id, doctors.name, doctors.email, doctors.password, doctors.clinic_id,
               doctors.is_arrived, doctors.phone, doctors.specialty, doctors.status,
               clinics.name AS clinic_name
        FROM doctors
        LEFT JOIN clinics ON doctors.clinic_id = clinics.id
        WHERE 1=1
    """ + (
        " AND (doctors.name LIKE ? OR doctors.email LIKE ? OR IFNULL(clinics.name,'') LIKE ?)"
        if q else ""
    ) + (
        " AND doctors.status = 'pending'" if status_filter == "pending" else
        " AND doctors.status = 'approved'" if status_filter == "approved" else ""
    ) + " ORDER BY doctors.id",
        (f"%{q}%", f"%{q}%", f"%{q}%") if q else (),
    )
    doctors = cursor.fetchall()

    cursor.execute("""
        SELECT doctors.id, doctors.name, doctors.email, doctors.password, doctors.clinic_id,
               doctors.is_arrived, doctors.phone, doctors.specialty, doctors.status,
               clinics.name AS clinic_name
        FROM doctors
        LEFT JOIN clinics ON doctors.clinic_id = clinics.id
        WHERE doctors.status = 'pending'
        ORDER BY doctors.id
    """)
    pending_list = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM doctors WHERE status = 'pending'")
    pending_doctors = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM doctors")
    total_doctors = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM clinics")
    total_clinics = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM bookings WHERE status = 'waiting'")
    bookings_waiting = cursor.fetchone()[0]

    cursor.execute("""
        SELECT bookings.id, bookings.booked_at, bookings.status, bookings.arrived,
               patients.name AS patient_name, patients.email AS patient_email,
               clinics.id AS clinic_id, clinics.name AS clinic_name
        FROM bookings
        JOIN patients ON bookings.patient_id = patients.id
        JOIN clinics ON bookings.clinic_id = clinics.id
        ORDER BY bookings.booked_at DESC
        LIMIT 40
    """)
    recent_bookings = cursor.fetchall()

    cursor.execute("""
        SELECT id, name, doctor, patients_waiting, minutes_per_patient,
               (patients_waiting * minutes_per_patient) AS est_wait
        FROM clinics
        WHERE is_open = 1
          AND (patients_waiting >= 10 OR (patients_waiting * minutes_per_patient) >= 120)
        ORDER BY est_wait DESC
        LIMIT 10
    """)
    queue_hot = cursor.fetchall()

    cursor.execute("""
        SELECT id, name, doctor, patients_waiting, minutes_per_patient
        FROM clinics
        WHERE is_open = 0 AND patients_waiting > 0
        ORDER BY patients_waiting DESC
        LIMIT 8
    """)
    queue_closed_busy = cursor.fetchall()

    cursor.execute(
        "SELECT id, action, detail, created_at FROM admin_audit_log ORDER BY id DESC LIMIT 30"
    )
    audit_log = cursor.fetchall()

    conn.close()

    csrf_token = session["admin_csrf"]
    return render_template(
        "admin.html",
        doctors=doctors,
        pending_list=pending_list,
        total_doctors=total_doctors,
        pending_doctors=pending_doctors,
        total_patients=total_patients,
        total_clinics=total_clinics,
        bookings_waiting=bookings_waiting,
        recent_bookings=recent_bookings,
        queue_hot=queue_hot,
        queue_closed_busy=queue_closed_busy,
        audit_log=audit_log,
        filter_q=q,
        filter_status=status_filter,
        csrf_token=csrf_token,
    )

@app.route("/admin/approve/<int:doctor_id>", methods=["POST"])
def approve_doctor(doctor_id):
    if session.get("admin") != True:
        return redirect("/admin/login")
    if not admin_csrf_valid():
        flash("Security check failed. Please refresh the admin page and try again.", "error")
        return admin_redirect_after_mutation()
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    ensure_admin_schema(cursor)
    cursor.execute("SELECT name, email FROM doctors WHERE id = ?", (doctor_id,))
    row = cursor.fetchone()
    cursor.execute("UPDATE doctors SET status = 'approved' WHERE id = ?", (doctor_id,))
    cursor.execute(
        "UPDATE clinics SET is_open = 1 WHERE id = (SELECT clinic_id FROM doctors WHERE id = ?)",
        (doctor_id,),
    )
    if row:
        log_admin_action(cursor, "approve_doctor", f"id={doctor_id} name={row[0]} email={row[1]}")
    conn.commit()
    conn.close()
    flash("Doctor approved and clinic opened.", "success")
    return admin_redirect_after_mutation()

@app.route("/admin/reject/<int:doctor_id>", methods=["POST"])
def reject_doctor(doctor_id):
    if session.get("admin") != True:
        return redirect("/admin/login")
    if not admin_csrf_valid():
        flash("Security check failed. Please refresh the admin page and try again.", "error")
        return admin_redirect_after_mutation()
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    ensure_admin_schema(cursor)
    cursor.execute("SELECT name, email FROM doctors WHERE id = ?", (doctor_id,))
    row = cursor.fetchone()
    delete_doctor_and_clinic(cursor, doctor_id)
    if row:
        log_admin_action(cursor, "reject_doctor", f"id={doctor_id} name={row[0]} email={row[1]}")
    conn.commit()
    conn.close()
    flash("Registration rejected and removed.", "success")
    return admin_redirect_after_mutation()

@app.route("/admin/doctor/add", methods=["POST"])
def admin_add_doctor():
    if session.get("admin") != True:
        return redirect("/admin/login")
    if not admin_csrf_valid():
        flash("Security check failed. Please refresh the admin page and try again.", "error")
        return admin_redirect_after_mutation()
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    phone = request.form.get("phone", "").strip()
    clinic_name = request.form.get("clinic_name", "").strip()
    specialty = request.form.get("specialty", "").strip()
    minutes_raw = request.form.get("minutes_per_patient", "15").strip()
    address = request.form.get("address", "").strip() or "Cairo, Egypt"
    lat_raw = request.form.get("latitude", "").strip()
    lng_raw = request.form.get("longitude", "").strip()

    if not all([name, email, password, phone, clinic_name, specialty]):
        flash("Please fill in all required fields.", "error")
        return admin_redirect_after_mutation()
    try:
        minutes_per_patient = max(5, min(120, int(minutes_raw)))
    except ValueError:
        flash("Minutes per patient must be a number (5–120).", "error")
        return admin_redirect_after_mutation()
    try:
        latitude = float(lat_raw) if lat_raw else 30.0444
        longitude = float(lng_raw) if lng_raw else 31.2357
    except ValueError:
        flash("Latitude and longitude must be valid numbers.", "error")
        return admin_redirect_after_mutation()

    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    ensure_admin_schema(cursor)
    cursor.execute("SELECT id FROM doctors WHERE email = ?", (email,))
    if cursor.fetchone():
        conn.close()
        flash("That email is already registered.", "error")
        return admin_redirect_after_mutation()
    cursor.execute(
        """INSERT INTO clinics (name, doctor, specialty, patients_waiting, minutes_per_patient, is_open,
           latitude, longitude, address) VALUES (?, ?, ?, 0, ?, 1, ?, ?, ?)""",
        (clinic_name, name, specialty, minutes_per_patient, latitude, longitude, address),
    )
    clinic_id = cursor.lastrowid
    cursor.execute(
        """INSERT INTO doctors (name, email, password, clinic_id, is_arrived, phone, specialty, status)
           VALUES (?, ?, ?, ?, 0, ?, ?, 'approved')""",
        (name, email, password, clinic_id, phone, specialty),
    )
    new_id = cursor.lastrowid
    log_admin_action(
        cursor,
        "add_doctor",
        f"id={new_id} name={name} email={email} clinic={clinic_name} clinic_id={clinic_id}",
    )
    conn.commit()
    conn.close()
    flash(f"Doctor {name} added and approved.", "success")
    return admin_redirect_after_mutation()

@app.route("/admin/doctor/delete/<int:doctor_id>", methods=["POST"])
def admin_delete_doctor(doctor_id):
    if session.get("admin") != True:
        return redirect("/admin/login")
    if not admin_csrf_valid():
        flash("Security check failed. Please refresh the admin page and try again.", "error")
        return admin_redirect_after_mutation()
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    ensure_admin_schema(cursor)
    cursor.execute("SELECT name FROM doctors WHERE id = ?", (doctor_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        flash("Doctor not found.", "error")
        return admin_redirect_after_mutation()
    doc_name = row[0]
    delete_doctor_and_clinic(cursor, doctor_id)
    log_admin_action(cursor, "delete_doctor", f"id={doctor_id} name={doc_name}")
    conn.commit()
    conn.close()
    flash(f"Removed doctor: {doc_name}.", "success")
    return admin_redirect_after_mutation()

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    session.pop("admin_csrf", None)
    flash("You are logged out of the admin panel.", "success")
    return redirect("/admin/login")

# ─── REVIEW ROUTES ────────────────────────────────────────
@app.route("/review/<int:booking_id>")
def leave_review(booking_id):
    if "patient_id" not in session:
        return redirect("/patient/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE id = ? AND patient_id = ?",
                  (booking_id, session["patient_id"]))
    booking = cursor.fetchone()
    if not booking:
        conn.close()
        return redirect("/my_bookings")
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (booking[2],))
    clinic = cursor.fetchone()
    conn.close()
    return render_template("leave_review.html", clinic=clinic, booking_id=booking_id, error=None)

@app.route("/review/submit", methods=["POST"])
def submit_review():
    if "patient_id" not in session:
        return redirect("/patient/login")
    clinic_id = request.form["clinic_id"]
    booking_id = request.form["booking_id"]
    rating = request.form.get("rating")
    comment = request.form["comment"]
    if not rating:
        conn = sqlite3.connect("tabibak.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,))
        clinic = cursor.fetchone()
        conn.close()
        return render_template("leave_review.html", clinic=clinic,
                             booking_id=booking_id, error="Please select a star rating!")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reviews (patient_id, clinic_id, rating, comment) VALUES (?, ?, ?, ?)",
                  (session["patient_id"], clinic_id, rating, comment))
    cursor.execute("UPDATE bookings SET reviewed = 1 WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()
    return redirect("/my_bookings?reviewed=true")

if __name__ == "__main__":
    app.run(debug=True)