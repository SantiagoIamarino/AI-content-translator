"""Conservative, inspectable ASR differences; never infer acoustic truth from agreement.

Only an explicit orthographic equivalence or a punctuated discourse insertion
can bypass another source adjudication. Unknown differences remain localized
review work, not evidence that every word of a cue has a competing meaning.
"""
import re
import copy
from difflib import SequenceMatcher
from .util import fingerprint

POLICY = "aidub.source_disagreement.v2"
ORTHOGRAPHY = {"hábitat": "habitat", "vídeo": "video"}
NUMBERS = {"cero": "0", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
           "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10"}


def acoustic_numbers_differ(evidence):
    """Selecting one supplied ASR cannot establish which competing number is true."""
    def numbers(text):
        text = re.sub(r"(?<=\d)\s*[.,]\s*(?=\d{3}(?:\D|$))", "", text)
        return [t for t in _tokens(text) if t.isdigit()]
    a = numbers(evidence.get("primary_text", ""))
    b = numbers(evidence.get("inside", {}).get("text", ""))
    return bool(a or b) and a != b


def _tokens(text):
    return [NUMBERS.get(t, ORTHOGRAPHY.get(t, t)) for t in re.findall(r"\w+", text.lower())]


def _discourse(text, words, a, b):
    # No stopword stripping: only one clearly delimited discourse token or an
    # initial conjunction. Repetitions, pronouns, verbs and hedges stay content.
    if b - a != 1:
        return False
    token = words[a]
    if a == 0 and token == "y":
        return True
    occurrence = list(re.finditer(r"\w+", text))[a]
    before, after = text[:occurrence.start()].rstrip(), text[occurrence.end():]
    boundary = not before or before[-1] in ",;.!?…"
    return (token in {"bueno", "bien"} and bool(re.match(r"\s*[,;.!?…]", after))
            and (boundary or token == "bueno" and a > 0 and words[a - 1] == "que"))


def compare_readings(first, other):
    a, b = _tokens(first), _tokens(other)
    changes = [{"primary_range": [i, j], "alternative_range": [k, l],
                "primary": a[i:j], "alternative": b[k:l]}
               for op, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op != "equal"]
    if not changes:
        return {"kind": "equivalent", "reason": "punctuation or explicit orthographic/numeral equivalence", "changes": []}
    # A changed number or polarity is always material here. Resolving it still
    # needs the existing evidence-bound source adjudication, never this helper.
    polarity = {"no", "nunca", "jamás", "jamas", "tampoco", "nadie", "nada", "sin"}
    if any(any(t.isdigit() or t in polarity for t in c["primary"] + c["alternative"]) for c in changes):
        kind, reason = "material", "competing number or polarity; explicit acoustic adjudication required"
    elif min(len(a), len(b)) >= 3 and all(
            (not c["alternative"] and _discourse(first, a, *c["primary_range"])) or
            (not c["primary"] and _discourse(other, b, *c["alternative_range"])) for c in changes):
        kind, reason = "minor", "only delimited discourse/initial connector differs; retain its conversational function"
    else:
        kind, reason = "localized", "unadjudicated lexical/grammar difference; isolate changed ranges for source review"
    return {"kind": kind, "reason": reason, "changes": changes}


def disagreement(seg):
    parts = seg.get("source_cues") or [seg]
    comparisons = []
    for alt in seg.get("asr_alternatives", []):
        source = max(parts, key=lambda p: SequenceMatcher(None, _tokens(p["spanish"]), _tokens(alt["text"])).ratio())
        comparisons.append(dict(compare_readings(source["spanish"], alt["text"]),
                                primary_text=source["spanish"], alternative_text=alt["text"]))
    # A contextual hearing may expose a conflict absent from the earlier pass.
    e = (seg.get("source_comparison_evidence") or seg.get("source_evidence") or
         (seg.get("source_resolution") or {}).get("evidence") or {})
    if e.get("inside", {}).get("text") and e.get("primary_text"):
        comparisons.append(dict(compare_readings(e["primary_text"], e["inside"]["text"]),
                                primary_text=e["primary_text"], alternative_text=e["inside"]["text"]))
    rank = {"equivalent": 0, "minor": 1, "localized": 2, "material": 3}
    kind = max((c["kind"] for c in comparisons), key=rank.get, default="equivalent")
    return {"policy": POLICY, "kind": kind, "comparisons": comparisons}


def bind_comparison_evidence(seg, evidence, mic_sha):
    """Copy only a current, integrity-bound saved hearing; never copy a decision."""
    out = copy.deepcopy(seg)
    if (evidence.get("identity") == fingerprint({k: v for k, v in evidence.items() if k != "identity"})
            and evidence.get("mic_sha256") == mic_sha and evidence.get("complete")
            and evidence.get("span") == [seg["start"], seg["end"]]
            and evidence.get("primary_text") == seg["spanish"]):
        out["source_comparison_evidence"] = copy.deepcopy(evidence)
    return out


def lexical_support(seg):
    e = seg.get("source_evidence") or {}
    words = e.get("primary_words") or seg.get("source_words") or []
    span = e.get("span") or [seg.get("start", float("inf")), seg.get("end", -float("inf"))]
    return bool(words and sum(w.get("probability", 0) for w in words) / len(words) >= .6 and
                any(w.get("end", -1) > span[0] and w.get("start", float("inf")) < span[1] for w in words))
