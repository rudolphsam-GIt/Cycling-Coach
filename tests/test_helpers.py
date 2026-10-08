import os
import tempfile
import unittest

from components.theme import rgba
from metrics.units import num


class SharedHelpersTest(unittest.TestCase):
    def test_num(self):
        self.assertEqual(num("12.5"), 12.5)
        for bad in (None, "", "abc", float("nan"), float("inf")):
            self.assertIsNone(num(bad))

    def test_rgba(self):
        self.assertEqual(rgba("#ff8000", 0.5), "rgba(255,128,0,0.5)")


class ConversationWindowTest(unittest.TestCase):
    def setUp(self):
        from db import schema
        self.schema = schema
        self.tmp = tempfile.TemporaryDirectory()
        self.old = schema.DB_PATH
        schema.DB_PATH = os.path.join(self.tmp.name, "t.db")
        schema.run_migrations()

    def tearDown(self):
        self.schema.DB_PATH = self.old
        self.tmp.cleanup()

    def _add(self, n):
        from db.queries import save_message
        for i in range(n):
            save_message("user" if i % 2 == 0 else "assistant", f"m{i}")

    def test_short_chat_sends_everything(self):
        from db.queries import get_conversation_window
        self._add(12)
        self.assertEqual(len(get_conversation_window()), 12)

    def test_window_start_moves_in_steps(self):
        from db.queries import get_conversation_window
        self._add(30)
        first = get_conversation_window()[0]["content"]
        self._add(2)
        self.assertEqual(get_conversation_window()[0]["content"], first)
        self.assertTrue(18 <= len(get_conversation_window()) < 28)


if __name__ == "__main__":
    unittest.main()
