"""Text extraction from ChatGPT message content types.

Ported from chat-recall-mcp — handles all 12 known ChatGPT content types.
"""

from typing import Any


def extract_text(content: dict[str, Any] | None) -> str:
    """Extract searchable plain text from a message content dict."""
    if not content:
        return ""
    content_type = content.get("content_type", "")
    extractor = EXTRACTORS.get(content_type, _extract_unknown)
    return extractor(content)


def _extract_text(content: dict) -> str:
    parts = content.get("parts")
    if not parts:
        return ""
    text_parts = []
    for part in parts:
        if isinstance(part, str):
            text_parts.append(part)
    return "\n".join(text_parts)


def _extract_code(content: dict) -> str:
    text = content.get("text", "")
    lang = content.get("language", "")
    if lang and text:
        return f"```{lang}\n{text}\n```"
    return text or ""


def _extract_multimodal_text(content: dict) -> str:
    parts = content.get("parts")
    if not parts:
        return ""
    text_parts = []
    for part in parts:
        if isinstance(part, str):
            text_parts.append(part)
        elif isinstance(part, dict):
            if part.get("content_type") == "image_asset_pointer":
                continue
            inner = part.get("text", "")
            if inner:
                text_parts.append(inner)
    return "\n".join(text_parts)


def _extract_reasoning_recap(content: dict) -> str:
    for key in ("recap", "content", "text", "summary"):
        val = content.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _extract_thoughts(content: dict) -> str:
    text = content.get("text")
    if isinstance(text, str) and text:
        return text
    thoughts = content.get("thoughts")
    if isinstance(thoughts, list):
        parts = []
        for t in thoughts:
            if isinstance(t, dict):
                c = t.get("content", "")
                if c:
                    parts.append(c)
            elif isinstance(t, str):
                parts.append(t)
        return "\n".join(parts)
    return ""


def _extract_computer_output(content: dict) -> str:
    text = content.get("text")
    if isinstance(text, str) and text:
        return text
    output = content.get("output")
    if isinstance(output, str) and output:
        return output
    return ""


def _extract_execution_output(content: dict) -> str:
    return content.get("text", "") or content.get("output", "") or ""


def _extract_system_error(content: dict) -> str:
    return content.get("text", "") or content.get("message", "") or ""


def _extract_tether_browsing_display(content: dict) -> str:
    result = content.get("result", "")
    if result:
        return result
    return content.get("text", "") or content.get("summary", "") or ""


def _extract_sonic_webpage(content: dict) -> str:
    return content.get("text", "") or content.get("url", "") or ""


def _extract_tether_quote(content: dict) -> str:
    quote = content.get("text", "") or content.get("quote", "") or ""
    title = content.get("title", "")
    url = content.get("url", "")
    parts = []
    if title:
        parts.append(f"[{title}]")
    if quote:
        parts.append(quote)
    if url:
        parts.append(f"({url})")
    return " ".join(parts)


def _extract_user_editable_context(content: dict) -> str:
    parts = []
    for key in ("user_profile", "user_instructions", "text", "user_context"):
        val = content.get(key)
        if isinstance(val, str) and val:
            parts.append(val)
    return "\n".join(parts) if parts else ""


def _extract_unknown(content: dict) -> str:
    for key in ("text", "parts", "result", "output", "message"):
        val = content.get(key)
        if isinstance(val, str) and val:
            return val
        if isinstance(val, list):
            text_parts = [p for p in val if isinstance(p, str)]
            if text_parts:
                return "\n".join(text_parts)
    return ""


EXTRACTORS: dict[str, Any] = {
    "text": _extract_text,
    "code": _extract_code,
    "multimodal_text": _extract_multimodal_text,
    "reasoning_recap": _extract_reasoning_recap,
    "thoughts": _extract_thoughts,
    "computer_output": _extract_computer_output,
    "execution_output": _extract_execution_output,
    "system_error": _extract_system_error,
    "tether_browsing_display": _extract_tether_browsing_display,
    "sonic_webpage": _extract_sonic_webpage,
    "tether_quote": _extract_tether_quote,
    "user_editable_context": _extract_user_editable_context,
}
