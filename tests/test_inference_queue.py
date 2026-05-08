from __future__ import annotations

from pathlib import Path

from AGENT_Joko.inference_queue import InferenceQueue


def test_inference_queue_add_list_cancel_persist(tmp_path: Path) -> None:
    store = tmp_path / "q.json"
    q = InferenceQueue(storage_path=str(store))

    it = q.add_chat(messages=[{"role": "user", "content": "hi"}], model="m1", fallback_models=["m2"])
    assert it.id
    assert it.status == "queued"

    items = q.list(limit=10)
    assert any(x.id == it.id for x in items)

    q.cancel(it.id)
    it2 = q.get(it.id)
    assert it2.status == "cancelled"

    q2 = InferenceQueue(storage_path=str(store))
    it3 = q2.get(it.id)
    assert it3.status == "cancelled"

