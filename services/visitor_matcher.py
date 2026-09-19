# services/visitor_matcher.py
"""
1:N fingerprint identification against all enrolled visitors.
Mirrors inmate_matcher but scoped to the Visitor table.
"""
from models.visitor import Visitor
from services.biometric_matcher import compare_templates


class VisitorMatcher:

    @staticmethod
    def identify(probe_template, threshold: int = 75, top_n: int = 5):
        enrolled = Visitor.query.filter_by(biometric_enrolled=True).all()

        if not enrolled:
            return {
                'match': False, 'visitor': None, 'score': 0.0,
                'candidates': [], 'enrolled_count': 0,
            }

        results = []
        for v in enrolled:
            if not v.fingerprint_template:
                continue
            score = compare_templates(probe_template, v.fingerprint_template)
            results.append({'visitor': v, 'score': score})

        results.sort(key=lambda r: r['score'], reverse=True)
        top = results[:top_n]
        best = top[0] if top else {'visitor': None, 'score': 0.0}
        matched = bool(top and best['score'] >= threshold)

        return {
            'match': matched,
            'visitor': best['visitor'] if matched else None,
            'score': best['score'],
            'candidates': top,
            'enrolled_count': len(results),
        }