# =====================================================
# ai_service.py - AI/ML Module for Prison Management System
# =====================================================

import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib
import os
import logging
from flask import current_app

from models import db, Visitor, VisitLog, Inmate, AIAnalysisLog, VisitorPattern, PopulationForecast

logger = logging.getLogger(__name__)


class VisitorAnomalyDetector:
    """
    AI module for detecting anomalous visitor behavior patterns
    Uses Isolation Forest for unsupervised anomaly detection
    """
    
    MODEL_PATH = 'ml_models/visitor_anomaly_model.joblib'
    SCALER_PATH = 'ml_models/visitor_scaler.joblib'
    CONTAMINATION = 0.1  # Expected proportion of anomalies
    
    @classmethod
    def prepare_visitor_features(cls, visitor_id, lookback_days=90):
        """
        Extract feature vector for a visitor based on historical data
        
        Features:
        1. Visit frequency (visits per week)
        2. Average visit duration
        3. Time between visits (variance)
        4. Number of different inmates visited
        5. Ratio of visits during unusual hours
        6. Number of visits with items brought
        7. Days since first visit
        8. Visit consistency (standard deviation of visit days)
        """
        cutoff_date = date.today() - timedelta(days=lookback_days)
        
        visits = VisitLog.query.filter(
            VisitLog.visitor_id == visitor_id,
            VisitLog.check_in_time >= datetime.combine(
                cutoff_date, datetime.min.time()
            )
        ).order_by(VisitLog.visit_date).all()
        
        if len(visits) < 3:
            # Not enough data for meaningful analysis
            return None
        
        # Feature 1: Visit frequency (visits per week)
        date_range = (visits[-1].visit_date - visits[0].visit_date).days or 1
        visit_frequency = len(visits) / (date_range / 7)
        
        # Feature 2: Average visit duration
        durations = [v.visit_duration_minutes for v in visits if v.visit_duration_minutes]
        avg_duration = np.mean(durations) if durations else 0
        
        # Feature 3: Time between visits (variance)
        visit_dates = [v.visit_date for v in visits]
        if len(visit_dates) > 1:
            gaps = [(visit_dates[i+1] - visit_dates[i]).days for i in range(len(visit_dates)-1)]
            gap_variance = np.var(gaps) if gaps else 0
        else:
            gap_variance = 0
        
        # Feature 4: Number of different inmates visited
        unique_inmates = len(set(v.inmate_id for v in visits))
        
        # Feature 5: Ratio of visits during unusual hours (before 8am or after 5pm)
        unusual_hour_visits = sum(
            1 for v in visits 
            if v.check_in_time and (v.check_in_time.hour < 8 or v.check_in_time.hour > 17)
        )
        unusual_hour_ratio = unusual_hour_visits / len(visits)
        
        # Feature 6: Number of visits with items brought
        items_visits = sum(1 for v in visits if v.items_brought)
        
        # Feature 7: Days since first visit
        days_since_first = (date.today() - visits[0].visit_date).days
        
        # Feature 8: Visit consistency (std dev of visit days of week)
        visit_days = [v.visit_date.weekday() for v in visits]
        day_consistency = np.std(visit_days) if len(visit_days) > 1 else 0
        
        # Feature 9: Multiple inmate association ratio
        inmate_visit_counts = {}
        for v in visits:
            inmate_visit_counts[v.inmate_id] = inmate_visit_counts.get(v.inmate_id, 0) + 1
        max_inmate_visits = max(inmate_visit_counts.values()) if inmate_visit_counts else 0
        inmate_concentration = max_inmate_visits / len(visits)
        
        # Feature 10: Recent anomaly history
        recent_anomalies = sum(1 for v in visits if v.anomaly_flagged)
        
        features = [
            visit_frequency,
            avg_duration,
            gap_variance,
            unique_inmates,
            unusual_hour_ratio,
            items_visits,
            days_since_first,
            day_consistency,
            inmate_concentration,
            recent_anomalies
        ]
        
        return np.array(features).reshape(1, -1)
    
    @classmethod
    def train_model(cls, contamination=None):
        """
        Train Isolation Forest model on historical visitor data
        """
        if contamination is None:
            contamination = cls.CONTAMINATION
        
        # Get all visitors with sufficient visit history
        visitors = Visitor.query.filter(
            Visitor.total_visits >= 3
        ).all()
        
        if len(visitors) < 10:
            logger.warning("Insufficient data for model training")
            return None
        
        # Extract features for all visitors
        feature_matrix = []
        
        for visitor in visitors:
            features = cls.prepare_visitor_features(visitor.visitor_id)
            if features is not None:
                feature_matrix.append(features.flatten())
        
        if len(feature_matrix) < 10:
            logger.warning("Insufficient feature vectors for training")
            return None
        
        X = np.array(feature_matrix)
        
        # Scale features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Train Isolation Forest
        model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100,
            max_samples='auto',
            bootstrap=False
        )
        
        model.fit(X_scaled)
        
        # Save model and scaler
        os.makedirs('ml_models', exist_ok=True)
        joblib.dump(model, cls.MODEL_PATH)
        joblib.dump(scaler, cls.SCALER_PATH)
        
        logger.info(f"Model trained on {len(feature_matrix)} samples")
        
        return model
    
    @classmethod
    def load_model(cls):
        """
        Load trained model from disk
        """
        if os.path.exists(cls.MODEL_PATH) and os.path.exists(cls.SCALER_PATH):
            model = joblib.load(cls.MODEL_PATH)
            scaler = joblib.load(cls.SCALER_PATH)
            return model, scaler
        return None, None
    
    @classmethod
    def analyze_visitor(cls, visitor_id):
        """
        Analyze a single visitor for anomalies
        """
        model, scaler = cls.load_model()
        
        if model is None:
            # Train model if not exists
            model = cls.train_model()
            if model is None:
                return {
                    'success': False,
                    'error': 'Model not available'
                }
            _, scaler = cls.load_model()
        
        features = cls.prepare_visitor_features(visitor_id)
        
        if features is None:
            return {
                'success': False,
                'error': 'Insufficient data for analysis',
                'visitor_id': visitor_id
            }
        
        # Scale features
        features_scaled = scaler.transform(features)
        
        # Predict anomaly
        prediction = model.predict(features_scaled)[0]  # -1 for anomaly, 1 for normal
        anomaly_score = model.decision_function(features_scaled)[0]
        
        is_anomaly = prediction == -1
        
        # Determine severity based on score
        if anomaly_score < -0.3:
            severity = 'Critical'
        elif anomaly_score < -0.2:
            severity = 'High'
        elif anomaly_score < -0.1:
            severity = 'Medium'
        else:
            severity = 'Low'
        
        # Generate reason
        reason = cls._generate_anomaly_reason(visitor_id, features.flatten())
        
        # Update visitor record
        visitor = Visitor.query.get(visitor_id)
        if visitor:
            visitor.anomaly_score = abs(anomaly_score)
            visitor.anomaly_flag = is_anomaly
            visitor.last_anomaly_check = datetime.utcnow()
            
            # Log analysis
            AIAnalysisLog.log_analysis(
                analysis_type='Visitor Anomaly',
                target_entity='Visitor',
                target_id=visitor_id,
                result_summary=f"Anomaly detected: {is_anomaly}",
                detailed_result={
                    'anomaly_score': float(anomaly_score),
                    'features': features.flatten().tolist(),
                    'reason': reason
                },
                confidence_score=abs(anomaly_score),
                anomaly_score=abs(anomaly_score),
                severity=severity,
                recommended_action=cls._get_recommended_action(severity)
            )
            
            db.session.commit()
        
        return {
            'success': True,
            'visitor_id': visitor_id,
            'is_anomaly': is_anomaly,
            'anomaly_score': float(abs(anomaly_score)),
            'severity': severity,
            'reason': reason
        }
    
    @classmethod
    def check_visit_anomaly(cls, visitor_id, inmate_id, visit_time):
        """
        Real-time anomaly check for a specific visit
        """
        visitor = Visitor.query.get(visitor_id)
        
        if not visitor:
            return {'is_anomaly': False, 'score': 0, 'reason': None}
        
        reasons = []
        anomaly_score = 0
        
        # Check 1: Is visitor already flagged?
        if visitor.anomaly_flag:
            reasons.append("Visitor has existing anomaly flags")
            anomaly_score += 0.3
        
        # Check 2: Unusual visit time
        if visit_time.hour < 8 or visit_time.hour > 17:
            reasons.append(f"Visit outside normal hours ({visit_time.hour}:00)")
            anomaly_score += 0.2
        
        # Check 3: Rapid succession visits
        recent_visits = VisitLog.query.filter(
            VisitLog.visitor_id == visitor_id,
            VisitLog.check_in_time >= datetime.combine(
                date.today() - timedelta(days=1), datetime.min.time()
            )
        ).count()
        
        if recent_visits >= 2:
            reasons.append(f"Multiple visits in 24 hours ({recent_visits})")
            anomaly_score += 0.25
        
        # Check 4: Visiting multiple inmates in short period
        recent_inmates = db.session.query(VisitLog.inmate_id)\
            .filter(
                VisitLog.visitor_id == visitor_id,
                VisitLog.check_in_time >= datetime.combine(
                    date.today() - timedelta(days=7), datetime.min.time()
                )
            ).distinct().count()
        
        if recent_inmates >= 3:
            reasons.append(f"Visiting multiple inmates ({recent_inmates} in 7 days)")
            anomaly_score += 0.2
        
        # Check 5: First visit to this inmate
        previous_visits_to_inmate = VisitLog.query.filter(
            VisitLog.visitor_id == visitor_id,
            VisitLog.inmate_id == inmate_id
        ).count()
        
        if previous_visits_to_inmate == 0 and visitor.total_visits > 5:
            reasons.append("First visit to this inmate despite history")
            anomaly_score += 0.15
        
        is_anomaly = anomaly_score >= 0.4
        
        # Determine severity
        if anomaly_score >= 0.7:
            severity = 'Critical'
        elif anomaly_score >= 0.5:
            severity = 'High'
        elif anomaly_score >= 0.4:
            severity = 'Medium'
        else:
            severity = 'Low'
        
        return {
            'is_anomaly': is_anomaly,
            'score': min(anomaly_score, 1.0),
            'reason': '; '.join(reasons) if reasons else None,
            'severity': severity if is_anomaly else 'Info'
        }
    
    @classmethod
    def _generate_anomaly_reason(cls, visitor_id, features):
        """
        Generate human-readable reason for anomaly detection
        """
        reasons = []
        
        # Feature indices:
        # 0: visit_frequency, 1: avg_duration, 2: gap_variance, 3: unique_inmates
        # 4: unusual_hour_ratio, 5: items_visits, 6: days_since_first
        # 7: day_consistency, 8: inmate_concentration, 9: recent_anomalies
        
        if features[0] > 5:  # Visit frequency > 5 per week
            reasons.append("Unusually high visit frequency")
        
        if features[4] > 0.3:  # >30% unusual hours
            reasons.append("Frequent visits during unusual hours")
        
        if features[3] > 5:  # More than 5 different inmates
            reasons.append("Visiting unusually many different inmates")
        
        if features[8] < 0.3:  # Low concentration on single inmate
            reasons.append("No clear primary inmate association")
        
        if features[9] > 0:  # Previous anomalies
            reasons.append("History of flagged visits")
        
        if not reasons:
            reasons.append("Statistical anomaly in visit pattern")
        
        return '; '.join(reasons)
    
    @classmethod
    def _get_recommended_action(cls, severity):
        """
        Get recommended action based on severity
        """
        actions = {
            'Critical': 'Immediate review required. Consider denying visit and investigating.',
            'High': 'Review visitor history and consider additional security screening.',
            'Medium': 'Flag for security officer attention during next visit.',
            'Low': 'Monitor for pattern development.'
        }
        return actions.get(severity, 'Continue monitoring.')


