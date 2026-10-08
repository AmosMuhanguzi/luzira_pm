# models/medical.py
from datetime import date
from sqlalchemy import text
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
    incident_time = db.Column(db.Time)
    incident_type = db.Column(db.String(100))

    description       = db.Column(db.Text)
    is_violent        = db.Column(db.Boolean, nullable=True, default=False)
    injured_count     = db.Column(db.Integer)
    witnesses         = db.Column(db.Text)
    action_taken      = db.Column(db.Text)
    punishment_assigned = db.Column(db.Text)
    punishment_start_date = db.Column(db.Date)
    punishment_end_date   = db.Column(db.Date)

    reported_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    inmate = db.relationship('Inmate', back_populates='disciplinary_logs')

    def __repr__(self):
        return f'<DisciplinaryLog {self.log_id} inmate={self.inmate_id}>'


class EscapeAttemptLog(BaseModel):
    __tablename__ = 'escape_attempt_logs'

    event_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    inmate_id = db.Column(
        db.Integer, db.ForeignKey('inmates.inmate_id'), nullable=False, index=True
    )
    incident_date = db.Column(db.Date, nullable=False, default=date.today)
    incident_time = db.Column(db.Time, nullable=False)
    description = db.Column(db.Text, nullable=False)
    outcome = db.Column(db.Text)
    action_taken = db.Column(db.Text)
    reported_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    inmate = db.relationship('Inmate', back_populates='escape_attempt_logs')

    def __repr__(self):
        return f'<EscapeAttemptLog {self.event_id} inmate={self.inmate_id}>'


class WorkTransferLog(BaseModel):
    __tablename__ = 'work_transfer_logs'
    __table_args__ = (
        db.Index(
            'uq_work_transfer_open_inmate',
            'inmate_id',
            unique=True,
            sqlite_where=text('checked_in_at IS NULL'),
            postgresql_where=text('checked_in_at IS NULL'),
        ),
    )

    transfer_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    inmate_id = db.Column(
        db.Integer, db.ForeignKey('inmates.inmate_id'), nullable=False, index=True
    )
    work_location = db.Column(db.String(200), nullable=False)
    work_description = db.Column(db.Text)
    checked_out_at = db.Column(db.DateTime, nullable=False)
    checkout_fingerprint_score = db.Column(db.Numeric(5, 2), nullable=False)
    checked_out_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))
    checked_in_at = db.Column(db.DateTime)
    checkin_fingerprint_score = db.Column(db.Numeric(5, 2))
    checked_in_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    inmate = db.relationship('Inmate', back_populates='work_transfer_logs')
    checkout_officer = db.relationship('UserAccount', foreign_keys=[checked_out_by])
    checkin_officer = db.relationship('UserAccount', foreign_keys=[checked_in_by])

    @property
    def is_out(self):
        return self.checked_in_at is None

    @property
    def time_out(self):
        if self.checked_in_at is None:
            return None
        return max(0, int((self.checked_in_at - self.checked_out_at).total_seconds() // 60))

    def __repr__(self):
        return f'<WorkTransferLog {self.transfer_id} inmate={self.inmate_id}>'