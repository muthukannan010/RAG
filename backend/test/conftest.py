import os
import tempfile
from pathlib import Path


TEST_ROOT = Path(
    tempfile.mkdtemp(prefix="local-rag-tests-")
)

TEST_DATA = TEST_ROOT / "data"

os.environ["DATA_DIR"] = str(TEST_DATA)
os.environ["DOCUMENTS_DIR"] = str(
    TEST_DATA / "documents"
)
os.environ["SQLITE_DB_PATH"] = str(
    TEST_DATA / "rag.sqlite3"
)
os.environ["CHROMA_DB_PATH"] = str(
    TEST_DATA / "chroma"
)
os.environ["LOG_LEVEL"] = "WARNING"