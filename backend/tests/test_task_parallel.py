"""Đợt 7 kế hoạch Văn phòng 3D: chia việc con thành đợt theo phụ thuộc; mặc định vẫn lần lượt."""
import inspect

from app.core.types import Task
from app.research.pipeline import ResearchPipeline, dependency_waves, task_parallel_limit


def task(tid, deps=()):
    return Task(task_id=tid, domain="general", goal=tid, depends_on=list(deps), evidence_needs=[])


def test_independent_tasks_share_a_wave_and_dependents_wait():
    waves = dependency_waves([task("T1"), task("T2"), task("T3", ["T1"]), task("T4", ["T3", "T2"])])
    assert [[t.task_id for t in w] for w in waves] == [["T1", "T2"], ["T3"], ["T4"]]


def test_unknown_dependency_does_not_block():
    assert [[t.task_id for t in w] for w in dependency_waves([task("T1", ["X9"])])] == [["T1"]]


def test_limit_defaults_to_sequential_and_is_capped(monkeypatch):
    monkeypatch.delenv("PRODUCT_TASK_PARALLEL", raising=False)
    assert task_parallel_limit() == 1
    monkeypatch.setenv("PRODUCT_TASK_PARALLEL", "3")
    assert task_parallel_limit() == 3
    monkeypatch.setenv("PRODUCT_TASK_PARALLEL", "99")
    assert task_parallel_limit() == 4
    monkeypatch.setenv("PRODUCT_TASK_PARALLEL", "abc")
    assert task_parallel_limit() == 1


def test_experiments_never_run_in_parallel():
    """Thực nghiệm A/B/C (product_mode=False) luôn lần lượt, không đọc biến song song."""
    src = inspect.getsource(ResearchPipeline._run)
    assert "parallel = task_parallel_limit() if product_mode else 1" in src
