# services/ai_visitor.py
"""
Visitor anomaly detection — Pure Python Isolation Forest.
No scikit-learn, numpy, or pandas required.
The algorithm follows Liu, Ting & Zhou (2008) "Isolation Forest".
"""
import os
import math
import random
import pickle
import logging
from datetime import date, datetime, timedelta
from collections import Counter

from extensions import db
from models.visitor import Visitor, VisitLog
from models.ai import AIAnalysisLog, VisitorPattern
from models.notification import Notification

logger = logging.getLogger(__name__)

MODEL_DIR   = 'ml_models'
MODEL_PATH  = os.path.join(MODEL_DIR, 'visitor_anomaly_model.pkl')

MIN_VISITORS_TO_TRAIN   = 10
MIN_VISITS_PER_VISITOR  = 3
CONTAMINATION           = 0.10
LOOKBACK_DAYS           = 180
N_ESTIMATORS            = 100
MAX_SAMPLES             = 256
RANDOM_SEED             = 42


# =====================================================================
# Core Isolation Forest (pure Python)
# =====================================================================
def _c(n):
    """Average path length of unsuccessful BST search — HF correction factor."""
    if n <= 1:
        return 0.0
    return 2.0 * (math.log(n - 1) + 0.5772156649) - 2.0 * (n - 1) / n


class _Node:
    __slots__ = ('size', 'feature', 'split', 'left', 'right', 'is_external')
    def __init__(self, size, feature=None, split=None,
                 left=None, right=None, is_external=False):
        self.size = size
        self.feature = feature
        self.split = split
        self.left = left
        self.right = right
        self.is_external = is_external


def _build_tree(X, indices, depth, max_depth, rng):
    n = len(indices)
    if depth >= max_depth or n <= 1:
        return _Node(size=n, is_external=True)

    d = len(X[0])
    varying = [f for f in range(d)
               if min(X[i][f] for i in indices) != max(X[i][f] for i in indices)]
    if not varying:
        return _Node(size=n, is_external=True)

    f = rng.choice(varying)
    lo = min(X[i][f] for i in indices)
    hi = max(X[i][f] for i in indices)
    split = rng.uniform(lo, hi)

    left  = [i for i in indices if X[i][f] <  split]
    right = [i for i in indices if X[i][f] >= split]
    if not left or not right:
        return _Node(size=n, is_external=True)

    return _Node(
        size=n, feature=f, split=split,
        left=_build_tree(X, left,  depth + 1, max_depth, rng),
        right=_build_tree(X, right, depth + 1, max_depth, rng),
    )


def _path_length(x, node, depth=0):
    if node.is_external:
        return depth + _c(node.size)
    if x[node.feature] < node.split:
        return _path_length(x, node.left,  depth + 1)
    return _path_length(x, node.right, depth + 1)


class PurePythonIsolationForest:
    """Minimal Isolation Forest — sklearn-compatible predict() convention."""

    def __init__(self, n_estimators=N_ESTIMATORS, max_samples=MAX_SAMPLES,
                 contamination=CONTAMINATION, random_state=RANDOM_SEED):
        self.n_estimators  = n_estimators
        self.max_samples   = max_samples
        self.contamination = contamination
        self.seed          = random_state
        self.trees         = []
        self.threshold_    = 0.5

    def fit(self, X):
        n = len(X)
        if n == 0:
            return self
        sample_size = min(self.max_samples, n)
        max_depth   = max(1, int(math.ceil(math.log2(sample_size)))) if sample_size > 1 else 1
        rng = random.Random(self.seed)

        self.trees = []
        for _ in range(self.n_estimators):
            idx = rng.sample(range(n), sample_size)
            self.trees.append(_build_tree(X, idx, 0, max_depth, rng))

        scores = [self._score(x) for x in X]
        scores_sorted = sorted(scores)
        k = int(self.contamination * n)
        if k > 0 and k < n:
            self.threshold_ = scores_sorted[n - k]
        else:
            self.threshold_ = max(scores) if scores else 0.5
        return self

    def _score(self, x):
        if not self.trees:
            return 0.5
        avg = sum(_path_length(x, t) for t in self.trees) / len(self.trees)
        sample_size = max(2, min(self.max_samples,
                                 max(t.size for t in self.trees)))
        cn = _c(sample_size) or 1.0
        return 2 ** (-avg / cn)

    def predict(self, X):
        """-1 = anomaly, 1 = normal (sklearn convention)."""
        return [-1 if self._score(x) >= self.threshold_ else 1 for x in X]


class PurePythonScaler:
    """Z-score standardiser — replaces sklearn.preprocessing.StandardScaler."""
    def __init__(self):
        self.mean_ = []
        self.std_  = []

    def fit(self, X):
        n = len(X)
        if n == 0:
            return self
        d = len(X[0])
        self.mean_ = [sum(row[j] for row in X) / n for j in range(d)]
        self.std_ = []
        for j in range(d):
            var = sum((row[j] - self.mean_[j]) ** 2 for row in X) / n
            self.std_.append(math.sqrt(var) if var > 0 else 1.0)
        return self

    def transform(self, X):
        return [[(row[j] - self.mean_[j]) / (self.std_[j] or 1.0)
                 for j in range(len(row))] for row in X]


