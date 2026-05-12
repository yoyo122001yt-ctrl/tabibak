from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
import os
import math
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "tabibak_secret_123"

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
    return render_template("clinics.html", clinics=data)

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

    data = request.get_json()
    patient_lat = data.get("lat")
    patient_lng = data.get("lng")

    if not patient_lat or not patient_lng:
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
    cursor.execute("""
        SELECT patients.* FROM patients
        JOIN medical_documents ON patients.id = medical_documents.patient_id
        GROUP BY patients.id
    """)
    patients = cursor.fetchall()
    # Get arrived patients
    cursor.execute("""
        SELECT patients.name, patients.phone, bookings.booked_at
        FROM bookings
        JOIN patients ON bookings.patient_id = patients.id
        WHERE bookings.clinic_id = ? AND bookings.arrived = 1 AND bookings.status = 'waiting'
        ORDER BY bookings.booked_at DESC
    """, (session["clinic_id"],))
    arrived_patients = cursor.fetchall()
    conn.close()
    return render_template("doctor_dashboard.html",
        doctor=session["doctor_name"],
        clinic=clinic,
        patients=patients,
        arrived_patients=arrived_patients)

@app.route("/doctor/patient/<int:patient_id>")
def doctor_view_patient(patient_id):
    if "doctor_id" not in session:
        return redirect("/doctor/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    patient = cursor.fetchone()
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
            return redirect("/admin")
        return render_template("admin_login.html", error="Wrong password!")
    return render_template("admin_login.html", error=None)

@app.route("/admin")
def admin():
    if session.get("admin") != True:
        return redirect("/admin/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors")
    doctors = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM doctors WHERE status = 'pending'")
    pending_doctors = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM clinics")
    total_clinics = cursor.fetchone()[0]
    conn.close()
    return render_template("admin.html",
        doctors=doctors,
        total_doctors=len(doctors),
        pending_doctors=pending_doctors,
        total_patients=total_patients,
        total_clinics=total_clinics)

@app.route("/admin/approve/<int:doctor_id>")
def approve_doctor(doctor_id):
    if session.get("admin") != True:
        return redirect("/admin/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE doctors SET status = 'approved' WHERE id = ?", (doctor_id,))
    cursor.execute("UPDATE clinics SET is_open = 1 WHERE id = (SELECT clinic_id FROM doctors WHERE id = ?)", (doctor_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/admin/reject/<int:doctor_id>")
def reject_doctor(doctor_id):
    if session.get("admin") != True:
        return redirect("/admin/login")
    conn = sqlite3.connect("tabibak.db")
    cursor = conn.cursor()
    cursor.execute("SELECT clinic_id FROM doctors WHERE id = ?", (doctor_id,))
    result = cursor.fetchone()
    if result:
        cursor.execute("DELETE FROM clinics WHERE id = ?", (result[0],))
    cursor.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

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
