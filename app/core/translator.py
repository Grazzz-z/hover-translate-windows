from __future__ import annotations

import json
import logging
import os

from app.core.local_dictionary import LocalDictionary
from app.core.types import TranslationResult
from app.utils.text_utils import english_token_spans, normalize_text

try:
    import argostranslate.translate as argos_translate
except ImportError:  # pragma: no cover - dependency check at runtime
    argos_translate = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - dependency check at runtime
    OpenAI = None


class Translator:
    def __init__(
        self,
        model: str,
        timeout_s: float = 8.0,
        backend: str = "local",
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._model = model
        self._timeout_s = timeout_s
        self._backend = backend if backend in {"local", "argos", "openai", "auto"} else "local"
        self._dictionary = LocalDictionary()
        self._client: OpenAI | None = None

    def translate(self, word: str, context: str | None = None) -> TranslationResult:
        if self._backend in {"local", "auto"} and self.is_local_configured():
            return self._translate_local(word, context)

        if self._backend == "argos" and self.is_argos_configured():
            return self._translate_argos(word, context)

        if self._backend in {"openai", "auto"} and self.is_openai_configured():
            return self._translate_openai(word, context)

        raise RuntimeError(
            "No translation backend is configured. Build the local dictionary "
            "or set OPENAI_API_KEY and TRANSLATION_BACKEND=openai."
        )

    def translate_sentence(self, sentence: str, context: str | None = None) -> TranslationResult:
        normalized = normalize_text(sentence)
        if not normalized:
            raise RuntimeError("No sentence text to translate.")

        if self._backend == "openai" and self.is_openai_configured():
            return self._translate_openai_sentence(normalized, context)

        if self._backend in {"local", "argos", "auto"} and self.is_argos_configured():
            return self._translate_argos_sentence(normalized, context)

        if self._backend in {"local", "auto"} and self.is_local_configured():
            return self._translate_sentence_dictionary(normalized, context)

        if self._backend in {"openai", "auto"} and self.is_openai_configured():
            return self._translate_openai_sentence(normalized, context)

        raise RuntimeError("No sentence translation backend is configured.")

    def is_configured(self) -> bool:
        if self._backend == "local":
            return self.is_local_configured()
        if self._backend == "argos":
            return self.is_argos_configured()
        if self._backend == "openai":
            return self.is_openai_configured()
        return self.is_local_configured() or self.is_openai_configured()

    def is_local_configured(self) -> bool:
        return self._dictionary.is_available

    def is_argos_configured(self) -> bool:
        if argos_translate is None:
            return False
        return self._get_argos_translation() is not None

    def is_openai_configured(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    @property
    def backend_name(self) -> str:
        if self._backend in {"local", "auto"} and self.is_local_configured():
            return "local"
        if self._backend == "argos" and self.is_argos_configured():
            return "argos"
        if self._backend in {"openai", "auto"} and self.is_openai_configured():
            return "openai"
        return self._backend

    def _translate_local(self, word: str, context: str | None) -> TranslationResult:
        entry = self._dictionary.lookup(word)
        if entry is None:
            return TranslationResult(
                word=word,
                translation=word,
                phonetic="",
                explanation="Not found in local dictionary",
                source="local-dictionary",
                context=context,
            )

        translation = _format_dictionary_translation(entry.translation, entry.definition)
        return TranslationResult(
            word=entry.word,
            translation=translation or word,
            phonetic=f"/{entry.phonetic}/" if entry.phonetic else "",
            explanation="Local dictionary",
            source="local-dictionary",
            context=context,
            examples=_build_examples(entry.word, context, entry.translation),
        )

    def _translate_argos(self, word: str, context: str | None) -> TranslationResult:
        translation = self._get_argos_translation()
        if translation is None:
            raise RuntimeError("Argos English-to-Chinese model is not installed.")

        translated = translation.translate(word).strip()
        return TranslationResult(
            word=word,
            translation=translated or word,
            phonetic="",
            explanation="Local offline translation",
            source="local-argos",
            context=context,
            examples=_build_examples(word, context, ""),
        )

    def _translate_argos_sentence(self, sentence: str, context: str | None) -> TranslationResult:
        translation = self._get_argos_translation()
        if translation is None:
            raise RuntimeError("Argos English-to-Chinese model is not installed.")

        translated = translation.translate(sentence).strip()
        return TranslationResult(
            word=sentence,
            translation=translated or sentence,
            phonetic="",
            explanation="Local neural sentence translation",
            source="local-argos",
            context=context,
            examples=(),
            is_sentence=True,
        )

    def _get_argos_translation(self) -> object | None:
        if argos_translate is None:
            return None

        try:
            installed_languages = argos_translate.get_installed_languages()
        except Exception:
            self._logger.exception("Failed to inspect Argos Translate languages")
            return None

        from_language = next(
            (language for language in installed_languages if language.code == "en"),
            None,
        )
        to_language = next(
            (language for language in installed_languages if language.code == "zh"),
            None,
        )
        if from_language is None or to_language is None:
            return None
        return from_language.get_translation(to_language)

    def _translate_openai(self, word: str, context: str | None = None) -> TranslationResult:
        client = self._get_client()
        payload = {
            "word": word,
            "context": context or "",
        }
        response = client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            max_tokens=200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You translate a single English word into concise Simplified Chinese. "
                        "Return strict JSON with keys word, translation, phonetic, explanation, examples. "
                        "examples must be an array of 1-2 short English example sentences. "
                        "Keep explanation short, practical, and natural for a Chinese learner."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            timeout=self._timeout_s,
        )

        content = response.choices[0].message.content or "{}"
        self._logger.debug("OpenAI translation response for %s: %s", word, content)

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse translation response: {content}") from exc

        return TranslationResult(
            word=str(data.get("word", word)).strip() or word,
            translation=str(data.get("translation", "")).strip() or "Unavailable",
            phonetic=str(data.get("phonetic", "")).strip(),
            explanation=str(data.get("explanation", "")).strip(),
            source="openai",
            context=context,
            examples=_normalize_examples(data.get("examples")),
        )

    def _translate_openai_sentence(
        self,
        sentence: str,
        context: str | None = None,
    ) -> TranslationResult:
        client = self._get_client()
        payload = {
            "sentence": sentence,
            "context": context or "",
        }
        response = client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            max_tokens=260,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the English sentence into concise Simplified Chinese. "
                        "Return strict JSON with keys word, translation, phonetic, explanation. "
                        "Set word to the original sentence and keep explanation short."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            timeout=self._timeout_s,
        )
        content = response.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse sentence translation response: {content}") from exc

        return TranslationResult(
            word=str(data.get("word", sentence)).strip() or sentence,
            translation=str(data.get("translation", "")).strip() or "Unavailable",
            phonetic=str(data.get("phonetic", "")).strip(),
            explanation=str(data.get("explanation", "")).strip(),
            source="openai",
            context=context,
            examples=(),
            is_sentence=True,
        )

    def _translate_sentence_dictionary(
        self,
        sentence: str,
        context: str | None,
    ) -> TranslationResult:
        glosses: list[str] = []
        seen: set[str] = set()

        for token, _, _ in english_token_spans(sentence):
            word = token.lower()
            if word in seen:
                continue
            seen.add(word)
            entry = self._dictionary.lookup(word)
            if entry is None:
                continue
            translation = _first_translation_line(entry.translation)
            if translation:
                glosses.append(f"{token}: {translation}")
            if len(glosses) >= 16:
                break

        return TranslationResult(
            word=sentence,
            translation="\n".join(glosses) if glosses else sentence,
            phonetic="",
            explanation="Local dictionary word-by-word sentence gloss",
            source="local-dictionary",
            context=context,
            examples=(),
            is_sentence=True,
        )

    def _get_client(self) -> OpenAI:
        if OpenAI is None:
            raise RuntimeError("openai is not installed.")

        if self._client is None:
            if not self.is_openai_configured():
                raise RuntimeError("OPENAI_API_KEY is not set.")
            self._client = OpenAI()
        return self._client


def _format_dictionary_translation(translation: str, definition: str) -> str:
    source = translation or definition
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    return "\n".join(lines[:3])


def _first_translation_line(translation: str) -> str:
    for line in translation.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _build_examples(word: str, context: str | None, translation: str) -> tuple[str, ...]:
    examples: list[str] = []
    normalized_context = normalize_text(context)
    if (
        normalized_context
        and len(normalized_context) <= 180
        and word.lower() in normalized_context.lower()
        and normalized_context.lower() != word.lower()
    ):
        examples.append(normalized_context)

    if _looks_like_verb(translation):
        examples.append(f"We need to {word} the plan carefully.")
    elif _looks_like_adjective(translation):
        examples.append(f"This is a {word} example.")
    elif word:
        examples.append(f"The word \"{word}\" appears in this sentence.")

    return tuple(dict.fromkeys(examples[:2]))


def _looks_like_verb(translation: str) -> bool:
    lowered = translation.lower()
    return any(marker in lowered for marker in ("v.", "vt.", "vi."))


def _looks_like_adjective(translation: str) -> bool:
    lowered = translation.lower()
    return "adj." in lowered or "a." in lowered


def _normalize_examples(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value[:2] if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()
