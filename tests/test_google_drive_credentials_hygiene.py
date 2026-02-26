import json
import unittest
from pathlib import Path


class TestGoogleDriveCredentialsHygiene(unittest.TestCase):
    def test_gitignore_blocks_local_google_secret_files(self):
        gitignore = Path('.gitignore').read_text(encoding='utf-8')
        self.assertIn('credentials.json', gitignore)
        self.assertIn('token.json', gitignore)

    def test_example_credentials_template_is_valid_and_redacted(self):
        example_path = Path('config/google/credentials.example.json')
        self.assertTrue(example_path.exists(), 'Missing example Google credentials template.')

        payload = json.loads(example_path.read_text(encoding='utf-8'))
        self.assertIn('installed', payload)

        installed = payload['installed']
        for key in ('client_id', 'client_secret', 'auth_uri', 'token_uri'):
            self.assertIn(key, installed)

        self.assertNotIn('AIza', example_path.read_text(encoding='utf-8'))
        self.assertIn('YOUR_CLIENT_ID', installed['client_id'])
        self.assertIn('YOUR_CLIENT_SECRET', installed['client_secret'])

    def test_example_credentials_template_does_not_embed_runtime_tokens(self):
        payload_text = Path('config/google/credentials.example.json').read_text(encoding='utf-8')

        self.assertNotIn('access_token', payload_text)
        self.assertNotIn('refresh_token', payload_text)
        self.assertNotIn('expires_at', payload_text)


if __name__ == '__main__':
    unittest.main()
