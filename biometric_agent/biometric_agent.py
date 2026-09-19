# =====================================================
# biometric_agent.py - Local Biometric Agent
# Runs on intake terminal as microservice
# =====================================================

from flask import Flask, request, jsonify
from pyfingerprint.pyfingerprint import PyFingerprint
import base64
import json
import logging

app = Flask(__name__)

# Configuration
SCANNER_PORT = '/dev/ttyUSB0'  # Linux
# SCANNER_PORT = 'COM3'  # Windows
SCANNER_BAUDRATE = 57600
SCANNER_ADDRESS = 0xFFFFFFFF
SCANNER_PASSWORD = 0x00000000

class BiometricService:
    def __init__(self):
        self.sensor = None
        self.initialize_sensor()
    
    def initialize_sensor(self):
        """Initialize fingerprint sensor connection"""
        try:
            self.sensor = PyFingerprint(
                SCANNER_PORT, 
                SCANNER_BAUDRATE, 
                SCANNER_ADDRESS, 
                SCANNER_PASSWORD
            )
            
            if not self.sensor.verifyPassword():
                raise Exception("Sensor password verification failed")
            
            logging.info(f"Sensor initialized. Template capacity: {self.sensor.getTemplateCount()}/{self.sensor.getStorageCapacity()}")
            return True
            
        except Exception as e:
            logging.error(f"Sensor initialization failed: {e}")
            self.sensor = None
            return False
    
    def capture_fingerprint(self, timeout=10):
        """
        Capture fingerprint and return template
        Returns: dict with template, quality, success
        """
        if not self.sensor:
            return {'success': False, 'error': 'Sensor not initialized'}
        
        try:
            # Wait for finger to be placed
            logging.info("Waiting for finger...")
            while not self.sensor.readImage():
                pass
            
            # Convert image to characteristics (template)
            self.sensor.convertImage(0x01)
            
            # Get template as bytes
            template = self.sensor.downloadCharacteristics(0x01)
            
            # Calculate quality score (simplified)
            quality = self._calculate_quality(template)
            
            return {
                'success': True,
                'template': base64.b64encode(bytes(template)).decode('utf-8'),
                'quality': quality,
                'template_size': len(template)
            }
            
        except Exception as e:
            logging.error(f"Capture failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def capture_multiple_samples(self, count=3):
        """
        Capture multiple fingerprint samples and create consolidated template
        Used for new enrolment for improved accuracy
        """
        templates = []
        qualities = []
        
        for i in range(count):
            result = self.capture_fingerprint()
            if result['success']:
                templates.append(result['template'])
                qualities.append(result['quality'])
            else:
                return {'success': False, 'error': f'Sample {i+1} failed: {result["error"]}'}
        
        # In production, consolidate templates using SDK
        # For prototype, use the highest quality template
        best_idx = qualities.index(max(qualities))
        
        return {
            'success': True,
            'template': templates[best_idx],
            'quality': max(qualities),
            'samples_captured': count
        }
    
    def _calculate_quality(self, template):
        """Calculate template quality score (0-100)"""
        # Simplified quality calculation
        # In production, use SDK's quality assessment
        if len(template) < 256:
            return 30
        elif len(template) < 512:
            return 60
        else:
            return min(95, 60 + (len(template) - 512) // 10)


biometric_service = BiometricService()


@app.route('/api/scan', methods=['POST'])
def scan_fingerprint():
    """Capture single fingerprint"""
    result = biometric_service.capture_fingerprint()
    return jsonify(result)


@app.route('/api/enroll', methods=['POST'])
def enroll_fingerprint():
    """Capture multiple samples for enrolment"""
    result = biometric_service.capture_multiple_samples(count=3)
    return jsonify(result)


@app.route('/api/status', methods=['GET'])
def get_status():
    """Check sensor status"""
    return jsonify({
        'initialized': biometric_service.sensor is not None,
        'capacity': biometric_service.sensor.getStorageCapacity() if biometric_service.sensor else 0,
        'template_count': biometric_service.sensor.getTemplateCount() if biometric_service.sensor else 0
    })


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False)