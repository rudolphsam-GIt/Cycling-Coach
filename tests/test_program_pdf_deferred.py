"""
The program PDF is built when the rider asks for it, not every time the Coach tab draws. The cache key
includes fitness and fatigue, so building it on each draw rebuilt it whenever those moved.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema


def _app():
    from components import program_ui
    program = {"title": "Spring build", "start_date": "2026-11-02", "phases": []}
    program_ui._pdf_button(program, "pdf", {"ctl": 41.3, "atl": 38.2})


class ProgramPdfDeferredTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.built = []
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch("program_pdf.build_pdf", lambda *a, **k: self.built.append(1) or b"%PDF"),
                  mock.patch("programs.projected_fitness", return_value=[]),
                  mock.patch("programs.weekly_ctl", return_value={})):
            p.start()
            self.addCleanup(p.stop)
        schema.run_migrations()
        from components import program_ui
        program_ui._pdf_bytes.clear()

    def test_drawing_the_button_does_not_build_the_pdf(self):
        at = AppTest.from_function(_app, default_timeout=30).run()
        self.assertFalse(at.exception)
        self.assertEqual(self.built, [])


if __name__ == "__main__":
    unittest.main()
