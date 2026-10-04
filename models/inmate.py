from datetime import datetime, date
from sqlalchemy import Numeric
from extensions import db
from models.base import BaseModel


class Inmate(BaseModel):
    __tablename__ = 'inmates'

    inmate_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    inmate_number = db.Column(db.String(20), unique=True, nullable=False, index=True)

    # ---- Personal ----
    full_name     = db.Column(db.String(150), nullable=False, index=True)
    alias_names   = db.Column(db.Text)            # JSON list as string
    date_of_birth = db.Column(db.Date, nullable=False)
    gender        = db.Column(db.String(10), nullable=False)
    nationality   = db.Column(db.String(50), nullable=False)
    tribe         = db.Column(db.String(50))
    religion      = db.Column(db.String(50))

    # ---- Identification ----
    national_id_number = db.Column(db.String(50))
    passport_number    = db.Column(db.String(50))

    # ---- Next of Kin ----
    next_of_kin_name         = db.Column(db.String(150))
    next_of_kin_relationship = db.Column(db.String(50))
    next_of_kin_phone        = db.Column(db.String(20))
    next_of_kin_address      = db.Column(db.Text)

    # ---- Physical ----
    height_cm            = db.Column(db.Integer)
    weight_kg            = db.Column(db.Integer)
    eye_color            = db.Column(db.String(20))
    hair_color           = db.Column(db.String(20))
    distinguishing_marks = db.Column(db.Text)
    photo_path           = db.Column(db.String(255))

    # ---- Legal ----
    crime_category        = db.Column(db.String(100), index=True)
    crime_description     = db.Column(db.Text)
    court_case_number     = db.Column(db.String(50))
    sentencing_court      = db.Column(db.String(100))
    judge_name            = db.Column(db.String(100))
    sentence_type         = db.Column(db.String(50))
    sentence_duration     = db.Column(db.String(50))
    sentence_start_date   = db.Column(db.Date)
    expected_release_date = db.Column(db.Date, index=True)
    actual_release_date   = db.Column(db.Date)

    # ---- Facility ----
    cell_block              = db.Column(db.String(20), index=True)
    cell_number             = db.Column(db.String(20))
    security_classification = db.Column(db.String(20), default='Medium')

    # ---- BIOMETRIC (the core feature) ----
    fingerprint_template      = db.Column(db.LargeBinary)         # BLOB
    biometric_enrolled        = db.Column(db.Boolean, default=False, index=True)
    biometric_enrollment_date = db.Column(db.DateTime)
    biometric_quality_score   = db.Column(db.Integer)

    # ---- Status ----
    status                 = db.Column(db.String(20), default='Active', index=True)
    current_admission_date = db.Column(db.Date, nullable=False, default=date.today)
    total_admissions       = db.Column(db.Integer, default=1)

    # ---- Medical flags ----
    has_medical_condition = db.Column(db.Boolean, default=False)
    medical_alert         = db.Column(db.Text)

    # ---- Risk ----
    risk_level             = db.Column(db.String(20), default='Low')
    violence_history       = db.Column(db.Boolean, default=False)
    escape_attempt_history = db.Column(db.Boolean, default=False)

    # ---- Metadata ----
    created_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    # ---- Relationships ----
    admission_episodes = db.relationship(
        'AdmissionEpisode', back_populates='inmate',
        cascade='all, delete-orphan', lazy='dynamic'
    )
    medical_records = db.relationship(
        'MedicalRecord', back_populates='inmate',
        cascade='all, delete-orphan', lazy='dynamic'
    )
    disciplinary_logs = db.relationship(
        'DisciplinaryLog', back_populates='inmate',
        cascade='all, delete-orphan', lazy='dynamic'
    )
    visit_logs = db.relationship(
        'VisitLog', back_populates='inmate', lazy='dynamic'
    )


    @staticmethod
    def generate_number():
        from datetime import datetime
        year = datetime.now().year
        last_entry = Inmate.query.order_by(Inmate.inmate_id.desc()).first()
        next_id = (last_entry.inmate_id + 1) if last_entry else 1
        return f"LZR-{year}-{next_id:06d}"

    def current_episode(self):
        return self.admission_episodes.filter_by(is_current=True).first()

    def to_dict(self):
        """Converts model to dictionary for AJAX form pre-population on biometric match."""
        return {
            'inmate_id': self.inmate_id,
            'inmate_number': self.inmate_number,
            'full_name': self.full_name,
            'alias_names': self.alias_names,
            'date_of_birth': self.date_of_birth.strftime('%Y-%m-%d') if self.date_of_birth else None,
            'gender': self.gender,
            'nationality': self.nationality,
            'tribe': self.tribe,
            'religion': self.religion,
            'national_id_number': self.national_id_number,
            'passport_number': self.passport_number,
            'next_of_kin_name': self.next_of_kin_name,
            'next_of_kin_relationship': self.next_of_kin_relationship,
            'next_of_kin_phone': self.next_of_kin_phone,
            'next_of_kin_address': self.next_of_kin_address,
            'height_cm': self.height_cm,
            'weight_kg': self.weight_kg,
            'eye_color': self.eye_color,
            'hair_color': self.hair_color,
            'distinguishing_marks': self.distinguishing_marks,
            'photo_path': self.photo_path,
            'crime_category': self.crime_category,
            'crime_description': self.crime_description,
            'court_case_number': self.court_case_number,
            'sentencing_court': self.sentencing_court,
            'sentence_type': self.sentence_type,
            'cell_block': self.cell_block,
            'cell_number': self.cell_number,
            'security_classification': self.security_classification,
            'risk_level': self.risk_level,
            'has_medical_condition': self.has_medical_condition,
            'medical_alert': self.medical_alert,
            'biometric_enrolled': self.biometric_enrolled,
            'total_admissions': self.total_admissions,
            'status': self.status
        }

    

    def __repr__(self):
        return f'<Inmate {self.inmate_number} {self.full_name}>'


class AdmissionEpisode(BaseModel):
    __tablename__ = 'admission_episodes'

    episode_id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    inmate_id        = db.Column(db.Integer, db.ForeignKey('inmates.inmate_id'), nullable=False, index=True)
    admission_date   = db.Column(db.Date, nullable=False, default=date.today)
    admission_type   = db.Column(db.String(20), nullable=False)  # New / Re-admission / Transfer-In
    admission_reason = db.Column(db.Text)
    releasing_facility = db.Column(db.String(100))

    receiving_officer_id = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    release_date    = db.Column(db.Date)
    release_type    = db.Column(db.String(30))
    release_notes   = db.Column(db.Text)
    release_cash_amount = db.Column(Numeric(12, 2), nullable=False, default=0)
    release_property_claims = db.Column(db.Text)
    released_at = db.Column(db.DateTime)
    release_fingerprint_score = db.Column(Numeric(5, 2))
    releasing_officer_id = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))

    is_current = db.Column(db.Boolean, default=True, index=True)

    inmate = db.relationship('Inmate', back_populates='admission_episodes')

    def __repr__(self):
        return f'<Episode {self.episode_id} inmate={self.inmate_id} type={self.admission_type}>'


