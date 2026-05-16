import pytest
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def seed_clinic(db_conn):
    db_conn.execute(
        "INSERT INTO clinics (name, doctor, specialty, patients_waiting, minutes_per_patient, is_open, latitude, longitude, address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Test Clinic", "Dr. Test", "General", 5, 15, 1, 30.0444, 31.2357, "Cairo"),
    )
    db_conn.commit()
    return db_conn.execute("SELECT id FROM clinics ORDER BY id DESC LIMIT 1").fetchone()[0]


def seed_patient(db_conn):
    from werkzeug.security import generate_password_hash

    pw = generate_password_hash("testpass")
    db_conn.execute(
        "INSERT INTO patients (name, email, password, age, blood_type, phone) VALUES (?, ?, ?, ?, ?, ?)",
        ("Test Patient", "patient@test.com", pw, 30, "O+", "01000000000"),
    )
    db_conn.commit()
    return db_conn.execute("SELECT id FROM patients ORDER BY id DESC LIMIT 1").fetchone()[0]


def seed_doctor(db_conn, clinic_id):
    from werkzeug.security import generate_password_hash

    pw = generate_password_hash("docpass")
    db_conn.execute(
        "INSERT INTO doctors (name, email, password, clinic_id, is_arrived, phone, specialty, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("Dr. Test", "doc@test.com", pw, clinic_id, 0, "01000000001", "General", "approved"),
    )
    db_conn.commit()
    return db_conn.execute("SELECT id FROM doctors ORDER BY id DESC LIMIT 1").fetchone()[0]


def seed_booking(db_conn, patient_id, clinic_id, status="waiting", arrived=0):
    db_conn.execute(
        "INSERT INTO bookings (patient_id, clinic_id, booked_at, status, arrived) VALUES (?, ?, ?, ?, ?)",
        (patient_id, clinic_id, datetime.now(), status, arrived),
    )
    db_conn.commit()
    return db_conn.execute("SELECT id FROM bookings ORDER BY id DESC LIMIT 1").fetchone()[0]


class TestApp:
    def test_home_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_map_page(self, client):
        resp = client.get("/map")
        assert resp.status_code == 200

    def test_clinics_page(self, client):
        resp = client.get("/clinics")
        assert resp.status_code == 200


class TestHelpers:
    def test_safe_int_valid(self, app):
        from backend.data.database import safe_int
        with app.app_context():
            assert safe_int("42") == 42
            assert safe_int("0") == 0
            assert safe_int(-5) == -5

    def test_safe_int_invalid(self, app):
        from backend.data.database import safe_int
        with app.app_context():
            assert safe_int("abc") is None
            assert safe_int(None) is None
            assert safe_int("", 0) == 0

    def test_allowed_file(self, app):
        from backend.data.database import allowed_file
        with app.app_context():
            assert allowed_file("test.png") is True
            assert allowed_file("test.jpg") is True
            assert allowed_file("test.pdf") is True
            assert allowed_file("test.exe") is False
            assert not allowed_file("")
            assert not allowed_file(None)

    def test_get_distance_km(self, app):
        from backend.data.database import get_distance_km
        with app.app_context():
            dist = get_distance_km(30.0444, 31.2357, 30.0444, 31.2357)
            assert dist == 0
            dist2 = get_distance_km(30.0444, 31.2357, 30.0626, 31.2497)
            assert dist2 > 0
            dist3 = get_distance_km(None, 31.2357, 30.0444, 31.2357)
            assert dist3 == 999


