# services/ai_visitor.py
"""Visitor anomaly detection using weekly frequency features and Isolation Forest."""
import os
import logging
import tempfile
from datetime import date, datetime, timedelta
from io import BytesIO

import joblib
import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from extensions import db
from models.visitor import Visitor, VisitLog
from models.ai import AIAnalysisLog, VisitorPattern
from models.notification import Notification

logger = logging.getLogger(__name__)

MODEL_DIR   = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ml_models')
MODEL_PATH  = os.path.join(MODEL_DIR, 'visitor_anomaly_model.joblib')

MIN_VISITORS_TO_TRAIN   = 10
MIN_VISITS_PER_VISITOR  = 3
CONTAMINATION           = 0.10
LOOKBACK_DAYS           = 180
N_ESTIMATORS            = 100
MAX_SAMPLES             = 256
RANDOM_SEED             = 42
WEEK_BUCKETS = (LOOKBACK_DAYS + 6) // 7


def _load_sklearn_components():
    try:
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import StandardScaler
    except ImportError as error:
        return None, None, error
    return IsolationForest, StandardScaler, None


# =====================================================================
# Detector
# =====================================================================
class VisitorAnomalyDetector:

    # ---------------- feature extraction ----------------
    @classmethod
    def prepare_features(cls, visitor_id, lookback_days=LOOKBACK_DAYS):
        today = date.today()
        cutoff = today - timedelta(days=lookback_days)
        cutoff_at = datetime.combine(cutoff, datetime.min.time())
        visits = (VisitLog.query
                  .filter(VisitLog.visitor_id == visitor_id,
                          VisitLog.check_in_time >= cutoff_at)
                  .order_by(VisitLog.check_in_time).all())
        if len(visits) < MIN_VISITS_PER_VISITOR:
            return None

        dates = [v.check_in_time.date() for v in visits if v.check_in_time]
        if len(dates) < MIN_VISITS_PER_VISITOR:
            return None
        span  = max((dates[-1] - dates[0]).days, 1)
        freq  = len(dates) / (span / 7.0)

        durations = [
            v.duration_minutes for v in visits
            if v.duration_minutes is not None
        ]
        avg_dur   = float(np.mean(durations)) if durations else 0.0

        gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates) - 1)]
        gap_var = float(np.var(gaps)) if gaps else 0.0

        unique_inmates = len({v.inmate_id for v in visits})

        unusual = sum(1 for v in visits
                      if v.check_in_time and (v.check_in_time.hour < 8 or v.check_in_time.hour > 17))
        unusual_ratio = unusual / len(visits)

        items_count = sum(1 for v in visits if v.items_brought)
        days_first  = (today - dates[0]).days

        dow = [d.weekday() for d in dates]
        dow_std = float(np.std(dow)) if len(dow) > 1 else 0.0

        counts = pd.Series([v.inmate_id for v in visits]).value_counts()
        max_single = int(counts.max()) if not counts.empty else 0
        concentration = max_single / len(visits)

        recent_anom = sum(1 for v in visits if getattr(v, 'anomaly_flag', False))

        visit_times = pd.DatetimeIndex(
            v.check_in_time for v in visits if v.check_in_time
        )
        week_numbers = (
            (visit_times.normalize() - pd.Timestamp(cutoff)).days // 7
        )
        weekly_counts = (
            pd.Series(1, index=week_numbers, dtype='int64')
            .groupby(level=0)
            .sum()
            .reindex(range(WEEK_BUCKETS), fill_value=0)
        )
        weekly_features = weekly_counts.to_numpy(dtype=np.float64).tolist()

        return [
            freq, avg_dur, gap_var, unique_inmates,
            unusual_ratio, items_count, days_first,
            dow_std, concentration, recent_anom,
            *weekly_features,
        ]

    # ---------------- training ----------------
    @classmethod
    def train_model(cls):
        isolation_forest, standard_scaler, import_error = _load_sklearn_components()
        if import_error:
            return {
                'success': False,
                'error': (
                    'scikit-learn could not be loaded because one of its native '
                    f'dependencies failed: {import_error}'
                ),
            }

        rows = []
        for v in Visitor.query.all():
            f = cls.prepare_features(v.visitor_id)
            if f is not None:
                rows.append(f)

        if len(rows) < MIN_VISITORS_TO_TRAIN:
            return {
                'success': False,
                'error': (f'Need at least {MIN_VISITORS_TO_TRAIN} visitors with '
                          f'>={MIN_VISITS_PER_VISITOR} visits to train. '
                          f'Currently have {len(rows)}.'),
                'samples': len(rows),
            }

        feature_matrix = np.asarray(rows, dtype=np.float64)
        scaler = standard_scaler().fit(feature_matrix)
        Xs = scaler.transform(feature_matrix)
        model = isolation_forest(
            n_estimators=N_ESTIMATORS,
            max_samples=min(MAX_SAMPLES, len(rows)),
            contamination=CONTAMINATION,
            random_state=RANDOM_SEED,
        ).fit(Xs)
        model.training_scores_ = np.sort(model.decision_function(Xs))

        os.makedirs(MODEL_DIR, exist_ok=True)
        bundle = {
            'model': model,
            'scaler': scaler,
            'feature_version': 2,
            'trained_at': datetime.utcnow().isoformat(),
            'training_samples': len(rows),
        }
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=MODEL_DIR,
                prefix='.visitor-anomaly-',
                suffix='.tmp',
                delete=False,
            ) as temporary_file:
                temporary_path = temporary_file.name
            joblib.dump(bundle, temporary_path)
            os.replace(temporary_path, MODEL_PATH)
            temporary_path = None
        except OSError as error:
            logger.exception('Could not save the trained visitor anomaly model.')
            return {
                'success': False,
                'error': f'Could not save the trained visitor anomaly model: {error}',
            }
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

        AIAnalysisLog.log_analysis(
            analysis_type='ModelTraining',
            target_entity='System',
            target_id=None,
            result_summary=f'Visitor anomaly model trained on {len(rows)} samples',
            detailed_result={
                'algorithm': 'sklearn.ensemble.IsolationForest',
                'feature_set': '180-day weekly visit-frequency time series plus behavior indicators',
                'contamination': CONTAMINATION,
                'training_samples': len(rows),
            },
            confidence_score=None,
            severity='Info',
            recommended_action='None',
            model_version='SklearnIF-Weekly-v2.0',
        )
        db.session.commit()

        return {
            'success': True,
            'samples': len(rows),
            'algorithm': 'scikit-learn Isolation Forest',
            'feature_version': 2,
        }

    # ---------------- analysis ----------------
    @classmethod
    def _load(cls):
        _, _, import_error = _load_sklearn_components()
        if import_error:
            raise RuntimeError(
                'scikit-learn could not be loaded because one of its native '
                f'dependencies failed: {import_error}'
            )
        if not os.path.exists(MODEL_PATH):
            return None, None
        if os.path.getsize(MODEL_PATH) == 0:
            logger.warning(
                'Visitor anomaly model artifact is empty; it will be retrained.'
            )
            return None, None
        try:
            bundle = joblib.load(MODEL_PATH)
        except (EOFError, OSError, ValueError, KeyError, AttributeError, ImportError) as error:
            logger.warning(
                'Visitor anomaly model artifact is unreadable and will be retrained: %s',
                error,
            )
            return None, None
        if not isinstance(bundle, dict):
            logger.warning(
                'Visitor anomaly model artifact has an invalid structure; it will be retrained.'
            )
            return None, None
        if bundle.get('feature_version') != 2:
            logger.warning(
                'Stored visitor model feature version is unsupported; it will be retrained.'
            )
            return None, None
        if 'model' not in bundle or 'scaler' not in bundle:
            logger.warning(
                'Visitor anomaly model artifact is incomplete; it will be retrained.'
            )
            return None, None
        return bundle['model'], bundle['scaler']

    @classmethod
    def analyze_visitor(cls, visitor_id, model=None, scaler=None):
        if model is None or scaler is None:
            try:
                model, scaler = cls._load()
            except RuntimeError as error:
                return {'success': False, 'error': str(error)}
            if model is None:
                training = cls.train_model()
                if not training.get('success'):
                    return {
                        'success': False,
                        'error': training.get(
                            'error',
                            'Visitor anomaly model is unavailable and could not be retrained.',
                        ),
                    }
                try:
                    model, scaler = cls._load()
                except RuntimeError as error:
                    return {'success': False, 'error': str(error)}
                if model is None:
                    return {
                        'success': False,
                        'error': 'Visitor anomaly model training completed, but the saved model could not be loaded.',
                    }

        f = cls.prepare_features(visitor_id)
        if f is None:
            return {'success': False, 'error': 'Not enough visit history.',
                    'visitor_id': visitor_id}

        scaled = scaler.transform(np.asarray([f], dtype=np.float64))
        is_anomaly = bool(model.predict(scaled)[0] == -1)
        decision_score = float(model.decision_function(scaled)[0])
        training_scores = getattr(model, 'training_scores_', np.array([]))
        if len(training_scores):
            lower_tail_rank = np.searchsorted(
                training_scores, decision_score, side='left'
            ) / len(training_scores)
            anomaly_score = float(np.clip(1.0 - lower_tail_rank, 0.0, 1.0))
        else:
            anomaly_score = float(is_anomaly)

        if is_anomaly and anomaly_score >= 0.99: severity = 'Critical'
        elif is_anomaly and anomaly_score >= 0.97: severity = 'High'
        elif is_anomaly:                          severity = 'Medium'
        else:                                     severity = 'Low'

        reason = cls._reason(f)

        visitor = Visitor.query.get(visitor_id)
        if visitor:
            visitor.anomaly_score      = round(anomaly_score, 4)
            visitor.anomaly_flag       = is_anomaly
            db.session.commit()

        cls._update_pattern(visitor_id, f, is_anomaly)

        AIAnalysisLog.log_analysis(
            analysis_type='VisitorAnomaly',
            target_entity='Visitor',
            target_id=visitor_id,
            result_summary=(f'{"Anomaly" if is_anomaly else "Normal"}: {reason}'),
            detailed_result={'features': f,
                             'weekly_visit_counts': f[10:],
                             'model_decision_score': round(decision_score, 6),
                             'statistical_risk_index': round(anomaly_score, 4),
                             'risk_interpretation': (
                                 'Unsupervised activity-pattern screening index; '
                                 'not a calibrated probability of contraband smuggling.'
                             ),
                             'severity': severity},
            confidence_score=None,
            anomaly_score=round(anomaly_score, 4),
            severity=severity if is_anomaly else 'Info',
            recommended_action=cls._action(severity) if is_anomaly else 'Continue monitoring.',
            model_version='SklearnIF-Weekly-v2.0',
        )

        if is_anomaly and severity in ('High', 'Critical') and visitor:
            Notification.create_ai_alert(
                title=f'Visitor anomaly: {visitor.full_name}',
                message=reason,
                related_entity_type='Visitor',
                related_entity_id=visitor_id,
                severity=severity,
            )
        db.session.commit()

        return {'success': True, 'visitor_id': visitor_id,
                'is_anomaly': is_anomaly,
                'anomaly_score': round(anomaly_score, 4),
                'severity': severity, 'reason': reason}

    @classmethod
    def analyze_all(cls):
        try:
            model, scaler = cls._load()
        except RuntimeError as error:
            return {'success': False, 'error': str(error)}
        if model is None:
            training = cls.train_model()
            if not training.get('success'):
                return {
                    'success': False,
                    'error': training.get(
                        'error',
                        'Visitor anomaly model is unavailable and could not be retrained.',
                    ),
                }
            try:
                model, scaler = cls._load()
            except RuntimeError as error:
                return {'success': False, 'error': str(error)}
            if model is None:
                return {
                    'success': False,
                    'error': 'Visitor anomaly model training completed, but the saved model could not be loaded.',
                }

        analyzed = flagged = skipped = 0
        for v in Visitor.query.all():
            r = cls.analyze_visitor(v.visitor_id, model=model, scaler=scaler)
            if r.get('success'):
                analyzed += 1
                if r.get('is_anomaly'):
                    flagged += 1
            else:
                skipped += 1
        return {'success': True, 'analyzed': analyzed,
                'flagged': flagged, 'skipped': skipped}

    # ---------------- real-time heuristic (unchanged) ----------------
    @staticmethod
    def check_visit_anomaly(visitor_id, inmate_id, when=None):
        when = when or datetime.utcnow()
        visitor = Visitor.query.get(visitor_id)
        if not visitor:
            return {'is_anomaly': False, 'score': 0.0, 'reason': None, 'severity': 'Info'}

        reasons = []
        score = 0.0

        if visitor.anomaly_flag:
            reasons.append('Existing anomaly flag on file')
            score += 0.30
        if when.hour < 8 or when.hour > 17:
            reasons.append(f'Visit outside standard hours ({when.hour:02d}:00)')
            score += 0.20

        last_24h = VisitLog.query.filter(
            VisitLog.visitor_id == visitor_id,
            VisitLog.check_in_time >= when - timedelta(hours=24),
        ).count()
        if last_24h >= 2:
            reasons.append(f'{last_24h} visits in last 24 hours')
            score += 0.25

        unique_inmates_7d = (db.session.query(VisitLog.inmate_id)
                             .filter(VisitLog.visitor_id == visitor_id,
                                     VisitLog.check_in_time >= datetime.combine(
                                         date.today() - timedelta(days=7),
                                         datetime.min.time(),
                                     ))
                             .distinct().count())
        if unique_inmates_7d >= 3:
            reasons.append(f'Visiting {unique_inmates_7d} different inmates in 7 days')
            score += 0.20

        prior_to_this_inmate = VisitLog.query.filter_by(
            visitor_id=visitor_id, inmate_id=inmate_id
        ).count()
        if prior_to_this_inmate == 0 and (visitor.total_visits or 0) > 5:
            reasons.append('First visit to this inmate despite long history')
            score += 0.15

        is_anomaly = score >= 0.40
        if   score >= 0.70: severity = 'Critical'
        elif score >= 0.50: severity = 'High'
        elif score >= 0.40: severity = 'Medium'
        else:               severity = 'Info'

        return {'is_anomaly': is_anomaly,
                'score': round(min(score, 1.0), 4),
                'reason': '; '.join(reasons) if reasons else None,
                'severity': severity}

    # ---------------- helpers ----------------
    @classmethod
    def _reason(cls, f):
        reasons = []
        if f[0] > 5:    reasons.append('unusually high visit frequency')
        if f[4] > 0.3:  reasons.append('frequent out-of-hours visits')
        if f[3] > 5:    reasons.append('visiting unusually many inmates')
        if f[8] < 0.3:  reasons.append('no clear primary inmate association')
        if f[9] > 0:    reasons.append('prior flagged visits')
        if len(f) > 17 and sum(f[-4:]) > sum(f[-8:-4]):
            reasons.append('recent weekly visit frequency is increasing')
        return '; '.join(reasons) if reasons else 'statistical anomaly in visit pattern'

    @classmethod
    def _action(cls, severity):
        return {
            'Critical': 'Immediate human review and secondary screening by security.',
            'High':     'Review visitor history and apply additional security screening.',
            'Medium':   'Flag for security officer attention during the visit.',
            'Low':      'Continue monitoring.',
        }.get(severity, 'Continue monitoring.')

    @staticmethod
    def _update_pattern(visitor_id, f, is_anomaly):
        p = VisitorPattern.query.filter_by(visitor_id=visitor_id).first()
        if not p:
            p = VisitorPattern(visitor_id=visitor_id)
            db.session.add(p)
        p.avg_visit_frequency_days   = float(f[0]) if f[0] else None
        p.avg_visit_duration_minutes = float(f[1]) if f[1] else None
        p.unusual_time_visits        = int(f[4] * 10)
        p.multiple_inmate_associations = int(f[3])
        p.rapid_succession_visits    = int(f[2] > 5)
        p.total_flagged_visits       = int(f[9])
        if is_anomaly:
            p.last_flagged_date = date.today()
        p.calculated_at = datetime.utcnow()
        db.session.commit()

    @classmethod
    def weekly_activity_chart(cls):
        """Return an in-memory PNG of weekly visitor visit counts."""
        start = date.today() - timedelta(weeks=12)
        rows = db.session.query(VisitLog.check_in_time).filter(
            VisitLog.check_in_time >= datetime.combine(
                start, datetime.min.time()
            )
        ).all()
        timestamps = [timestamp for (timestamp,) in rows if timestamp]
        if timestamps:
            visits = pd.Series(
                1, index=pd.DatetimeIndex(timestamps), dtype='int64'
            ).resample('W-SUN').sum()
        else:
            visits = pd.Series(dtype='int64')
        weekly_index = pd.date_range(
            start=pd.Timestamp(start),
            end=pd.Timestamp(date.today()),
            freq='W-SUN',
        )
        visits = visits.reindex(weekly_index, fill_value=0)

        figure = Figure(figsize=(9, 3.2), tight_layout=True)
        axis = figure.subplots()
        axis.plot(
            visits.index,
            visits.to_numpy(dtype=np.int64),
            color='#0d6efd',
            marker='o',
            linewidth=2,
        )
        axis.set_title('Visitor Check-ins per Week')
        axis.set_ylabel('Visits')
        axis.set_xlabel('Week')
        axis.grid(True, alpha=0.25)
        figure.autofmt_xdate()

        image = BytesIO()
        FigureCanvasAgg(figure).print_png(image)
        image.seek(0)
        return image