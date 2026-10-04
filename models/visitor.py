# models/visitor.py
from models.visit import VisitLog  # Re-export VisitLog
from extensions import db
from models.base import BaseModel


class Visitor(BaseModel):
    __tablename__ = 'visitors'

    visitor_id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # 1. ADDED THIS COLUMN:
    visitor_number     = db.Column(db.String(30), unique=True, index=True, nullable=True)

    full_name          = db.Column(db.String(150), nullable=False, index=True)
    national_id_number = db.Column(db.String(50), unique=True, index=True)
    passport_number    = db.Column(db.String(50), unique=True, index=True)
    gender             = db.Column(db.String(10))
    date_of_birth      = db.Column(db.Date)
    phone_number       = db.Column(db.String(20), nullable=False, index=True)
    email              = db.Column(db.String(255))
    address            = db.Column(db.Text)
    nationality        = db.Column(db.String(50), default='Ugandan')
    relationship_type  = db.Column(db.String(50))
    anomaly_flag       = db.Column(db.Boolean, default=False, nullable=False)

    # Biometric or Photo Data
    photo_path          = db.Column(db.String(255))
    fingerprint_template = db.Column(db.LargeBinary)
    biometric_enrolled  = db.Column(db.Boolean, default=False, nullable=False)
    biometric_enrollment_date = db.Column(db.DateTime, nullable=True)
    biometric_quality_score   = db.Column(db.Integer, default=0)

    # Security & Monitoring Flags
    is_flagged        = db.Column(db.Boolean, default=False, index=True)
    flag_reason       = db.Column(db.Text)
    risk_rating       = db.Column(db.String(20), default='Low')
    total_visits_made = db.Column(db.Integer, default=0)

    # Relationships
    visit_logs = db.relationship('VisitLog', back_populates='visitor', cascade='all, delete-orphan', lazy='dynamic')
    
    # Use back_populates here to match VisitorPattern
    pattern = db.relationship('VisitorPattern', back_populates='visitor', uselist=False, cascade='all, delete-orphan')

    # --- Property Aliases for VisitorService Compatibility ---
    @property
    def id_number(self):
        return self.national_id_number or self.passport_number

    @id_number.setter
    def id_number(self, value):
        self.national_id_number = value

    @property
    def physical_address(self):
        return self.address

    @physical_address.setter
    def physical_address(self, value):
        self.address = value

    @property
    def relationship_to_inmate(self):
        return self.relationship_type

    @relationship_to_inmate.setter
    def relationship_to_inmate(self, value):
        self.relationship_type = value

    @property
    def total_visits(self):
        return self.total_visits_made

    @total_visits.setter
    def total_visits(self, value):
        self.total_visits_made = value

    @property
    def is_blacklisted(self):
        return self.is_flagged

    @property
    def blacklist_reason(self):
        return self.flag_reason

    def to_dict(self):
        return {
            'visitor_id': self.visitor_id,
            'visitor_number': self.visitor_number,
            'full_name': self.full_name,
            'national_id_number': self.national_id_number,
            'passport_number': self.passport_number,
            'phone_number': self.phone_number,
            'email': self.email,
            'gender': self.gender,
            'address': self.address,
            'relationship_type': self.relationship_type,
            'is_flagged': self.is_flagged,
            'flag_reason': self.flag_reason,
            'risk_rating': self.risk_rating,
            'total_visits_made': self.total_visits_made,
            'anomaly_flag': self.anomaly_flag
        }
    @property
    def formatted_duration(self):
        # 1. Grab stored duration or calculate dynamically if missing
        mins = self.visit_duration_minutes
        if mins is None and self.check_in_time and self.check_out_time:
            delta = self.check_out_time - self.check_in_time
            mins = max(0, int(delta.total_seconds() // 60))

        if mins is None:
            return "—"

        # 2. Format into clean text (e.g., "18 mins", "1 hr 15 mins")
        if mins < 60:
            return f"{mins} min{'s' if mins != 1 else ''}"

        hours = mins // 60
        remaining_mins = mins % 60
        if remaining_mins == 0:
            return f"{hours} hr{'s' if hours != 1 else ''}"
        return f"{hours} hr {remaining_mins} min{'s' if remaining_mins != 1 else ''}"

    def __repr__(self):
        return f'<Visitor {self.visitor_number or self.full_name} ({self.national_id_number or "No NIN"})>'