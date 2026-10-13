"""Local Windows agent for Mantra MFS100 fingerprint scanners."""
import base64
import os

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


class MantraScanner:
    def __init__(self):
        self.sdk_path = os.environ.get(
            'MANTRA_SDK_PATH',
            r'C:\Program Files\Mantra\MFS100\Driver\MFS100Test\MANTRA.MFS100.dll',
        )
        self.device = None

    def _connect(self):
        if self.device is not None:
            return
        try:
            import clr
            clr.AddReference(self.sdk_path)
            from MANTRA import MFS100
            self.device = MFS100()
        except ImportError as error:
            raise RuntimeError(
                'pythonnet is required by the Mantra agent. '
                'Install the agent requirements first.'
            ) from error
        except Exception as error:
            self.device = None
            raise RuntimeError(
                f'Mantra .NET SDK was not found at "{self.sdk_path}". '
                'Install the MFS100 SDK or set MANTRA_SDK_PATH.'
            ) from error

        result = self.device.Init()
        if result != 0:
            self.device = None
            raise RuntimeError(f'Mantra scanner initialization failed ({result}).')

    def _capture_template(self):
        self._connect()
        from MANTRA import FingerData
        result = self.device.AutoCapture(FingerData(), 10000, True, False)
        if not isinstance(result, tuple):
            result = (result,)
        status, finger = result[0], result[-1]
        if status != 0:
            message = self.device.GetErrorMsg(status)
            raise RuntimeError(message or f'Mantra capture failed ({status}).')
        template = bytes(finger.ISOTemplate)
        if not template:
            raise RuntimeError('No fingerprint detected or scan timed out.')
        encoded = base64.b64encode(template).decode('ascii')
        quality = finger.Quality
        return encoded, max(0, min(100, int(quality or 0)))

    def scan(self):
        template, quality = self._capture_template()
        return {'success': True, 'template': template, 'quality': quality}

    def enroll(self, samples):
        captures = [self._capture_template() for _ in range(max(1, samples))]
        template, quality = max(captures, key=lambda item: item[1])
        return {
            'success': True,
            'template': template,
            'quality': quality,
            'samples_captured': len(captures),
        }

    def match(self, probe_template, enrolled_template):
        self._connect()
        probe = base64.b64decode(probe_template)
        enrolled = base64.b64decode(enrolled_template)
        # The SDK signature is MatchISO(byte[], byte[], ref int score).
        result = self.device.MatchISO(probe, enrolled, 0)
        if not isinstance(result, tuple):
            result = (result,)
        status, score = result[0], result[-1]
        if status != 0:
            message = self.device.GetErrorMsg(status)
            raise RuntimeError(message or f'Mantra match failed ({status}).')
        # MFS100 reports MatchISO scores from 0 to 10000; the application
        # consistently exposes confidence as a percentage.
        confidence = float(score) / 100.0
        return {'success': True, 'score': max(0.0, min(100.0, confidence))}

    def status(self):
        try:
            self._connect()
            return {'initialized': True, 'sdk_path': self.sdk_path}
        except RuntimeError as error:
            return {'initialized': False, 'sdk_path': self.sdk_path, 'error': str(error)}


scanner = MantraScanner()


@app.get('/')
def health_check():
    return jsonify({'status': 'running', 'driver': 'mantra'})


@app.post('/api/scan')
def scan():
    try:
        return jsonify(scanner.scan())
    except (RuntimeError, ValueError) as error:
        return jsonify({'success': False, 'error': str(error)}), 503


@app.post('/api/enroll')
def enroll():
    payload = request.get_json(silent=True) or {}
    try:
        samples = int(payload.get('samples', 3))
        return jsonify(scanner.enroll(samples))
    except (RuntimeError, ValueError) as error:
        return jsonify({'success': False, 'error': str(error)}), 503


@app.post('/api/match')
def match():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(scanner.match(
            payload['probe_template'], payload['enrolled_template']
        ))
    except (KeyError, RuntimeError, TypeError, ValueError) as error:
        return jsonify({'success': False, 'error': str(error)}), 503


@app.get('/api/status')
def status():
    return jsonify(scanner.status())


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False)
