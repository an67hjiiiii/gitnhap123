"""Conservative Vietnamese syllable repair, adapted from measured join_v2 rules."""
import re
import unicodedata
from collections import Counter
from math import log1p, isclose

CLEANER_VERSION = "legal-rules-v3"

TONES = {"̀", "́", "̃", "̉", "̣"}
ONSET = r"(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdđghklmnprstvx])?"
NUC = ("iêu yêu oai oao oay oeo uây uôi uya uyê ươi ươu "
       "ai ao au ay âu ây eo êu ia iu iê oa oă oe oi ôi ơi ua uâ uê ui uô uơ uy ưa ưi ưu ươ ya yê "
       "a ă â e ê i o ô ơ u ư y").split()
CODA = r"(?:ch|ng|nh|[cmnpt])?"
SYL = re.compile(rf"^{ONSET}(?:{'|'.join(NUC)}){CODA}$")
VOWEL = set("aăâeêioôơuưy")


def strip_tone(w):
    d = unicodedata.normalize("NFD", w)
    return unicodedata.normalize("NFC", "".join(c for c in d if c not in TONES)), sum(c in TONES for c in d)


def valid(w):
    # Observed false positives: Vietnamese morphology alone accepts these.
    # Keeping them invalid also lets lookahead repair "ba n hành", "kiế n áp".
    if w.lower() in {"náp", "nhành", "viáp", "vịm"}:
        return False
    base, n = strip_tone(w.lower())
    # Checked syllables allow only sắc/nặng (e.g. "đào" + "t" is not valid).
    marks = set(unicodedata.normalize("NFD", w.lower())) & TONES
    if re.search(r"(?:ch|[cpt])$", base) and not marks.intersection({"\u0301", "\u0323"}):
        return False
    return n <= 1 and bool(SYL.match(base))


def ntone(w):
    return strip_tone(w)[1]


def document_vocabulary(text):
    """Count intact syllables/pairs once, before any repairs in this file."""
    syllables, pairs = Counter(), Counter()
    for line in text.splitlines():
        tokens = re.findall(r"[^\W\d_]+|[^\w\s]", line, re.UNICODE)
        intact = [valid(t) for t in tokens]
        # Neighbours of a broken fragment are not intact training examples.
        intact = [ok and not any(tokens[j].isalpha() and not valid(tokens[j])
                                for j in (i - 1, i + 1) if 0 <= j < len(tokens))
                  for i, ok in enumerate(intact)]
        for i, (a, b) in enumerate(zip(tokens, tokens[1:])):
            if (a.isalpha() and b.isalpha() and a.islower() and b.islower()
                    and valid(a + b) and (not valid(a) or not valid(b)
                    or (strip_tone(b[0])[0] in VOWEL and ntone(a) == 0
                        and ntone(b) == 1 and strip_tone(a[-1])[0] in VOWEL))):
                intact[i] = intact[i + 1] = False
        for i, token in enumerate(tokens):
            if intact[i]:
                syllables[token.lower()] += 1
                if i and intact[i - 1]:
                    pairs[tokens[i - 1].lower(), token.lower()] += 1
    return syllables, pairs


