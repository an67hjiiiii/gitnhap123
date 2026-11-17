"""Deterministic normalization and the product-only feature boundary."""
import ast
import asyncio
from pathlib import Path
import tomllib

import pytest

from app.research.query_normalize import normalize_query
from app.research import pipeline as pipeline_module


@pytest.mark.parametrize("query,expected", [
    ("", ""), ("  mật   khẩu\n", "mật khẩu"), ("MẬT KHẨU", "mật khẩu"),
    ("ma\u0323\u0302t khẩu", "mật khẩu"),
    ("mat khau", "mật khẩu"), ("dang nhap", "đăng nhập"),
    ("nhat ky", "nhật ký"), ("thong tu", "thông tư"),
    ("hieu luc", "hiệu lực"), ("tuyen sinh", "tuyển sinh"),
    ("TT", "thông tư"), ("NĐ", "nghị định"), ("QĐ", "quyết định"),
    ("BGDĐT", "bộ giáo dục và đào tạo"), ("GV", "giáo viên"),
    ("SV", "sinh viên"), ("ĐH", "đại học"), ("SĐH", "sau đại học"),
    ("mk", "mật khẩu"), ("một", "1"), ("mười", "10"),
    ("mười lăm phút", "15 phút"), ("hai mươi giờ", "20 giờ"),
    ("một trăm ngày", "100 ngày"), ("nửa giờ", "0,5 giờ"),
    ("nua gio", "0,5 giờ"), ("nửa ngày", "nửa ngày"),
    ("06/2026/TT-BGDĐT", "06/2026/TT-BGDĐT"),
    ("TT 06/2026/TT-BGDĐT", "thông tư 06/2026/TT-BGDĐT"),
    ("mật khẩu", "mật khẩu"), ("không đăng nhập", "không đăng nhập"),
    ("năm học", "năm học"), ("5 năm", "5 năm"),
    ("15 mins", "15 phút"), ("2 hours", "2 giờ"),
    ("50 percent", "50 %"), ("2 kilobytes", "2 kb"),
    ("amk mat khaud", "amk mat khaud"),
    ("hết hạn", "hết hạn (quá hạn)"),
    ("hết hiệu lực", "hết hiệu lực (không còn hiệu lực)"),
])
def test_normalization(query, expected):
    result, changes = normalize_query(query)
    assert result == expected
    assert isinstance(changes, list)
    assert normalize_query(result) == (result, [])
    if query == expected:
        assert changes == []


@pytest.mark.parametrize("word,value", zip("một hai ba bốn năm sáu bảy tám chín mười".split(), range(1, 11)))
def test_small_numbers(word, value):
    assert normalize_query(word)[0] == str(value)


def test_low_ascii_ratio_does_not_guess():
    query = "tôi muốn biết về mật khẩu và tài khoản mat khau"
    assert normalize_query(query) == (query, [])


def test_changes_are_ordered():
    assert normalize_query("  MAT KHAU  ")[1] == ["whitespace", "case", "diacritics"]


@pytest.mark.parametrize("flag,product,expected", [
    (None, True, "MAT KHAU"), ("off", True, "MAT KHAU"),
    ("on", True, "mật khẩu"), ("on", False, "MAT KHAU"),
])
def test_pipeline_boundary(monkeypatch, sf1_pipeline_factory, sf1_fake_provider_env, flag, product, expected):
    if flag is None:
        monkeypatch.delenv("QUERY_NORMALIZE", raising=False)
    else:
        monkeypatch.setenv("QUERY_NORMALIZE", flag)
    monkeypatch.setenv("RETRIEVAL_RETRY", "0")
    instance = sf1_pipeline_factory()
    seen = []
    intent = []
    model = []
    original_help = pipeline_module.product_help_response
    monkeypatch.setattr(pipeline_module, "product_help_response", lambda q: (intent.append(q), original_help(q))[1])
    monkeypatch.setattr(instance, "_retrieve_candidates", lambda q, *a, **kw: (seen.append(q), [])[1])
    original_answer = pipeline_module.answer_vanilla
    async def answer(provider, query, *args, **kwargs):
        model.append(query)
        return await original_answer(provider, query, *args, **kwargs)
    monkeypatch.setattr(pipeline_module, "answer_vanilla", answer)
    result = asyncio.run(instance.run("MAT KHAU", "A", product_mode=product))
    assert result["status"] != "FAILED"
    assert seen == [expected]
    if product:
        assert intent == [expected]
    assert model == ["MAT KHAU"]


def test_import_contracts_ast():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    graph = {}
    for path in (root / "app").rglob("*.py"):
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        imports = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                imports.update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imports.add(node.module)
        graph[module] = imports
    for start in ("app.research.query_normalize", "app.research.pipeline"):
        for contract in contracts:
            if not any(start == s or start.startswith(s + ".") for s in contract["source_modules"]):
                continue
            pending, visited = [start], set()
            while pending:
                module = pending.pop()
                if module in visited:
                    continue
                visited.add(module)
                assert not any(module == f or module.startswith(f + ".") for f in contract["forbidden_modules"]), (start, module)
                pending.extend(graph.get(module, ()))
