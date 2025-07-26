# wiretide/logging.py
import os
import logging
from logging.handlers import RotatingFileHandler

LOG_FILE = "/var/log/wiretide.log"

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Configure rotating log handler (5MB per file, keep 5 backups)
handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5)
formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)

# Root logger setup
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(handler)

# Redirect uvicorn logs to the same file
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("uvicorn.error").addHandler(handler)
logging.getLogger("uvicorn.access").addHandler(handler)
