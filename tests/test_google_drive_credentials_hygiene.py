import unittest
from pathlib import Path

from metroliza.integrations.google_credentials_hygiene import (
    EXAMPLE_GOOGLE_CREDENTIALS_PATH,
    validate_example_credentials_template_hygiene,
)


class TestGoogleDriveCredentialsHygiene(unittest.TestCase):
    def test_gitignore_blocks_local_google_secret_files(self):
        gitignore = Path('.gitignore').read_text(encoding='utf-8')
        self.assertIn('credentials.json', gitignore)
        self.assertIn('token.json', gitignore)

    def test_example_credentials_template_is_valid_and_redacted(self):
        example_path = EXAMPLE_GOOGLE_CREDENTIALS_PATH
        self.assertTrue(example_path.exists(), 'Missing example Google credentials template.')

        validate_example_credentials_template_hygiene()

    def test_example_credentials_template_does_not_embed_runtime_tokens(self):
        validate_example_credentials_template_hygiene()


if __name__ == '__main__':
    unittest.main()
