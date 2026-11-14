from app.chat.progress import friendly_error, stage_label


def test_progress_mapping_and_friendly_errors():
    assert stage_label({"stage": "request_understanding"}) == {
        "step": "understanding", "text": "\u0110ang \u0111\u1ecdc v\u00e0 hi\u1ec3u c\u00e2u h\u1ecfi c\u1ee7a b\u1ea1n\u2026"
    }
    assert stage_label({"stage": "decomposition", "tasks": [
        {"task_id": "T1", "goal": "Gi\u1eef v\u00e9 30 ng\u00e0y"},
        {"task_id": "T2", "goal": "G\u1eedi email"},
    ]})["text"] == "\u0110\u00e3 chia th\u00e0nh 2 b\u01b0\u1edbc: Gi\u1eef v\u00e9 30 ng\u00e0y; G\u1eedi email"
    assert stage_label({"stage": "task_retrieval", "task_id": "T2"})["text"] == "\u0110ang t\u00ecm trong t\u00e0i li\u1ec7u cho b\u01b0\u1edbc T2\u2026"
    assert stage_label({"stage": "task_completed", "result": {"task_id": "T2"}})["text"] == "Xong b\u01b0\u1edbc T2."
    assert stage_label({"stage": "internal_noise"}) is None
    assert friendly_error("PLAN_REJECTED") == {
        "code": "PLAN_REJECTED",
        "message": "M\u00ecnh ch\u01b0a chia nh\u1ecf \u0111\u01b0\u1ee3c y\u00eau c\u1ea7u n\u00e0y th\u00e0nh c\u00e1c b\u01b0\u1edbc ph\u00f9 h\u1ee3p.",
        "hint": "B\u1ea1n th\u1eed t\u00e1ch th\u00e0nh t\u1eebng c\u00e2u ng\u1eafn h\u01a1n r\u1ed3i g\u1eedi l\u1ea1i nh\u00e9.",
    }
    assert friendly_error("PROVIDER_LIMIT")["message"] == "M\u00f4 h\u00ecnh \u0111ang b\u1eadn ho\u1eb7c ph\u1ea3n h\u1ed3i qu\u00e1 ch\u1eadm."
    assert friendly_error("PROVIDER_LIMIT")["hint"] == "\u0110\u1ee3i m\u1ed9t ch\u00fat r\u1ed3i th\u1eed l\u1ea1i nh\u00e9."
    assert friendly_error("RATE_LIMITED")["message"] == "B\u1ea1n g\u1eedi h\u01a1i nhanh, m\u00ecnh c\u1ea7n ch\u1eadm l\u1ea1i m\u1ed9t ch\u00fat."
    assert friendly_error("RATE_LIMITED")["hint"] == "Th\u1eed l\u1ea1i sau v\u00e0i gi\u00e2y."
    assert friendly_error("nonsense")["code"] == "UNKNOWN"


def test_pipeline_event_callback_receives_all_events_and_isolated(sf1_fake_provider_env, sf1_pipeline_factory):
    import asyncio

    pipeline = sf1_pipeline_factory()
    seen = []
    result = asyncio.run(pipeline.run("What is in the policy?", on_event=seen.append))
    assert seen == result["events"]

    def raising_callback(_event):
        raise RuntimeError("callback failure")

    again = asyncio.run(pipeline.run("What is in the policy?", on_event=raising_callback))
    assert again["status"] != "FAILED"
