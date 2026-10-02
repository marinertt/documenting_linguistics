"""A persistent Unicode word bank with source-linked corpus examples."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unicodedata

import pandas as pd
from linguisticdocs.corpus_search import search_audio


def _key(word):
    word = unicodedata.normalize("NFC", " ".join(word.split()).casefold())
    if not word:
        raise ValueError("word must contain non-whitespace text")
    return word


class Lexicon:
    """JSON-backed entries; add() saves immediately and merges repeat examples.

    Entry keys ignore case and normalize Unicode, but preserve accents. Multiple
    meanings may be recorded in the meaning field. Intended for a single writer.
    """

    def __init__(self, path="data/lexicon.json"):
        self.path = Path(path)

    def _load(self):
        if not self.path.exists():
            return {"version": 1, "entries": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("entries"), dict):
            raise ValueError("Unsupported lexicon format")
        return data

    def _save(self, data):
        # Replace only after a complete JSON file has been written.
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=self.path.parent, delete=False) as stream:
                name = stream.name
                stream.write(payload + "\n")
            os.replace(name, self.path)
        finally:
            if name is not None and Path(name).exists():
                Path(name).unlink()

    def add(self, word, df, *, source_file, meaning=None, notes=None,
            part_of_speech=None, example_ids=None, whole_word=True):
        """Add/update a word and collect its matching original-language examples.

        source_file identifies the EAF used to build df. Optional example_ids
        selects matching segment annotation IDs for curation. None metadata
        preserves existing values; an empty string explicitly clears a value.
        Sentence translations are examples, never inferred lexical meanings.
        Words with no matches may be saved with an empty examples list.
        """
        key = _key(word)
        found = search_audio(df, word, whole_word=whole_word)
        if example_ids is not None:
            selected = {example_ids} if isinstance(example_ids, str) else set(example_ids)
            unknown = selected - set(found["annotation_id"])
            if unknown:
                raise ValueError(f"Selected annotations do not match this word: {sorted(unknown)}")
            found = found.loc[found["annotation_id"].isin(selected)]
        source = str(Path(source_file).resolve())
        examples = []
        for _, row in found.iterrows():
            examples.append({
                "source_file": source,
                "annotation_id": row["annotation_id"],
                "tier": row["tier"],
                "transcript": row["transcript"],
                "translation": row["translation"],
                "start_ms": None if pd.isna(row["start_ms"]) else int(row["start_ms"]),
                "end_ms": None if pd.isna(row["end_ms"]) else int(row["end_ms"]),
                "timing_scope": "transcript segment",
                "matching_child_intervals": row["matching_child_intervals"],
                "participant": row["participant"],
                "media": copy.deepcopy(df.attrs.get("media", [])),
                "match_mode": "whole_word" if whole_word else "substring",
            })
        data = self._load()
        entry = data["entries"].setdefault(key, {
            "word": unicodedata.normalize("NFC", " ".join(word.split())),
            "meaning": "", "notes": "", "part_of_speech": "", "examples": [],
        })
        for field, value in (("meaning", meaning), ("notes", notes),
                             ("part_of_speech", part_of_speech)):
            if value is not None:
                entry[field] = value
        merged = {(e["source_file"], e["annotation_id"]): e for e in entry["examples"]}
        merged.update({(e["source_file"], e["annotation_id"]): e for e in examples})
        entry["examples"] = list(merged.values())
        self._save(data)
        return copy.deepcopy(entry)

    def get(self, word):
        """Read a complete entry, including examples; raise KeyError if absent."""
        return self._load()["entries"][_key(word)]

    def to_dataframe(self):
        """Show the word bank with one row per entry."""
        return pd.DataFrame([
            {"word": e["word"], "meaning": e["meaning"],
             "part_of_speech": e["part_of_speech"], "notes": e["notes"],
             "example_count": len(e["examples"])}
            for e in self._load()["entries"].values()
        ], columns=["word", "meaning", "part_of_speech", "notes", "example_count"])

    def examples(self, word):
        """Show saved contextual examples for a word as a DataFrame."""
        return pd.DataFrame(self.get(word)["examples"], columns=[
            "source_file", "annotation_id", "tier", "transcript", "translation",
            "start_ms", "end_ms", "timing_scope", "matching_child_intervals",
            "participant", "media", "match_mode",
        ])
