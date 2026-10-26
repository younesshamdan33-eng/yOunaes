import json
import pytest
from cinema_core import config, jobs

@pytest.fixture
def store(tmp_path):
    return jobs.JobStore(config.load(tmp_path))

def test_create_and_lifecycle(store):
    j = store.create("render")
    assert j["state"] == "queued" and (store.dir / j["id"] / "output").is_dir()
    store.transition(j["id"], "running")
    store.set_progress(j["id"], 40)
    done = store.transition(j["id"], "completed")
    assert done["progress"] == 100 and done["finished"]

def test_invalid_transition_and_progress(store):
    j = store.create("render")
    with pytest.raises(jobs.JobError):
        store.transition(j["id"], "completed")
    with pytest.raises(jobs.JobError):
        store.set_progress(j["id"], 10)
    store.cancel(j["id"])
    with pytest.raises(jobs.JobError):
        store.transition(j["id"], "running")

def test_storage_admission(tmp_path):
    (tmp_path / "cinema.json").write_text(json.dumps({"min_free_mb": 10**9}))
    with pytest.raises(jobs.JobError):
        jobs.JobStore(config.load(tmp_path)).create("render")

def test_concurrency_limit(store):
    a, b = store.create("render"), store.create("render")
    store.transition(a["id"], "running")
    with pytest.raises(jobs.JobError):
        store.transition(b["id"], "running")

def test_bad_id_and_kind(store):
    for bad in ("../x", "abc", "", None):
        with pytest.raises(jobs.JobError):
            store.get(bad)
    with pytest.raises(jobs.JobError):
        store.create("rm -rf /")

def test_recover_interrupted(store):
    j = store.create("render")
    store.transition(j["id"], "running")
    job = store.get(j["id"]); job["pid"] = 999999; store._write(job)
    assert store.recover() == 1
    assert store.get(j["id"])["state"] == "failed"

def test_recover_keeps_live_runner(store):
    j = store.create("render")
    store.transition(j["id"], "running")
    assert store.recover() == 0

def test_list_flags_corrupt(store):
    j = store.create("render")
    (store.dir / j["id"] / "job.json").write_text("{bad")
    assert store.list()[0]["state"] == "corrupt"
