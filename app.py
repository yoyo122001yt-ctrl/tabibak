from flask import Flask, render_template, request, redirect, session
import sqlite3

app = Flask(__name__)
app.secret_key = "tabibak_secret_123"

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

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/clinics")
def clinics():
    data = get_clinics()
    return render_template("clinics.html", clinics=data)

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
    conn.close()
    return render_template("doctor_dashboard.html", doctor=session["doctor_name"], clinic=clinic)

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

if __name__ == "__main__":
    app.run(debug=True)