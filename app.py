from flask import Flask, render_template, request, redirect, session, jsonify, flash
import sqlite3
import os
import math
import secrets
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
# Use environment variable for secret key in production
app.secret_key = os.environ.get("SECRET_KEY", "tabibak_secret_123")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB upload limit
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "tabibak.db")

# ============ HELPER FUNCTIONS ============

def allowed_file(filename):
    return filename and "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_db():
    """Get database connection with row factory for named columns"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_clinics():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics")
    clinics = cursor.fetchall()
    conn.close()
    return clinics

def get_doctor_by_email(email):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE email = ?", (email,))
    doctor = cursor.fetchone()
    conn.close()
    return doctor

def get_patient_by_email(email):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE email = ?", (email,))
    patient = cursor.fetchone()
    conn.close()
    return patient

def update_clinic_status(clinic_id, is_open):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE clinics SET is_open = ? WHERE id = ?", (is_open, clinic_id))
    conn.commit()
    conn.close()

def get_distance_km(lat1, lng1, lat2, lng2):
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return 999
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def login_required(role=None):
    """Decorator to check if user is logged in"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if role == 'patient' and 'patient_id' not in session:
                return redirect('/patient/login')
            elif role == 'doctor' and 'doctor_id' not in session:
                return redirect('/doctor/login')
            elif role == 'admin' and session.get('admin') != True:
                return redirect('/admin/login')
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ============ MAIN PAGES ============

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/map")
def map_view():
    data = get_clinics()
    # Convert SQLite Row objects to plain dicts for JSON serialization in template
    clinics = [dict(c) for c in data]
    return render_template("map.html", clinics=clinics)

@app.route("/clinics")
def clinics():
    data = get_clinics()
    conn = get_db()
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
        reviews[r['clinic_id']] = {"avg": r['avg_rating'], "count": r['review_count']}
    return render_template("clinics.html", clinics=data, reviews=reviews)

# ============ BOOKING ROUTES ============

@app.route("/book/<int:clinic_id>")
@login_required('patient')
def book_clinic(clinic_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if patient already has a booking for this clinic
    cursor.execute("SELECT * FROM bookings WHERE patient_id = ? AND clinic_id = ? AND status = 'waiting'",
                  (session["patient_id"], clinic_id))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return redirect(f"/booking/confirm/{clinic_id}?already=true")
    
    # Increment waiting patients and create booking
    cursor.execute("UPDATE clinics SET patients_waiting = patients_waiting + 1 WHERE id = ?", (clinic_id,))
    cursor.execute("INSERT INTO bookings (patient_id, clinic_id, booked_at, status) VALUES (?, ?, ?, 'waiting')",
                  (session["patient_id"], clinic_id, datetime.now()))
    conn.commit()
    conn.close()
    return redirect(f"/booking/confirm/{clinic_id}")

@app.route("/booking/confirm/<int:clinic_id>")
@login_required('patient')
def booking_confirm(clinic_id):
    already = request.args.get("already", False)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,))
    clinic = cursor.fetchone()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (session["patient_id"],))
    patient = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE clinic_id = ? AND status = 'waiting'", (clinic_id,))
    queue_position = cursor.fetchone()['count']
    conn.close()
    
    wait_time = clinic['patients_waiting'] * clinic['minutes_per_patient']
    return render_template("booking_confirm.html",
        clinic=clinic,
        patient=patient,
        wait_time=wait_time,
        queue_position=queue_position,
        already=already)