class PopulationForecaster:
    """
    AI module for forecasting prison population and overcrowding risk
    """
    
    @classmethod
    def forecast_population(cls, forecast_days=30):
        """
        Forecast prison population for the next N days
        """
        # Get historical admission and release data
        history_days = 90
        today = date.today()
        start_date = today - timedelta(days=history_days)
        
        # Daily admissions
        admissions = db.session.query(
            AdmissionEpisode.admission_date,
            db.func.count(AdmissionEpisode.episode_id)
        ).filter(
            AdmissionEpisode.admission_date >= start_date,
            AdmissionEpisode.admission_date <= today
        ).group_by(AdmissionEpisode.admission_date).all()
        
        # Daily releases
        releases = db.session.query(
            AdmissionEpisode.release_date,
            db.func.count(AdmissionEpisode.episode_id)
        ).filter(
            AdmissionEpisode.release_date >= start_date,
            AdmissionEpisode.release_date.isnot(None),
            AdmissionEpisode.release_date <= today
        ).group_by(AdmissionEpisode.release_date).all()
        
        # Create dataframes
        admission_df = pd.DataFrame(admissions, columns=['date', 'admissions'])
        release_df = pd.DataFrame(releases, columns=['date', 'releases'])
        
        # Merge and fill missing dates
        date_range = pd.date_range(start=start_date, end=today)
        
        admission_df = admission_df.set_index('date').reindex(date_range, fill_value=0)
        release_df = release_df.set_index('date').reindex(date_range, fill_value=0)
        
        # Calculate net change
        daily_change = admission_df['admissions'] - release_df['releases']
        
        # Get current population
        current_population = Inmate.query.filter(Inmate.status == 'Active').count()
        
        # Simple moving average forecast
        avg_daily_change = daily_change.rolling(window=14, min_periods=1).mean().iloc[-1]
        
        # Forecast
        forecast_date = today + timedelta(days=forecast_days)
        predicted_population = max(
            int(round(current_population + (avg_daily_change * forecast_days))),
            0,
        )

        capacity = current_app.config.get('FACILITY_CAPACITY', 30000)
        if capacity <= 0:
            raise ValueError('Facility capacity must be greater than zero.')
        
        # Overcrowding risk
        utilization = predicted_population / capacity
        
        if utilization > 1.0:
            risk_level = 'Critical'
            overcrowding_risk = 1.0
        elif utilization > 0.9:
            risk_level = 'High'
            overcrowding_risk = 0.8
        elif utilization > 0.8:
            risk_level = 'Medium'
            overcrowding_risk = 0.5
        else:
            risk_level = 'Low'
            overcrowding_risk = 0.2
        
        # Save forecast
        forecast = PopulationForecast(
            forecast_date=forecast_date,
            forecast_period=f'Next {forecast_days} days',
            predicted_population=predicted_population,
            predicted_admissions=int(admission_df['admissions'].mean() * forecast_days),
            predicted_releases=int(release_df['releases'].mean() * forecast_days),
            predicted_overcrowding_risk=overcrowding_risk,
            current_capacity=capacity,
            projected_capacity=capacity,
            capacity_utilization=utilization * 100,
            model_confidence=0.75,  # Based on data quality
            based_on_data_from=start_date,
            based_on_data_to=today,
            generated_by_model='Moving Average v1.0'
        )
        
        db.session.add(forecast)
        db.session.commit()
        
        return {
            'success': True,
            'forecast_date': forecast_date.isoformat(),
            'current_population': current_population,
            'predicted_population': predicted_population,
            'capacity': capacity,
            'utilization_percent': round(utilization * 100, 1),
            'overcrowding_risk': risk_level,
            'avg_daily_change': round(avg_daily_change, 2)
        }


