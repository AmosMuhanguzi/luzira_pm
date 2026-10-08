# services/ai_inmate_risk.py
"""
Rule-based inmate behavioural risk scoring.
Deterministic, explainable, no training data required.
"""
import logging
from datetime import datetime

from extensions import db
from models.inmate import Inmate
from models.medical import DisciplinaryLog
from models.ai import AIAnalysisLog

logger = logging.getLogger(__name__)

SEVERE_CRIMES = {
    'murder', 'rape', 'armed robbery', 'kidnapping', 'treason',
}


class InmateRiskScorer:

    @classmethod
    def calculate(cls, inmate_id, persist=True):
        inmate = Inmate.query.get(inmate_id)
        if not inmate:
            return {'success': False, 'error': 'Inmate not found.'}

        score = 0
        factors = []

        crime = (inmate.crime_category or '').strip().lower()
        if crime in SEVERE_CRIMES:
            score += 25
            factors.append(('Severe crime category', 25))

        if inmate.violence_history:
            score += 20
            factors.append(('History of violence', 20))

        if inmate.escape_attempt_history:
            score += 30
            factors.append(('Previous escape attempt', 30))

        disc_count = DisciplinaryLog.query.filter_by(inmate_id=inmate_id).count()
        if disc_count:
            pts = min(disc_count * 5, 20)
            score += pts
            factors.append((f'{disc_count} disciplinary incident(s)', pts))

        repeat_pts = min(max((inmate.total_admissions or 1) - 1, 0) * 10, 20)
        if repeat_pts:
            score += repeat_pts
            factors.append((f'Repeat offender ({inmate.total_admissions} admissions)', repeat_pts))

        if inmate.security_classification == 'Maximum':
            score += 15
            factors.append(('Maximum security classification', 15))

        score = min(score, 100)
        if score >= 80:   level = 'Critical'
        elif score >= 60: level = 'High'
        elif score >= 40: level = 'Medium'
        else:             level = 'Low'

        if persist:
            inmate.risk_level = level
            db.session.commit()

            AIAnalysisLog.log_analysis(
                analysis_type='InmateRiskProfile',
                target_entity='Inmate',
                target_id=inmate_id,
                result_summary=(f'Risk {score}/100 → {level}. '
                                f'Factors: ' +
                                ', '.join(f'{n} (+{p})' for n, p in factors) or 'none'),
                detailed_result={'score': score, 'level': level,
                                 'factors': [{'name': n, 'points': p} for n, p in factors]},
                confidence_score=None,
                severity=level if level in ('High', 'Critical') else 'Info',
                recommended_action=cls._recommend(level, factors),
                model_version='RuleBased-v1.0',
            )
            db.session.commit()

        return {
            'success': True,
            'inmate_id': inmate_id,
            'risk_score': score,
            'risk_level': level,
            'risk_factors': factors,
            'recommendations': cls._recommend(level, factors).split(' | '),
        }

    @classmethod
    def score_all(cls):
        inmates = Inmate.query.filter_by(status='Active').all()
        results = []
        for i in inmates:
            r = cls.calculate(i.inmate_id)
            if r.get('success'):
                results.append(r)
        return {'success': True, 'scored': len(results)}

    @classmethod
    def _recommend(cls, level, factors):
        recs = []
        if level in ('Critical', 'High'):
            recs.append('Increase monitoring frequency')
            recs.append('Consider segregation review')
        for name, _ in factors:
            low = name.lower()
            if 'escape' in low:
                recs.append('Enhanced perimeter checks')
            if 'violence' in low:
                recs.append('Psychological evaluation')
            if 'disciplinary' in low:
                recs.append('Behavioural intervention program')
        if not recs:
            recs.append('Continue routine supervision')
        return ' | '.join(recs)