@app.route("/cancel_booking/<int:booking_id>")
@login_required('patient')
def cancel_booking(booking_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # Get the clinic_id from the booking
    cursor.execute("SELECT clinic_id FROM bookings WHERE id = ? AND patient_id = ?", 
                  (booking_id, session["patient_id"]))
    booking = cursor.fetchone()
    
    if booking:
        # Decrease queue count
        cursor.execute("UPDATE clinics SET patients_waiting = MAX(0, patients_waiting - 1) WHERE id = ?", 
                      (booking['clinic_id'],))
        # Update booking status to cancelled
        cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        conn.commit()
    
    conn.close()
    return redirect("/my_bookings")

@app.route("/my_bookings")
@login_required('patient')
def my_bookings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT bookings.id, bookings.patient_id, bookings.clinic_id,
               bookings.booked_at, bookings.status, bookings.arrived,
               clinics.name, clinics.doctor, clinics.patients_waiting,
               clinics.minutes_per_patient, clinics.latitude, clinics.longitude,
               bookings.reviewed
        FROM bookings
        JOIN clinics ON bookings.clinic_id = clinics.id
        WHERE bookings.patient_id = ? AND bookings.status IN ('waiting', 'completed')
        ORDER BY bookings.booked_at DESC
    """, (session["patient_id"],))
    bookings = cursor.fetchall()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (session["patient_id"],))
    patient = cursor.fetchone()
    conn.close()
    return render_template("my_bookings.html", bookings=bookings, patient=patient)

# ============ AUTO ARRIVE ============

@app.route("/api/check_arrival", methods=["POST"])
@login_required('patient')
def check_arrival():
    data = request.get_json()
    patient_lat = data.get("lat")
    patient_lng = data.get("lng")

    if patient_lat is None or patient_lng is None:
        return jsonify({"error": "no location"}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT bookings.id, bookings.clinic_id, clinics.latitude, clinics.longitude, clinics.name
        FROM bookings
        JOIN clinics ON bookings.clinic_id = clinics.id
        WHERE bookings.patient_id = ? AND bookings.status = 'waiting' AND bookings.arrived = 0
    """, (session["patient_id"],))
    bookings = cursor.fetchall()

    arrived_clinics = []
    for booking in bookings:
        if booking['latitude'] is not None and booking['longitude'] is not None:
            distance = get_distance_km(patient_lat, patient_lng, booking['latitude'], booking['longitude'])
            if distance <= 0.2:  # Within 200 meters
                cursor.execute("UPDATE bookings SET arrived = 1 WHERE id = ?", (booking['id'],))
                arrived_clinics.append({
                    "clinic_id": booking['clinic_id'],
                    "clinic_name": booking['name'],
                    "distance_m": round(distance * 1000)
                })

    conn.commit()
    conn.close()
    return jsonify({"arrived": arrived_clinics})

# ============ DOCTOR ROUTES ============

@app.route("/doctor/register", methods=["GET", "POST"])
def doctor_register():
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

        conn = get_db()
        cursor = conn.cursor()
        
        # Check if email already exists
        cursor.execute("SELECT * FROM doctors WHERE email = ?", (email,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return render_template("doctor_register.html", error="Email already registered!", success=False)
        
        # Hash the password
        hashed_password = generate_password_hash(password)
        
        # Create clinic
        cursor.execute("""INSERT INTO clinics (name, doctor, specialty, patients_waiting, minutes_per_patient, is_open) 
                       VALUES (?, ?, ?, 0, ?, 0)""",
                      (clinic_name, name, specialty, minutes_per_patient))
        clinic_id = cursor.lastrowid
        
        # Create doctor with pending status
        cursor.execute("""INSERT INTO doctors (name, email, password, clinic_id, is_arrived, phone, specialty, status) 
                       VALUES (?, ?, ?, ?, 0, ?, ?, 'pending')""",
                      (name, email, hashed_password, clinic_id, phone, specialty))
        
        conn.commit()
        conn.close()
        return render_template("doctor_register.html", error=None, success=True)
    
    return render_template("doctor_register.html", error=None, success=False)

@app.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        doctor = get_doctor_by_email(email)
        
        if doctor and check_password_hash(doctor['password'], password):
            if doctor['status'] == "pending":
                return render_template("doctor_login.html", error="Your account is still pending approval. Please wait.")
            elif doctor['status'] == "rejected":
                return render_template("doctor_login.html", error="Your account has been rejected. Contact support.")
            
            session["doctor_id"] = doctor['id']
            session["doctor_name"] = doctor['name']
            session["clinic_id"] = doctor['clinic_id']
            return redirect("/doctor/dashboard")
        else:
            return render_template("doctor_login.html", error="Wrong email or password!")
    
    return render_template("doctor_login.html", error=None)

@app.route("/doctor/dashboard")
@login_required('doctor')
def doctor_dashboard():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (session["clinic_id"],))
    clinic = cursor.fetchone()
    
    # Get patients for this clinic only
    cursor.execute("""
        SELECT DISTINCT patients.* FROM patients
        JOIN bookings ON bookings.patient_id = patients.id
        WHERE bookings.clinic_id = ?
    """, (session["clinic_id"],))
    patients = cursor.fetchall()
    
    # Get arrived patients waiting
    cursor.execute("""
        SELECT patients.name, patients.phone, patients.id as patient_id, bookings.booked_at
        FROM bookings
        JOIN patients ON bookings.patient_id = patients.id
        WHERE bookings.clinic_id = ? AND bookings.arrived = 1 AND bookings.status = 'waiting'
        ORDER BY bookings.booked_at ASC
    """, (session["clinic_id"],))
    arrived_patients = cursor.fetchall()
    
    # Get queue count
    cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE clinic_id = ? AND status = 'waiting' AND arrived = 0", 
                  (session["clinic_id"],))
    queue_count = cursor.fetchone()['count']
    
    conn.close()
    return render_template("doctor_dashboard.html",
        doctor=session["doctor_name"],
        clinic=clinic,
        patients=patients,
        arrived_patients=arrived_patients,
        queue_count=queue_count)