class InmateRiskProfiler:
    """
    AI module for profiling inmate behavioral risk
    """
    
    @classmethod
    def calculate_risk_score(cls, inmate_id):
        """
        Calculate comprehensive risk score for an inmate
        """
        inmate = Inmate.query.get(inmate_id)
        
        if not inmate:
            return {'success': False, 'error': 'Inmate not found'}
        
        risk_factors = []
        risk_score = 0
        
        # Factor 1: Crime severity
        severe_crimes = ['Murder', 'Rape', 'Armed Robbery', 'Treason', 'Kidnapping']
        if inmate.crime_category in severe_crimes:
            risk_score += 25
            risk_factors.append(('Severe crime category', 25))
        
        # Factor 2: Violence history
        if inmate.violence_history:
            risk_score += 20
            risk_factors.append(('History of violence', 20))
        
        # Factor 3: Escape attempt history
        if inmate.escape_attempt_history:
            risk_score += 30
            risk_factors.append(('Previous escape attempt', 30))
        
        # Factor 4: Disciplinary incidents
        disciplinary_count = DisciplinaryLog.query.filter_by(inmate_id=inmate_id).count()
        if disciplinary_count > 0:
            points = min(disciplinary_count * 5, 20)
            risk_score += points
            risk_factors.append((f'{disciplinary_count} disciplinary incidents', points))
        
        # Factor 5: Repeat offender
        if inmate.total_admissions > 1:
            points = min((inmate.total_admissions - 1) * 10, 20)
            risk_score += points
            risk_factors.append((f'Repeat offender ({inmate.total_admissions} admissions)', points))
        
        # Factor 6: Security classification
        if inmate.security_classification == 'Maximum':
            risk_score += 15
            risk_factors.append(('Maximum security classification', 15))
        
        # Normalize to 0-100
        risk_score = min(risk_score, 100)
        
        # Determine risk level
        if risk_score >= 80:
            risk_level = 'Critical'
        elif risk_score >= 60:
            risk_level = 'High'
        elif risk_score >= 40:
            risk_level = 'Medium'
        else:
            risk_level = 'Low'
        
        # Update inmate record
        inmate.risk_level = risk_level
        db.session.commit()
        
        return {
            'success': True,
            'inmate_id': inmate_id,
            'risk_score': risk_score,
            'risk_level': risk_level,
            'risk_factors': risk_factors,
            'recommendations': cls._get_recommendations(risk_level, risk_factors)
        }
    
    @classmethod
    def _get_recommendations(cls, risk_level, risk_factors):
        """
        Get recommendations based on risk assessment
        """
        recommendations = []
        
        if risk_level in ['Critical', 'High']:
            recommendations.append('Increase monitoring frequency')
            recommendations.append('Consider segregation if necessary')
        
        for factor, score in risk_factors:
            if 'escape' in factor.lower():
                recommendations.append('Enhanced perimeter checks')
            if 'violence' in factor.lower():
                recommendations.append('Regular psychological evaluation')
            if 'disciplinary' in factor.lower():
                recommendations.append('Behavioral intervention program')
        
        return recommendations