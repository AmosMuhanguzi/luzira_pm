# services/inmate_matcher.py
"""
1:N fingerprint identification against all enrolled inmates.
"""
from models.inmate import Inmate
from services.biometric_matcher import compare_templates


class InmateMatcher:

    @staticmethod
    def identify(probe_template, threshold: int = 75, top_n: int = 5):
        enrolled = Inmate.query.filter_by(biometric_enrolled=True).all()

        if not enrolled:
            return {
                'match': False, 'inmate': None, 'score': 0.0,
                'candidates': [], 'enrolled_count': 0,
            }

        results = []
        for inmate in enrolled:
            if not inmate.fingerprint_template:
                continue
            score = compare_templates(probe_template, inmate.fingerprint_template)
            results.append({'inmate': inmate, 'score': score})

        results.sort(key=lambda r: r['score'], reverse=True)
        top = results[:top_n]
        best = top[0] if top else {'inmate': None, 'score': 0.0}
        matched = bool(top and best['score'] >= threshold)

        return {
            'match': matched,
            'inmate': best['inmate'] if matched else None,
            'score': best['score'],
            'candidates': top,
            'enrolled_count': len(results),
        }