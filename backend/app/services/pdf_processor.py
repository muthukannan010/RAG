
import re
import pymupdf
import pytesseract

from PIL import Image
from io import BytesIO

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def extract_pdf_pages(pdf_bytes: bytes) -> list[dict]:
    """
    Extract text blocks from PDF pages using PyMuPDF.
    If a page has no extractable text, use Tesseract OCR.

    Bounding boxes use PDF page coordinates:
    [x0, y0, x1, y1].
    """

    try:
        with pymupdf.open(
            stream=pdf_bytes,
            filetype="pdf",
        ) as pdf:

            if pdf.needs_pass:
                raise ValueError(
                    "Password-protected PDFs are not supported."
                )

            if pdf.page_count == 0:
                raise ValueError(
                    "The PDF contains no pages."
                )

            pages = []

            for page_index, page in enumerate(pdf):
                blocks = []

                # First, extract selectable text.
                for block in page.get_text(
                    "blocks",
                    sort=True,
                ):
                    if len(block) < 5:
                        continue

                    x0, y0, x1, y1, raw_text = block[:5]

                    # Ignore image-only blocks.
                    if len(block) >= 7 and block[6] == 1:
                        continue

                    text = re.sub(
                        r"\s+",
                        " ",
                        str(raw_text),
                    ).strip()

                    if not text:
                        continue

                    blocks.append(
                        {
                            "text": text,
                            "bbox": [
                                float(x0),
                                float(y0),
                                float(x1),
                                float(y1),
                            ],
                        }
                    )

                # If no text was extracted, run OCR.
                if not blocks:
                    pix = page.get_pixmap(
                        matrix=pymupdf.Matrix(2, 2),
                        alpha=False,
                    )

                    image = Image.open(
                        BytesIO(pix.tobytes("png"))
                    )

                    ocr_data = pytesseract.image_to_data(
                        image,
                        output_type=pytesseract.Output.DICT,
                    )

                    # Group recognized words into text lines.
                    lines = {}

                    for i, word in enumerate(
                        ocr_data["text"]
                    ):
                        word = word.strip()

                        if not word:
                            continue

                        key = (
                            ocr_data["block_num"][i],
                            ocr_data["par_num"][i],
                            ocr_data["line_num"][i],
                        )

                        lines.setdefault(key, []).append(i)

                    scale = 2.0

                    for indexes in lines.values():
                        text = " ".join(
                            ocr_data["text"][i].strip()
                            for i in indexes
                        ).strip()

                        if not text:
                            continue

                        x0 = min(
                            ocr_data["left"][i]
                            for i in indexes
                        ) / scale

                        y0 = min(
                            ocr_data["top"][i]
                            for i in indexes
                        ) / scale

                        x1 = max(
                            ocr_data["left"][i]
                            + ocr_data["width"][i]
                            for i in indexes
                        ) / scale

                        y1 = max(
                            ocr_data["top"][i]
                            + ocr_data["height"][i]
                            for i in indexes
                        ) / scale

                        blocks.append(
                            {
                                "text": re.sub(
                                    r"\s+",
                                    " ",
                                    text,
                                ),
                                "bbox": [
                                    float(x0),
                                    float(y0),
                                    float(x1),
                                    float(y1),
                                ],
                            }
                        )

                    # Sort OCR lines from top to bottom.
                    blocks.sort(
                        key=lambda b: (
                            b["bbox"][1],
                            b["bbox"][0],
                        )
                    )

                pages.append(
                    {
                        "page_number": page_index + 1,
                        "blocks": blocks,
                    }
                )

            return pages

    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "The uploaded file is not a readable PDF."
        ) from exc
