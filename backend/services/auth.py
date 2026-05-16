from functools import wraps
from flask import session, redirect
from werkzeug.security import generate_password_hash, check_password_hash

from backend.data.database import get_db


def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if role == "patient" and "patient_id" not in session:
                return redirect("/patient/login")
            elif role == "doctor" and "doctor_id" not in session:
                return redirect("/doctor/login")
            elif role == "admin" and session.get("admin") is not True:
                return redirect("/admin/login")
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password, hashed):
    return check_password_hash(hashed, password)


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
