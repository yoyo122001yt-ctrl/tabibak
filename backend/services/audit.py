from datetime import datetime

from backend.data.database import get_db


def log_action(action, detail=""):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO admin_audit_log (action, detail, created_at) VALUES (?, ?, ?)",
            (action, detail, datetime.now()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_recent_logs(limit=30):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin_audit_log ORDER BY created_at DESC LIMIT ?", (limit,))
    logs = cursor.fetchall()
    conn.close()
    return logs
