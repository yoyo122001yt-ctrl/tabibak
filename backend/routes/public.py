from flask import Blueprint, render_template

from backend.services.clinic import get_clinics, get_clinic_reviews_summary

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def home():
    return render_template("index.html")


@public_bp.route("/map")
def map_view():
    data = get_clinics()
    clinics = [dict(c) for c in data]
    return render_template("map.html", clinics=clinics)


@public_bp.route("/clinics")
def clinics():
    data = get_clinics()
    reviews = get_clinic_reviews_summary()
    return render_template("clinics.html", clinics=data, reviews=reviews)
