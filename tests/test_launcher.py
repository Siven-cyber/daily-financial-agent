"""Launcher must not depend on relocated virtualenv activation."""
import unittest
from pathlib import Path


class LauncherTests(unittest.TestCase):
    def test_launcher_uses_project_interpreter(self):
        text = (Path(__file__).resolve().parents[1] / 'run_bot.sh').read_text()
        self.assertIn('exec "${HERE}/.venv/bin/python" -m finance_agent.bot', text)
        self.assertNotIn('source .venv/bin/activate', text)


if __name__ == '__main__':
    unittest.main()
