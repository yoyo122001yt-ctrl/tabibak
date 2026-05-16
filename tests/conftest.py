import pytest
import os
import sys
import tempfile
import gc

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    import backend.data.database as db_module
    from backend.config import Config

    Config.DB_PATH = db_path
    Config.DB_ENGINE = "sqlite"

    from backend.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret-key"
    application.config["UPLOAD_FOLDER"] = tempfile.mkdtemp()

    with application.app_context():
        db_module.init_db()

    yield application

    gc.collect()
    for _ in range(3):
        try:
            os.unlink(db_path)
            break
        except PermissionError:
            import time
            time.sleep(0.1)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_conn(app):
    from backend.data.database import get_db

    conn = get_db()
    yield conn
    conn.close()