@app.route("/doctor/patient/<int:patient_id>")
@login_required('doctor')
def doctor_view_patient(patient_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT patients.* FROM patients
        JOIN bookings ON bookings.patient_id = patients.id
        WHERE patients.id = ? AND bookings.clinic_id = ?
    """, (patient_id, session["clinic_id"]))
    patient = cursor.fetchone()
    if not patient:
        conn.close()
        return redirect("/doctor/dashboard")
    
    # Check if doctor has access to documents
    cursor.execute("""
        SELECT * FROM document_access_requests 
        WHERE doctor_id = ? AND patient_id = ? AND status = 'approved'
        ORDER BY responded_at DESC LIMIT 1
    """, (session["doctor_id"], patient_id))
    access_granted = cursor.fetchone()
    
    # Check if there's a pending request
    cursor.execute("""
        SELECT * FROM document_access_requests 
        WHERE doctor_id = ? AND patient_id = ? AND status = 'pending'
        ORDER BY requested_at DESC LIMIT 1
    """, (session["doctor_id"], patient_id))
    pending_request = cursor.fetchone()
    
    # Only show documents if access is granted
    documents = []
    if access_granted:
        cursor.execute("SELECT * FROM medical_documents WHERE patient_id = ?", (patient_id,))
        documents = cursor.fetchall()
    
    conn.close()
    return render_template("doctor_view_patient.html", 
                         patient=patient, 
                         documents=documents,
                         access_granted=access_granted,
                         pending_request=pending_request)

@app.route("/doctor/arrive")
@login_required('doctor')
def doctor_arrive():
    update_clinic_status(session["clinic_id"], 1)
    return redirect("/doctor/dashboard")

@app.route("/doctor/leave")
@login_required('doctor')
def doctor_leave():
    update_clinic_status(session["clinic_id"], 0)
    return redirect("/doctor/dashboard")

@app.route("/doctor/next")
@login_required('doctor')
def next_patient():
    conn = get_db()
    cursor = conn.cursor()
    
    # Get the oldest waiting patient who has arrived
    cursor.execute("""
        SELECT id FROM bookings 
        WHERE clinic_id = ? AND status = 'waiting' AND arrived = 1 
        ORDER BY booked_at ASC LIMIT 1
    """, (session["clinic_id"],))
    booking = cursor.fetchone()
    
    if booking:
        # Mark this booking as completed
        cursor.execute("UPDATE bookings SET status = 'completed' WHERE id = ?", (booking['id'],))
        # Decrease the waiting counter
        cursor.execute("UPDATE clinics SET patients_waiting = MAX(0, patients_waiting - 1) WHERE id = ?", 
                      (session["clinic_id"],))
        conn.commit()
    
    conn.close()
    return redirect("/doctor/dashboard")

@app.route("/doctor/request_documents/<int:patient_id>", methods=["POST"])
@login_required('doctor')
def request_documents(patient_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # Verify patient has booked this doctor's clinic
    cursor.execute("""
        SELECT * FROM bookings 
        WHERE patient_id = ? AND clinic_id = ?
    """, (patient_id, session["clinic_id"]))
    booking = cursor.fetchone()
    
    if not booking:
        conn.close()
        return redirect("/doctor/dashboard")
    
    # Check if request already exists
    cursor.execute("""
        SELECT * FROM document_access_requests 
        WHERE doctor_id = ? AND patient_id = ? AND status = 'pending'
    """, (session["doctor_id"], patient_id))
    existing = cursor.fetchone()
    
    if not existing:
        # Create new request
        cursor.execute("""
            INSERT INTO document_access_requests (doctor_id, patient_id, clinic_id, status, requested_at)
            VALUES (?, ?, ?, 'pending', ?)
        """, (session["doctor_id"], patient_id, session["clinic_id"], datetime.now()))
        conn.commit()
    
    conn.close()
    return redirect(f"/doctor/patient/{patient_id}")

@app.route("/doctor/logout")
def doctor_logout():
    session.pop("doctor_id", None)
    session.pop("doctor_name", None)
    session.pop("clinic_id", None)
    return redirect("/")

# ============ PATIENT ROUTES ============

@app.route("/patient/register", methods=["GET", "POST"])
def patient_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        age = safe_int(request.form.get("age"), None)
        blood_type = request.form.get("blood_type", "").strip()
        phone = request.form.get("phone", "").strip()
        
        if not name or not email or not password or age is None or not blood_type or not phone:
            return render_template("patient_register.html", error="All fields are required!")

        conn = get_db()
        cursor = conn.cursor()
        
        # Check if email already exists
        existing = get_patient_by_email(email)
        if existing:
            conn.close()
            return render_template("patient_register.html", error="Email already registered!")
        
        # Hash the password
        hashed_password = generate_password_hash(password)
        
        cursor.execute("""INSERT INTO patients (name, email, password, age, blood_type, phone) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                      (name, email, hashed_password, age, blood_type, phone))
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
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        patient = get_patient_by_email(email)
        
        if patient and check_password_hash(patient['password'], password):
            session["patient_id"] = patient['id']
            session["patient_name"] = patient['name']
            return redirect("/patient/profile")
        else:
            return render_template("patient_login.html", error="Wrong email or password!")
    
    return render_template("patient_login.html", error=None)

