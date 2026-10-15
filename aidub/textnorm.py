"""English/Spanish text normalization, syllable estimates and sequence-aware comparison.

The comparison is a heuristic over ASR text. It tolerates contractions, number
formatting, fillers and small spelling variation, and it reports what it found;
it does not prove that the spoken audio is correct.
"""

from __future__ import annotations

import re
import unicodedata

_APOS = str.maketrans({"\u2019": "'", "\u2018": "'", "`": "'", "\u00b4": "'"})

_FIXED = {
    "can't": "can not", "cannot": "can not", "won't": "will not", "shan't": "shall not",
    "ain't": "is not", "let's": "let us", "it's": "it is", "that's": "that is",
    "there's": "there is", "here's": "here is", "what's": "what is", "where's": "where is",
    "where'd": "where did",
    "who's": "who is", "how's": "how is", "he's": "he is", "she's": "she is",
    "y'all": "you all", "'cause": "because", "cause": "because", "cuz": "because", "cos": "because",
    "gonna": "going to", "wanna": "want to", "gotta": "got to", "gimme": "give me",
    "lemme": "let me", "kinda": "kind of", "sorta": "sort of", "outta": "out of",
    "dunno": "do not know", "ya": "you", "alright": "all right", "ok": "okay", "k": "okay",
    "yep": "yeah", "yup": "yeah", "yea": "yeah", "nope": "no", "nah": "no",
    "o'clock": "oclock", "'em": "them",
}
_SUFFIXES = (("n't", " not"), ("'re", " are"), ("'ve", " have"), ("'ll", " will"), ("'m", " am"), ("'d", " would"))
FILLERS = {"uh", "um", "uhm", "umm", "erm", "er", "hmm", "hm", "mm", "mhm", "uhh", "ehh"}
STOPWORDS = {"a", "an", "the", "i", "it", "to", "of", "and", "or", "so", "we", "you", "is", "am", "are"}
NEGATIONS = {"not", "no", "never", "nothing", "nobody", "none", "neither", "nor", "nowhere", "without"}
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
NUMBER_WORDS = set(_ONES) | set(_TENS[2:]) | {"hundred", "thousand", "million", "billion", "half"}
_EQUIV = [
    {"there", "their", "theyre"}, {"to", "too"}, {"your", "youre"},
    {"would", "had"}, {"yeah", "yes"}, {"okay", "kay"}, {"oh", "o"}, {"wow", "whoa", "woah"},
    {"oof", "uff", "ouf"}, {"huh", "ha"}, {"right", "write"},
]
_EQUIV_MAP = {word: frozenset(group) for group in _EQUIV for word in group}
_TOKEN = re.compile(r"[a-z0-9']+")


def number_words(n: int) -> str:
    if n < 0:
        return "minus " + number_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + ("" if not ones else " " + _ONES[ones])
    for size, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= size:
            head, rest = divmod(n, size)
            return number_words(head) + " " + name + ("" if not rest else " " + number_words(rest))
    return str(n)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _expand(word: str) -> str:
    if word in _FIXED:
        return _FIXED[word]
    if word.isdigit():
        return number_words(int(word)) if len(word) < 10 else word
    m = re.fullmatch(r"(\d+)(st|nd|rd|th)", word)
    if m:
        return number_words(int(m.group(1)))
    for suffix, replacement in _SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix):
            return word[: -len(suffix)] + replacement
    if word.endswith("'s") and len(word) > 2:
        return word[:-2]
    if word.endswith("s'") and len(word) > 2:
        return word[:-1]
    return word


def normalize_tokens(text: str, *, drop_fillers: bool = True) -> list[str]:
    raw = strip_accents((text or "").translate(_APOS).lower())
    raw = raw.replace("%", " percent ").replace("&", " and ")
    raw = re.sub(r"(\d),(\d)", r"\1\2", raw)
    raw = re.sub(r"[-_/]", " ", raw)
    out = []
    for word in _TOKEN.findall(raw):
        word = word.strip("'")
        if not word:
            continue
        for part in _expand(word).split():
            part = part.replace("'", "")
            if part and not (drop_fillers and part in FILLERS):
                out.append(part)
    return out


def content_tokens(tokens: list[str]) -> list[str]:
    content = [w for w in tokens if w not in STOPWORDS]
    return content or tokens


