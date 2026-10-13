import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from download_scheduler import ScheduleStore


class ScheduleStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="medialivre-schedule-test-")
        self.store = ScheduleStore(Path(self.temp.name) / "test.sqlite3")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def tearDown(self):
        self.temp.cleanup()

    def test_add_pending_job_and_claim_only_when_due(self):
        job = self.store.add(
            "https://example.com/video",
            self.now + timedelta(minutes=5),
            {"quality": "720p", "destination": "/tmp/media"},
        )
        self.assertEqual(job.state, "pending")
        self.assertIsNone(self.store.claim_next_due(self.now))
        claimed = self.store.claim_next_due(self.now + timedelta(minutes=6))
        self.assertEqual(claimed.id, job.id)
        self.assertEqual(claimed.state, "running")
        self.assertIsNone(self.store.claim_next_due(self.now + timedelta(minutes=6)))

    def test_finish_cancel_and_manual_requeue(self):
        job = self.store.add("https://example.com/a", self.now, {})
        claimed = self.store.claim_next_due(self.now)
        self.assertEqual(claimed.id, job.id)
        self.assertTrue(self.store.finish(job.id, "failed", "temporary error"))
        self.assertFalse(self.store.finish(job.id, "completed"))
        self.assertTrue(self.store.requeue(job.id, self.now + timedelta(minutes=1)))
        self.assertEqual(self.store.get(job.id).state, "pending")
        self.assertTrue(self.store.cancel(job.id))
        self.assertEqual(self.store.get(job.id).state, "cancelled")

    def test_rejects_invalid_urls_and_naive_datetime(self):
        with self.assertRaises(ValueError):
            self.store.add("file:///tmp/video.mp4", self.now, {})
        with self.assertRaises(ValueError):
            self.store.add("https://example.com/a", datetime.now(), {})

    def test_rejects_credentials_embedded_in_url(self):
        with self.assertRaises(ValueError):
            self.store.add("https://user:pass@example.com/a", self.now, {})

    def test_interrupted_running_jobs_are_marked_failed_not_repeated(self):
        job = self.store.add("https://example.com/a", self.now, {})
        self.store.claim_next_due(self.now)
        self.assertEqual(self.store.recover_interrupted_jobs(), 1)
        recovered = self.store.get(job.id)
        self.assertEqual(recovered.state, "failed")
        self.assertIn("terminou durante", recovered.last_error)
        self.assertIsNone(self.store.claim_next_due(self.now + timedelta(days=1)))


if __name__ == "__main__":
    unittest.main()
