# biometric_agent/agent.py
"""
Local biometric agent.
Runs on the intake terminal. Exposes a tiny HTTP API on 127.0.0.1:5001.
The web app calls this to obtain fingerprint templates.

Supports two modes:
  - Real hardware (pyfingerprint / ZKTeco / DigitalPersona SDK)
  - Mock (returns synthetic templates for development)
"""
import os
import base64
import logging
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('biometric-agent')

app = Flask(__name__)

SCANNER_PORT      = os.environ.get('SCANNER_PORT', '/dev/ttyUSB0')
SCANNER_BAUDRATE  = int(os.environ.get('SCANNER_BAUDRATE', 57600))
SCANNER_ADDRESS   = int(os.environ.get('SCANNER_ADDRESS', '0xFFFFFFFF'), 16)
SCANNER_PASSWORD  = int(os.environ.get('SCANNER_PASSWORD', '0x00000000'), 16)
MOCK_MODE         = os.environ.get('BIOMETRIC_MOCK_MODE', 'true').lower() == 'true'


# ---------- Real sensor wrapper ----------
class FingerprintSensor:
    def __init__(self):
        self.ok = False
        self.sensor = None
        if MOCK_MODE:
            log.info('Agent running in MOCK mode — no hardware required.')
            return
        try:
            from pyfingerprint.pyfingerprint import PyFingerprint
            self.sensor = PyFingerprint(
                SCANNER_PORT, SCANNER_BAUDRATE,
                SCANNER_ADDRESS, SCANNER_PASSWORD
            )
            if not self.sensor.verifyPassword():
                raise RuntimeError('Sensor password rejected')
            self.ok = True
            log.info('Fingerprint sensor initialised.')
        except Exception as e:
            log.error(f'Sensor init failed: {e}')
            self.ok = False

    def scan(self):
        """Capture a single sample. Returns dict."""
        if MOCK_MODE:
            return self._mock_result(samples=1)
        if not self.ok:
            return {'success': False, 'error': 'Sensor not available'}

        try:
            while not self.sensor.readImage():
                pass
            self.sensor.convertImage(0x01)
            chars = self.sensor.downloadCharacteristics(0x01)
            template_bytes = bytes(chars)
            return {
                'success': True,
                'template': base64.b64encode(template_bytes).decode('utf-8'),
                'quality': 85,
                'size': len(template_bytes),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def enroll(self, samples=3):
        """Capture N samples and return a consolidated template."""
        if MOCK_MODE:
            return self._mock_result(samples=samples)
        if not self.ok:
            return {'success': False, 'error': 'Sensor not available'}

        captured = []
        qualities = []
        for i in range(samples):
            r = self.scan()
            if not r['success']:
                return {'success': False, 'error': f'Sample {i+1}: {r["error"]}'}
            captured.append(base64.b64decode(r['template']))
            qualities.append(r['quality'])

        best = captured[qualities.index(max(qualities))]
        return {
            'success': True,
            'template': base64.b64encode(best).decode('utf-8'),
            'quality': max(qualities),
            'samples_captured': samples,
        }

    def _mock_result(self, samples=1):
        seed = (os.environ.get('AGENT_MOCK_SECRET', 'luzira-dev-secret') * 4).encode()
        template = (seed * 4)[:256]
        return {
            'success': True,
            'template': base64.b64encode(template).decode('utf-8'),
            'quality': 90,
            'samples_captured': samples,
            'mock': True,
        }


sensor = FingerprintSensor()


# ---------- Routes ----------
@app.route('/api/status')
def status():
    return jsonify({
        'initialized': MOCK_MODE or sensor.ok,
        'mode': 'mock' if MOCK_MODE else 'hardware',
    })


@app.route('/api/scan', methods=['POST'])
def scan():
    return jsonify(sensor.scan())


@app.route('/api/enroll', methods=['POST'])
def enroll():
    body = request.get_json(silent=True) or {}
    n = int(body.get('samples', 3))
    return jsonify(sensor.enroll(samples=n))


if __name__ == '__main__':
    log.info(f'Starting biometric agent on 127.0.0.1:5001 (mock={MOCK_MODE})')
    app.run(host='127.0.0.1', port=5001, debug=False)