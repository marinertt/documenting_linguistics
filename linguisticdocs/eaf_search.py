"""Search the annotation text in an EAF file using only the standard library."""

import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from os import PathLike


def eaf_translation_rows(path, *, text_tier="JBMassa-des", translation_tier="Traducao"):
    """Return one row per timed transcription, with its referenced translation.

    Supports a direct child translation tier using reference annotations.
    Empty or absent translations are returned as empty strings. Joins use
    annotation IDs, not row order or matching timestamps.
    """
    root = ET.parse(path).getroot()
    tiers = {t.get("TIER_ID"): t for t in root.findall("TIER")}
    for name in (text_tier, translation_tier):
        if name not in tiers:
            raise ValueError(f"Tier {name!r} not found in {str(path)!r}")
    if tiers[translation_tier].get("PARENT_REF") != text_tier:
        raise ValueError("Translation tier must be a direct child of the text tier")
    slots = {
        s.get("TIME_SLOT_ID"): int(s.get("TIME_VALUE"))
        for s in root.findall("./TIME_ORDER/TIME_SLOT")
        if s.get("TIME_VALUE") is not None
    }
    translations = {}
    for annotation in tiers[translation_tier].findall("./ANNOTATION/*"):
        if annotation.tag != "REF_ANNOTATION":
            raise ValueError("Translation tier must use reference annotations")
        ref = annotation.get("ANNOTATION_REF")
        if ref in translations:
            raise ValueError(f"Multiple translations reference annotation {ref!r}")
        translations[ref] = annotation.findtext("ANNOTATION_VALUE", default="")
    rows = []
    for annotation in tiers[text_tier].findall("./ANNOTATION/*"):
        if annotation.tag != "ALIGNABLE_ANNOTATION":
            raise ValueError("Text tier must use time-aligned annotations")
        annotation_id = annotation.get("ANNOTATION_ID")
        rows.append({
            "annotation_id": annotation_id,
            "start_ms": slots.get(annotation.get("TIME_SLOT_REF1")),
            "end_ms": slots.get(annotation.get("TIME_SLOT_REF2")),
            "text": annotation.findtext("ANNOTATION_VALUE", default=""),
            "translation": translations.get(annotation_id, ""),
        })
    return rows


def count_eaf_words(paths, *, tier, case_sensitive=True):
    """Count whitespace-separated words in a tier across one or more EAF files.

    Pass a file path or an iterable of paths. Accents and punctuation are
    preserved; canonically equivalent Unicode spellings count as the same word.
    Case is preserved by default. Every file must contain the requested tier.
    Returns a Counter mapping normalized words to occurrence counts.
    """
    if isinstance(paths, (str, bytes, PathLike)):
        paths = [paths]
    counts = Counter()
    for path in paths:
        root = ET.parse(path).getroot()
        layers = [t for t in root.findall("TIER") if t.get("TIER_ID") == tier]
        if not layers:
            raise ValueError(f"Tier {tier!r} not found in {str(path)!r}")
        for layer in layers:
            for value in layer.findall("./ANNOTATION/*/ANNOTATION_VALUE"):
                for word in (value.text or "").split():
                    if not case_sensitive:
                        word = word.casefold()
                    counts[unicodedata.normalize("NFC", word)] += 1
    return counts


def search_eaf(path, query, *, tier=None, case_sensitive=False):
    """Return literal substring matches for a word or phrase.

    Search all tiers, or restrict to an exact tier ID with ``tier``.
    Unicode normalization treats equivalent combining-accent spellings equally;
    accents remain significant. Whitespace runs are treated as single spaces.
    Results retain the original annotation text. Times are milliseconds, with
    None for boundaries that have no explicit time value in the file.
    """
    def normalize(text):
        text = unicodedata.normalize("NFC", " ".join(text.split()))
        return text if case_sensitive else unicodedata.normalize("NFC", text.casefold())

    needle = normalize(query)
    if not needle:
        raise ValueError("query must contain non-whitespace text")

    root = ET.parse(path).getroot()
    slots = {
        slot.get("TIME_SLOT_ID"): (
            int(slot.get("TIME_VALUE")) if slot.get("TIME_VALUE") is not None else None
        )
        for slot in root.findall("./TIME_ORDER/TIME_SLOT")
    }
    annotations = {
        annotation.get("ANNOTATION_ID"): annotation
        for annotation in root.findall("./TIER/ANNOTATION/*")
    }

    def timing(annotation):
        seen = set()
        while annotation.tag == "REF_ANNOTATION":
            ref = annotation.get("ANNOTATION_REF")
            if ref in seen or ref not in annotations:
                return None, None
            seen.add(ref)
            annotation = annotations[ref]
        return (
            slots.get(annotation.get("TIME_SLOT_REF1")),
            slots.get(annotation.get("TIME_SLOT_REF2")),
        )

    results = []
    for layer in root.findall("TIER"):
        if tier is not None and layer.get("TIER_ID") != tier:
            continue
        for annotation in layer.findall("./ANNOTATION/*"):
            text = annotation.findtext("ANNOTATION_VALUE", default="")
            if needle in normalize(text):
                start, end = timing(annotation)
                results.append({
                    "tier": layer.get("TIER_ID"),
                    "annotation_id": annotation.get("ANNOTATION_ID"),
                    "text": text,
                    "start_ms": start,
                    "end_ms": end,
                })
    return results
