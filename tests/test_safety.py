import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app
import audio
import config
import jobs


class DummyUpload:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, size=-1):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class SafetyTests(unittest.TestCase):
    def test_uploaded_path_rejects_outside_uploads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            uploads = root / "uploads"
            uploads.mkdir()
            outside = root / "outside.pdf"
            outside.write_bytes(b"%PDF-1.4")

            with patch.object(config, "UPLOADS_DIR", uploads):
                with self.assertRaises(HTTPException) as cm:
                    app._uploaded_path(str(outside), (".pdf",))

            self.assertEqual(cm.exception.status_code, 400)

    def test_uploaded_path_accepts_pdf_inside_uploads(self):
        with tempfile.TemporaryDirectory() as td:
            uploads = Path(td) / "uploads"
            uploads.mkdir()
            pdf = uploads / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4")

            with patch.object(config, "UPLOADS_DIR", uploads):
                self.assertEqual(
                    app._uploaded_path(str(pdf), (".pdf",)),
                    pdf.resolve(strict=False),
                )

    def test_save_upload_limited_removes_oversized_file(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "too-large.bin"
            upload = DummyUpload([b"12345", b"67890"])

            with self.assertRaises(HTTPException) as cm:
                asyncio.run(app._save_upload_limited(upload, dest, 8))

            self.assertEqual(cm.exception.status_code, 413)
            self.assertFalse(dest.exists())

    def test_parse_segments_discards_empty_short_video_lines(self):
        segments = jobs._parse_segments("[00:00] 開場\n\n[00:05]   ", "short_video")

        self.assertEqual(segments, [{"speaker": "旁白", "text": "開場"}])
        self.assertTrue(jobs._has_speakable_segments(segments))

    def test_approve_job_rejects_empty_script(self):
        with tempfile.TemporaryDirectory() as td:
            job = jobs.Job(
                id="empty",
                status=jobs.STATUS_AWAITING_REVIEW,
                output_mode="single",
                script_text="   ",
                created_at="now",
                updated_at="now",
            )
            with patch.object(config, "JOBS_DIR", Path(td)):
                with jobs._jobs_lock:
                    jobs._jobs[job.id] = job
                try:
                    result = jobs.approve_job(job.id)
                    self.assertIs(result, job)
                    self.assertEqual(result.status, jobs.STATUS_AWAITING_REVIEW)
                    self.assertIn("沒有可合成", result.error)
                finally:
                    with jobs._jobs_lock:
                        jobs._jobs.pop(job.id, None)

    def test_audio_synthesize_rejects_empty_segments(self):
        with tempfile.TemporaryDirectory() as td:
            job = jobs.Job(id="empty-audio", segments=[{"speaker": "旁白", "text": "  "}])

            with self.assertRaisesRegex(RuntimeError, "沒有可合成"):
                audio.synthesize(job, Path(td), lambda *_: None)


if __name__ == "__main__":
    unittest.main()
