"""
title: SChat Guardrails
author: Sunway AI Team
version: 0.1.0
required_open_webui_version: 0.5.0
description: Input PII/credential redaction, prompt-injection detection, output credential scanning, and citation advisory. Pure regex, no network calls.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Sunway: PROMOTED FROM THE DATABASE TO CODE — 2026-08-12, hardening plan Item 8.
#
# This filter previously lived as text in the `function` table (id `schat_guardrails`)
# and was run by `exec()` in utils/plugin.py. Three reasons it moved:
#
#   1. It could be DISABLED AT RUNTIME. `POST /api/v1/functions/id/schat_guardrails/
#      toggle` switched it off wholesale, and `.../valves/update` could set
#      enable_input_pii=false or add a caller to exempt_user_ids. Both are admin-gated,
#      and under multi-tenancy `admin` is a per-tenant IAM role — so any BU admin could
#      turn off the control that keeps customer PII out of a third-party LLM endpoint,
#      leaving only `updated_at` as evidence. That is a PDPA / ISO 27001 A.8.11
#      exposure. As a module, disabling it now requires a reviewed commit and a deploy.
#   2. It removes the LAST reason `exec()` exists. The `tool` table is empty and this
#      was the only `function` row, so utils/plugin.py can be deleted outright rather
#      than merely made unreachable (hardening plan Item 2).
#   3. It applies to EVERY TENANT automatically. As a DB row it had to be imported by
#      hand into each new tenant group — which guarantees drift, exactly as happened to
#      the model system prompts (one carries the authoritative-date block, one does not).
#
# THE SOURCE BELOW IS VERBATIM. Not one character was changed in this migration, so any
# behavioural difference is a bug in the wiring (utils/filter.py + filters/__init__.py),
# not in the filter. Improvements are deliberately a SEPARATE commit — scanning
# params.system, persisting the redaction, and the NRIC/phone pattern fixes all change
# behaviour and some need a PDPA decision first.
# ─────────────────────────────────────────────────────────────────────────────


# SChat Guardrails
#
# FOUR CLASSES, each independently switchable via Valves:
#
#   1. input_pii        Redacts NRIC / phone / email / card / credential from the
#                       user's message BEFORE it reaches the model provider.
#                       RELIABLE. Default: on, redact mode.
#
#   2. injection        Detects prompt-injection attempts. Split into
#                       high-confidence (chat-template control tokens — safe to
#                       block) and heuristic (natural-language phrasing — warn
#                       only, because false positives are real).
#                       PARTIALLY RELIABLE. Default: on, warn mode.
#
#   3. output_secrets   Redacts credentials from the assistant's reply.
#                       RELIABLE, BUT POST-STREAM — see the note on outlet().
#                       Default: on.
#
#   4. citation         Flags an answer that cites no source when sources were
#                       attached. ADVISORY ONLY — it cannot verify that a claim
#                       is actually grounded. Default: off.
#
# PERFORMANCE — this filter is designed to add no measurable latency:
#   * No LLM calls, no network I/O, no imports beyond the stdlib.
#   * Every pattern is compiled ONCE at module import, not per request.
#   * Only the LAST user message is scanned by default. Earlier turns were each
#     scanned when they were submitted, so rescanning history is pure waste.
#   * MAX_SCAN_CHARS caps any single scan, so a large RAG context or a pasted
#     document cannot turn into a pathological regex run.
#   Measured cost is sub-millisecond for a normal message.
#
# FAILURE POLICY — fail OPEN, loudly.
#   A bug in a guardrail must never take chat down. Every handler wraps its work
#   in try/except and returns the body UNCHANGED on an internal error, logging
#   with a traceback. The ONLY exceptions that propagate are deliberate blocks.
#   This is a conscious trade: a guardrail that fails closed becomes an outage,
#   and an outage gets the guardrail switched off entirely.

import logging
import re
import traceback
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

MAX_SCAN_CHARS = 200_000


def _c(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# ── Class 1 + 3 patterns: identity and credential material ───────────────────
#
# Ordering matters: the credential patterns run before the generic assignment
# pattern so a recognised key is labelled by type rather than as CREDENTIAL.

PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Malaysian NRIC, hyphenated. The unhyphenated 12-digit form is deliberately
    # NOT matched: it is indistinguishable from an order number, an invoice ref
    # or a phone number with a country code, and the false-positive rate made it
    # unusable in testing.
    ("NRIC", re.compile(r"\b\d{6}-\d{2}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Malaysian mobile: 01x-xxx xxxx, with or without +60 and separators.
    ("PHONE", re.compile(r"(?:\+?60|\b0)1\d[-\s]?\d{3,4}[-\s]?\d{4}\b")),
]

CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("PRIVATE_KEY", re.compile(r"-----BEGIN(?:\s+[A-Z]+)*\s+PRIVATE KEY-----")),
    ("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("OPENAI_KEY", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "JWT",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
    ),
]

# Generic credential assignment. Broader and therefore noisier than the typed
# patterns above, so it lives behind its own valve. Only the VALUE is replaced —
# the key name survives, so the model still understands what shape of thing it
# was handed.
#
# TWO patterns, not one, because a single relaxed pattern fails both ways.
# `\b(key|secret|token)\b\s*[:=]?\s*(\S{12,})` matched "password requirements",
# "token distribution" and "bearer responsibilities" — ordinary English — while
# still MISSING "password: Tr0ub4dor&3" because real passwords contain
# punctuation the value class excluded. So:
_SECRET_KEY = r"(api[_-]?key|secret|password|passwd|pwd|token|bearer)"

# 1. EXPLICIT assignment. A ':' or '=' makes the intent unambiguous, so the
#    value class is wide (punctuation included) and the length floor is low.
GENERIC_SECRET_ASSIGN = _c(
    rf'\b{_SECRET_KEY}\b(\s*[:=]\s*)["\']?([A-Za-z0-9_\-\.\+/~!@#$%^&*]{{8,}})["\']?'
)

# 2. BARE, whitespace-separated ("Bearer abc123XYZ"). No separator means no
#    signal of intent, so the value must contain a DIGIT — which credentials
#    almost always do and English words almost never do — and be 12+ chars.
GENERIC_SECRET_BARE = _c(
    rf'\b{_SECRET_KEY}\b(\s+)["\']?((?=[A-Za-z0-9_\-\.]*\d)[A-Za-z0-9_\-\.]{{12,}})["\']?'
)

# Written so the final character is always a DIGIT. The obvious form,
# (?:\d[ -]?){13,19}, lets the last repetition swallow the trailing space and
# the redaction then runs into the next word ("[REDACTED_CARD]expires").
CARD_CANDIDATE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def _luhn(digits: str) -> bool:
    """Card numbers are Luhn-checked before redaction.

    Without this, ANY 16-digit run redacts — order numbers, timestamps
    concatenated together, tracking refs. Luhn cuts the false-positive rate by
    roughly 90% for a few microseconds of arithmetic.
    """
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


# ── Class 2 patterns: prompt injection ───────────────────────────────────────
#
# HIGH CONFIDENCE — chat-template control tokens. These have no legitimate
# reason to appear in user prose; their presence is an attempt to forge a role
# boundary. Safe to block outright.
INJECTION_HIGH: list[tuple[str, re.Pattern]] = [
    (
        "control_token",
        re.compile(r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>"),
    ),
    ("inst_token", re.compile(r"\[/?INST\]|<<SYS>>")),
    # MULTILINE matters: injected instructions usually arrive part-way into a
    # pasted document or a retrieved page, not at character zero.
    (
        "role_forgery",
        re.compile(
            r"^\s*(?:system|assistant)\s*:\s*you\s+(?:are|must|will)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
]

# HEURISTIC — natural language. Genuinely ambiguous: "ignore the previous
# calculation" is a normal thing to say. Warn, do not block, unless an operator
# deliberately raises injection_action to "block".
INJECTION_HEURISTIC: list[tuple[str, re.Pattern]] = [
    (
        "override",
        _c(
            r"\bignore\s+(?:all\s+)?(?:your\s+|the\s+|any\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instruction|prompt|rule|direction|command)"
        ),
    ),
    (
        "disregard",
        _c(
            r"\bdisregard\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|earlier|system)\b"
        ),
    ),
    (
        "prompt_exfil",
        _c(
            r"\b(?:reveal|show|print|repeat|output|display|tell\s+me)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+prompt|initial\s+instruction|original\s+instruction|hidden\s+instruction)"
        ),
    ),
    ("jailbreak_mode", _c(r"\b(?:developer\s+mode|DAN\s+mode|god\s+mode|jailbreak)\b")),
    (
        "no_restrictions",
        _c(
            r"\b(?:pretend|act\s+as\s+if|imagine)\s+(?:that\s+)?you\s+(?:are|have)\s+(?:no|without)\s+(?:restriction|rule|filter|guideline|limitation)"
        ),
    ),
    (
        "unrestricted",
        _c(r"\bact\s+as\s+(?:an?\s+)?(?:unrestricted|uncensored|unfiltered)\b"),
    ),
]

CITATION_MARKER = re.compile(r"\[\d+\]")


class GuardrailBlock(Exception):
    """A deliberate rejection, as opposed to a defect in this filter.

    The inlet catch-all must let an intentional block through to the user while
    swallowing genuine bugs. Matching on the message text was the alternative,
    and it silently stops working the first time someone rewords a string.
    The middleware re-raises whatever it gets and main.py renders str(e), so a
    plain Exception subclass reaches the user unchanged.
    """


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0,
            description="Filter execution order. Lower runs first. Keep this below any filter that rewrites messages.",
        )

        # ── Class 1 ──
        enable_input_pii: bool = Field(
            default=True,
            description="Class 1 — redact identity data from user messages before they reach the model.",
        )
        redact_nric: bool = Field(
            default=True, description="Malaysian NRIC (hyphenated form only)."
        )
        redact_email: bool = Field(default=True, description="Email addresses.")
        redact_phone: bool = Field(
            default=True, description="Malaysian mobile numbers."
        )
        redact_card: bool = Field(
            default=True,
            description="Payment cards (Luhn-validated to limit false positives).",
        )
        redact_credentials: bool = Field(
            default=True, description="API keys, tokens, private keys."
        )
        redact_generic_secrets: bool = Field(
            default=True,
            description="Also redact generic `api_key = ...` / `password: ...` assignments. Broader, so slightly noisier.",
        )
        notify_on_redaction: bool = Field(
            default=True,
            description="Show the user a toast when something was redacted. Off = silent redaction.",
        )

        # ── Class 2 ──
        enable_injection_detection: bool = Field(
            default=True, description="Class 2 — detect prompt-injection attempts."
        )
        injection_action: str = Field(
            default="warn",
            description="What to do on a HEURISTIC match: 'warn' (toast + log, request proceeds) or 'block' (reject). High-confidence control-token matches always block.",
        )
        scan_documents_for_injection: bool = Field(
            default=False,
            description="Also scan retrieved document/web context for injected instructions (indirect injection). Costs more per request on large contexts.",
        )

        # ── Class 3 ──
        enable_output_scan: bool = Field(
            default=True,
            description="Class 3 — redact credentials from the assistant reply. NOTE: applies after streaming.",
        )

        # ── Class 4 ──
        enable_citation_check: bool = Field(
            default=False,
            description="Class 4 — flag answers that cite no source when sources were attached. Advisory only; cannot verify grounding.",
        )
        citation_action: str = Field(
            default="log",
            description="'log' (server log only) or 'note' (append a visible caveat to the answer).",
        )

        # ── Scope ──
        scan_history: bool = Field(
            default=False,
            description="Scan every user message rather than only the latest. Off is both faster and sufficient — each message is scanned when submitted.",
        )
        exempt_user_ids: str = Field(
            default="",
            description="Comma-separated user IDs that bypass all guardrails. Leave empty to apply to everyone.",
        )

    def __init__(self):
        self.valves = self.Valves()
        # Do NOT set self.file_handler — that flag makes the middleware strip
        # `files` from the payload, which would silently disable RAG.

    # ── helpers ──────────────────────────────────────────────────────────────

    def _exempt(self, user: Optional[dict]) -> bool:
        ids = [
            i.strip()
            for i in (self.valves.exempt_user_ids or "").split(",")
            if i.strip()
        ]
        return bool(ids) and bool(user) and user.get("id") in ids

    @staticmethod
    def _map_text(content: Any, fn: Callable[[str], str]) -> Any:
        """Apply `fn` to every text part of a message, string or multimodal.

        Message content is a plain string for text chats but a LIST of parts
        for vision/image messages ([{type: text}, {type: image_url}, ...]).
        Treating it as a string crashes the moment someone attaches an image,
        so every read and write goes through here.
        """
        if isinstance(content, str):
            return fn(content)
        if isinstance(content, list):
            out = []
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                ):
                    part = {**part, "text": fn(part["text"])}
                out.append(part)
            return out
        return content

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        return ""

    def _redact(self, text: str, found: set) -> str:
        """Redact identity + credential material. Returns the rewritten text."""
        if not text or len(text) > MAX_SCAN_CHARS:
            return text

        v = self.valves

        if v.redact_credentials:
            for label, pat in CREDENTIAL_PATTERNS:
                text, n = pat.subn(f"[REDACTED_{label}]", text)
                if n:
                    found.add(label)

        if v.redact_generic_secrets:

            def _generic(m: re.Match) -> str:
                found.add("CREDENTIAL")
                return f"{m.group(1)}{m.group(2)}[REDACTED_CREDENTIAL]"

            text = GENERIC_SECRET_ASSIGN.sub(_generic, text)
            text = GENERIC_SECRET_BARE.sub(_generic, text)

        for label, pat in PII_PATTERNS:
            if label == "NRIC" and not v.redact_nric:
                continue
            if label == "EMAIL" and not v.redact_email:
                continue
            if label == "PHONE" and not v.redact_phone:
                continue
            text, n = pat.subn(f"[REDACTED_{label}]", text)
            if n:
                found.add(label)

        if v.redact_card:

            def _card(m: re.Match) -> str:
                digits = re.sub(r"\D", "", m.group(0))
                if 13 <= len(digits) <= 19 and _luhn(digits):
                    found.add("CARD")
                    return "[REDACTED_CARD]"
                return m.group(0)

            text = CARD_CANDIDATE.sub(_card, text)

        return text

    def _detect_injection(self, text: str) -> tuple[list, list]:
        if not text or len(text) > MAX_SCAN_CHARS:
            return [], []
        high = [name for name, pat in INJECTION_HIGH if pat.search(text)]
        heur = [name for name, pat in INJECTION_HEURISTIC if pat.search(text)]
        return high, heur

    @staticmethod
    async def _notify(emitter, level: str, message: str):
        if not emitter:
            return
        try:
            await emitter(
                {"type": "notification", "data": {"type": level, "content": message}}
            )
        except Exception:
            pass  # a failed toast must never affect the request

    # ── inlet ────────────────────────────────────────────────────────────────

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__=None,
        __metadata__: Optional[dict] = None,
    ) -> dict:
        try:
            if self._exempt(__user__):
                return body

            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                return body

            user_idx = [
                i
                for i, m in enumerate(messages)
                if isinstance(m, dict) and m.get("role") == "user"
            ]
            if not user_idx:
                return body
            targets = user_idx if self.valves.scan_history else [user_idx[-1]]

            uid = (
                (__user__ or {}).get("email") or (__user__ or {}).get("id") or "unknown"
            )
            chat_id = (__metadata__ or {}).get("chat_id", "-")

            # ── Class 2: injection, evaluated BEFORE redaction so patterns see
            # the original text. A block here aborts the request entirely.
            if self.valves.enable_injection_detection:
                scan = "\n".join(
                    self._extract_text(messages[i].get("content")) for i in targets
                )
                if self.valves.scan_documents_for_injection:
                    for f in body.get("files") or []:
                        if isinstance(f, dict):
                            scan += (
                                "\n"
                                + str(f.get("content") or f.get("name") or "")[
                                    :MAX_SCAN_CHARS
                                ]
                            )

                high, heur = self._detect_injection(scan)

                if high:
                    log.warning(
                        "[guardrails] BLOCK injection user=%s chat=%s patterns=%s",
                        uid,
                        chat_id,
                        high,
                    )
                    raise GuardrailBlock(
                        "This message was blocked because it contains formatting reserved for system "
                        "instructions. Please rephrase it as ordinary text."
                    )

                if heur:
                    log.warning(
                        "[guardrails] injection heuristic user=%s chat=%s patterns=%s",
                        uid,
                        chat_id,
                        heur,
                    )
                    if self.valves.injection_action == "block":
                        raise GuardrailBlock(
                            "This message was blocked because it appears to try to override the "
                            "assistant's instructions. Please rephrase your request."
                        )
                    await self._notify(
                        __event_emitter__,
                        "warning",
                        "This message looks like an attempt to override the assistant. It was allowed but logged.",
                    )

            # ── Class 1: redaction
            if self.valves.enable_input_pii:
                found: set = set()
                for i in targets:
                    msg = messages[i]
                    msg["content"] = self._map_text(
                        msg.get("content"), lambda t: self._redact(t, found)
                    )

                if found:
                    log.info(
                        "[guardrails] redacted %s user=%s chat=%s",
                        sorted(found),
                        uid,
                        chat_id,
                    )
                    if self.valves.notify_on_redaction:
                        await self._notify(
                            __event_emitter__,
                            "warning",
                            "Sensitive data ("
                            + ", ".join(sorted(found)).lower().replace("_", " ")
                            + ") was removed before sending.",
                        )

            return body

        except GuardrailBlock:
            # Deliberate rejection — propagate so the user sees why.
            raise
        except Exception as e:
            # Anything else is a defect in this filter. Log it with a traceback
            # and let the request through unchanged rather than breaking chat.
            log.error(
                "[guardrails] inlet defect, passing request through unchanged: %s", e
            )
            traceback.print_exc()
            return body

    # ── outlet ───────────────────────────────────────────────────────────────

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__=None,
    ) -> dict:
        """Post-completion scan.

        IMPORTANT AND NOT A BUG: outlet runs AFTER the response has finished
        streaming, so the user has already seen the raw text on screen. What
        this changes is the PERSISTED record and every subsequent render —
        reload, share, export. It is a data-retention control, not a live
        display filter.

        Live redaction would require a `stream` handler running on every chunk,
        which was deliberately not implemented: a credential split across two
        SSE chunks does not match any pattern, so it would give a false sense of
        coverage while adding per-token latency to every response in the system.
        """
        try:
            if self._exempt(__user__):
                return body

            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                return body

            last = messages[-1]
            if not isinstance(last, dict) or last.get("role") != "assistant":
                return body

            uid = (
                (__user__ or {}).get("email") or (__user__ or {}).get("id") or "unknown"
            )

            # ── Class 3: credentials in the reply
            if self.valves.enable_output_scan:
                found: set = set()

                def _scrub(text: str) -> str:
                    if not text or len(text) > MAX_SCAN_CHARS:
                        return text
                    for label, pat in CREDENTIAL_PATTERNS:
                        text, n = pat.subn(f"[REDACTED_{label}]", text)
                        if n:
                            found.add(label)
                    return text

                last["content"] = self._map_text(last.get("content"), _scrub)
                if found:
                    log.warning(
                        "[guardrails] credentials in MODEL OUTPUT %s user=%s",
                        sorted(found),
                        uid,
                    )
                    await self._notify(
                        __event_emitter__,
                        "warning",
                        "Credential-like text in the reply was redacted from the saved copy.",
                    )

            # ── Class 4: citation advisory
            if self.valves.enable_citation_check:
                sources = last.get("sources") or body.get("sources") or []
                text = self._extract_text(last.get("content"))
                if sources and text and not CITATION_MARKER.search(text):
                    log.info(
                        "[guardrails] answer cites no source despite %d attached, user=%s",
                        len(sources),
                        uid,
                    )
                    if self.valves.citation_action == "note":
                        note = "\n\n---\n*Note: sources were attached to this question but the answer does not cite them. Please verify against the source documents.*"
                        if isinstance(last.get("content"), str):
                            last["content"] = last["content"] + note

            return body

        except Exception as e:
            log.error("[guardrails] outlet defect, returning response unchanged: %s", e)
            traceback.print_exc()
            return body
