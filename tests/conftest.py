import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force SQLite for test runs to avoid dependency on a running MySQL instance
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-unit-testing-min-32-chars-long"
os.environ["DEBUG"] = "true"
os.environ["RATE_LIMIT_PERSISTENT"] = "false"
