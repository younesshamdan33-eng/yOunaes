# CINEMA CORE integration (API v1)

    from cinema_core.api import Core, JobError
    core = Core()                      # uses cinema.json in the project root
    job = core.submit_job("render", {"script": "..."})
    core.start_job(job["id"])          # runner: queued -> running
    core.report_progress(job["id"], 40)
    if core.is_cancelled(job["id"]): ...   # runner must poll; cancel only records state
    core.finish_job(job["id"])         # or core.fail_job(id, "reason")

Rules
- Import only `cinema_core.api`; internals may change.
- Jobs are local files under var/jobs/<id>/ (job.json, job.log, output/).
- Cancelling a running job does NOT kill anything: the runner must stop itself.
- A job does not survive a phone/Termux restart: `cinema jobs --recover` marks it failed.
- Validate every input file/param in the app before submit_job; the core never runs user commands.
- The HTTP server exposes only /health and /ready, bound to 127.0.0.1.
CLI: `cinema status --json`, `cinema jobs --json`.