class TestAuth:
    def test_patient_register_success(self, client, db_conn):
        resp = client.post(
            "/patient/register",
            data={
                "name": "New Patient",
                "email": "new@test.com",
                "password": "pass123",
                "age": "25",
                "blood_type": "A+",
                "phone": "01000000005",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        row = db_conn.execute("SELECT * FROM patients WHERE email='new@test.com'").fetchone()
        assert row is not None
        assert row["name"] == "New Patient"

    def test_patient_register_missing_fields(self, client):
        resp = client.post("/patient/register", data={"name": "", "email": "x@x.com"})
        assert resp.status_code == 200

    def test_patient_register_duplicate_email(self, client, db_conn):
        seed_patient(db_conn)
        resp = client.post(
            "/patient/register",
            data={
                "name": "Another",
                "email": "patient@test.com",
                "password": "pass",
                "age": "25",
                "blood_type": "B+",
                "phone": "01000000006",
            },
        )
        assert resp.status_code == 200

    def test_patient_login_success(self, client, db_conn):
        seed_patient(db_conn)
        resp = client.post(
            "/patient/login", data={"email": "patient@test.com", "password": "testpass"}, follow_redirects=True
        )
        assert resp.status_code == 200

    def test_patient_login_wrong_password(self, client, db_conn):
        seed_patient(db_conn)
        resp = client.post(
            "/patient/login", data={"email": "patient@test.com", "password": "wrongpass"}
        )
        assert resp.status_code == 200

    def test_doctor_register_success(self, client, db_conn):
        resp = client.post(
            "/doctor/register",
            data={
                "name": "Dr. New",
                "email": "newdoc@test.com",
                "password": "docpass",
                "phone": "01000000010",
                "clinic_name": "New Clinic",
                "specialty": "Dermatology",
                "minutes_per_patient": "20",
            },
        )
        assert resp.status_code == 200
        row = db_conn.execute("SELECT * FROM doctors WHERE email='newdoc@test.com'").fetchone()
        assert row is not None
        assert row["status"] == "pending"

    def test_doctor_login_success(self, client, db_conn):
        cid = seed_clinic(db_conn)
        seed_doctor(db_conn, cid)
        resp = client.post(
            "/doctor/login", data={"email": "doc@test.com", "password": "docpass"}, follow_redirects=True
        )
        assert resp.status_code == 200

    def test_doctor_login_rejected(self, client, db_conn):
        cid = seed_clinic(db_conn)
        from werkzeug.security import generate_password_hash
        pw = generate_password_hash("docpass")
        db_conn.execute(
            "INSERT INTO doctors (name, email, password, clinic_id, phone, specialty, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Dr. Rejected", "rejected@test.com", pw, cid, "01000000002", "General", "rejected"),
        )
        db_conn.commit()
        resp = client.post(
            "/doctor/login", data={"email": "rejected@test.com", "password": "docpass"}
        )
        assert resp.status_code == 200


class TestBooking:
    def test_book_clinic_while_logged_out(self, client):
        resp = client.get("/book/1", follow_redirects=True)
        assert resp.status_code == 200

    def test_book_clinic_success(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.get(f"/book/{cid}", follow_redirects=True)
        assert resp.status_code == 200
        booking = db_conn.execute(
            "SELECT * FROM bookings WHERE patient_id=? AND clinic_id=?", (pid, cid)
        ).fetchone()
        assert booking is not None
        assert booking["status"] == "waiting"

    def test_book_clinic_duplicate(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        seed_booking(db_conn, pid, cid)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.get(f"/book/{cid}", follow_redirects=True)
        assert resp.status_code == 200

    def test_cancel_booking(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        bid = seed_booking(db_conn, pid, cid)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.get(f"/cancel_booking/{bid}", follow_redirects=True)
        assert resp.status_code == 200
        booking = db_conn.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
        assert booking["status"] == "cancelled"

    def test_my_bookings(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        seed_booking(db_conn, pid, cid)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.get("/my_bookings")
        assert resp.status_code == 200

    def test_booking_confirm(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        seed_booking(db_conn, pid, cid)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.get(f"/booking/confirm/{cid}")
        assert resp.status_code == 200


class TestDoctorDashboard:
    def test_dashboard_redirect_when_logged_out(self, client):
        resp = client.get("/doctor/dashboard", follow_redirects=True)
        assert resp.status_code == 200

    def test_dashboard_logged_in(self, client, db_conn):
        cid = seed_clinic(db_conn)
        did = seed_doctor(db_conn, cid)
        with client.session_transaction() as sess:
            sess["doctor_id"] = did
            sess["doctor_name"] = "Dr. Test"
            sess["clinic_id"] = cid
        resp = client.get("/doctor/dashboard")
        assert resp.status_code == 200

    def test_doctor_arrive_leave(self, client, db_conn):
        cid = seed_clinic(db_conn)
        did = seed_doctor(db_conn, cid)
        with client.session_transaction() as sess:
            sess["doctor_id"] = did
            sess["doctor_name"] = "Dr. Test"
            sess["clinic_id"] = cid
        resp = client.get("/doctor/arrive", follow_redirects=True)
        assert resp.status_code == 200
        clinic = db_conn.execute("SELECT is_open FROM clinics WHERE id=?", (cid,)).fetchone()
        assert clinic["is_open"] == 1
        resp = client.get("/doctor/leave", follow_redirects=True)
        assert resp.status_code == 200
        clinic = db_conn.execute("SELECT is_open FROM clinics WHERE id=?", (cid,)).fetchone()
        assert clinic["is_open"] == 0

    def test_next_patient(self, client, db_conn):
        cid = seed_clinic(db_conn)
        did = seed_doctor(db_conn, cid)
        pid = seed_patient(db_conn)
        bid = seed_booking(db_conn, pid, cid, arrived=1)
        with client.session_transaction() as sess:
            sess["doctor_id"] = did
            sess["doctor_name"] = "Dr. Test"
            sess["clinic_id"] = cid
        resp = client.get("/doctor/next", follow_redirects=True)
        assert resp.status_code == 200
        booking = db_conn.execute("SELECT status FROM bookings WHERE id=?", (bid,)).fetchone()
        assert booking["status"] == "completed"


class TestAdmin:
    def test_admin_login_wrong(self, client):
        resp = client.post("/admin/login", data={"password": "wrong"})
        assert resp.status_code == 200

    def test_admin_login_correct(self, app, client):
        from backend.config import Config
        Config.ADMIN_PASSWORD = "testadmin"
        resp = client.post("/admin/login", data={"password": "testadmin"}, follow_redirects=True)
        assert resp.status_code == 200

    def test_admin_page(self, client):
        with client.session_transaction() as sess:
            sess["admin"] = True
        resp = client.get("/admin")
        assert resp.status_code == 200

    def test_admin_approve_doctor(self, client, db_conn):
        cid = seed_clinic(db_conn)
        from werkzeug.security import generate_password_hash
        pw = generate_password_hash("docpass")
        db_conn.execute(
            "INSERT INTO doctors (name, email, password, clinic_id, phone, specialty, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Dr. Pending", "pending@test.com", pw, cid, "01000000003", "General", "pending"),
        )
        db_conn.commit()
        did = db_conn.execute("SELECT id FROM doctors WHERE email='pending@test.com'").fetchone()[0]
        with client.session_transaction() as sess:
            sess["admin"] = True
        resp = client.get(f"/admin/approve/{did}", follow_redirects=True)
        assert resp.status_code == 200
        doc = db_conn.execute("SELECT status FROM doctors WHERE id=?", (did,)).fetchone()
        assert doc["status"] == "approved"

    def test_admin_reject_doctor(self, client, db_conn):
        cid = seed_clinic(db_conn)
        from werkzeug.security import generate_password_hash
        pw = generate_password_hash("docpass")
        db_conn.execute(
            "INSERT INTO doctors (name, email, password, clinic_id, phone, specialty, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Dr. Reject", "reject@test.com", pw, cid, "01000000004", "General", "pending"),
        )
        db_conn.commit()
        did = db_conn.execute("SELECT id FROM doctors WHERE email='reject@test.com'").fetchone()[0]
        with client.session_transaction() as sess:
            sess["admin"] = True
        resp = client.get(f"/admin/reject/{did}", follow_redirects=True)
        assert resp.status_code == 200
        doc = db_conn.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
        assert doc is None


class TestCheckArrival:
    def test_check_arrival_no_location(self, client, db_conn):
        pid = seed_patient(db_conn)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.post("/api/check_arrival", json={})
        assert resp.status_code == 400

    def test_check_arrival_no_bookings(self, client, db_conn):
        pid = seed_patient(db_conn)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.post("/api/check_arrival", json={"lat": 30.0444, "lng": 31.2357})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["arrived"] == []

    def test_check_arrival_within_range(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        seed_booking(db_conn, pid, cid)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.post("/api/check_arrival", json={"lat": 30.0444, "lng": 31.2357})
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["arrived"]) == 1
        assert data["arrived"][0]["clinic_id"] == cid

    def test_check_arrival_far_away(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        seed_booking(db_conn, pid, cid)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.post("/api/check_arrival", json={"lat": 31.0, "lng": 32.0})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["arrived"] == []


class TestReviews:
    def test_leave_review_redirects_when_not_completed(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        bid = seed_booking(db_conn, pid, cid)
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.get(f"/review/{bid}", follow_redirects=True)
        assert resp.status_code == 200

    def test_submit_review(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        bid = seed_booking(db_conn, pid, cid, status="completed")
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.post(
            "/review/submit",
            data={"clinic_id": cid, "booking_id": bid, "rating": 4, "comment": "Great!"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        review = db_conn.execute(
            "SELECT * FROM reviews WHERE patient_id=? AND clinic_id=?", (pid, cid)
        ).fetchone()
        assert review is not None
        assert review["rating"] == 4
        booking = db_conn.execute("SELECT reviewed FROM bookings WHERE id=?", (bid,)).fetchone()
        assert booking["reviewed"] == 1


class TestDocumentAccess:
    def test_request_documents(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        did = seed_doctor(db_conn, cid)
        seed_booking(db_conn, pid, cid)
        with client.session_transaction() as sess:
            sess["doctor_id"] = did
            sess["doctor_name"] = "Dr. Test"
            sess["clinic_id"] = cid
        resp = client.post(f"/doctor/request_documents/{pid}", follow_redirects=True)
        assert resp.status_code == 200
        req = db_conn.execute(
            "SELECT * FROM document_access_requests WHERE doctor_id=? AND patient_id=?", (did, pid)
        ).fetchone()
        assert req is not None
        assert req["status"] == "pending"

    def test_approve_document_request(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        did = seed_doctor(db_conn, cid)
        db_conn.execute(
            "INSERT INTO document_access_requests (doctor_id, patient_id, clinic_id, status, requested_at) VALUES (?, ?, ?, 'pending', ?)",
            (did, pid, cid, datetime.now()),
        )
        db_conn.commit()
        req_id = db_conn.execute(
            "SELECT id FROM document_access_requests ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.post(f"/patient/approve_request/{req_id}", follow_redirects=True)
        assert resp.status_code == 200
        req = db_conn.execute("SELECT status FROM document_access_requests WHERE id=?", (req_id,)).fetchone()
        assert req["status"] == "approved"

    def test_reject_document_request(self, client, db_conn):
        pid = seed_patient(db_conn)
        cid = seed_clinic(db_conn)
        did = seed_doctor(db_conn, cid)
        db_conn.execute(
            "INSERT INTO document_access_requests (doctor_id, patient_id, clinic_id, status, requested_at) VALUES (?, ?, ?, 'pending', ?)",
            (did, pid, cid, datetime.now()),
        )
        db_conn.commit()
        req_id = db_conn.execute(
            "SELECT id FROM document_access_requests ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        with client.session_transaction() as sess:
            sess["patient_id"] = pid
            sess["patient_name"] = "Test Patient"
        resp = client.post(f"/patient/reject_request/{req_id}", follow_redirects=True)
        assert resp.status_code == 200
        req = db_conn.execute("SELECT status FROM document_access_requests WHERE id=?", (req_id,)).fetchone()
        assert req["status"] == "rejected"


class TestLogout:
    def test_patient_logout(self, client):
        with client.session_transaction() as sess:
            sess["patient_id"] = 1
            sess["patient_name"] = "Test"
        resp = client.get("/patient/logout", follow_redirects=True)
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert "patient_id" not in sess

    def test_doctor_logout(self, client):
        with client.session_transaction() as sess:
            sess["doctor_id"] = 1
            sess["doctor_name"] = "Test"
            sess["clinic_id"] = 1
        resp = client.get("/doctor/logout", follow_redirects=True)
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert "doctor_id" not in sess

    def test_admin_logout(self, client):
        with client.session_transaction() as sess:
            sess["admin"] = True
        resp = client.get("/admin/logout", follow_redirects=True)
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get("admin") is not True


class TestPractice:
    def test_practice_script(self):
        import practice
        assert hasattr(practice, "wait_time")
        assert callable(practice.wait_time)
