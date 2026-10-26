from cinema_core.api import Core, API_VERSION

def test_job_flow(tmp_path):
    core = Core(tmp_path)
    j = core.submit_job("render", {"x": 1})
    core.start_job(j["id"])
    core.report_progress(j["id"], 50)
    assert core.get_job(j["id"])["progress"] == 50
    core.finish_job(j["id"])
    assert core.get_job(j["id"])["state"] == "completed"
    assert [x["id"] for x in core.list_jobs()] == [j["id"]]

def test_cancel_visible_to_runner(tmp_path):
    core = Core(tmp_path)
    j = core.submit_job("render")
    core.start_job(j["id"])
    core.cancel_job(j["id"])
    assert core.is_cancelled(j["id"])

def test_status_and_diagnostics(tmp_path):
    core = Core(tmp_path)
    assert core.status()["running"] is False
    assert all({"name", "ok", "detail"} <= set(d) for d in core.diagnostics())
    assert API_VERSION == 1
