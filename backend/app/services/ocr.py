import os
import shutil
from pathlib import Path

import pytesseract


def configure_tesseract() -> None:
    command = (
        os.environ.get("TESSERACT_CMD")
        or shutil.which("tesseract")
    )

    if command is None and os.name == "nt":
        windows_install = Path(
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        )
        if windows_install.is_file():
            command = str(windows_install)

    if command:
        pytesseract.pytesseract.tesseract_cmd = command
