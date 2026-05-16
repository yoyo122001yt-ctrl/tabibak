from flask import Blueprint, request, jsonify, redirect, render_template, session

from backend.services.auth import login_required
from backend.services.booking import check_arrival
from backend.services.review import get_reviewable_booking, submit_review
from backend.services.clinic import get_clinic_by_id
from backend.data.database import safe_int

api_bp = Blueprint("api", __name__)


@api_bp.route("/api/check_arrival", methods=["POST"])
@login_required("patient")
def check_arrival_endpoint():
    data = request.get_json()
    patient_lat = data.get("lat")
    patient_lng = data.get("lng")

    if patient_lat is None or patient_lng is None:
        return jsonify({"error": "no location"}), 400

    arrived = check_arrival(session["patient_id"], patient_lat, patient_lng)
    return jsonify({"arrived": arrived})


@api_bp.route("/review/<int:booking_id>")
@login_required("patient")
def leave_review(booking_id):
    booking = get_reviewable_booking(booking_id, session["patient_id"])
    if not booking:
        return redirect("/my_bookings")

    clinic = get_clinic_by_id(booking["clinic_id"])
    return render_template("leave_review.html", clinic=clinic, booking_id=booking_id, error=None)


@api_bp.route("/review/submit", methods=["POST"])
@login_required("patient")
def submit_review_endpoint():
    clinic_id = safe_int(request.form.get("clinic_id"))
    booking_id = safe_int(request.form.get("booking_id"))
    rating = safe_int(request.form.get("rating"))
    comment = request.form.get("comment", "").strip()

    if not clinic_id or not booking_id or not rating:
        return redirect("/my_bookings")

    success = submit_review(clinic_id, booking_id, session["patient_id"], rating, comment)
    return redirect("/my_bookings?reviewed=true" if success else "/my_bookings")
