# services/biometric_matcher.py
"""
Template comparison helpers.
In production, replace `compare_templates` with the SDK's matcher
(pyfingerprint / DigitalPersona / ZKTeco). The interface stays the same.
"""
import base64


def compare_templates(template_a, template_b) -> float:
    """
    Return a similarity score 0–100.
    Accepts bytes or base64 strings.
    """
    a = _to_bytes(template_a)
    b = _to_bytes(template_b)

    if not a or not b:
        return 0.0
    if len(a) != len(b):
        # Different lengths → no meaningful comparison
        return 0.0

    # Placeholder: byte-level similarity. Replace with SDK matcher in production.
    matches = sum(1 for x, y in zip(a, b) if x == y)
    return (matches / len(a)) * 100.0


def _to_bytes(v):
    if v is None:
        return b''
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        try:
            return base64.b64decode(v)
        except Exception:
            return v.encode('utf-8')
    return b''