"""Deterministic scorer for benchmark v1; standard library only."""
import argparse
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

def canonical(value, unit):
    raw = str(value).replace(",", ".").strip().lower()
    try: number = float(raw)
    except ValueError: return ("text", re.sub(r"\s+", " ", raw))
    unit = unit.lower().strip()
    factor = {"giờ":3600,"hour":3600,"hours":3600,"h":3600,"phút":60,"minute":60,"minutes":60,"min":60,"ngày":86400,"day":86400,"days":86400,"năm":31536000,"year":31536000,"years":31536000,"giây":1,"second":1,"seconds":1}.get(unit)
    return ("number", number * factor if factor else (number, unit))

NUM_RE = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)(?:\s*([^\W\d_][\w/.-]*))?", re.I)

def quantities(text):
    found = set()
    for m in NUM_RE.finditer(text):
        found.add(canonical(m.group(1), m.group(2) or ""))
    return found

def answer_correct(q, answer, status):
    if q["expected_status"] == "NO_EVIDENCE":
        return status == "NO_EVIDENCE" and not quantities(answer)
    if status == "NO_EVIDENCE": return False
    low = answer.casefold()
    if any(bad.casefold() in low for bad in q.get("must_not_contain", [])): return False
    available = quantities(answer)
    for fact in q["expected_facts"]:
        expected = canonical(fact["value"], fact["unit"])
        if expected[0] == "number":
            if isinstance(expected[1], tuple):
                numeric = re.escape(str(fact["value"]).replace(",", "."))
                if not re.search(r"(?<!\w)" + numeric + r"(?!\w)", low): return False
                if fact["unit"] and fact["unit"].casefold() not in low: return False
            elif expected not in available: return False
        elif expected[1] not in low: return False
    return True

def answer_metrics(answers, questions):
    byid = {a["qid"]: a for a in answers}
    stats = {"answerable_correct":0,"answerable_total":0,"no_answer_correct":0,"no_answer_total":0,"hallucinations":0,"trap_wrong_attribute":0,"languages":{}}
    for q in questions:
        a = byid.get(q["qid"], {"answer":"","status":"NO_EVIDENCE"})
        good = answer_correct(q, a.get("answer", ""), a.get("status", ""))
        lang = stats["languages"].setdefault(q.get("language", "unknown"), {"correct":0,"total":0})
        lang["total"] += 1; lang["correct"] += bool(good)
        if q["expected_status"] == "NO_EVIDENCE":
            stats["no_answer_total"] += 1; stats["no_answer_correct"] += bool(good)
            if a.get("status") != "NO_EVIDENCE" or quantities(a.get("answer", "")): stats["hallucinations"] += 1
        else:
            stats["answerable_total"] += 1; stats["answerable_correct"] += bool(good)
            if q.get("trap") and any(f["attribute"].casefold() not in a.get("answer", "").casefold() for f in q["expected_facts"]):
                stats["trap_wrong_attribute"] += 1
    return stats

def mcnemar_exact(b, c):
    n = b + c
    if n == 0: return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b,c)+1)) / (2**n)
    return min(1.0, 2 * tail)

def wilson(success, total, z=1.959963984540054):
    if not total: return (0.0, 1.0)
    p=success/total; den=1+z*z/total
    mid=(p+z*z/(2*total))/den
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return (mid-half, mid+half)

def _doc_text(name, truth):
    if name in truth.get("document_texts", {}): return truth["document_texts"][name]
    p=Path(name)
    if not p.is_absolute(): p=ROOT/name
    try: return p.read_text(encoding="utf-8")
    except (OSError, UnicodeError): return str(name)

def contradiction_metrics(candidates, truth):
    expected = {"contradiction":{},"duplicate":{},"decoy":{}}
    for kind, items in (("contradiction",truth["contradictions"]),("duplicate",truth["duplicates"]),("decoy",truth["decoys"])):
        for item in items:
            if kind == "duplicate": a=b=item["fact_id"]
            else: a,b=item["fact_a"],item["fact_b"]
            expected[kind][frozenset((a,b))]=item
    result={kind:{"tp":0,"fp":0,"fn":len(items)} for kind,items in expected.items() if kind != "decoy"}
    result.update({"decoy_hits":0,"invalid_quotes":0,"candidate_count":len(candidates)})
    for cand in candidates:
        ta,tb=_doc_text(cand.get("doc_a",""),truth),_doc_text(cand.get("doc_b",""),truth)
        qa,qb=cand.get("quote_a",""),cand.get("quote_b","")
        valid=bool(qa and qb and qa in ta and qb in tb)
        if not valid: result["invalid_quotes"]+=1
        ids_a=[fid for fid,f in truth["facts"].items() if f["sentence"] in qa]
        ids_b=[fid for fid,f in truth["facts"].items() if f["sentence"] in qb]
        matched=False
        for a in ids_a:
            for b in ids_b:
                pair=frozenset((a,b))
                if pair in expected["decoy"]: result["decoy_hits"]+=1
                kind=cand.get("kind")
                if valid and kind in result and pair in expected[kind]:
                    result[kind]["tp"]+=1; result[kind]["fn"]-=1; matched=True; break
            if matched: break
        if cand.get("kind") in result and not matched: result[cand["kind"]]["fp"]+=1
    for kind in ("contradiction","duplicate"):
        v=result[kind]; v["precision"] = v["tp"]/(v["tp"]+v["fp"]) if v["tp"]+v["fp"] else 0.0
        total=v["tp"]+v["fn"]; v["recall"]=v["tp"]/total if total else 0.0
    return result

def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

