from flask import Flask, jsonify
from flask_cors import CORS
import base64

# Note: Using win32com for ZKTeco ZK4500 / ZKFinger SDK
# For Digital Persona, replace with dpfpdd library bindings
import win32com.client

agent_app = Flask(__name__)
CORS(agent_app)  # Allow web browser JavaScript to query local port 5001


@agent_app.route('/', methods=['GET'])
def health_check():
    return jsonify({
        "status": "running",
        "scan_endpoint": "/scan-fingerprint"
    }), 200


@agent_app.route('/scan-fingerprint', methods=['GET'])
def scan_fingerprint():
    try:
        # Initialize ZKFinger COM Object
        zk_engine = win32com.client.Dispatch("ZKFINGERX.ZKFingerXCtrl.1")
        
        if zk_engine.InitEngine() != 0:
            return jsonify({"status": "error", "message": "Failed to initialize USB fingerprint sensor."}), 500
        
        # Begin capture sequence (Timeout after 5 seconds)
        zk_engine.BeginCapture()
        
        # Simulated/Captured Template Extraction
        # In production, hook into the OnCapture event of ZKFingerX
        template_data = zk_engine.GetTemplateAsString()
        zk_engine.EndCapture()
        
        if not template_data:
            return jsonify({"status": "error", "message": "No fingerprint detected or scan timed out."}), 400

        return jsonify({
            "status": "success",
            "template": template_data
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    print("Biometric Agent running on http://127.0.0.1:5001")
    agent_app.run(port=5001)