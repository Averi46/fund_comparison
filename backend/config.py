from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FUNDS_CSV = PROJECT_ROOT / "funds.csv"
METADATA_OVERRIDES_CSV = PROJECT_ROOT / "fund_metadata_overrides.csv"
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "fund_cache.db"
