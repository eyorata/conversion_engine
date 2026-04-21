import logging
import sys

from agent.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)
