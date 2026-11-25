import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.config import ConfigurationError, load_settings


class SettingsTests(unittest.TestCase):
    def test_missing_voice_credentials_name_variables_without_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch("backend.app.config.PROJECT_ROOT", Path(temporary_directory)),
                patch.dict(
                    os.environ,
                    {
                        "GOOGLE_API_KEY": "   ",
                        "ELEVENLABS_API_KEY": "",
                        "ELEVENLABS_VOICE_ID": "",
                    },
                    clear=True,
                ),
            ):
                with self.assertRaises(ConfigurationError) as raised:
                    load_settings(require_voice_credentials=True)

        message = str(raised.exception)
        self.assertIn("GOOGLE_API_KEY", message)
        self.assertIn("ELEVENLABS_API_KEY", message)
        self.assertIn("ELEVENLABS_VOICE_ID", message)
        self.assertNotIn("secret", message.casefold())


if __name__ == "__main__":
    unittest.main()
