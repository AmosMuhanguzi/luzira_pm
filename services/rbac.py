# services/rbac.py
"""
Role-Based Access Control.
Defines all permissions and maps them to the system roles.
"""
from functools import wraps
from flask import abort, jsonify, request
from flask_login import current_user


class Permissions:
    # Inmate
    INMATE_VIEW              = 'inmate:view'
    INMATE_CREATE            = 'inmate:create'
    INMATE_EDIT              = 'inmate:edit'
    INMATE_DELETE            = 'inmate:delete'
    INMATE_RELEASE           = 'inmate:release'
    INMATE_BIOMETRIC_ENROLL  = 'inmate:biometric_enroll'
    INMATE_BIOMETRIC_VERIFY  = 'inmate:biometric_verify'
    MEDICAL_RECORD_VIEW      = 'medical_record:view'
    MEDICAL_RECORD_CREATE    = 'medical_record:create'
    MEDICAL_RECORD_APPROVE   = 'medical_record:approve'
    DISCIPLINARY_CREATE      = 'disciplinary:create'

        # Inmate — request edit via approval workflow
    INMATE_EDIT_REQUEST = 'inmate:edit_request'
    INMATE_EDIT_APPROVE = 'inmate:edit_approve'

    # Visitor
    VISITOR_VIEW             = 'visitor:view'
    VISITOR_CREATE           = 'visitor:create'
    VISITOR_EDIT             = 'visitor:edit'
    VISITOR_BLACKLIST        = 'visitor:blacklist'
    VISITOR_BLACKLIST_CLEAR  = 'visitor:blacklist_clear'
    VISITOR_BIOMETRIC_ENROLL = 'visitor:biometric_enroll'
    VISITOR_BIOMETRIC_VERIFY = 'visitor:biometric_verify'

    # Visit
    VISIT_VIEW               = 'visit:view'
    VISIT_CREATE             = 'visit:create'
    VISIT_APPROVE            = 'visit:approve'
    VISIT_DENY               = 'visit:deny'

    # AI
    AI_VIEW_ALERTS           = 'ai:view_alerts'
    AI_REVIEW_ALERTS         = 'ai:review_alerts'
    AI_VIEW_DASHBOARD        = 'ai:view_dashboard'
    AI_EXPORT_REPORTS        = 'ai:export_reports'

    # Reports
    REPORT_VIEW              = 'report:view'
    REPORT_GENERATE          = 'report:generate'
    REPORT_EXPORT            = 'report:export'

    # Users
    USER_VIEW                = 'user:view'
    USER_CREATE              = 'user:create'
    USER_EDIT                = 'user:edit'
    USER_DELETE              = 'user:delete'
    USER_RESET_PASSWORD      = 'user:reset_password'

    # System
    SYSTEM_SETTINGS          = 'system:settings'
    SYSTEM_AUDIT_LOG         = 'system:audit_log'
    SYSTEM_BACKUP            = 'system:backup'
    SYSTEM_MAINTENANCE       = 'system:maintenance'


