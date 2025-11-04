import logging
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


logger = logging.getLogger("omni_pro")

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logger.setLevel(LOG_LEVEL)
