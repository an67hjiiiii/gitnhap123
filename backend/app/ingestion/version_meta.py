"""Evidence-backed version suggestions; no inference of current legal validity."""
from __future__ import annotations

import re
from datetime import date


DOC = r"\d{1,3}/\d{4}/[A-ZĐ]+(?:-[A-ZĐ0-9]+)+"
DATE = r"(?:ngày\s+)?(\d{1,2})\s*(?:/|tháng\s+)(\d{1,2})\s*(?:/|năm\s+)(\d{4})"


def _label_view(raw):
    """Recognize spaced label syllables; retain offsets for verbatim evidence.

    This limited recognition vocabulary is independent of ingestion cleaning.
    It neither repairs arbitrary prose nor learns syllable joins.
    """
    words = ("Số hiệu Hà Nội ngày tháng năm Phiên bản Ngày ban hành dự thảo Hiệu lực "
             "từ kiến Tình trạng đã bị thay thế hết Kèm theo Thông tư này có thi kể "
             "Điều khoản áp dụng đối với cho khóa khoá tuyển sinh chuyển tiếp "
             "bãi bỏ một phần điểm Sửa đổi bổ sung Phạm vi Căn cứ Nơi nhận").split()
    text, offsets = raw, list(range(len(raw)))
    for word in sorted(set(words), key=len, reverse=True):
        pattern = r"(?<!\w)" + r"[^\S\n]*".join(map(re.escape, word)) + r"(?!\w)"
        matches = list(re.finditer(pattern, text, re.I))
        for match in reversed(matches):
            # Already intact labels keep their spelling and capitalization.
            chars = [i for i in range(match.start(), match.end()) if not text[i].isspace()]
            replacement = "".join(text[i] for i in chars)
            text = text[:match.start()] + replacement + text[match.end():]
            offsets[match.start():match.end()] = [offsets[i] for i in chars]
    phrases = ("Thông tư này", "Thông tư số", "hiệu lực thi hành", "hiệu lực",
               "thi hành", "từ ngày", "áp dụng đối với", "thay thế", "bãi bỏ",
               "sửa đổi, bổ sung", "sửa đổi bổ sung", "chuyển tiếp", "Hà Nội",
               "Phạm vi áp dụng", "Điều khoản thi hành", "Số hiệu", "tuyển sinh")
    for phrase in phrases:
        pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, phrase.split())) + r"(?!\w)"
        for match in reversed(list(re.finditer(pattern, text, re.I))):
            positions = []
            replacement = []
            for part in re.finditer(r"\S+|\s+", match[0]):
                start = match.start() + part.start()
                if part[0].isspace():
                    replacement.append(" ")
                    positions.append(offsets[start])
                else:
                    replacement.append(part[0])
                    positions.extend(offsets[start:start + len(part[0])])
            text = text[:match.start()] + "".join(replacement) + text[match.end():]
            offsets[match.start():match.end()] = positions
    # Identifier spacing is structural, including TT -BGDĐT.
    pattern = r"\b\d{1,3}\s*/\s*\d{4}\s*/\s*[A-ZĐ]+(?:\s*-\s*[A-ZĐ0-9]+)+"
    for match in reversed(list(re.finditer(pattern, text))):
        chars = [i for i in range(match.start(), match.end()) if not text[i].isspace()]
        replacement = "".join(text[i] for i in chars)
        text = text[:match.start()] + replacement + text[match.end():]
        offsets[match.start():match.end()] = [offsets[i] for i in chars]
    text = text.replace("TT-BGDDT", "TT-BGDĐT")
    def original(quote):
        start = text.find(quote)
        return raw[offsets[start]:offsets[start + len(quote) - 1] + 1] if quote and start >= 0 else quote
    return text, original


def _date(text: str) -> str | None:
    match = re.search(DATE, text, re.I)
    if match:
        try:
            return date(int(match[3]), int(match[2]), int(match[1])).isoformat()
        except ValueError:
            pass
    return None