def join_line(line, log, audit=None, vocabulary=None, ambiguous=None):
    vocabulary = vocabulary if vocabulary is not None else document_vocabulary(line)
    toks = line.split(" ")
    out, i = [], 0
    while i < len(toks):
        a = toks[i]
        if i + 1 < len(toks):
            b_full = toks[i + 1]
            b = b_full.rstrip(".,;:)!?")
            tail = b_full[len(b):]
            c = (toks[i + 2] if i + 2 < len(toks) else "").rstrip(".,;:)!?")
            consonant_fragment = b.isalpha() and not any(v in VOWEL for v in strip_tone(b.lower())[0])
            if (consonant_fragment and not tail and a.isalpha() and a.islower()
                    and c.isalpha() and c.islower()):
                options = [(a + b, c), (a, b + c)]
                eligible = [all(valid(t) for t in option) for option in options]
                if any(eligible):
                    syllables, pairs = vocabulary
                    def score(option):
                        words = [t.lower() for t in option]
                        value = sum(log1p(syllables[t]) for t in words)
                        previous = (out[-1] if out else "").strip(".,;:()!?").lower()
                        following = (toks[i + 3] if i + 3 < len(toks) else "").strip(".,;:()!?").lower()
                        context = [previous, *words, following]
                        return value + sum(log1p(pairs[x, y]) for x, y in zip(context, context[1:]))
                    scores = [score(option) if ok else None for option, ok in zip(options, eligible)]
                    reason = "luật"
                    if all(eligible):
                        if isclose(scores[0], scores[1], abs_tol=1e-12):
                            if ambiguous is not None:
                                ambiguous.append({"before": " ".join(toks[i:i + 3]), "scores": scores})
                            out.extend(toks[i:i + 3]); i += 3; continue
                        direction = int(scores[1] > scores[0])
                        reason = "tần suất"
                    else:
                        direction = int(eligible[1])
                    start = i + direction
                    before = " ".join(toks[start:start + 2])
                    after = options[direction][direction]
                    prefix = out + ([a] if direction else [])
                    log.append(f"{before} -> {after}")
                    if audit is not None:
                        audit.append({"before": before, "after": after,
                                      "offset": len(" ".join(prefix)) + bool(prefix),
                                      "reason": reason, "scores": scores})
                    if direction:
                        out.append(a)
                        out.append(b + toks[i + 2])
                        i += 3
                    else:
                        out.append(a + b)
                        i += 2
                    continue
                # Neither candidate contains two legal syllables. Do not let
                # the pair fallback choose a direction for this triple.
                if ambiguous is not None:
                    ambiguous.append({"before": " ".join(toks[i:i + 3]), "scores": [None, None]})
                out.extend(toks[i:i + 3]); i += 3; continue
            b_starts_next = (c.isalpha() and c.islower() and not valid(b) and valid(b + c)
                             and not (consonant_fragment and valid(a + b)))
            if not b_starts_next and a.isalpha() and b.isalpha() and a.islower() and b.islower() and valid(a + b):
                b0 = strip_tone(b[0])[0]
                if (not valid(a)) or (not valid(b)) or (b0 in VOWEL and ntone(a) == 0 and ntone(b) == 1 and strip_tone(a[-1])[0] in VOWEL):
                    log.append(f"{a} {b} -> {a + b}")
                    if audit is not None:
                        audit.append({"before": a + " " + b, "after": a + b,
                                      "offset": len(" ".join(out)) + bool(out), "reason": "luật"})
                    out.append(a + b + tail); i += 2; continue
        out.append(a); i += 1
    return " ".join(out)


def clean_legal_text(text: str) -> tuple[str, dict]:
    """Repair measured PDF defects; return all edits for review, without I/O.

    Noise needs three occurrences per category (page numbers vary by page).
    Headings, numbered clauses and sentence punctuation retain their boundaries.
    """
    lines = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n").split("\n")
    def noise(line):
        s = line.strip()
        if re.fullmatch(r"\d+", s):
            return "page_number"
        if s.startswith("Ký bởi:"):
            return "signature"
        if "CÔNG BÁO" in s:
            return "gazette"
        return None

    counts = Counter(noise(line) for line in lines)
    vocabulary = document_vocabulary("\n".join(lines))
    log, kept, ambiguous = [], [], []
    removed = 0
    for line in lines:
        category = noise(line)
        if category and counts[category] >= 3:
            removed += 1
            continue
        kept.append(join_line(line, log, vocabulary=vocabulary, ambiguous=ambiguous))
    # PDF identifiers often have spaces surrounding the hyphen.
    kept = [re.sub(r"TT\s*-\s*BGD[ĐD]T", "TT-BGDĐT", line) for line in kept]
    output, joined_lines = [], 0
    for line in kept:
        s = line.strip()
        previous = next((v for v in reversed(output) if v), "")
        heading = re.match(r"(?:Điều\s|Chương\s|Phần\s|\d+[.)]|[a-zđ][)]|[-•])", s)
        if (s and previous and s[0].islower() and not heading
                and not re.search(r"[.!?;:…]$", previous)):
            while output and not output[-1]:
                output.pop()
            output[-1] += " " + s
            joined_lines += 1
        else:
            output.append(s)
    return "\n".join(output).strip(), {
        "syllable_joins": len(log), "joins": log,
        "line_joins": joined_lines, "noise_lines_removed": removed,
        "ambiguous": len(ambiguous), "ambiguous_cases": ambiguous,
    }


