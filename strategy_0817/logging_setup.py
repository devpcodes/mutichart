
# -*- coding: utf-8 -*-
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime

def setup_logging(app_name: str = "live", log_dir: str | None = None, level: int = logging.INFO):
    """
    Initialize logging:
    - Console handler (INFO)
    - Rotating file logs/{app_name}_YYYYMMDD.log (INFO)
    - File size rotation (10MB * 10 backups)
    """
    log_dir_path = Path(log_dir) if log_dir else Path("logs")
    log_dir_path.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    log_file = log_dir_path / f"{app_name}_{date_str}.log"

    root = logging.getLogger()
    # Avoid duplicate handlers
    if getattr(root, "_configured_by_strategy", False):
        return log_file

    root.setLevel(level)

    # Console
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s - %(message)s"))

    # File (rotating)
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=10, encoding="utf-8"
    )
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    root.addHandler(ch)
    root.addHandler(fh)
    root._configured_by_strategy = True
    logging.getLogger(__name__).info("Logging initialized. File: %s", log_file)
    return log_file
