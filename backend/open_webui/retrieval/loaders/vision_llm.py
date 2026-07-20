import base64
import logging
import mimetypes
import re
import sys
from typing import List, Optional

import requests
from langchain_core.documents import Document
from open_webui.env import CONTENT_EXTRACTION_REQUEST_TIMEOUT, GLOBAL_LOG_LEVEL, REQUESTS_VERIFY

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)

# Transcribe text AND describe visuals -- used when the vision LLM is the sole
# image reader (no separate OCR step).
DEFAULT_VISION_PROMPT = (
    'You extract the content of an image for a text-only assistant that cannot see it. '
    'First, transcribe ALL text in the image verbatim, in its original language -- do NOT '
    'translate -- preserving structure as Markdown (headings, lists, tables). If there is '
    'no clearly legible text, write nothing for this part; never guess, invent, or '
    'hallucinate text (including words in other languages/scripts) that is not plainly '
    'visible. Then, if the image contains non-text visuals (photos, charts, diagrams, '
    'screenshots), add a section "## Visual description" describing them factually. Do not '
    'summarize or invent anything that is not present. Output only the extracted content.'
)

# Describe visuals only -- used when Docling OCR already provides faithful text,
# so the vision LLM adds understanding without duplicating (or corrupting) text.
DEFAULT_VISION_DESCRIBE_PROMPT = (
    'A separate OCR step has already transcribed any text in this image. Describe the '
    'non-text visual content factually -- photos, charts, diagrams, screenshots, layout -- '
    'so a text-only assistant can understand what the image shows. Do not transcribe text '
    'again and do not invent anything not visible. If there is nothing beyond text, reply '
    'exactly: (no additional visual content).'
)

# Defensive removal of leaked chain-of-thought. Extraction needs the model's answer,
# never its reasoning. This is a no-op when the model server separates reasoning into
# `reasoning_content` or reasoning is disabled; it only does work when raw CoT leaks into
# `content` (e.g. a channel/harmony-formatted model whose vLLM reasoning-parser did not
# match its output). The robust fix is disabling reasoning at the server / via extra_body;
# this is a secondary net so a serving regression can't silently corrupt extracted text.
_REASONING_BLOCK_RE = re.compile(r'<\s*(think|thinking|reasoning)\s*>.*?<\s*/\s*\1\s*>', re.DOTALL | re.IGNORECASE)
# Matches only the final-channel MARKER (and an optional following <|message|> token),
# never the answer text after it -- so keep-after-marker preserves the model's answer.
_FINAL_CHANNEL_RE = re.compile(r'<\|?\s*channel\s*\|?>\s*final\b\s*(?:<\|?\s*message\s*\|?>)?', re.IGNORECASE)
_CONTROL_TOKEN_RE = re.compile(
    r'<\|?\s*(channel|start|end|message|assistant|analysis|commentary|final)\s*\|?>', re.IGNORECASE
)


def strip_model_reasoning(text: str) -> str:
    """Best-effort removal of leaked chain-of-thought / channel scaffolding."""
    if not text:
        return ''

    # Drop fully-delimited reasoning blocks (<think>...</think> et al.).
    cleaned = _REASONING_BLOCK_RE.sub('', text)

    # Harmony/channel format: if a 'final' channel marker exists, keep only what
    # follows the LAST one (the model's actual answer).
    final_matches = list(_FINAL_CHANNEL_RE.finditer(cleaned))
    if final_matches:
        cleaned = cleaned[final_matches[-1].end() :]

    # Remove any residual bare control tokens.
    cleaned = _CONTROL_TOKEN_RE.sub('', cleaned)

    return cleaned.strip()


def _content_to_text(content) -> str:
    """Coerce an OpenAI chat message `content` (str or list of parts) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get('type') == 'text':
                parts.append(p.get('text', ''))
            elif isinstance(p, str):
                parts.append(p)
        return ''.join(parts)
    return ''


class VisionLLMLoader:
    """Extract image content via an OpenAI-compatible vision LLM (e.g. Gemma served
    through vLLM/LiteLLM).

    Unlike OCR engines this also covers *pure-visual* images (photos, charts, diagrams)
    that have little or no text, so a text-only chat model can still "understand" an
    uploaded image. Sends NO tools and requests a clean answer (temperature 0); any
    leaked reasoning is stripped defensively.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        file_path: str,
        api_key: str = '',
        mime_type: Optional[str] = None,
        prompt: Optional[str] = None,
        max_tokens: int = 2048,
        timeout: Optional[int] = None,
        extra_body: Optional[dict] = None,
    ):
        if not base_url or not model:
            raise ValueError('Vision LLM base URL and model are required.')
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.file_path = file_path
        self.api_key = api_key
        self.mime_type = mime_type or mimetypes.guess_type(file_path)[0] or 'image/png'
        self.prompt = prompt or DEFAULT_VISION_PROMPT
        self.max_tokens = max_tokens
        self.timeout = timeout or CONTENT_EXTRACTION_REQUEST_TIMEOUT
        self.extra_body = extra_body or {}

    def load(self) -> List[Document]:
        log.info(f'Processing with vision LLM ({self.model}): {self.file_path}')

        with open(self.file_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
        data_uri = f'data:{self.mime_type};base64,{b64}'

        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        payload = {
            'model': self.model,
            'temperature': 0,
            'max_tokens': self.max_tokens,
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': self.prompt},
                        {'type': 'image_url', 'image_url': {'url': data_uri}},
                    ],
                }
            ],
            # No `tools`: an extraction worker must never decide to call web search etc.
            # `extra_body` is where reasoning can be disabled at request time, e.g.
            # {"chat_template_kwargs": {"enable_thinking": false}}.
            **self.extra_body,
        }

        r = requests.post(
            f'{self.base_url}/chat/completions',
            json=payload,
            headers=headers,
            timeout=(10, self.timeout),
            verify=REQUESTS_VERIFY,
        )
        r.raise_for_status()

        data = r.json()
        try:
            content = _content_to_text(data['choices'][0]['message'].get('content'))
        except (KeyError, IndexError, TypeError) as e:
            raise Exception(f'Vision LLM returned an unexpected response shape: {e}')

        content = strip_model_reasoning(content)

        return [
            Document(
                page_content=content,
                metadata={'Content-Type': self.mime_type, 'processing_engine': 'vision-llm'},
            )
        ]