def oracle_answers(questions):
    out=[]
    for q in questions:
        if q["expected_status"] == "NO_EVIDENCE": out.append({"qid":q["qid"],"answer":"Không có bằng chứng.","status":"NO_EVIDENCE"}); continue
        parts=[]
        for f in q["expected_facts"]:
            unit=f["unit"]
            shown=f["value"]
            if f["fact_id"]=="bak01": shown,unit="1","ngày"
            if f["fact_id"]=="onb05": shown,unit="30","phút"
            if f["fact_id"]=="bil07": shown,unit="365","ngày"
            parts.append(f"{f['attribute']}: {shown} {unit}" if unit else f"{f['attribute']}: {shown}")
        out.append({"qid":q["qid"],"answer":"; ".join(parts),"status":"ANSWERABLE"})
    return out

def oracle_pairs(truth):
    output=[]
    for kind,key in (("contradiction","contradictions"),("duplicate","duplicates")):
        for item in truth[key]:
            a=item.get("fact_a",item.get("fact_id")); b=item.get("fact_b",a)
            fa,fb=truth["facts"][a],truth["facts"][b]
            output.append({"quote_a":fa["sentence"],"quote_b":fb["sentence"],"doc_a":item["doc_a"],"doc_b":item["doc_b"],"kind":kind})
    return output

def self_test():
    questions=json.loads((DATA/"questions.json").read_text(encoding="utf-8"))
    truth=json.loads((DATA/"n30"/"truth.json").read_text(encoding="utf-8"))
    oracle=answer_metrics(oracle_answers(questions),questions)
    bad=answer_metrics([{"qid":q["qid"],"answer":"không rõ","status":"NO_EVIDENCE" if q["expected_status"]=="NO_EVIDENCE" else "ANSWERABLE"} for q in questions],questions)
    pairs=contradiction_metrics(oracle_pairs(truth),truth)
    passed=(oracle["answerable_correct"]==oracle["answerable_total"] and oracle["hallucinations"]==0 and pairs["contradiction"]["precision"]==pairs["contradiction"]["recall"]==1.0 and pairs["duplicate"]["precision"]==pairs["duplicate"]["recall"]==1.0 and bad["answerable_correct"]==0 and bad["no_answer_correct"]==bad["no_answer_total"])
    print(f"oracle answers: {oracle['answerable_correct']}/{oracle['answerable_total']} answerable; {oracle['no_answer_correct']}/{oracle['no_answer_total']} no-answer; hallucinations={oracle['hallucinations']}")
    print(f"oracle pairs: contradiction P={pairs['contradiction']['tp']}/{pairs['contradiction']['tp']+pairs['contradiction']['fp']} R={pairs['contradiction']['tp']}/{pairs['contradiction']['tp']+pairs['contradiction']['fn']}; duplicate P={pairs['duplicate']['tp']}/{pairs['duplicate']['tp']+pairs['duplicate']['fp']} R={pairs['duplicate']['tp']}/{pairs['duplicate']['tp']+pairs['duplicate']['fn']}")
    print(f"deliberately bad: {bad['answerable_correct']}/{bad['answerable_total']} answerable; {bad['no_answer_correct']}/{bad['no_answer_total']} no-answer; hallucinations={bad['hallucinations']}")
    print("SELF-TEST PASS" if passed else "SELF-TEST FAIL")
    return passed

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--self-test",action="store_true"); ap.add_argument("--corpus",default="n30"); ap.add_argument("--answers"); ap.add_argument("--pairs"); ap.add_argument("--compare",nargs=2,metavar=("A","B")); args=ap.parse_args()
    if args.self_test: raise SystemExit(0 if self_test() else 1)
    questions=json.loads((DATA/"questions.json").read_text(encoding="utf-8")); truth=json.loads((DATA/args.corpus/"truth.json").read_text(encoding="utf-8"))
    if args.answers:
        stats=answer_metrics(load_jsonl(args.answers),questions)
        print(f"RAW COUNTS answerable={stats['answerable_correct']}/{stats['answerable_total']} no-answer={stats['no_answer_correct']}/{stats['no_answer_total']} hallucinations={stats['hallucinations']} wrong-attribute={stats['trap_wrong_attribute']}")
        print("languages="+json.dumps(stats["languages"],ensure_ascii=False,sort_keys=True))
    if args.pairs:
        stats=contradiction_metrics(json.loads(Path(args.pairs).read_text(encoding="utf-8")),truth)
        print("RAW COUNTS contradictions="+json.dumps(stats,ensure_ascii=False,sort_keys=True))
    if args.compare:
        qa={q["qid"]:q for q in questions}; aa={a["qid"]:a for a in load_jsonl(args.compare[0])}; bb={a["qid"]:a for a in load_jsonl(args.compare[1])}
        common=sorted(qa.keys() & aa.keys() & bb.keys()); ac=bc=win_a=win_b=0
        for qid in common:
            x=answer_correct(qa[qid],aa[qid].get("answer",""),aa[qid].get("status","")); y=answer_correct(qa[qid],bb[qid].get("answer",""),bb[qid].get("status","")); ac+=x; bc+=y; win_a+=x and not y; win_b+=y and not x
        p=mcnemar_exact(win_a,win_b); print(f"RAW COUNTS paired A={ac}/{len(common)} B={bc}/{len(common)} b={win_a} c={win_b}; McNemar exact p={p:.6f}; A Wilson95={wilson(ac,len(common))}; B Wilson95={wilson(bc,len(common))}")
        if p>=.05: print("no significant difference")
        else: print("significant difference")
if __name__=="__main__": main()
