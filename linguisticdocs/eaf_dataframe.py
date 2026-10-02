"""Build a segment DataFrame while retaining dependent EAF annotations."""
import xml.etree.ElementTree as ET
import pandas as pd


def eaf_dataframe(path, *, transcript_tier="JBMassa-des",
                  translation_tier="Traducao", morpheme_tier="Morfemas",
                  gloss_tier="Morf Glossa"):
    """One row per transcript interval; dependent annotations remain nested.

    References are followed by ID. Timed children are matched within their
    declared parent tier using TIME_ORDER positions, including slots with no
    explicit millisecond value. Ambiguous parentage raises an error. Missing
    times remain unknown; no timestamps are interpolated.
    """
    root = ET.parse(path).getroot()
    tiers = {t.get("TIER_ID"): t for t in root.findall("TIER")}
    if transcript_tier not in tiers:
        raise ValueError(f"Unknown transcript tier: {transcript_tier}")
    slots = root.findall("./TIME_ORDER/TIME_SLOT")
    positions = {s.get("TIME_SLOT_ID"): i for i, s in enumerate(slots)}
    times = {s.get("TIME_SLOT_ID"): int(s.get("TIME_VALUE"))
             if s.get("TIME_VALUE") is not None else None for s in slots}
    annotations = {}
    by_tier = {}
    for name, tier in tiers.items():
        by_tier[name] = []
        for a in tier.findall("./ANNOTATION/*"):
            aid = a.get("ANNOTATION_ID")
            annotations[aid] = (name, a)
            by_tier[name].append(aid)

    def bounds(a):
        return positions[a.get("TIME_SLOT_REF1")], positions[a.get("TIME_SLOT_REF2")]

    parents = {}
    for aid, (name, a) in annotations.items():
        if name == transcript_tier:
            continue
        if a.tag == "REF_ANNOTATION":
            parents[aid] = a.get("ANNOTATION_REF")
        elif tiers[name].get("PARENT_REF"):
            lo, hi = bounds(a)
            candidates = [pid for pid in by_tier[tiers[name].get("PARENT_REF")]
                          if annotations[pid][1].tag == "ALIGNABLE_ANNOTATION"
                          and bounds(annotations[pid][1])[0] <= lo
                          and hi <= bounds(annotations[pid][1])[1]]
            if len(candidates) != 1:
                raise ValueError(f"Cannot uniquely associate {aid}: {candidates}")
            parents[aid] = candidates[0]

    def chain(aid):
        seen = set()
        while aid is not None:
            if aid in seen or aid not in annotations:
                raise ValueError(f"Invalid annotation reference chain at {aid}")
            seen.add(aid)
            yield aid
            aid = parents.get(aid)

    def record(aid):
        name, a = annotations[aid]
        timed = next((annotations[x][1] for x in chain(aid)
                      if annotations[x][1].tag == "ALIGNABLE_ANNOTATION"), None)
        return {
            "annotation_id": aid, "text": a.findtext("ANNOTATION_VALUE", ""),
            "start_ms": times.get(timed.get("TIME_SLOT_REF1")) if timed is not None else None,
            "end_ms": times.get(timed.get("TIME_SLOT_REF2")) if timed is not None else None,
            "parent_annotation_id": parents.get(aid),
            "attributes": dict(a.attrib), "tier_metadata": dict(tiers[name].attrib),
        }

    grouped = {aid: {} for aid in by_tier[transcript_tier]}
    unassociated = []
    for aid, (name, _) in annotations.items():
        if name == transcript_tier:
            continue
        owner = next((x for x in chain(aid) if x in grouped), None)
        if owner is None:
            unassociated.append(record(aid))
        else:
            grouped[owner].setdefault(name, []).append(record(aid))

    def timestamp(ms):
        if ms is None:
            return None
        seconds, millis = divmod(ms, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"

    rows = []
    for aid, related in grouped.items():
        item = record(aid)
        start, end = item["start_ms"], item["end_ms"]
        rows.append({
            "timestamp": timestamp(start), "end_timestamp": timestamp(end),
            "start_ms": start, "end_ms": end,
            "duration_ms": end - start if start is not None and end is not None else None,
            "transcript": item["text"],
            "translation": "\n".join(x["text"] for x in related.get(translation_tier, [])),
            "morphemes": [x["text"] for x in related.get(morpheme_tier, [])],
            "glosses": [x["text"] for x in related.get(gloss_tier, [])],
            "annotation_id": aid, "tier": transcript_tier,
            "participant": tiers[transcript_tier].get("PARTICIPANT"),
            "annotator": tiers[transcript_tier].get("ANNOTATOR"),
            "linguistic_type": tiers[transcript_tier].get("LINGUISTIC_TYPE_REF"),
            "transcript_details": item,
            "associated_annotations": related,
        })
    df = pd.DataFrame(rows)
    for column in ("start_ms", "end_ms", "duration_ms"):
        if column in df:
            df[column] = df[column].astype("Int64")
    df.attrs["unassociated_annotations"] = unassociated
    df.attrs["document_metadata"] = dict(root.attrib)
    df.attrs["media"] = [dict(m.attrib) for m in root.findall("./HEADER/MEDIA_DESCRIPTOR")]
    return df


def eaf_attribute_dataframe(path, **kwargs):
    """One row per annotation, with original XML attribute names as columns.

    The timestamp index is a TimedeltaIndex of annotation start times. Reference
    annotations inherit timing from their referenced annotation. Duplicate
    timestamps and NaT (unknown starts) are intentional. ANNOTATION_VALUE is
    element text, included alongside attributes for convenient inspection.
    """
    segments = eaf_dataframe(path, **kwargs)
    records = []
    for _, segment in segments.iterrows():
        records.append(segment["transcript_details"])
        for children in segment["associated_annotations"].values():
            records.extend(children)
    records.extend(segments.attrs["unassociated_annotations"])
    rows = [
        {**record["tier_metadata"], **record["attributes"],
         "ANNOTATION_VALUE": record["text"]}
        for record in records
    ]
    result = pd.DataFrame(rows)
    result.index = pd.TimedeltaIndex(
        pd.to_timedelta([record["start_ms"] for record in records], unit="ms"),
        name="timestamp",
    )
    return result.sort_index(kind="stable", na_position="last")
