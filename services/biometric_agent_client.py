# services/biometric_agent_client.py
"""
HTTP client for the local biometric agent (port 5001).
Uses stdlib urllib so no extra dependencies are needed.
"""
import json
import urllib.request
import urllib.error


class BiometricAgentError(Exception):
    pass


class BiometricAgentClient:

    def __init__(self, base_url: str, timeout: int = 20):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def _post(self, path: str, payload: dict = None) -> dict:
        url = f'{self.base_url}{path}'
        data = json.dumps(payload or {}).encode('utf-8')
        req = urllib.request.Request(
            url, data=data, method='POST',
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.URLError as e:
            raise BiometricAgentError(
                f'Biometric agent unreachable at {url}: {e.reason}'
            )
        except urllib.error.HTTPError as e:
            raise BiometricAgentError(
                f'Agent returned HTTP {e.code}: '
                f'{e.read().decode("utf-8", "replace")}'
            )

    def scan(self) -> dict:
        return self._post('/api/scan')

    def enroll(self, samples: int = 3) -> dict:
        return self._post('/api/enroll', {'samples': samples})

    def status(self) -> dict:
        url = f'{self.base_url}/api/status'
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return {'initialized': False, 'error': str(e)}