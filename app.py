from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
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

# ─── MAIN PAGES ───────────────────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/clinics")
def clinics():
    data = get_clinics()
    return render_template("clinics.html", clinics=data)

# ─── DOCTOR ROUTES ────────────────────────────────────────
@app.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        doctor = get_doctor_by_email(email)
        if doctor and doctor[3] == password:
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
    cursor.execute("SELECT patients.* FROM patients JOIN medical_documents ON patients.id = medical_documents.patient_id GROUP BY patients.id")
    patients = cursor.fetchall()
    conn.close()
    return render_template("doctor_dashboard.html", doctor=session["doctor_name"], clinic=clinic, patients=patients)

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
    conn.close()
    return render_template("patient_profile.html", patient=patient, documents=documents, success=None)

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

if __name__ == "__main__":
    app.run(debug=True)