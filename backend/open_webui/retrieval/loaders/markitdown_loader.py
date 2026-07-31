import logging
import sys
from typing import List, Optional

from langchain_core.documents import Document
from open_webui.env import GLOBAL_LOG_LEVEL

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)


class MarkItDownLoader:
    """Extract a document to Markdown via Microsoft MarkItDown.

    A lightweight, text-layer converter (no OCR / layout ML models) covering PDF, Office
    (docx/xlsx/pptx), HTML, CSV, etc. Used as one option of the Sunway office fast-path
    A/B (vs the langchain Unstructured loaders). Scanned / complex files still need Docling
    -- MarkItDown's PDF path reads the text layer only and does not OCR.
    """

    def __init__(self, file_path: str, mime_type: Optional[str] = None):
        self.file_path = file_path
        self.mime_type = mime_type

    def load(self) -> List[Document]:
        # Imported lazily so the dependency is only required when this engine is selected.
        from markitdown import MarkItDown

        log.info(f'Processing with MarkItDown: {self.file_path}')
        result = MarkItDown(enable_plugins=False).convert(self.file_path)
        content = (getattr(result, 'text_content', None) or '').strip()

        return [
            Document(
                page_content=content,
                metadata={'Content-Type': self.mime_type or '', 'processing_engine': 'markitdown'},
            )
        ]
