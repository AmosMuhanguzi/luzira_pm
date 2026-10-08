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
    attachment_path = db.Column(db.String(255))
    attachment_name = db.Column(db.String(255))
    approval_status = db.Column(db.String(20), nullable=False, default='Approved', index=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)

    inmate = db.relationship('Inmate', back_populates='medical_records')
    author = db.relationship('UserAccount', foreign_keys=[recorded_by])
    reviewer = db.relationship('UserAccount', foreign_keys=[reviewed_by])
    attachments = db.relationship(
        'MedicalRecordAttachment',
        back_populates='medical_record',
        cascade='all, delete-orphan',
        lazy='select',
    )

    def __repr__(self):
        return f'<MedicalRecord {self.record_id} inmate={self.inmate_id}>'


class MedicalRecordAttachment(BaseModel):
    __tablename__ = 'medical_record_attachments'

    attachment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    medical_record_id = db.Column(
        db.Integer,
        db.ForeignKey('medical_records.record_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    file_path = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)

    medical_record = db.relationship('MedicalRecord', back_populates='attachments')

    def __repr__(self):
        return f'<MedicalRecordAttachment {self.attachment_id}>'


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