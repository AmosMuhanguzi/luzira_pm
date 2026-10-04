import sys
import socket
from zk import ZK

ip = "192.168.1.201"
port = 3505

print(f"--- DIAGNOSTIC TEST: ZKTECO HANDSHAKE ({ip}:{port}) ---")

# 1. Quick raw TCP socket test
print("\n[Step 1] Verifying low-level TCP socket reachability...")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(3)
try:
    sock.connect((ip, port))
    print(" -> Low-level TCP Socket is OPEN and accepting connections!")
    sock.close()
except Exception as e:
    print(f" -> Low-level TCP Socket connection failed: {e}")

# 2. Permutations matrix for pyzk library handshake
print("\n[Step 2] Testing protocol handshake combinations...")

test_matrix = [
    {"udp": False, "pwd": 0,      "timeout": 10, "label": "TCP | Pass: 0 | Timeout: 10s"},
    {"udp": True,  "pwd": 0,      "timeout": 10, "label": "UDP | Pass: 0 | Timeout: 10s"},
    {"udp": False, "pwd": 123456, "timeout": 10, "label": "TCP | Pass: 123456 | Timeout: 10s"},
    {"udp": True,  "pwd": 123456, "timeout": 10, "label": "UDP | Pass: 123456 | Timeout: 10s"},
    {"udp": False, "pwd": 0,      "timeout": 15, "label": "TCP | Pass: 0 | Extended Timeout 15s"},
]

for config in test_matrix:
    label = config["label"]
    print(f"Testing: {label}...")
    zk = ZK(
        ip,
        port=port,
        timeout=config["timeout"],
        password=config["pwd"],
        force_udp=config["udp"]
    )
    try:
        conn = zk.connect()
        print(f"\n==========================================")
        print(f" SUCCESS! Connected via {label}")
        print(f" Firmware Version: {conn.get_firmware_version()}")
        print(f" Serial Number:    {conn.get_serialnumber()}")
        print(f" Device Name:      {conn.get_device_name()}")
        print(f"==========================================")
        conn.disconnect()
        sys.exit(0)
    except Exception as e:
        print(f"   FAILED: {type(e).__name__} - {e}")

print("\n[Step 3] All automated handshakes failed.")
print("Check the physical terminal keypad:")
print("1. Press M/OK -> Comm. -> PC Connection -> Comm Key.")
print("2. Ensure Comm Key is explicitly set to 0.")
print("3. Restart the terminal power supply and re-run python test_zk.py.")