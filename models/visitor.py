# models/visitor.py
from models.visit import VisitLog  # Re-export VisitLog
from extensions import db
from models.base import BaseModel


class Visitor(BaseModel):
    __tablename__ = 'visitors'

    visitor_id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    full_name          = db.Column(db.String(150), nullable=False, index=True)
    national_id_number = db.Column(db.String(50), unique=True, index=True)
    passport_number    = db.Column(db.String(50), unique=True, index=True)
    gender             = db.Column(db.String(10))
    date_of_birth      = db.Column(db.Date)
    phone_number       = db.Column(db.String(20), nullable=False, index=True)
    address            = db.Column(db.Text)
    relationship_type  = db.Column(db.String(50))

    # Biometric or Photo Data
    photo_path           = db.Column(db.String(255))
    fingerprint_template = db.Column(db.LargeBinary)

    # Security & Monitoring Flags
    is_flagged        = db.Column(db.Boolean, default=False, index=True)
    flag_reason       = db.Column(db.Text)
    risk_rating       = db.Column(db.String(20), default='Low')
    total_visits_made = db.Column(db.Integer, default=0)

    # Relationships
    visit_logs = db.relationship('VisitLog', back_populates='visitor', cascade='all, delete-orphan', lazy='dynamic')
    
    # Use back_populates here to match VisitorPattern
    pattern = db.relationship('VisitorPattern', back_populates='visitor', uselist=False, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'visitor_id': self.visitor_id,
            'full_name': self.full_name,
            'national_id_number': self.national_id_number,
            'passport_number': self.passport_number,
            'phone_number': self.phone_number,
            'gender': self.gender,
            'address': self.address,
            'relationship_type': self.relationship_type,
            'is_flagged': self.is_flagged,
            'flag_reason': self.flag_reason,
            'risk_rating': self.risk_rating,
            'total_visits_made': self.total_visits_made
        }

    def __repr__(self):
        return f'<Visitor {self.full_name} ({self.national_id_number or "No NIN"})>'