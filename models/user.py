# models/user.py
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from models.base import BaseModel


class Role(BaseModel):
    __tablename__ = 'roles'

    role_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    role_name   = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)

    users = db.relationship('UserAccount', back_populates='role', lazy='dynamic')

    def __repr__(self):
        return f'<Role {self.role_name}>'


class UserAccount(BaseModel):
    __tablename__ = 'user_accounts'

    user_id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username      = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email         = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name     = db.Column(db.String(150), nullable=False)
    phone_number  = db.Column(db.String(20))

    role_id = db.Column(db.Integer, db.ForeignKey('roles.role_id'), nullable=False)

    is_active             = db.Column(db.Boolean, default=True, nullable=False)
    account_locked        = db.Column(db.Boolean, default=False, nullable=False)
    failed_login_attempts = db.Column(db.Integer, default=0)
    last_login            = db.Column(db.DateTime)
    last_login_ip         = db.Column(db.String(45))

    # models/user.py  — inside class UserAccount, after last_login_ip line
    last_login_ip         = db.Column(db.String(45))

    # ---- Staff biometric (login 2FA) ----
    fingerprint_template      = db.Column(db.LargeBinary)
    biometric_enrolled        = db.Column(db.Boolean, default=False, nullable=False)
    biometric_enrollment_date = db.Column(db.DateTime)
    biometric_quality_score   = db.Column(db.Integer)

    role = db.relationship('Role', back_populates='users')

    # ---------- password helpers ----------
    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # ---------- login helpers ----------
    def register_login(self, ip_address=None):
        self.last_login = datetime.utcnow()
        self.last_login_ip = ip_address
        self.failed_login_attempts = 0

    def register_failed_login(self, max_attempts=5):
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        if self.failed_login_attempts >= max_attempts:
            self.account_locked = True

    def has_biometric(self) -> bool:
        return bool(self.biometric_enrolled and self.fingerprint_template)

    def enroll_biometric(self, template: bytes, quality: int):
        self.fingerprint_template = template
        self.biometric_enrolled = True
        self.biometric_enrollment_date = datetime.utcnow()
        self.biometric_quality_score = quality

    # ---------- Flask-Login required properties ----------
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.user_id)

    @property
    def role_name(self):
        return self.role.role_name if self.role else None

    def __repr__(self):
        return f'<User {self.username} ({self.role_name})>'