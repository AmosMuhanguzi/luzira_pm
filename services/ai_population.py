# services/ai_population.py
"""
Population forecasting — pure Python rolling mean.
No pandas required.
"""
import logging
from datetime import date, timedelta
from collections import Counter

from extensions import db
from models.inmate import Inmate, AdmissionEpisode
from models.ai import PopulationForecast, AIAnalysisLog
from models.notification import Notification

logger = logging.getLogger(__name__)


class PopulationForecaster:

    DEFAULT_CAPACITY = 3000
    HISTORY_DAYS = 90
    WINDOW = 14

    @classmethod
    def forecast(cls, horizon_days=30, capacity=None):
        capacity = capacity or cls.DEFAULT_CAPACITY
        start = date.today() - timedelta(days=cls.HISTORY_DAYS)

        adm_rows = (db.session.query(AdmissionEpisode.admission_date)
                    .filter(AdmissionEpisode.admission_date >= start)
                    .all())
        rel_rows = (db.session.query(AdmissionEpisode.release_date)
                    .filter(AdmissionEpisode.release_date.isnot(None),
                            AdmissionEpisode.release_date >= start)
                    .all())

        adm_counts = Counter(d for (d,) in adm_rows)
        rel_counts = Counter(d for (d,) in rel_rows)

        # Build daily net series
        net_series = []
        d = start
        while d <= date.today():
            net_series.append(adm_counts.get(d, 0) - rel_counts.get(d, 0))
            d += timedelta(days=1)

        window = net_series[-cls.WINDOW:] if len(net_series) >= cls.WINDOW else net_series
        avg_net = (sum(window) / len(window)) if window else 0.0

        current_pop = Inmate.query.filter_by(status='Active').count()
        predicted   = max(int(round(current_pop + avg_net * horizon_days)), 0)

        utilization = predicted / capacity if capacity else 0
        if   utilization >= 1.0: risk, rnum = 'Critical', 1.0
        elif utilization >= 0.9: risk, rnum = 'High',     0.8
        elif utilization >= 0.8: risk, rnum = 'Medium',   0.5
        else:                    risk, rnum = 'Low',      0.2

        avg_adm = (sum(adm_counts.values()) / max(len(net_series), 1))
        avg_rel = (sum(rel_counts.values()) / max(len(net_series), 1))

        fc = PopulationForecast(
            forecast_date=date.today() + timedelta(days=horizon_days),
            forecast_period=f'Next {horizon_days} days',
            predicted_population=predicted,
            predicted_admissions=int(avg_adm * horizon_days),
            predicted_releases=int(avg_rel * horizon_days),
            predicted_overcrowding_risk=rnum,
            current_capacity=capacity,
            projected_capacity=capacity,
            capacity_utilization=round(utilization * 100, 2),
            model_confidence=0.75,
            based_on_data_from=start,
            based_on_data_to=date.today(),
            generated_by_model='RollingMean-14d-py-v1.0',
        )
        db.session.add(fc)

        AIAnalysisLog.log_analysis(
            analysis_type='PopulationForecast',
            target_entity='Facility',
            target_id=None,
            result_summary=(f'Predicted population in {horizon_days}d: {predicted} '
                            f'({utilization*100:.1f}% of capacity). Risk: {risk}.'),
            detailed_result={'current_population': current_pop,
                             'predicted_population': predicted,
                             'capacity': capacity,
                             'utilization_percent': round(utilization * 100, 2),
                             'net_daily_change': round(avg_net, 2)},
            confidence_score=0.75,
            severity='High' if risk in ('High', 'Critical') else 'Info',
            recommended_action=('Plan early release review or inter-facility transfer.'
                                if risk in ('High', 'Critical')
                                else 'Continue monitoring.'),
            model_version='RollingMean-14d-py-v1.0',
        )

        if risk in ('High', 'Critical'):
            Notification.create_ai_alert(
                title=f'Population alert: {risk}',
                message=(f'Predicted {predicted} inmates in {horizon_days} days '
                         f'({utilization*100:.1f}% of {capacity}).'),
                related_entity_type='Facility',
                related_entity_id=None,
                severity='Critical' if risk == 'Critical' else 'High',
            )

        db.session.commit()

        return {'success': True,
                'forecast_date': (date.today() + timedelta(days=horizon_days)).isoformat(),
                'current_population': current_pop,
                'predicted_population': predicted,
                'capacity': capacity,
                'utilization_percent': round(utilization * 100, 2),
                'overcrowding_risk': risk,
                'net_daily_change': round(avg_net, 2)}