# =====================================================================
# Detector
# =====================================================================
class VisitorAnomalyDetector:

    # ---------------- feature extraction ----------------
    @classmethod
    def prepare_features(cls, visitor_id, lookback_days=LOOKBACK_DAYS):
        cutoff = date.today() - timedelta(days=lookback_days)
        visits = (VisitLog.query
                  .filter(VisitLog.visitor_id == visitor_id,
                          VisitLog.visit_date >= cutoff)
                  .order_by(VisitLog.visit_date).all())
        if len(visits) < MIN_VISITS_PER_VISITOR:
            return None

        dates = [v.visit_date for v in visits]
        span  = max((dates[-1] - dates[0]).days, 1)
        freq  = len(visits) / (span / 7.0)

        durations = [v.visit_duration_minutes for v in visits if v.visit_duration_minutes]
        avg_dur   = sum(durations) / len(durations) if durations else 0.0

        gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates) - 1)]
        if gaps:
            mean_gap = sum(gaps) / len(gaps)
            gap_var  = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
        else:
            gap_var = 0.0

        unique_inmates = len({v.inmate_id for v in visits})

        unusual = sum(1 for v in visits
                      if v.check_in_time and (v.check_in_time.hour < 8 or v.check_in_time.hour > 17))
        unusual_ratio = unusual / len(visits)

        items_count = sum(1 for v in visits if v.items_brought)
        days_first  = (date.today() - dates[0]).days

        dow = [d.weekday() for d in dates]
        if len(dow) > 1:
            mean_dow = sum(dow) / len(dow)
            dow_std  = math.sqrt(sum((x - mean_dow) ** 2 for x in dow) / len(dow))
        else:
            dow_std = 0.0

        counts = Counter(v.inmate_id for v in visits)
        max_single = max(counts.values()) if counts else 0
        concentration = max_single / len(visits)

        recent_anom = sum(1 for v in visits if v.anomaly_flagged)

        return [freq, avg_dur, gap_var, unique_inmates,
                unusual_ratio, items_count, days_first,
                dow_std, concentration, recent_anom]

    # ---------------- training ----------------
    @classmethod
    def train_model(cls):
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

        scaler = PurePythonScaler().fit(rows)
        Xs = scaler.transform(rows)

        model = PurePythonIsolationForest(
            n_estimators=N_ESTIMATORS, max_samples=MAX_SAMPLES,
            contamination=CONTAMINATION, random_state=RANDOM_SEED,
        ).fit(Xs)

        os.makedirs(MODEL_DIR, exist_ok=True)
        with open(MODEL_PATH, 'wb') as fh:
            pickle.dump({'model': model, 'scaler': scaler}, fh)

        AIAnalysisLog.log_analysis(
            analysis_type='ModelTraining',
            target_entity='System',
            target_id=None,
            result_summary=f'Visitor anomaly model trained on {len(rows)} samples',
            confidence_score=None,
            severity='Info',
            recommended_action='None',
            model_version='PurePythonIF-v1.0',
        )
        db.session.commit()

        return {'success': True, 'samples': len(rows)}

    # ---------------- analysis ----------------
    @classmethod
    def _load(cls):
        if not os.path.exists(MODEL_PATH):
            return None, None
        with open(MODEL_PATH, 'rb') as fh:
            bundle = pickle.load(fh)
        return bundle['model'], bundle['scaler']

    @classmethod
    def analyze_visitor(cls, visitor_id, model=None, scaler=None):
        if model is None or scaler is None:
            model, scaler = cls._load()
            if model is None:
                return {'success': False, 'error': 'Model not trained yet.'}

        f = cls.prepare_features(visitor_id)
        if f is None:
            return {'success': False, 'error': 'Not enough visit history.',
                    'visitor_id': visitor_id}

        scaled = scaler.transform([f])[0]
        is_anomaly = model.predict([scaled])[0] == -1
        raw_score  = model._score(scaled)
        # Normalise: scores > threshold are anomalies.
        # Map to a 0..1 anomaly-intensity measure anchored at the threshold.
        if model.threshold_ < 1.0:
            anomaly_score = max(0.0, (raw_score - model.threshold_) / (1 - model.threshold_))
        else:
            anomaly_score = 0.0

        if anomaly_score >= 0.5:     severity = 'Critical'
        elif anomaly_score >= 0.25:  severity = 'High'
        elif anomaly_score >= 0.10:  severity = 'Medium'
        else:                        severity = 'Low'

        reason = cls._reason(f)

        visitor = Visitor.query.get(visitor_id)
        if visitor:
            visitor.anomaly_score      = round(anomaly_score, 4)
            visitor.anomaly_flag       = is_anomaly
            visitor.last_anomaly_check = datetime.utcnow()
            db.session.commit()

        cls._update_pattern(visitor_id, f, is_anomaly)

        AIAnalysisLog.log_analysis(
            analysis_type='VisitorAnomaly',
            target_entity='Visitor',
            target_id=visitor_id,
            result_summary=(f'{"Anomaly" if is_anomaly else "Normal"}: {reason}'),
            detailed_result={'features': f,
                             'raw_score': round(raw_score, 4),
                             'anomaly_score': round(anomaly_score, 4),
                             'severity': severity},
            confidence_score=round(anomaly_score, 4),
            anomaly_score=round(anomaly_score, 4),
            severity=severity if is_anomaly else 'Info',
            recommended_action=cls._action(severity) if is_anomaly else 'Continue monitoring.',
            model_version='PurePythonIF-v1.0',
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
        model, scaler = cls._load()
        if model is None:
            return {'success': False, 'error': 'Model not trained yet.'}

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
                                     VisitLog.visit_date >= date.today() - timedelta(days=7))
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
        return '; '.join(reasons) if reasons else 'statistical anomaly in visit pattern'

    @classmethod
    def _action(cls, severity):
        return {
            'Critical': 'Deny entry; escalate to Warden for investigation.',
            'High':     'Additional security screening required before entry.',
            'Medium':   'Flag for security officer attention during visit.',
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