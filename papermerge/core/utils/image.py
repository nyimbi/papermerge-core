import logging
from pathlib import Path
from uuid import UUID

try:
	from pdf2image import convert_from_path
except ImportError:
	convert_from_path = None  # type: ignore[assignment]
from PIL import Image

from papermerge.core import constants as const
from papermerge.core import pathlib as core_pathlib
from papermerge.core.types import ImagePreviewSize
from papermerge.core import config

settings = config.get_settings()

PREVIEW_IMAGE_MAP = {
    # size name        : size in pixels
    ImagePreviewSize.sm: settings.preview_page_size_sm,
}

logger = logging.getLogger(__name__)

# Image file extensions that can be thumbnailed directly (not PDFs)
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.gif', '.webp'}


def file_name_generator(size):
    yield str(size)


def gen_doc_thumbnail(
    page_id: UUID,
    doc_ver_id: UUID,
    page_number: int,
    file_name: str,
    size: int = const.DEFAULT_THUMBNAIL_SIZE,
):
    """
    Extracts jpg image of page `page_number` from document file associated with
    given `doc_ver_id`.

    For PDF files: extracts page as image using pdf2image/poppler.
    For image files (JPEG, PNG, TIFF, etc.): creates thumbnail directly using PIL.

    `doc_ver_id` and `file_name` are required for getting the file location.
    `page_id` and `size` are required for knowing where to save jpg file.
    """
    thb_path = core_pathlib.abs_thumbnail_path(str(page_id))
    doc_path = core_pathlib.abs_docver_path(str(doc_ver_id), file_name)

    # Check if the file is an image (not a PDF)
    file_ext = Path(file_name).suffix.lower()
    if file_ext in IMAGE_EXTENSIONS:
        # For image files, create thumbnail directly using PIL
        generate_image_thumbnail(
            image_path=doc_path,
            output_folder=thb_path.parent,
            size_px=settings.preview_page_size_sm,
            size_name=ImagePreviewSize.sm.value,
        )
    else:
        # For PDF files, use pdf2image
        generate_preview(
            pdf_path=doc_path,
            output_folder=thb_path.parent,
            page_number=page_number,
            size_px=settings.preview_page_size_sm,
            size_name=ImagePreviewSize.sm.value,
        )


def generate_image_thumbnail(
    image_path: Path,
    output_folder: Path,
    size_px: int,
    size_name: str,
):
    """Generate jpg thumbnail from an image file (JPEG, PNG, TIFF, etc.)"""
    output_folder.mkdir(exist_ok=True, parents=True)
    output_path = output_folder / f"{size_name}.jpg"

    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (e.g., for RGBA PNGs)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            # Calculate new size maintaining aspect ratio
            width, height = img.size
            if width > height:
                new_width = size_px
                new_height = int(height * (size_px / width))
            else:
                new_height = size_px
                new_width = int(width * (size_px / height))

            # Resize using high-quality resampling
            img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Save as JPEG
            img_resized.save(output_path, 'JPEG', quality=85)
            logger.debug(f"Generated thumbnail: {output_path}")
    except Exception as e:
        logger.error(f"Failed to generate image thumbnail: {e}")


def generate_preview(
    pdf_path: Path,
    output_folder: Path,
    size_px: int,
    size_name: str,
    page_number: int = 1,
):
    """Generate jpg thumbnail/preview images of PDF document"""
    kwargs = {
        "pdf_path": str(pdf_path),
        "output_folder": str(output_folder),
        "fmt": "jpg",
        "first_page": page_number,
        "last_page": page_number,
        "single_file": True,
        "size": (size_px, None),
        "output_file": file_name_generator(size_name),
    }

    output_folder.mkdir(exist_ok=True, parents=True)

    # generates jpeg previews of PDF file using pdftoppm (poppler-utils)
    convert_from_path(**kwargs)
