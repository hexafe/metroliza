import json
import unittest
from pathlib import Path


EXAMPLE_GOOGLE_CREDENTIALS_PATH = Path('config/google/credentials.example.json')


def validate_example_credentials_template_hygiene() -> None:
    payload_text = EXAMPLE_GOOGLE_CREDENTIALS_PATH.read_text(encoding='utf-8')
    payload = json.loads(payload_text)
    installed = payload.get('installed')
    if not isinstance(installed, dict):
        raise AssertionError("Missing 'installed' OAuth section in credentials example template.")

    for key in ('client_id', 'client_secret', 'auth_uri', 'token_uri'):
        if key not in installed:
            raise AssertionError(f"Missing required OAuth field in credentials template: {key}")

    if 'YOUR_CLIENT_ID' not in installed['client_id']:
        raise AssertionError("credentials.example.json must keep redacted client_id placeholder.")
    if 'YOUR_CLIENT_SECRET' not in installed['client_secret']:
        raise AssertionError("credentials.example.json must keep redacted client_secret placeholder.")
    if 'AIza' in payload_text:
        raise AssertionError('credentials.example.json contains a real-looking API key prefix.')

    for disallowed_key in ('access_token', 'refresh_token', 'expires_at'):
        if disallowed_key in payload_text:
            raise AssertionError(f"credentials.example.json must not include runtime token key: {disallowed_key}")


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
