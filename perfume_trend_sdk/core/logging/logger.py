import json
from datetime import datetime


def log_event(level: str, message: str, **kwargs) -> None:
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "message": message,
        **kwargs,
    }
    print(json.dumps(entry))
