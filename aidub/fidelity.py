"""Conservative blocking of demonstrated, materially conflicting ASR readings.

This is not semantic adjudication. It refuses to guess between opposite polarity
readings of shared content; nonmaterial disagreements remain visible to review.
"""
import re
import unicodedata
from difflib import SequenceMatcher


def tokens(text):
    text="".join(c for c in unicodedata.normalize("NFD",text.lower()) if unicodedata.category(c)!="Mn")
    return re.findall(r"\w+",text)


def material_conflict(seg):
    negators={"no","nunca","jamas","tampoco","nadie","nada","sin"}
    for alternative in seg.get("asr_alternatives",[]):
        other=tokens(alternative["text"])
        # A joined take can contain an unrelated negation in another source
        # part. Compare the alternative with its closest original part.
        parts=seg.get("source_cues") or [seg]
        source=max(parts,key=lambda p:SequenceMatcher(None,tokens(p["spanish"]),other).ratio())
        first=tokens(source["spanish"])
        common={w for w in set(first)&set(other) if len(w)>=4 and w not in {"pero","bueno","vamos","entonces"}}
        if common and bool(set(first)&negators)!=bool(set(other)&negators):
            return {"kind":"opposite_source_polarity","first":source["spanish"],"alternative":alternative["text"],
                    "shared_content":sorted(common),"decision":"unvoiced_pending_source_resolution"}
    return None
