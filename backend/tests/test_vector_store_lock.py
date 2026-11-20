"""Hai luồng gọi _configured_vector_store cùng lúc chỉ tạo một kho vector (Qdrant nhúng cấm hai client)."""
import threading


def test_vector_store_created_once_under_concurrency(monkeypatch, tmp_path):
    import importlib, sys
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")   # nhập app.main không cần PostgreSQL
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    sys.modules.pop("app.main", None)
    m = importlib.import_module("app.main")

    made = []

    def slow_create(backend):
        import time
        time.sleep(0.05)
        made.append(backend)
        m._derived_vector_store, m._derived_vector_store_backend = object(), backend
        return m._derived_vector_store

    monkeypatch.setattr(m, "VECTOR_BACKEND", "memory")
    monkeypatch.setattr(m, "_derived_vector_store", None)
    monkeypatch.setattr(m, "_create_vector_store", slow_create)
    out = []
    threads = [threading.Thread(target=lambda: out.append(m._configured_vector_store())) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert made == ["memory"] and len({id(x) for x in out}) == 1
    sys.modules.pop("app.main", None)  # tránh để lại bản nhập với cấu hình thử cho kiểm thử khác