@app.route("/patient/profile")
@login_required('patient')
def patient_profile():
    conn = get_db()
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
    
    # Get pending document access requests
    cursor.execute("""
        SELECT dar.*, doctors.name as doctor_name, clinics.name as clinic_name
        FROM document_access_requests dar
        JOIN doctors ON dar.doctor_id = doctors.id
        JOIN clinics ON dar.clinic_id = clinics.id
        WHERE dar.patient_id = ? AND dar.status = 'pending'
        ORDER BY dar.requested_at DESC
    """, (session["patient_id"],))
    pending_requests = cursor.fetchall()
    
    conn.close()
    return render_template("patient_profile.html", 
                         patient=patient, 
                         documents=documents, 
                         success=None, 
                         bookings=bookings,
                         pending_requests=pending_requests)

@app.route("/patient/upload", methods=["POST"])
@login_required('patient')
def patient_upload():
    description = request.form.get("description", "").strip()
    file = request.files.get("document")
    if not file or file.filename == "":
        return redirect("/patient/profile")

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{session['patient_id']}_{timestamp}_{filename}"
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_filename)
        file.save(file_path)
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO medical_documents (patient_id, filename, description, uploaded_at) VALUES (?, ?, ?, ?)",
                      (session["patient_id"], unique_filename, description, datetime.now()))
        conn.commit()
        conn.close()
    return redirect("/patient/profile")

