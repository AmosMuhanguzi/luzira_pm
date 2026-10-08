# models/ai.py
from datetime import datetime
from sqlalchemy.orm import synonym
from extensions import db
from models.base import BaseModel


class AIAnalysisLog(BaseModel):
    __tablename__ = 'ai_analysis_log'

    analysis_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    analysis_type = db.Column(db.String(50), nullable=False, index=True)
    target_entity = db.Column(db.String(50))
    target_type   = synonym('target_entity')
    target_id     = db.Column(db.Integer)

    result_summary  = db.Column(db.Text, nullable=False)
    result          = synonym('result_summary')
    detailed_result = db.Column(db.Text)   # JSON
    confidence_score = db.Column(db.Numeric(5, 4))
    anomaly_score    = db.Column(db.Numeric(5, 4))

    severity           = db.Column(db.String(20), index=True)
    recommended_action = db.Column(db.Text)
    action_taken       = db.Column(db.Text)
    action_taken_by    = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))
    action_taken_at    = db.Column(db.DateTime)

    is_reviewed  = db.Column(db.Boolean, default=False, index=True)
    reviewed_by  = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))
    reviewed_at  = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)

    analysis_timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    timestamp          = synonym('analysis_timestamp')
    model_version      = db.Column(db.String(20))

    @classmethod
    def log_analysis(cls, analysis_type, target_entity, target_id,
                     result_summary, detailed_result=None, confidence_score=None,
                     anomaly_score=None, severity='Info', recommended_action=None,
                     model_version='v1.0'):
        import json
        entry = cls(
            analysis_type=analysis_type,
            target_entity=target_entity,
            target_id=target_id,
            result_summary=result_summary,
            detailed_result=json.dumps(detailed_result) if detailed_result else None,
            confidence_score=confidence_score,
            anomaly_score=anomaly_score,
            severity=severity,
            recommended_action=recommended_action,
            model_version=model_version,
        )
        db.session.add(entry)
        return entry


class VisitorPattern(BaseModel):
    __tablename__ = 'visitor_patterns'

    pattern_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey('visitors.visitor_id'),
                           nullable=False, unique=True, index=True)

    avg_visit_frequency_days   = db.Column(db.Numeric(10, 2))
    avg_visit_duration_minutes = db.Column(db.Numeric(10, 2))
    typical_visit_days         = db.Column(db.Text)   # JSON
    typical_visit_hours        = db.Column(db.Text)   # JSON

    unusual_time_visits              = db.Column(db.Integer, default=0)
    multiple_inmate_associations     = db.Column(db.Integer, default=0)
    rapid_succession_visits          = db.Column(db.Integer, default=0)
    inconsistent_relationship_claims = db.Column(db.Integer, default=0)

    total_flagged_visits = db.Column(db.Integer, default=0)
    last_flagged_date    = db.Column(db.Date)

    calculated_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    visitor = db.relationship('Visitor', back_populates='pattern')


class PopulationForecast(BaseModel):
    __tablename__ = 'population_forecasts'

    forecast_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    forecast_date   = db.Column(db.Date, nullable=False, index=True)
    forecast_period = db.Column(db.String(20))

    predicted_population        = db.Column(db.Integer)
    predicted_admissions        = db.Column(db.Integer)
    predicted_releases          = db.Column(db.Integer)
    predicted_overcrowding_risk = db.Column(db.Numeric(5, 4))

    current_capacity      = db.Column(db.Integer)
    projected_capacity    = db.Column(db.Integer)
    capacity_utilization  = db.Column(db.Numeric(5, 2))

    model_confidence      = db.Column(db.Numeric(5, 4))
    based_on_data_from    = db.Column(db.Date)
    based_on_data_to      = db.Column(db.Date)

    generated_at       = db.Column(db.DateTime, default=datetime.utcnow)
    generated_by_model = db.Column(db.String(50))