def _lev(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def tokens_equivalent(a: str, b: str, *, name: bool = False) -> bool:
    if a == b:
        return True
    group = _EQUIV_MAP.get(a)
    if group and b in group:
        return True
    for x, y in ((a, b), (b, a)):
        if x + "s" == y or x + "es" == y:
            return True
    shorter = min(len(a), len(b))
    if a.isalpha() and b.isalpha():
        if shorter >= 4 and _lev(a, b) <= 1:
            return True
        if name and shorter >= 5 and _lev(a, b) <= 2:
            return True
    return False


def align(expected: list[str], heard: list[str], names: set[str] | None = None) -> list[tuple[str, int | None, int | None]]:
    """Token edit alignment; ops are match, sub, del (missing from heard) and ins (extra)."""
    names = names or set()
    n, m = len(expected), len(heard)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i
    for j in range(1, m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = tokens_equivalent(expected[i - 1], heard[j - 1], name=expected[i - 1] in names)
            cost[i][j] = min(cost[i - 1][j - 1] + (0 if same else 1), cost[i - 1][j] + 1, cost[i][j - 1] + 1)
    ops = []
    i, j = n, m
    while i or j:
        if i and j:
            same = tokens_equivalent(expected[i - 1], heard[j - 1], name=expected[i - 1] in names)
            if cost[i][j] == cost[i - 1][j - 1] + (0 if same else 1):
                ops.append(("match" if same else "sub", i - 1, j - 1))
                i, j = i - 1, j - 1
                continue
        if i and cost[i][j] == cost[i - 1][j] + 1:
            ops.append(("del", i - 1, None))
            i -= 1
        else:
            ops.append(("ins", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def _max_runs(tokens: list[str], n: int) -> dict[tuple, int]:
    best: dict[tuple, int] = {}
    for start in range(len(tokens) - n + 1):
        gram = tuple(tokens[start:start + n])
        reps, pos = 1, start + n
        while tuple(tokens[pos:pos + n]) == gram:
            reps += 1
            pos += n
        if reps > best.get(gram, 0):
            best[gram] = reps
    return best


def repetitions(expected: list[str], heard: list[str]) -> list[str]:
    """N-grams repeated back to back more often in the heard text than in the expected text."""
    found = []
    for n in (1, 2, 3, 4):
        exp_runs = _max_runs(expected, n)
        for gram, reps in _max_runs(heard, n).items():
            if reps < 2 or (n == 1 and reps < 3):
                continue
            if reps > exp_runs.get(gram, 1):
                found.append(" ".join(gram) + f" x{reps}")
    return found


def name_tokens(original_text: str, extra_names: list[str] | None = None) -> set[str]:
    """Capitalized words that are not sentence initial, plus configured glossary names."""
    names = set()
    words = re.findall(r"[\w'’]+|[.!?]", original_text or "")
    sentence_start = True
    for word in words:
        if word in ".!?":
            sentence_start = True
            continue
        if not sentence_start and word[:1].isupper() and word.lower() not in {"i", "i'm", "i'll", "i've", "i'd"}:
            names.update(normalize_tokens(word))
        sentence_start = False
    for item in extra_names or []:
        names.update(normalize_tokens(item))
    return {n for n in names if n not in STOPWORDS and n not in NEGATIONS}


def _critical_counts(tokens: list[str], names: set[str]) -> dict[str, list[str]]:
    return {
        "negation": [t for t in tokens if t in NEGATIONS],
        "number": [t for t in tokens if t in NUMBER_WORDS or t.isdigit()],
        "name": [t for t in tokens if t in names],
    }


def _missing_from(a: list[str], b: list[str], name: bool = False) -> list[str]:
    pool = list(b)
    missing = []
    for token in a:
        hit = next((k for k, other in enumerate(pool) if tokens_equivalent(token, other, name=name)), None)
        if hit is None:
            missing.append(token)
        else:
            pool.pop(hit)
    return missing


def sequence_check(expected_text: str, heard_text: str | None, *, language: str | None = None,
                   names: list[str] | None = None) -> dict:
    """Compare intended English with ASR of the synthesized take.

    Returns hard issues (reject), soft issues (disputed: worth a second hearing)
    and the evidence used. Short phrases are judged leniently because ASR
    commonly respells reactions.
    """
    result = {"hard": [], "soft": [], "skipped": heard_text is None}
    if heard_text is None:
        return result
    exp = normalize_tokens(expected_text)
    hyp = normalize_tokens(heard_text)
    name_set = name_tokens(expected_text, names)
    result.update(expected_tokens=exp, heard_tokens=hyp)
    if not exp:
        # Fillers can be the entire intended performance. Removing both sides
        # from comparison previously let a missing hesitation pass unchecked.
        original = normalize_tokens(expected_text, drop_fillers=False)
        heard = normalize_tokens(heard_text, drop_fillers=False)
        if original and all(w in FILLERS for w in original):
            family = FILLERS | {"eh", "uhhh", "ummm"}
            if not heard or not any(w in family for w in heard):
                result["hard"].append("missing_vocal_event")
            if any(w not in family for w in heard):
                result["hard"].append("extra_speech")
            result["vocal_event_check"] = {"expected": original, "heard": heard}
        return result
    ops = align(exp, hyp, name_set)
    matches = sum(1 for op in ops if op[0] == "match")
    subs = [exp[i] for op, i, _ in ops if op == "sub"]
    dels = [exp[i] for op, i, _ in ops if op == "del"]
    ins = [hyp[j] for op, _, j in ops if op == "ins"]
    n = len(exp)
    content_n = len(content_tokens(exp))
    missing_content = [w for w in subs + dels if w not in STOPWORDS]
    extra_content = [w for w in ins if w not in STOPWORDS]
    result.update(matches=matches, substituted=subs, missing=dels, extra=ins,
                  error_rate=round((len(subs) + len(dels) + len(ins)) / n, 4))
    short = content_n <= 2
    lang = (language or "").lower()
    if lang and lang not in {"en", "english"} and matches / n < 0.5:
        result["hard"].append("wrong_language")
    if short:
        if len(extra_content) >= 4:
            result["hard"].append("extra_speech")
        elif matches < n or extra_content:
            result["soft"].append("short_phrase_mismatch")
    else:
        if matches == 0 and hyp:
            result["hard"].append("missing_or_incorrect_text")
        elif len(missing_content) / max(1, content_n) > 0.34:
            result["hard"].append("missing_or_incorrect_text")
        elif missing_content:
            result["soft"].append("missing_words")
        if len(extra_content) >= max(3, (content_n + 1) // 2):
            result["hard"].append("extra_speech")
        elif extra_content:
            result["soft"].append("extra_words")
    reps = repetitions(exp, hyp)
    if reps:
        result["repeated"] = reps
        heavy = any(len(r.split(" x")[0].split()) >= 2 for r in reps) or any(int(r.rsplit("x", 1)[1]) >= 4 for r in reps)
        (result["hard"] if heavy else result["soft"]).append("repetition")
    trailing = 0
    for op, i, _ in reversed(ops):
        if op == "ins":
            continue
        if op in {"del", "sub"} and exp[i] not in STOPWORDS:
            trailing += 1
            continue
        break
    if n >= 3 and matches >= n / 2 and trailing:
        (result["hard"] if trailing >= 2 else result["soft"]).append("truncated_speech")
    if n >= 4:
        bag = n - len(_missing_from(exp, hyp))
        if bag / n >= 0.8 and (bag - matches) / n >= 0.25:
            result["hard"].append("reordered_words")
            result["bag_matches"] = bag
    exp_c, hyp_c = _critical_counts(exp, name_set), _critical_counts(hyp, name_set)
    critical = {}
    for kind in ("negation", "number", "name"):
        lost = _missing_from(exp_c[kind], hyp, name=kind == "name")
        added = _missing_from(hyp_c[kind], exp, name=kind == "name") if kind != "name" else []
        if lost or added:
            critical[kind] = {"missing": lost, "extra": added}
            presence_flip = (bool(exp_c[kind]) != bool(hyp_c[kind])) or (kind != "negation" and lost)
            if short:
                result["soft"].append(f"critical_{kind}")
            elif presence_flip:
                result["hard"].append(f"critical_{kind}")
            else:
                result["soft"].append(f"critical_{kind}")
    if critical:
        result["critical"] = critical
    result["hard"] = sorted(set(result["hard"]))
    result["soft"] = sorted(set(result["soft"]) - set(result["hard"]))
    return result


_EN_VOWELS = re.compile(r"[aeiouy]+")


def english_syllables(text: str) -> int:
    total = 0
    for word in normalize_tokens(text, drop_fillers=False):
        word = re.sub(r"[^a-z]", "", word)
        if not word:
            continue
        groups = len(_EN_VOWELS.findall(word))
        if word.endswith("e") and not word.endswith(("le", "ee", "ye")) and groups > 1:
            groups -= 1
        if word.endswith(("ed",)) and not word.endswith(("ted", "ded")) and groups > 1:
            groups -= 1
        total += max(1, groups)
    return total


_ES_VOWEL_GROUPS = re.compile(r"[aeiouáéíóúü]+")
_ES_STRONG = set("aeoáéíóú")


def spanish_syllables(text: str) -> int:
    total = 0
    for word in re.findall(r"[a-záéíóúüñ]+", (text or "").lower()):
        count = 0
        for group in _ES_VOWEL_GROUPS.findall(word):
            strong = sum(1 for c in group if c in _ES_STRONG)
            count += max(1, strong)
        total += max(1, count)
    return total
