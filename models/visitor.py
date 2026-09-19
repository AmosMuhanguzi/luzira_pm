# models/visitor.py
from datetime import datetime, date
from extensions import db
from models.base import BaseModel


class Visitor(BaseModel):
    __tablename__ = 'visitors'

    visitor_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    visitor_number = db.Column(db.String(20), unique=True, index=True)

    full_name   = db.Column(db.String(150), nullable=False, index=True)
    date_of_birth = db.Column(db.Date)
    gender      = db.Column(db.String(10))
    nationality = db.Column(db.String(50))

    id_type   = db.Column(db.String(50))
    id_number = db.Column(db.String(50))

    phone_number     = db.Column(db.String(20), nullable=False)
    email            = db.Column(db.String(120))
    physical_address = db.Column(db.Text)

    relationship_to_inmate = db.Column(db.String(50))

    # ---- BIOMETRIC ----
    fingerprint_template      = db.Column(db.LargeBinary)
    biometric_enrolled        = db.Column(db.Boolean, default=False, index=True)
    biometric_enrollment_date = db.Column(db.DateTime)
    biometric_quality_score   = db.Column(db.Integer)

    photo_path = db.Column(db.String(255))

    # ---- Blacklist ----
    is_blacklisted   = db.Column(db.Boolean, default=False, index=True)
    blacklist_reason = db.Column(db.Text)
    blacklist_date   = db.Column(db.Date)
    blacklisted_by   = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    # ---- AI analysis ----
    total_visits      = db.Column(db.Integer, default=0)
    last_visit_date   = db.Column(db.Date)
    anomaly_score     = db.Column(db.Numeric(5, 4))
    anomaly_flag      = db.Column(db.Boolean, default=False, index=True)
    last_anomaly_check = db.Column(db.DateTime)

    created_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    visit_logs = db.relationship(
        'VisitLog', back_populates='visitor',
        cascade='all, delete-orphan', lazy='dynamic'
    )
    pattern = db.relationship(
        'VisitorPattern', back_populates='visitor',
        uselist=False, cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<Visitor {self.visitor_number} {self.full_name}>'


class VisitLog(BaseModel):
    __tablename__ = 'visit_logs'

    visit_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey('visitors.visitor_id'), nullable=False, index=True)
    inmate_id  = db.Column(db.Integer, db.ForeignKey('inmates.inmate_id'), nullable=False, index=True)

    visit_date     = db.Column(db.Date, nullable=False, default=date.today, index=True)
    check_in_time  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    check_out_time = db.Column(db.DateTime)
    visit_duration_minutes = db.Column(db.Integer)
    visit_type     = db.Column(db.String(30), default='Regular')

    items_brought     = db.Column(db.Text)
    items_approved    = db.Column(db.Text)
    items_confiscated = db.Column(db.Text)

    security_check_passed = db.Column(db.Boolean, default=True)
    security_notes        = db.Column(db.Text)
    security_officer_id   = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    biometric_verified    = db.Column(db.Boolean, default=False)
    verification_timestamp = db.Column(db.DateTime)
    verification_score    = db.Column(db.Numeric(5, 2))

    anomaly_flagged = db.Column(db.Boolean, default=False, index=True)
    anomaly_score   = db.Column(db.Numeric(5, 4))
    anomaly_reason  = db.Column(db.Text)

    visit_status  = db.Column(db.String(20), default='Completed', index=True)
    denial_reason = db.Column(db.Text)

    processed_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    visitor = db.relationship('Visitor', back_populates='visit_logs')
    inmate  = db.relationship('Inmate', back_populates='visit_logs')

    def __repr__(self):
        return f'<VisitLog {self.visit_id} visitor={self.visitor_id} inmate={self.inmate_id}>'