# Permission sets per role — this is the single source of truth
ROLE_PERMISSIONS = {
    'System Administrator': [
        Permissions.INMATE_VIEW, Permissions.INMATE_CREATE, Permissions.INMATE_EDIT,
        Permissions.INMATE_DELETE, Permissions.INMATE_RELEASE,
        Permissions.INMATE_BIOMETRIC_ENROLL, Permissions.INMATE_BIOMETRIC_VERIFY,
        Permissions.VISITOR_VIEW, Permissions.VISITOR_CREATE, Permissions.VISITOR_EDIT,
        Permissions.VISITOR_BLACKLIST, Permissions.VISITOR_BLACKLIST_CLEAR,
        Permissions.VISITOR_BIOMETRIC_ENROLL, Permissions.VISITOR_BIOMETRIC_VERIFY,
        Permissions.VISIT_VIEW, Permissions.VISIT_CREATE, Permissions.VISIT_APPROVE, Permissions.VISIT_DENY,
        Permissions.AI_VIEW_ALERTS, Permissions.AI_REVIEW_ALERTS, Permissions.AI_VIEW_DASHBOARD, Permissions.AI_EXPORT_REPORTS,
        Permissions.REPORT_VIEW, Permissions.REPORT_GENERATE, Permissions.REPORT_EXPORT,
        Permissions.USER_VIEW, Permissions.USER_CREATE, Permissions.USER_EDIT,
        Permissions.USER_DELETE, Permissions.USER_RESET_PASSWORD,
        Permissions.SYSTEM_SETTINGS, Permissions.SYSTEM_AUDIT_LOG,
        Permissions.SYSTEM_BACKUP, Permissions.SYSTEM_MAINTENANCE,
        Permissions.INMATE_EDIT_REQUEST, Permissions.INMATE_EDIT_APPROVE,
        Permissions.MEDICAL_RECORD_VIEW, Permissions.MEDICAL_RECORD_CREATE,
        Permissions.MEDICAL_RECORD_APPROVE,
        Permissions.DISCIPLINARY_CREATE,
    ],
    'Warden': [
        Permissions.INMATE_VIEW,
        Permissions.INMATE_RELEASE,
        Permissions.VISITOR_VIEW,
        Permissions.VISIT_VIEW, Permissions.VISIT_APPROVE, Permissions.VISIT_DENY,
        Permissions.AI_VIEW_ALERTS, Permissions.AI_REVIEW_ALERTS, Permissions.AI_VIEW_DASHBOARD,
        Permissions.REPORT_VIEW, Permissions.REPORT_GENERATE, Permissions.REPORT_EXPORT,
        Permissions.INMATE_EDIT_REQUEST,
        Permissions.DISCIPLINARY_CREATE,
        Permissions.VISITOR_BLACKLIST,
    ],
    'Records Officer': [
        Permissions.INMATE_VIEW, Permissions.INMATE_CREATE,
        Permissions.INMATE_RELEASE,
        Permissions.INMATE_BIOMETRIC_ENROLL, Permissions.INMATE_BIOMETRIC_VERIFY,
        Permissions.VISITOR_VIEW, Permissions.VISITOR_CREATE, Permissions.VISITOR_EDIT,
        Permissions.VISITOR_BIOMETRIC_ENROLL, Permissions.VISITOR_BIOMETRIC_VERIFY,
        Permissions.VISIT_VIEW, Permissions.VISIT_CREATE,
        Permissions.AI_VIEW_DASHBOARD,
        Permissions.INMATE_EDIT_REQUEST,
        Permissions.VISITOR_BLACKLIST,
    ],
    'Receptionist': [
        Permissions.INMATE_VIEW, Permissions.INMATE_CREATE,
        Permissions.INMATE_RELEASE,
        Permissions.INMATE_BIOMETRIC_ENROLL, Permissions.INMATE_BIOMETRIC_VERIFY,
        Permissions.VISITOR_VIEW, Permissions.VISITOR_CREATE, Permissions.VISITOR_EDIT,
        Permissions.VISITOR_BIOMETRIC_ENROLL, Permissions.VISITOR_BIOMETRIC_VERIFY,
        Permissions.VISIT_VIEW, Permissions.VISIT_CREATE,
        Permissions.AI_VIEW_DASHBOARD,
        Permissions.INMATE_EDIT_REQUEST,
        Permissions.VISITOR_BLACKLIST,
    ],
    'Security Officer': [
        Permissions.INMATE_VIEW,
        Permissions.VISITOR_VIEW,
        Permissions.VISITOR_BIOMETRIC_VERIFY,
        Permissions.VISIT_VIEW, Permissions.VISIT_APPROVE, Permissions.VISIT_DENY,
        Permissions.AI_VIEW_ALERTS,
        Permissions.INMATE_EDIT_REQUEST,
        Permissions.DISCIPLINARY_CREATE,
        Permissions.VISITOR_BLACKLIST,
    ],
    'Medical Officer': [
        Permissions.INMATE_VIEW,
        Permissions.MEDICAL_RECORD_VIEW, Permissions.MEDICAL_RECORD_CREATE,
    ],
}


def has_permission(permission: str) -> bool:
    """Check if the currently logged-in user has a permission."""
    if not current_user.is_authenticated:
        return False
    role = current_user.role_name
    return permission in ROLE_PERMISSIONS.get(role, [])


def require_permission(permission: str):
    """Decorator: route requires a specific permission."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return _deny(401, 'Authentication required')
            if not has_permission(permission):
                return _deny(403, 'Permission denied')
            return f(*args, **kwargs)
        return wrapper
    return decorator


def require_role(*roles):
    """Decorator: route requires one of the given roles."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return _deny(401, 'Authentication required')
            if current_user.role_name not in roles:
                return _deny(403, 'Insufficient privileges')
            return f(*args, **kwargs)
        return wrapper
    return decorator


def _deny(code, message):
    if request.is_json or request.path.startswith('/api/'):
        return jsonify({'error': message}), code
    abort(code)