def propose_version(text: str, source_name: str) -> dict:
    """Propose ISO dates and labels from explicit text, with per-field quotes.

    `status` is a proposed label only. Persistence keeps status unverified until
    human confirmation, retaining this proposed label in evidence.
    """
    result = dict.fromkeys(("family_key", "doc_number", "version_label", "issued_on",
                           "effective_from", "effective_to", "applies_from",
                           "applies_note", "transition_note"))
    result.update(status="unverified", relations=[], evidence={})
    evidence = result["evidence"]
    text, original = _label_view(text)
    def put(field, value, quote):
        if value is not None:
            result[field] = original(value) if field.endswith("_note") else value
            evidence[field] = original(quote).strip()

    # Canonicalize identifiers only; extraction never repairs prose implicitly.
    lines = text.splitlines()
    header = "\n".join(lines[:45])
    for line in lines[:45]:
        match = re.match(r"\s*Số(?: hiệu)?\s*:\s*(\S+)", line, re.I)
        if match:
            number = match[1].rstrip(".,;")
            if re.fullmatch(DOC, number) or re.fullmatch(r"[A-Z]+(?:-[A-Z0-9]+)+", number):
                put("doc_number", number, line)
                break
    if not result["doc_number"]:
        match = re.search(r"(?:TT)?(\d{2})[_/-](\d{4})[_/-](?:TT[-_])?BGD[ĐD]T", source_name, re.I)
        if match:
            put("doc_number", f"{match[1]}/{match[2]}/TT-BGDĐT", "từ tên tệp: " + source_name)
    put("family_key", result["doc_number"], evidence.get("doc_number", ""))
    for line in lines[:45]:
        match = re.match(r"\s*Phiên bản:\s*(\S+)", line, re.I)
        if match:
            put("version_label", match[1], line)
        if re.search(r"Ngày (?:ban hành|dự thảo):|Hà Nội,\s*ngày", line, re.I):
            put("issued_on", _date(line), line)
        if re.match(r"\s*Hiệu lực (?:từ|dự kiến):", line, re.I):
            put("effective_from", _date(line), line)
        if re.match(r"\s*Tình trạng:", line, re.I):
            label = "draft" if re.search(r"dự thảo", line, re.I) else (
                "superseded" if re.search(r"đã (?:bị )?thay thế|hết hiệu lực", line, re.I) else "issued")
            put("status", label, line)

    if not result["issued_on"] and result["doc_number"]:
        # An annex can supply the missing issue date, but only for this document.
        annex = re.search(r"\(Kèm theo Thông tư số\s+" + re.escape(result["doc_number"])
                          + r"\s+(" + DATE + r")", text, re.I)
        if annex:
            put("issued_on", _date(annex[1]), annex[0])

    articles = list(re.finditer(r"^\s*Điều\s+(\d+)\s*\.\s*", text, re.M))
    effective = []
    for i, match in enumerate(articles):
        end = articles[i + 1].start() if i + 1 < len(articles) else len(text)
        block = text[match.start():end].strip()
        # Stop at annexes/signatures so they cannot become evidence.
        block = re.split(r"\n(?:PHỤ LỤC|Nơi nhận:|KT\. BỘ TRƯỞNG)", block)[0]
        first = block.splitlines()[0]
        is_effective = bool(re.search(r"^(?:Điều\s+\d+\.\s*)(?:Hiệu lực|Điều khoản thi hành|Thông tư này có hiệu lực)", first, re.I))
        if is_effective:
            effective.append(("Điều " + match[1], block))
            found = re.search(r"có hiệu lực(?:\s+thi hành)?\s+(?:kể\s+)?từ\s+(" + DATE + r")", block, re.I)
            if found and not result["effective_from"]:
                put("effective_from", _date(found[1]), block)
            # A quoted amendment belongs to the older instrument, even when
            # its text says "Thông tư này". Restrict scope to own clauses.
            own_clauses = []
            for paragraph in re.split(r"\n\s*\d+\.\s+", block):
                if not re.search(r"sửa đổi|bổ sung|như sau|[“\"]", paragraph, re.I):
                    own_clauses.append(paragraph)
            own = "\n".join(own_clauses)
            scope = re.search(r"Thông tư này[^.]*?(áp dụng đối với[^.]+)", own, re.I)
            if scope:
                put("applies_note", scope[1], scope[0])
                put("applies_from", _date(scope[1]), scope[0])
            cohort = re.search(r"[^\n.]*có hiệu lực(?:\s+thi hành)?\s+cho\s+kh[oó][aá]\s+tuyển sinh\s+từ\s+năm\s+\d{4}[^\n.]*", own, re.I)
            if cohort and not result["applies_note"]:
                put("applies_note", cohort[0], cohort[0])
        if "chuyển tiếp" in first.lower():
            if is_effective:
                transition = re.search(r"(?:^|\n)2\.\s+.*?(?=\n3\.|$)", block, re.S)
                quote = transition[0].strip() if transition else None
            else:
                quote = block
            if quote:
                put("transition_note", quote, quote)

    def relation(kind, target, clause, quote, version=None):
        item = {"type": kind, "target_doc_number": target, "clause_ref": clause, "quote": original(quote).strip()}
        if version:
            item["target_version_label"] = version
        if not any(r["type"] == kind and r["target_doc_number"] == target for r in result["relations"]):
            result["relations"].append(item)

    for clause, block in effective:
        # Only the operative replacement sentence, never the preamble or transition.
        for sentence in re.split(r"(?<=[.])\s+|\n(?=\d+\.)", block):
            found = re.search(r"thay thế\s+", sentence, re.I)
            if found:
                for target in re.findall(DOC, sentence[found.end():]):
                    relation("replaces", target, clause, sentence)
            found = re.search(r"bãi bỏ\s+(?:một phần\s+|(?=(?:khoản|điểm|Điều)\s))", sentence, re.I)
            if found:
                for target in re.findall(DOC, sentence[found.end():]):
                    relation("partially_repeals", target, clause, sentence)
            # Explicit cessation of older instruments when this one takes effect.
            cessation = re.search(r"hết hiệu lực(?:\s+thi hành)?\s+(?:kể\s+)?từ\s+ngày\s+Thông tư này có hiệu lực", sentence, re.I)
            if cessation:
                for target in re.findall(DOC, sentence[:cessation.start()]):
                    relation("replaces", target, clause, sentence)
        for amendment in re.finditer(r"(?:^|\n)\s*\d+\.\s*Sửa đổi,?\s+bổ sung.*?(?=\n\s*\d+\.|[“\"]|$)", block, re.I | re.S):
            for target in re.findall(DOC, amendment[0]):
                relation("amends", target, clause, amendment[0])
    for line in lines[:45]:
        if re.match(r"\s*Thay thế:", line, re.I):
            target = re.search(r"\(([A-Z]+(?:-[A-Z0-9]+)+),", line)
            version = re.search(r"phiên bản\s+([\d.]+)", line, re.I)
            if target:
                relation("replaces", target[1], "Thay thế", line, version[1] if version else None)
    # Amending instrument: its title/operative article, excluding citations in Căn cứ.
    title = re.split(r"Căn cứ", header, flags=re.I)[0]
    for match in re.finditer(r"sửa đổi,?\s+bổ sung[^.]*?(?:Thông tư|thông tư)\s+số\s+(" + DOC + r")", title, re.I):
        relation("amends", match[1], "Tiêu đề", match[0])
    for clause, block in [("Điều " + m[1], text[m.start():articles[i+1].start() if i+1 < len(articles) else len(text)]) for i,m in enumerate(articles)]:
        first = block.splitlines()[0].strip()
        if re.match(r"Điều\s+\d+\.\s*Sửa đổi", first, re.I):
            for target in re.findall(DOC, first):
                relation("amends", target, clause, first)
    scope = re.search(r"^\s*Điều\s+\d+\.\s*Phạm vi áp dụng\s*\n([^\n]+)", text, re.M | re.I)
    if scope and re.search(r"Thông tư này.*áp dụng", scope[1], re.I) and not result["applies_note"]:
        put("applies_note", scope[1], scope[0])
    if result["status"] == "unverified" and result["doc_number"] and result["issued_on"]:
        put("status", "issued", evidence["issued_on"] + "\n" + evidence["doc_number"])
    if result["relations"]:
        evidence["relations"] = [r["quote"] for r in result["relations"]]
    return result
