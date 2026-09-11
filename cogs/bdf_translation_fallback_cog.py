# -*- coding: utf-8 -*-
# cogs/bdf_translation_fallback_cog.py

import asyncio
import re

from deep_translator import GoogleTranslator, MyMemoryTranslator

from cogs.bdf_news_cog import (
    BDFNewsCog,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    TemporaryContentError,
)

MYMEMORY_MAX_BYTES = 450

# Values after these labels are game names/titles and must stay exactly as BDF writes them.
PROTECTED_NAME_LABELS = (
    "Quest Name",
    "Quest Title",
    "NPC",
    "NPC Name",
    "Item",
    "Item Name",
    "Monster",
    "Monster Name",
    "Boss",
    "Boss Name",
    "Skill",
    "Skill Name",
    "Location",
    "Area",
    "Node",
    "Region",
    "Knowledge",
    "Title",
    "Character",
    "Character Name",
)

# Common BDO proper names that may appear inside otherwise translatable sentences.
PROTECTED_GAME_TERMS = (
    "Black Spirit",
    "Edania",
    "Agris",
    "Hakainza",
    "Hakainza Society",
)


def _validate_translation(cog: BDFNewsCog, translated: str | None, provider: str) -> str:
    translated = (translated or "").strip()

    if not translated or cog.contains_error_page(translated):
        raise TemporaryContentError(
            f"{provider} returned an empty response or an upstream error page"
        )

    return translated


def _protect_game_names(text: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Replace BDO names with neutral placeholders before machine translation.
    Labels/descriptive prose can be translated, but quest/item/NPC/etc. names stay original.
    """
    protected: list[tuple[str, str]] = []

    def stash(value: str) -> str:
        token = f"XQX{len(protected):04d}XQX"
        protected.append((token, value))
        return token

    result = text

    # Protect values after explicit game-name labels, e.g.
    # "Quest Name: [Edania] The World's Final Journey".
    labels = "|".join(re.escape(label) for label in sorted(PROTECTED_NAME_LABELS, key=len, reverse=True))
    label_pattern = re.compile(
        rf"(?i)\b({labels})\s*:\s*([^\n]+)$"
    )

    match = label_pattern.search(result)
    if match:
        original_value = match.group(2).strip()
        if original_value:
            result = (
                result[:match.start(2)]
                + stash(original_value)
                + result[match.end(2):]
            )

    # Protect bracketed BDO prefixes/tags such as [Edania], [Event], etc.
    result = re.sub(
        r"\[[^\]\n]{1,80}\]",
        lambda m: stash(m.group(0)),
        result,
    )

    # Protect quoted game names/titles.
    quote_patterns = (
        r'"[^"\n]{2,140}"',
        r"“[^”\n]{2,140}”",
        r"‘[^’\n]{2,140}’",
        r"«[^»\n]{2,140}»",
    )
    for pattern in quote_patterns:
        result = re.sub(pattern, lambda m: stash(m.group(0)), result)

    # Protect a small set of recurring BDO proper nouns inside normal sentences.
    for term in sorted(PROTECTED_GAME_TERMS, key=len, reverse=True):
        result = re.sub(
            rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])",
            lambda m: stash(m.group(0)),
            result,
            flags=re.IGNORECASE,
        )

    return result, protected


def _restore_game_names(translated: str, protected: list[tuple[str, str]], provider: str) -> str:
    result = translated

    for token, original in protected:
        token_pattern = re.compile(re.escape(token), re.IGNORECASE)
        if not token_pattern.search(result):
            raise TemporaryContentError(
                f"{provider} changed a protected BDO-name placeholder"
            )
        result = token_pattern.sub(lambda _m, value=original: value, result)

    return result.strip()


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
    safe_text, protected = _protect_game_names(text)
    translated = GoogleTranslator(source="auto", target="uk").translate(safe_text)
    translated = _validate_translation(cog, translated, "Google Translate")
    return _restore_game_names(translated, protected, "Google Translate")


def _translate_mymemory(cog: BDFNewsCog, text: str) -> str:
    safe_text, protected = _protect_game_names(text)
    chunks = _split_for_mymemory(safe_text)
    if not chunks:
        return ""

    translator = MyMemoryTranslator(source="english", target="ukrainian")
    translated_parts: list[str] = []

    for chunk in chunks:
        translated = translator.translate(chunk)
        translated_parts.append(
            _validate_translation(cog, translated, "MyMemory")
        )

    translated = " ".join(translated_parts).strip()
    return _restore_game_names(translated, protected, "MyMemory")


async def translate_uk_with_fallback(self: BDFNewsCog, text: str) -> str:
    """
    Google is primary. If it errors, immediately try MyMemory.
    If both fail, retry the whole chain up to MAX_RETRIES times.
    BDO names/titles are protected from translation in both providers.
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
    print("[BDFNewsCog] Translation fallback enabled: Google -> MyMemory; BDO names preserved")
