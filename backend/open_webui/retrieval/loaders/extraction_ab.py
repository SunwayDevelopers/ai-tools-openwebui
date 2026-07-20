"""Sunway A/B: runtime-mutable extraction-strategy toggles.

The PDF / office fast-path decisions are read from here at *request time* (not from the
boot-time env constants), so the Admin UI can flip them WITHOUT restarting the app --
each new upload picks up the current values. Seeded from env at import.

Scope note: this is a process-global (per-worker) in-memory store, meant for dev A/B
benchmarking. Under multi-worker production it would differ per worker and resets on
restart; production should pin the strategy via the env defaults rather than toggling
here at runtime.
"""

from open_webui.env import (
    RAG_OFFICE_FAST_PATH,
    RAG_OFFICE_FAST_PATH_ENGINE,
    RAG_PDF_FAST_PATH,
    RAG_PDF_FAST_PATH_ENGINE,
)

PDF_ENGINES = ('pypdf', 'markitdown')
OFFICE_ENGINES = ('unstructured', 'markitdown')

_STATE = {
    'pdf_fast_path': RAG_PDF_FAST_PATH,
    'pdf_engine': (RAG_PDF_FAST_PATH_ENGINE if RAG_PDF_FAST_PATH_ENGINE in PDF_ENGINES else 'pypdf'),
    'office_fast_path': RAG_OFFICE_FAST_PATH,
    'office_engine': (RAG_OFFICE_FAST_PATH_ENGINE if RAG_OFFICE_FAST_PATH_ENGINE in OFFICE_ENGINES else 'unstructured'),
}


def get_state() -> dict:
    """Return a copy of the current toggle values."""
    return dict(_STATE)


def update_state(
    pdf_fast_path: bool | None = None,
    pdf_engine: str | None = None,
    office_fast_path: bool | None = None,
    office_engine: str | None = None,
) -> dict:
    """Set any subset of toggles and return the new state.

    Unknown engine values are ignored (state is left unchanged for that key).
    """
    if pdf_fast_path is not None:
        _STATE['pdf_fast_path'] = bool(pdf_fast_path)
    if pdf_engine is not None and pdf_engine in PDF_ENGINES:
        _STATE['pdf_engine'] = pdf_engine
    if office_fast_path is not None:
        _STATE['office_fast_path'] = bool(office_fast_path)
    if office_engine is not None and office_engine in OFFICE_ENGINES:
        _STATE['office_engine'] = office_engine
    return dict(_STATE)
