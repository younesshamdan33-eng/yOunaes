import os
from pathlib import Path

class Cfg:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get("CW_HOME") or (Path.home() / "cinema-worker"))
        self.token = os.environ.get("CW_TOKEN", "")
        tf = self.home / "token"
        if not self.token and tf.is_file():
            self.token = tf.read_text().strip()
        self.host = os.environ.get("CW_HOST", "127.0.0.1")
        self.port = int(os.environ.get("CW_PORT", "8800"))
        self.max_queue = int(os.environ.get("CW_MAX_QUEUE", "20"))
        self.keep_days = int(os.environ.get("CW_KEEP_DAYS", "7"))
        self.enable_fake = os.environ.get("CW_ENABLE_FAKE") == "1"
    @property
    def models_dir(self):
        return self.home / "models"
    @property
    def jobs_dir(self):
        return self.home / "jobs"
