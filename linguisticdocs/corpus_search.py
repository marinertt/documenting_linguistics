"""Search joined EAF segment DataFrames and their annotated audio intervals."""
import unicodedata


def _matcher(query, *, whole_word=True, ignore_accents=False):
    def normalize(text):
        text = unicodedata.normalize("NFD", str(text).casefold())
        if ignore_accents:
            text = "".join(c for c in text if not unicodedata.category(c).startswith("M"))
        return unicodedata.normalize("NFC", " ".join(text.split()))

    needle = normalize(query)
    if not needle:
        raise ValueError("query must contain non-whitespace text")

    def word_character(char):
        # Combining accents remain part of a word, including those NFC cannot compose.
        return unicodedata.category(char)[0] in "LMN" or char in "_'’ʼ-"

    def matches(text):
        haystack = normalize(text)
        start = haystack.find(needle)
        while start >= 0:
            end = start + len(needle)
            if not whole_word or (
                (start == 0 or not word_character(haystack[start - 1]))
                and (end == len(haystack) or not word_character(haystack[end]))
            ):
                return True
            start = haystack.find(needle, start + 1)
        return False
    return matches


def search_translation(df, query, *, whole_word=True, ignore_accents=True):
    """Return segment rows matching a Portuguese word or phrase.

    Case-insensitive; Portuguese accents are ignored by default. This finds
    translated segments, not word-to-word lexical equivalents.
    """
    matches = _matcher(query, whole_word=whole_word, ignore_accents=ignore_accents)
    return df.loc[df["translation"].fillna("").map(matches)].copy()


def search_transcript(df, query, *, whole_word=True, ignore_accents=False):
    """Return rows matching an original-language word or phrase.

    Accents are significant by default; equivalent Unicode spellings match.
    Set whole_word=False to search within words.
    """
    matches = _matcher(query, whole_word=whole_word, ignore_accents=ignore_accents)
    return df.loc[df["transcript"].fillna("").map(matches)].copy()


def search_audio(df, query, *, language="transcript", whole_word=True,
                 ignore_accents=None, morpheme_tier="Morfemas"):
    """Find EAF-annotated audio intervals, not untranscribed speech in a waveform.

    Main timestamps cover the matching transcript segment. For original-language
    searches, matching timed morpheme annotations are also provided as a list.
    Unknown child times are retained. Portuguese queries locate the corresponding
    source-language segment, not a Portuguese utterance in the recording.
    """
    if language not in ("transcript", "translation"):
        raise ValueError("language must be 'transcript' or 'translation'")
    if ignore_accents is None:
        ignore_accents = language == "translation"
    search = search_transcript if language == "transcript" else search_translation
    found = search(df, query, whole_word=whole_word, ignore_accents=ignore_accents)
    found["start_seconds"] = found["start_ms"] / 1000
    found["end_seconds"] = found["end_ms"] / 1000
    found["timing_scope"] = "transcript segment"
    matches = _matcher(query, whole_word=whole_word, ignore_accents=ignore_accents)
    found["matching_child_intervals"] = [
        [{"annotation_id": item["annotation_id"], "text": item["text"],
          "start_ms": item["start_ms"], "end_ms": item["end_ms"]}
         for item in related.get(morpheme_tier, []) if matches(item["text"])]
        if language == "transcript" else []
        for related in found["associated_annotations"]
    ]
    return found
