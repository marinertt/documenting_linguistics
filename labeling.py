"""Explainable draft lexical labels from aligned sentence word sets."""
import unicodedata
from collections import Counter


def tokens(text, portuguese=False):
    text = unicodedata.normalize('NFC', text.casefold())
    if portuguese:
        text = ''.join(c for c in unicodedata.normalize('NFD', text)
                       if not unicodedata.category(c).startswith('M'))
    # Keep source transcription conventions inside tokens; strip edge punctuation.
    words = []
    for part in text.split():
        if portuguese:
            part = ''.join(c if c.isalnum() or c in "-'" else ' ' for c in part)
        for word in part.split():
            word = word.strip(".,;:!?\"[]()…'-" if portuguese else '.,;:!?"[]…')
            if word and any(c.isalpha() for c in word):
                words.append(unicodedata.normalize('NFC', word))
    return words


def propose_labels(df, entries, min_examples=2):
    """Suggest Portuguese meanings for repeated original-language words.

    Only translated passages supply candidates. Counts include untranslated
    occurrences so words such as pare remain discoverable with sparse evidence.
    Single-word lexicon meanings of other words are subtracted per passage.
    """
    seeds = {}
    for entry in entries:
        source = tokens(entry['word'])
        target = tokens(entry.get('meaning', ''), True)
        if len(source) == len(target) == 1:
            seeds[source[0]] = target[0]
    passages = []
    for _, r in df.iterrows():
        passages.append({'id': r.annotation_id, 'timestamp': r.timestamp,
                         'transcript': r.transcript, 'translation': r.translation,
                         'source': set(tokens(r.transcript)),
                         'target': set(tokens(r.translation, True))})
    translated = [p for p in passages if p['target']]
    counts = Counter(word for p in passages for word in p['source'])
    suggestions = []
    for word, count in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        if count < min_examples:
            continue
        supporting = [p for p in passages if word in p['source']]
        evidence, remaining = [], []
        for p in supporting:
            removed = {w: seeds[w] for w in p['source']
                       if w != word and w in seeds and seeds[w] in p['target']
                       and seeds[w] != seeds.get(word)}
            candidates = p['target'] - set(removed.values())
            if p['target']:
                remaining.append(candidates)
            evidence.append({k:p[k] for k in ('id','timestamp','transcript','translation')} |
                            {'remaining': sorted(candidates), 'removed': removed})
        shared = set.intersection(*remaining) if remaining else set()
        union = set.union(*remaining) if remaining else set()
        ranked = []
        for meaning in union:
            hits = sum(meaning in s for s in remaining)
            outside = sum(meaning in p['target'] and word not in p['source'] for p in translated)
            ranked.append({'word':meaning, 'support':hits, 'total':len(remaining),
                           'outside':outside, 'shared':meaning in shared})
        ranked.sort(key=lambda x:(not x['shared'], -x['support'], x['outside'], x['word']))
        status = ('lexicon-supported' if word in seeds else
                  'insufficient' if len(remaining)<2 else
                  'single-candidate' if len(shared)==1 else
                  'ambiguous' if shared else 'unresolved')
        suggestions.append({'word':word, 'support':count,
                            'translated_support':len(remaining), 'status':status,
                            'known_meaning':seeds.get(word), 'shared':sorted(shared),
                            'candidates':ranked, 'evidence':evidence})
    return {'suggestions': suggestions, 'seed_count':len(seeds),
            'translated_passages':len(translated),
            'method':'For each original-language word, compare Portuguese word sets in its translated passages and subtract meanings assigned to other source words. Candidates remain hypotheses.'}
