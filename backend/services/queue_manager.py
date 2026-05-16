from backend.config import Config

_redis_available = None
_redis_client = None


def _get_redis():
    global _redis_available, _redis_client
    if _redis_available is False:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as _redis_mod
        _redis_client = _redis_mod.from_url(Config.REDIS_URL, socket_timeout=2, decode_responses=True)
        _redis_client.ping()
        _redis_available = True
        return _redis_client
    except Exception:
        _redis_available = False
        _redis_client = None
        return None


def get_queue_key(clinic_id):
    return f"queue:{clinic_id}"


def publish_queue_update(clinic_id, data):
    r = _get_redis()
    if r is None:
        return False
    try:
        key = get_queue_key(clinic_id)
        import json
        r.setex(key, 300, json.dumps(data))
        r.publish(f"queue-updates:{clinic_id}", json.dumps(data))
        return True
    except Exception:
        return False


def get_cached_queue(clinic_id):
    r = _get_redis()
    if r is None:
        return None
    try:
        import json
        data = r.get(get_queue_key(clinic_id))
        if data:
            return json.loads(data)
        return None
    except Exception:
        return None
