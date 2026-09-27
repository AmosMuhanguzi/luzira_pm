from datetime import datetime
from extensions import db
from models.base import BaseModel


class VisitLog(BaseModel):
    __tablename__ = 'visit_logs'

    visit_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey('visitors.visitor_id'), nullable=False, index=True)
    inmate_id  = db.Column(db.Integer, db.ForeignKey('inmates.inmate_id'), nullable=False, index=True)

    # Timestamps
    check_in_time  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    check_out_time = db.Column(db.DateTime)

    # Visit Details
    visit_type       = db.Column(db.String(30), default='Regular', nullable=False)
    purpose_of_visit = db.Column(db.String(100))
    relationship     = db.Column(db.String(50))
    items_brought    = db.Column(db.Text)
    status           = db.Column(db.String(20), default='Completed', index=True)

    # AI Anomaly & Risk Tracking
    anomaly_flag   = db.Column(db.Boolean, default=False, index=True)
    anomaly_score  = db.Column(db.Float, default=0.0)
    anomaly_reason = db.Column(db.Text)

    # Processing Officer
    processed_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    # Relationships
    visitor = db.relationship('Visitor', back_populates='visit_logs')
    inmate  = db.relationship('Inmate', back_populates='visit_logs')

    @property
    def duration_minutes(self):
        """Calculates total duration in minutes if checked out."""
        if self.check_in_time and self.check_out_time:
            delta = self.check_out_time - self.check_in_time
            return max(0, int(delta.total_seconds() // 60))
        return None

    @property
    def formatted_duration(self):
        """Formats duration string for UI rendering (e.g., '45 mins' or '1h 15m')."""
        mins = self.duration_minutes
        if mins is None:
            return "—"
        if mins < 1:
            return "< 1 min"
        if mins < 60:
            return f"{mins} mins"
        hours = mins // 60
        rem_mins = mins % 60
        return f"{hours}h {rem_mins}m" if rem_mins else f"{hours}h"

    def to_dict(self):
        return {
            'visit_id': self.visit_id,
            'visitor_id': self.visitor_id,
            'visitor_name': self.visitor.full_name if self.visitor else None,
            'inmate_id': self.inmate_id,
            'inmate_number': self.inmate.inmate_number if self.inmate else None,
            'inmate_name': self.inmate.full_name if self.inmate else None,
            'date': self.check_in_time.strftime('%Y-%m-%d') if self.check_in_time else None,
            'visit_type': self.visit_type,
            'check_in_time': self.check_in_time.strftime('%H:%M') if self.check_in_time else None,
            'check_out_time': self.check_out_time.strftime('%H:%M') if self.check_out_time else '—',
            'duration': self.formatted_duration,
            'duration_minutes': self.duration_minutes,
            'purpose_of_visit': self.purpose_of_visit,
            'relationship': self.relationship,
            'items_brought': self.items_brought,
            'status': self.status,
            'anomaly_flag': self.anomaly_flag,
            'anomaly_score': self.anomaly_score,
            'anomaly_reason': self.anomaly_reason
        }

    def __repr__(self):
        return f'<VisitLog {self.visit_id} Visitor={self.visitor_id} Inmate={self.inmate_id}>'