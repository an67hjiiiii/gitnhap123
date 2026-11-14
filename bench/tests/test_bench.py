import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import generate
import score

def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}

def test_generation_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate.build(a); generate.freeze(a)
    generate.build(b); generate.freeze(b)
    assert hashes(a) == hashes(b)

def test_counts_and_freeze():
    data = ROOT / "data"
    questions = json.loads((data / "questions.json").read_text(encoding="utf-8"))
    assert len(questions) >= 40
    assert sum(q["expected_status"] == "NO_EVIDENCE" for q in questions) >= 8
    assert sum(q["language"] == "en" for q in questions) >= 6
    assert sum(q.get("trap", False) for q in questions) >= 6
    truth_by_size = {size: json.loads((data / size / "truth.json").read_text(encoding="utf-8"))
                     for size in ("n5", "n30", "n100")}
    assert [len(list((data / size / "docs").glob("*.md"))) for size in ("n5", "n30", "n100")] == [5, 30, 100]
    assert [len(t["contradictions"]) for t in truth_by_size.values()] == [3, 10, 25]
    for truth in truth_by_size.values():
        candidate_count = len(truth["contradictions"]) + len(truth["duplicates"]) + len(truth["decoys"])
        assert len(truth["decoys"]) / candidate_count >= 0.30
    freeze = json.loads((data / "FREEZE.json").read_text(encoding="utf-8"))
    actual = {k: v for k, v in hashes(data).items() if k != "FREEZE.json"}
    assert actual == freeze["files"]

def test_normalisation_equivalences():
    equivalents = [
        (("24", "giờ"), ("1", "ngày")),
        (("0.5", "giờ"), ("30", "phút")),
        (("1", "năm"), ("365", "ngày")),
    ]
    for a, b in equivalents:
        assert score.canonical(*a) == score.canonical(*b)

def test_self_test_passes(capsys):
    assert score.self_test()
    assert "SELF-TEST PASS" in capsys.readouterr().out

def test_mcnemar_known_tables():
    assert score.mcnemar_exact(5, 0) == 0.0625
    assert score.mcnemar_exact(7, 1) == 0.0703125
