# models/medical.py
from datetime import date
from extensions import db
from models.base import BaseModel


class MedicalRecord(BaseModel):
    __tablename__ = 'medical_records'

    record_id  = db.Column(db.Integer, primary_key=True, autoincrement=True)
    inmate_id  = db.Column(db.Integer, db.ForeignKey('inmates.inmate_id'), nullable=False, index=True)
    record_date = db.Column(db.Date, nullable=False, default=date.today)
    record_type = db.Column(db.String(50))

    complaint             = db.Column(db.Text)
    diagnosis             = db.Column(db.Text)
    treatment_prescribed  = db.Column(db.Text)
    medication_details    = db.Column(db.Text)

    attending_medical_officer = db.Column(db.String(150))
    referred_to_hospital      = db.Column(db.Boolean, default=False)
    hospital_name             = db.Column(db.String(150))
    notes                     = db.Column(db.Text)

    recorded_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    inmate = db.relationship('Inmate', back_populates='medical_records')

    def __repr__(self):
        return f'<MedicalRecord {self.record_id} inmate={self.inmate_id}>'


class DisciplinaryLog(BaseModel):
    __tablename__ = 'disciplinary_logs'

    log_id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    inmate_id    = db.Column(db.Integer, db.ForeignKey('inmates.inmate_id'), nullable=False, index=True)
    incident_date = db.Column(db.Date, nullable=False, default=date.today)
    incident_type = db.Column(db.String(100))

    description       = db.Column(db.Text)
    witnesses         = db.Column(db.Text)
    action_taken      = db.Column(db.Text)
    punishment_assigned = db.Column(db.Text)
    punishment_start_date = db.Column(db.Date)
    punishment_end_date   = db.Column(db.Date)

    reported_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    inmate = db.relationship('Inmate', back_populates='disciplinary_logs')

    def __repr__(self):
        return f'<DisciplinaryLog {self.log_id} inmate={self.inmate_id}>'