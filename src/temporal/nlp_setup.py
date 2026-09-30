"""
Shared spaCy pipeline for the temporal analysis engine.

spaCy is used strictly as a POS/morphology feature extractor here (tagger +
morphologizer) -- never as a text generator, and nothing here is trained to
predict tense or anything else. Every detector built on top of these tags
(tense_tagger.py, flashback_detector.py, temporal_markers.py, ...) is a
fixed rule reading that output, matching the SOW Phase 4 methodology
framing ("heuristics, not ML"). Parser/NER/lemmatizer/morphologizer are all disabled: tense_tagger.py's
rules only ever read `token.tag_` (Penn Treebank tags: VBD, VBN, VBP, VBZ,
VB, MD), never `token.morph`, so the morphologizer is pure unused overhead
here even though it sounds relevant to a tense-tagging task. Measured
directly (see the Phase 2 brief's verification notes): the tok2vec+tagger
core is the real cost at ~4.7ms/sentence, which is roughly 40-50 minutes for
the full 91-novel corpus (~550K sentences) as a one-time batch run --
multiprocessing via spaCy's n_process was tried and measured SLOWER for
per-sentence-sized texts (process-spawn/serialization overhead dominates
for short inputs), so this stays single-process.
"""
import spacy

_NLP = None


def get_nlp():
    global _NLP
    if _NLP is None:
        _NLP = spacy.load("en_core_web_sm", disable=["parser", "ner", "lemmatizer", "morphologizer"])
    return _NLP


def pipe_sentences(texts, batch_size: int = 500):
    """Process many sentence texts through spaCy in batches. Always call
    this instead of nlp(text) in a loop -- nlp.pipe amortizes per-call
    overhead and matters at this corpus's scale."""
    return get_nlp().pipe(texts, batch_size=batch_size)
