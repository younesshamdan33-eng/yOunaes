"""Persistent job queue with checkpoint/resume. SQLite-backed."""
import json, sqlite3, time, uuid
from pathlib import Path

class JobQueue:
    def __init__(self, db_path="var/queue.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, film_id TEXT, shot_id TEXT,
            state TEXT, payload TEXT, result TEXT, error TEXT,
            created REAL, updated REAL)""")
        self.db.commit()

    def enqueue(self, film_id, shot_id, payload):
        jid = uuid.uuid4().hex[:16]; now = time.time()
        self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                        (jid,film_id,shot_id,"pending",json.dumps(payload),None,None,now,now))
        self.db.commit(); return jid

    def claim_next(self):
        row = self.db.execute("SELECT id,payload FROM jobs WHERE state='pending' ORDER BY created LIMIT 1").fetchone()
        if not row: return None
        self.db.execute("UPDATE jobs SET state='running',updated=? WHERE id=?",(time.time(),row[0]))
        self.db.commit()
        return {"id":row[0],"payload":json.loads(row[1])}

    def complete(self, jid, result):
        self.db.execute("UPDATE jobs SET state='done',result=?,updated=? WHERE id=?",
                        (json.dumps(result),time.time(),jid)); self.db.commit()

    def fail(self, jid, err):
        self.db.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?",
                        (str(err)[:500],time.time(),jid)); self.db.commit()

    def resume(self):
        """Requeue anything stuck in 'running' (crash recovery)."""
        self.db.execute("UPDATE jobs SET state='pending' WHERE state='running'"); self.db.commit()

    def stats(self):
        return dict(self.db.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state").fetchall())

    def by_film(self, film_id):
        rows = self.db.execute("SELECT id,shot_id,state,result FROM jobs WHERE film_id=?",(film_id,)).fetchall()
        return [{"id":r[0],"shot_id":r[1],"state":r[2],"result":json.loads(r[3]) if r[3] else None} for r in rows]
