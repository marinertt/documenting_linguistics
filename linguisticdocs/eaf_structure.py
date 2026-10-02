"""Notebook-ready EAF inventory: preserve source plus an ordered XML tree."""
from pathlib import Path
from collections import Counter
from xml.dom import minidom, Node
import json


def inspect_eaf(path):
    # Keep original UTF-8 source, including declaration, whitespace and newlines.
    raw_xml = Path(path).read_bytes().decode("utf-8")
    document = minidom.parseString(raw_xml)
    elements = list(document.getElementsByTagName("*"))

    def encode(node):
        if node.nodeType == Node.ELEMENT_NODE:
            return {
                "tag": node.tagName,
                "attributes": dict(node.attributes.items()),
                "children": [encode(child) for child in node.childNodes],
            }
        # Includes whitespace text, comments and processing instructions.
        return {"node_type": node.nodeType, "name": node.nodeName,
                "value": node.nodeValue}

    inventory = {}
    for element in elements:
        entry = inventory.setdefault(element.tagName, {
            "count": 0, "attribute_values": {}, "child_tags": []})
        entry["count"] += 1
        for key, value in element.attributes.items():
            values = entry["attribute_values"].setdefault(key, [])
            if value not in values:
                values.append(value)
        for child in element.childNodes:
            if child.nodeType == Node.ELEMENT_NODE and child.tagName not in entry["child_tags"]:
                entry["child_tags"].append(child.tagName)

    tiers = []
    for tier in document.getElementsByTagName("TIER"):
        values = tier.getElementsByTagName("ANNOTATION_VALUE")
        tiers.append({
            **dict(tier.attributes.items()),
            "annotation_count": len(values),
            "empty_values": sum(not v.childNodes or not "".join(
                c.nodeValue or "" for c in v.childNodes).strip() for v in values),
        })

    tree = encode(document.documentElement)

    def walk(node):
        if "tag" in node:
            yield node
            for child in node["children"]:
                yield from walk(child)

    copied = list(walk(tree))
    # Confirm each element and attribute survived, in the original order.
    assert [(n["tag"], n["attributes"]) for n in copied] == [
        (e.tagName, dict(e.attributes.items())) for e in elements]
    return {
        "summary": {
            "source_lines": len(raw_xml.splitlines()),
            "element_count": len(elements),
            "attribute_count": sum(e.attributes.length for e in elements),
            "element_counts": dict(Counter(e.tagName for e in elements)),
            "tiers": tiers,
        },
        "inventory": inventory,
        "tree": tree,
        "raw_xml": raw_xml,
    }


if __name__ == "__main__":
    report = inspect_eaf("data/eaf_example.eaf")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
