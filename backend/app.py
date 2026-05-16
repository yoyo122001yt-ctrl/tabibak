import os

from flask import Flask

from backend.config import Config, BASE_DIR
from backend.routes.public import public_bp
from backend.routes.patient import patient_bp
from backend.routes.doctor import doctor_bp
from backend.routes.admin import admin_bp
from backend.routes.api import api_bp


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, "templates"),
        static_folder=os.path.join(BASE_DIR, "static"),
    )
    app.secret_key = Config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH
    app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER
    app.config["TESTING"] = os.environ.get("FLASK_TESTING", "0") == "1"

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

    app.register_blueprint(public_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    return app
