import os
from backend.app import create_app
from backend.config import BASE_DIR
from backend.data.database import init_db, seed_db

app = create_app()

if not os.path.exists(os.path.join(BASE_DIR, "tabibak.db")):
    init_db()
    seed_db()

if __name__ == "__main__":
    app.run(debug=True)
