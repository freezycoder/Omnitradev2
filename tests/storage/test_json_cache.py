from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from storage.cache.json_cache import load_json, save_json


def test_concurrent_writes_to_same_cache_file_remain_atomic(tmp_path):
    path = tmp_path / "ticker.json"
    worker_count = 8
    barrier = Barrier(worker_count)

    def write(index: int) -> None:
        barrier.wait()
        save_json(path, {"writer": index, "values": list(range(100))})

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(write, index)
            for index in range(worker_count)
        ]
        for future in futures:
            future.result()

    payload = load_json(path, {})

    assert payload["writer"] in range(worker_count)
    assert payload["values"] == list(range(100))
    assert list(tmp_path.glob("*.tmp")) == []
