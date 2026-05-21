"""Конвертация PDF в markdown через docling (пайплайн как в doclingocr)."""
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def pdf_to_markdown(pdf_path: Path) -> str:
    """
    Конвертирует PDF в markdown с тем же пайплайном, что и в doclingocr:
    OCR через Tesseract (rus + eng), без bbox/JSON — только распознавание и markdown.
    """
    ocr_options = TesseractCliOcrOptions(lang=["rus", "eng"])
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=ocr_options,
        generate_picture_images=False,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
    result = converter.convert(pdf_path)
    return result.document.export_to_markdown()
