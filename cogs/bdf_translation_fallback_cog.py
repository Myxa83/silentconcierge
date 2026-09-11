# -*- coding: utf-8 -*-
# cogs/bdf_translation_fallback_cog.py

import asyncio

from deep_translator import GoogleTranslator, MyMemoryTranslator

from cogs.bdf_news_cog import (
    BDFNewsCog,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    TemporaryContentError,
)

MYMEMORY_MAX_BYTES = 450


def _validate_translation(cog: BDFNewsCog, translated: str | None, provider: str) -> str:
    translated = (translated or "").strip()

    if not translated or cog.contains_error_page(translated):
        raise TemporaryContentError(
            f"{provider} returned an empty response or an upstream error page"
        )

    return translated


def _split_for_mymemory(text: str, max_bytes: int = MYMEMORY_MAX_BYTES) -> list[str]:
    """Split English source text so every MyMemory request stays below its byte limit."""
    text = " ".join(text.split())
    if not text:
        return []

    chunks: list[str] = []
    current = ""

    for word in text.split(" "):
        candidate = word if not current else f"{current} {word}"

        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        # Defensive handling for an unusually long token.
        token = word
        while len(token.encode("utf-8")) > max_bytes:
            cut = len(token)
            while cut > 1 and len(token[:cut].encode("utf-8")) > max_bytes:
                cut -= 1
            chunks.append(token[:cut])
            token = token[cut:]

        current = token

    if current:
        chunks.append(current)

    return chunks


def _translate_google(cog: BDFNewsCog, text: str) -> str:
    translated = GoogleTranslator(source="auto", target="uk").translate(text)
    return _validate_translation(cog, translated, "Google Translate")


def _translate_mymemory(cog: BDFNewsCog, text: str) -> str:
    chunks = _split_for_mymemory(text)
    if not chunks:
        return ""

    translator = MyMemoryTranslator(source="english", target="ukrainian")
    translated_parts: list[str] = []

    for chunk in chunks:
        translated = translator.translate(chunk)
        translated_parts.append(
            _validate_translation(cog, translated, "MyMemory")
        )

    return " ".join(translated_parts).strip()


async def translate_uk_with_fallback(self: BDFNewsCog, text: str) -> str:
    """
    Google is primary. If it errors, immediately try MyMemory.
    If both fail, retry the whole chain up to MAX_RETRIES times.
    """
    if not text:
        return ""

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await asyncio.to_thread(_translate_google, self, text)
        except Exception as google_error:
            last_error = google_error
            print(
                f"[BDFNewsCog] Google Translate attempt {attempt}/{MAX_RETRIES} failed: "
                f"{google_error}. Trying MyMemory fallback."
            )

        try:
            translated = await asyncio.to_thread(_translate_mymemory, self, text)
            print(
                f"[BDFNewsCog] MyMemory fallback succeeded "
                f"on attempt {attempt}/{MAX_RETRIES}"
            )
            return translated
        except Exception as mymemory_error:
            last_error = mymemory_error
            print(
                f"[BDFNewsCog] MyMemory fallback attempt {attempt}/{MAX_RETRIES} failed: "
                f"{mymemory_error}"
            )

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAY_SECONDS)

    raise TemporaryContentError(
        f"All translation providers failed after {MAX_RETRIES} attempts: {last_error}"
    )


async def setup(bot):
    # bdf_news_cog.py loads before this file alphabetically. Patching the class here
    # also updates the already-created cog instance before the bot becomes ready.
    BDFNewsCog.translate_uk = translate_uk_with_fallback
    print("[BDFNewsCog] Translation fallback enabled: Google -> MyMemory")
