import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_DB_PATH = ROOT / "tests" / "test_app.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
