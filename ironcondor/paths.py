from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "_cache.json"
SETTINGS_FILE = BASE_DIR / "settings.json"


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
