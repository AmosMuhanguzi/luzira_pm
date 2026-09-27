# models/__init__.py
"""
Import order matters: tables with no FK dependencies must be imported first.
"""
from models.base import BaseModel, TimestampMixin, SerializableMixin

from models.user import Role, UserAccount
from models.inmate import Inmate, AdmissionEpisode
from models.visitor import Visitor
from models.visit import VisitLog
from models.medical import MedicalRecord, DisciplinaryLog
from models.ai import AIAnalysisLog, VisitorPattern, PopulationForecast
from models.audit import AuditEvent
from models.notification import Notification, SystemSetting
from models.edit_request import EditRequest

__all__ = [
    'BaseModel', 'TimestampMixin', 'SerializableMixin',
    'Role', 'UserAccount',
    'Inmate', 'AdmissionEpisode',
    'Visitor', 'VisitLog',
    'MedicalRecord', 'DisciplinaryLog',
    'AIAnalysisLog', 'VisitorPattern', 'PopulationForecast',
    'AuditEvent',
    'Notification', 'SystemSetting',
    'EditRequest',
]