@app.route("/patient/approve_request/<int:request_id>", methods=["POST"])
@login_required('patient')
def approve_document_request(request_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # Verify this request belongs to the logged-in patient
    cursor.execute("""
        SELECT * FROM document_access_requests 
        WHERE id = ? AND patient_id = ? AND status = 'pending'
    """, (request_id, session["patient_id"]))
    request_data = cursor.fetchone()
    
    if request_data:
        cursor.execute("""
            UPDATE document_access_requests 
            SET status = 'approved', responded_at = ?
            WHERE id = ?
        """, (datetime.now(), request_id))
        conn.commit()
    
    conn.close()
    return redirect("/patient/profile")

@app.route("/patient/reject_request/<int:request_id>", methods=["POST"])
@login_required('patient')
def reject_document_request(request_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # Verify this request belongs to the logged-in patient
    cursor.execute("""
        SELECT * FROM document_access_requests 
        WHERE id = ? AND patient_id = ? AND status = 'pending'
    """, (request_id, session["patient_id"]))
    request_data = cursor.fetchone()
    
    if request_data:
        cursor.execute("""
            UPDATE document_access_requests 
            SET status = 'rejected', responded_at = ?
            WHERE id = ?
        """, (datetime.now(), request_id))
        conn.commit()
    
    conn.close()
    return redirect("/patient/profile")

@app.route("/patient/logout")
def patient_logout():
    session.pop("patient_id", None)
    session.pop("patient_name", None)
    return redirect("/")

# ============ ADMIN ROUTES ============

# Get admin password from environment variable (SECURITY FIX)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "tabibak_admin_2026")

def ensure_admin_schema():
    """Make sure audit log table exists"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def audit_log_entry(action, detail=""):
    """Write one row to the admin audit log"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO admin_audit_log (action, detail, created_at) VALUES (?, ?, ?)",
                      (action, detail, datetime.now()))
        conn.commit()
        conn.close()
    except Exception:
        pass

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form["password"] == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin")
        return render_template("admin_login.html", error="Wrong password!")
    return render_template("admin_login.html", error=None)

@app.route("/admin")
@login_required('admin')
def admin():
    ensure_admin_schema()
    conn = get_db()
    cursor = conn.cursor()

    # --- Filters ---
    filter_q = request.args.get('q', '').strip()
    filter_status = request.args.get('status', 'all')

    # --- Doctors (with optional clinic name join) ---
    doctor_query = """
        SELECT doctors.*, clinics.name as clinic_name
        FROM doctors
        LEFT JOIN clinics ON doctors.clinic_id = clinics.id
        WHERE 1=1
    """
    params = []
    if filter_q:
        doctor_query += " AND (doctors.name LIKE ? OR doctors.email LIKE ? OR clinics.name LIKE ?)"
        like = f"%{filter_q}%"
        params.extend([like, like, like])
    if filter_status != 'all':
        doctor_query += " AND doctors.status = ?"
        params.append(filter_status)
    doctor_query += " ORDER BY doctors.id DESC"
    cursor.execute(doctor_query, params)
    doctors = cursor.fetchall()

    # --- Pending list (always unfiltered) ---
    cursor.execute("""
        SELECT doctors.*, clinics.name as clinic_name
        FROM doctors
        LEFT JOIN clinics ON doctors.clinic_id = clinics.id
        WHERE doctors.status = 'pending'
        ORDER BY doctors.id DESC
    """)
    pending_list = cursor.fetchall()

    # --- Counts ---
    cursor.execute("SELECT COUNT(*) as count FROM doctors WHERE status = 'pending'")
    pending_doctors = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM patients")
    total_patients = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM clinics")
    total_clinics = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE status = 'waiting'")
    bookings_waiting = cursor.fetchone()['count']

    # --- Queue alerts ---
    cursor.execute("""
        SELECT id, name, doctor, patients_waiting, minutes_per_patient,
               patients_waiting * minutes_per_patient as est_wait, is_open
        FROM clinics
        WHERE is_open = 1 AND (patients_waiting >= 10 OR patients_waiting * minutes_per_patient >= 120)
    """)
    queue_hot = cursor.fetchall()

    cursor.execute("""
        SELECT id, name, doctor, patients_waiting, minutes_per_patient,
               patients_waiting * minutes_per_patient as est_wait, is_open
        FROM clinics
        WHERE is_open = 0 AND patients_waiting > 0
    """)
    queue_closed_busy = cursor.fetchall()

    # --- Recent bookings ---
    cursor.execute("""
        SELECT bookings.id, bookings.booked_at, bookings.status, bookings.arrived,
               patients.name, patients.email, patients.id as patient_id,
               clinics.name as clinic_name
        FROM bookings
        JOIN patients ON bookings.patient_id = patients.id
        JOIN clinics ON bookings.clinic_id = clinics.id
        ORDER BY bookings.booked_at DESC
        LIMIT 40
    """)
    recent_bookings = cursor.fetchall()

    # --- Audit log ---
    cursor.execute("SELECT * FROM admin_audit_log ORDER BY created_at DESC LIMIT 30")
    audit_log = cursor.fetchall()

    # --- CSRF token ---
    if 'csrf_token' not in session:
        import secrets
        session['csrf_token'] = secrets.token_hex(16)

    conn.close()
    return render_template("admin.html",
        doctors=doctors,
        total_doctors=len(doctors),
        pending_doctors=pending_doctors,
        pending_list=pending_list,
        total_patients=total_patients,
        total_clinics=total_clinics,
        bookings_waiting=bookings_waiting,
        queue_hot=queue_hot,
        queue_closed_busy=queue_closed_busy,
        recent_bookings=recent_bookings,
        audit_log=audit_log,
        filter_q=filter_q,
        filter_status=filter_status,
        csrf_token=session.get('csrf_token', ''))

@app.route("/admin/approve/<int:doctor_id>", methods=["GET", "POST"])
@login_required('admin')
def approve_doctor(doctor_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    cursor.execute("UPDATE doctors SET status = 'approved' WHERE id = ?", (doctor_id,))
    cursor.execute("UPDATE clinics SET is_open = 1 WHERE id = (SELECT clinic_id FROM doctors WHERE id = ?)", (doctor_id,))
    conn.commit()
    conn.close()
    if doc:
        audit_log_entry("APPROVE", f"Approved doctor: {doc['name']} (id={doctor_id})")
    return redirect("/admin")

@app.route("/admin/reject/<int:doctor_id>", methods=["GET", "POST"])
@login_required('admin')
def reject_doctor(doctor_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, clinic_id FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    if doc:
        cursor.execute("DELETE FROM clinics WHERE id = ?", (doc['clinic_id'],))
        audit_log_entry("REJECT", f"Rejected doctor: {doc['name']} (id={doctor_id})")
    cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/admin/add_doctor", methods=["POST"])
@login_required('admin')
def admin_add_doctor():
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
        from flask import flash
        flash("All required fields must be filled.", "error")
        return redirect("/admin")

    try:
        lat = float(latitude) if latitude else 30.0444
        lng = float(longitude) if longitude else 31.2357
    except ValueError:
        lat, lng = 30.0444, 31.2357

    hashed_password = generate_password_hash(password)

    conn = get_db()
    cursor = conn.cursor()

    # Check duplicate email
    cursor.execute("SELECT id FROM doctors WHERE email = ?", (email,))
    if cursor.fetchone():
        from flask import flash
        flash(f"Email {email} already exists.", "error")
        conn.close()
        return redirect("/admin")

    cursor.execute("""INSERT INTO clinics (name, doctor, specialty, patients_waiting, minutes_per_patient, is_open, latitude, longitude, address)
                   VALUES (?, ?, ?, 0, ?, 1, ?, ?, ?)""",
                  (clinic_name, name, specialty, minutes_per_patient, lat, lng, address))
    clinic_id = cursor.lastrowid

    cursor.execute("""INSERT INTO doctors (name, email, password, clinic_id, is_arrived, phone, specialty, status)
                   VALUES (?, ?, ?, ?, 0, ?, ?, 'approved')""",
                  (name, email, hashed_password, clinic_id, phone, specialty))

    conn.commit()
    conn.close()
    audit_log_entry("ADD_DOCTOR", f"Added doctor: {name} ({email}) with clinic: {clinic_name}")
    from flask import flash
    flash(f"Doctor {name} and clinic {clinic_name} created successfully!", "success")
    return redirect("/admin")

@app.route("/admin/delete_doctor/<int:doctor_id>", methods=["POST"])
@login_required('admin')
def admin_delete_doctor(doctor_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, clinic_id FROM doctors WHERE id = ?", (doctor_id,))
    doc = cursor.fetchone()
    if doc:
        clinic_id = doc['clinic_id']
        # Clean up related data
        cursor.execute("DELETE FROM bookings WHERE clinic_id = ?", (clinic_id,))
        cursor.execute("DELETE FROM reviews WHERE clinic_id = ?", (clinic_id,))
        cursor.execute("DELETE FROM clinics WHERE id = ?", (clinic_id,))
        cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
        audit_log_entry("DELETE", f"Deleted doctor: {doc['name']} (id={doctor_id}) and clinic_id={clinic_id}")
    conn.commit()
    conn.close()
    from flask import flash
    flash("Doctor and clinic deleted.", "success")
    return redirect("/admin")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/")

# ============ REVIEW ROUTES ============

@app.route("/review/<int:booking_id>")
@login_required('patient')
def leave_review(booking_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE id = ? AND patient_id = ? AND status = 'completed' AND reviewed = 0",
                  (booking_id, session["patient_id"]))
    booking = cursor.fetchone()
    if not booking:
        conn.close()
        return redirect("/my_bookings")
    cursor.execute("SELECT * FROM clinics WHERE id = ?", (booking['clinic_id'],))
    clinic = cursor.fetchone()
    conn.close()
    return render_template("leave_review.html", clinic=clinic, booking_id=booking_id, error=None)

@app.route("/review/submit", methods=["POST"])
@login_required('patient')
def submit_review():
    clinic_id = safe_int(request.form.get("clinic_id"))
    booking_id = safe_int(request.form.get("booking_id"))
    rating = safe_int(request.form.get("rating"))
    comment = request.form.get("comment", "").strip()

    if not clinic_id or not booking_id or not rating:
        conn = get_db()
        conn.close()
        return redirect("/my_bookings")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE id = ? AND patient_id = ? AND status = 'completed' AND reviewed = 0",
                  (booking_id, session["patient_id"]))
    booking = cursor.fetchone()
    if not booking or booking['clinic_id'] != clinic_id:
        conn.close()
        return redirect("/my_bookings")

    cursor.execute("INSERT INTO reviews (patient_id, clinic_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?)",
                  (session["patient_id"], clinic_id, rating, comment, datetime.now()))
    cursor.execute("UPDATE bookings SET reviewed = 1 WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()
    return redirect("/my_bookings?reviewed=true")

# ============ DATABASE INITIALIZATION ============

def init_db():
    """Initialize database with tables if they don't exist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create clinics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clinics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            doctor TEXT,
            specialty TEXT,
            patients_waiting INTEGER DEFAULT 0,
            minutes_per_patient INTEGER DEFAULT 15,
            is_open INTEGER DEFAULT 0,
            latitude REAL DEFAULT 0,
            longitude REAL DEFAULT 0,
            address TEXT DEFAULT ''
        )
    """)
    
    # Create doctors table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT,
            clinic_id INTEGER,
            is_arrived INTEGER DEFAULT 0,
            phone TEXT,
            specialty TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    
    # Create patients table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT,
            age INTEGER,
            blood_type TEXT,
            phone TEXT
        )
    """)
    
    # Create medical_documents table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medical_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            filename TEXT,
            description TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create bookings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            clinic_id INTEGER,
            booked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'waiting',
            arrived INTEGER DEFAULT 0,
            reviewed INTEGER DEFAULT 0
        )
    """)
    
    # Create reviews table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            clinic_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully!")

# Run database initialization
if not os.path.exists(DB_PATH):
    init_db()

if __name__ == "__main__":
    app.run(debug=True)