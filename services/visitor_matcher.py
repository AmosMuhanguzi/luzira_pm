# services/visitor_matcher.py
"""
1:N fingerprint identification against all enrolled visitors.
Mirrors inmate_matcher but scoped to the Visitor table.
"""
import logging

from models.visitor import Visitor
from services.biometric_agent_client import BiometricAgentError
from services.biometric_matcher import compare_templates

logger = logging.getLogger(__name__)


class VisitorMatcher:

    @staticmethod
    def identify(probe_template, threshold: int = 75, top_n: int = 5,
                 comparator=compare_templates):
        enrolled = Visitor.query.filter_by(biometric_enrolled=True).all()

        if not enrolled:
            return {
                'match': False, 'visitor': None, 'score': 0.0,
                'candidates': [], 'enrolled_count': 0,
            }

        results = []
        comparison_errors = 0
        for v in enrolled:
            if not v.fingerprint_template:
                continue
            try:
                score = comparator(probe_template, v.fingerprint_template)
            except (BiometricAgentError, RuntimeError, ValueError) as error:
                comparison_errors += 1
                logger.warning(
                    'Skipping visitor %s fingerprint comparison: %s',
                    v.visitor_id,
                    error,
                )
                continue
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
            'comparison_errors': comparison_errors,
        }