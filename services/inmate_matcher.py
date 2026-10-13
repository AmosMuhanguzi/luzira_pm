# services/inmate_matcher.py
"""
1:N fingerprint identification against all enrolled inmates.
"""
import logging

from models.inmate import Inmate
from services.biometric_agent_client import BiometricAgentError
from services.biometric_matcher import compare_templates

logger = logging.getLogger(__name__)


class InmateMatcher:

    @staticmethod
    def identify(probe_template, threshold: int = 75, top_n: int = 5,
                 comparator=compare_templates):
        enrolled = Inmate.query.filter_by(biometric_enrolled=True).all()

        if not enrolled:
            return {
                'match': False, 'inmate': None, 'score': 0.0,
                'candidates': [], 'enrolled_count': 0,
            }

        results = []
        comparison_errors = 0
        for inmate in enrolled:
            if not inmate.fingerprint_template:
                continue
            try:
                score = comparator(probe_template, inmate.fingerprint_template)
            except (BiometricAgentError, RuntimeError, ValueError) as error:
                comparison_errors += 1
                logger.warning(
                    'Skipping inmate %s fingerprint comparison: %s',
                    inmate.inmate_id,
                    error,
                )
                continue
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
            'comparison_errors': comparison_errors,
        }