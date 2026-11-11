import logging
import re
from io import BytesIO
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image


logger = logging.getLogger(__name__)


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def _find_quote_rects(
    words: list[tuple[str, pymupdf.Rect]],
    quote: str,
) -> list[pymupdf.Rect]:
    quote_tokens = _tokens(quote)
    if not quote_tokens:
        return []

    page_tokens = []
    for word_text, rectangle in words:
        word_tokens = _tokens(word_text)
        for token in word_tokens:
            page_tokens.append((token, rectangle))

    for start in range(len(page_tokens) - len(quote_tokens) + 1):
        if [
            token
            for token, _ in page_tokens[
                start:start + len(quote_tokens)
            ]
        ] != quote_tokens:
            continue

        return [
            rect
            for _, rect in page_tokens[
                start:start + len(quote_tokens)
            ]
        ]

    return []


def _matching_word_rects(
    page,
    quote: str,
) -> list[pymupdf.Rect]:
    words = [
        (str(word[4]), pymupdf.Rect(word[:4]))
        for word in page.get_text("words", sort=True)
    ]
    rectangles = _find_quote_rects(words, quote)
    if rectangles:
        return rectangles

    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(2, 2),
        alpha=False,
    )
    image = Image.open(BytesIO(pixmap.tobytes("png")))

    try:
        ocr = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
        )
    except (
        pytesseract.TesseractNotFoundError,
        pytesseract.TesseractError,
    ) as exc:
        logger.warning(
            "OCR could not locate a PDF citation highlight: %s",
            exc,
        )
        return []

    ocr_words = []
    for index, text in enumerate(ocr["text"]):
        if not str(text).strip():
            continue

        rectangle = pymupdf.Rect(
            ocr["left"][index] / 2,
            ocr["top"][index] / 2,
            (
                ocr["left"][index] + ocr["width"][index]
            ) / 2,
            (
                ocr["top"][index] + ocr["height"][index]
            ) / 2,
        )
        if page.rotation:
            rectangle *= page.derotation_matrix

        ocr_words.append((str(text), rectangle))

    return _find_quote_rects(ocr_words, quote)


def render_pdf_page(
    path: str | Path,
    page_number: int,
    quote: str | None = None,
) -> tuple[bytes, bool, float | None]:
    """Render a page as PNG and highlight only an exact word match."""

    with pymupdf.open(path) as document:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError("The requested PDF page does not exist.")

        page = document[page_number - 1]
        matched = False
        highlight_y = None

        if quote:
            rectangles = _matching_word_rects(page, quote)
            if rectangles:
                display_rectangles = [
                    rectangle * page.rotation_matrix
                    for rectangle in rectangles
                ]
                highlight_y = (
                    min(rect.y0 for rect in display_rectangles)
                    + max(rect.y1 for rect in display_rectangles)
                ) / (2 * page.rect.height)
                for rectangle in rectangles:
                    page.draw_rect(
                        rectangle,
                        color=(0.8, 0.55, 0),
                        fill=(1, 0.88, 0.2),
                        fill_opacity=0.38,
                        width=0.5,
                        overlay=True,
                    )
                matched = True

        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),
            alpha=False,
        )
        return pixmap.tobytes("png"), matched, highlight_y
