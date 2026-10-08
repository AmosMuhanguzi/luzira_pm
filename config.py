# config.py
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')


class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')

    # ---- Database ----
    # SQLite file lives in instance/ folder (auto-created)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(INSTANCE_DIR, "luzira_pms.db")}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # ---- Session / Security ----
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-change-me')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # ---- Biometric ----
    BIOMETRIC_MATCH_THRESHOLD = 75          # confidence % for 1:N match
    BIOMETRIC_QUALITY_MIN = 60              # min quality score to accept
    BIOMETRIC_SAMPLES_PER_ENROLL = 3        # samples captured per enrolment
    BIOMETRIC_AGENT_URL = 'http://127.0.0.1:5001'

    # ---- AI ----
    AI_ANOMALY_CONTAMINATION = 0.1
    AI_MODEL_DIR = os.path.join(BASE_DIR, 'ml_models')

    # ---- Facility ----
    FACILITY_NAME = 'Luzira Prison'
    FACILITY_CAPACITY = 30000

    # config.py — inside class Config, in the Biometric section
    BIOMETRIC_MATCH_THRESHOLD = 75
    BIOMETRIC_QUALITY_MIN = 60
    BIOMETRIC_SAMPLES_PER_ENROLL = 3
    BIOMETRIC_AGENT_URL = 'http://127.0.0.1:5001'

    # Set to True to bypass real hardware during development.
    # The agent will return a synthetic template instead of reading a real finger.
    BIOMETRIC_MOCK_MODE = os.environ.get('BIOMETRIC_MOCK_MODE', 'true').lower() == 'true'

    # How long a "password verified, waiting for fingerprint" session may live
    LOGIN_PENDING_TIMEOUT_SECONDS = 180   # 3 minutes


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}