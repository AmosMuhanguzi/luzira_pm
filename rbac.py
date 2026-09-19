# =====================================================
# rbac.py - Role-Based Access Control Implementation
# =====================================================

from functools import wraps
from flask import abort, jsonify, request
from flask_login import current_user


# Define all permissions in the system
class Permissions:
    # Inmate Management
    INMATE_VIEW = 'inmate:view'
    INMATE_CREATE = 'inmate:create'
    INMATE_EDIT = 'inmate:edit'
    INMATE_DELETE = 'inmate:delete'
    INMATE_BIOMETRIC_ENROLL = 'inmate:biometric_enroll'
    INMATE_BIOMETRIC_VERIFY = 'inmate:biometric_verify'
    
    # Visitor Management
    VISITOR_VIEW = 'visitor:view'
    VISITOR_CREATE = 'visitor:create'
    VISITOR_EDIT = 'visitor:edit'
    VISITOR_BLACKLIST = 'visitor:blacklist'
    VISITOR_BIOMETRIC_ENROLL = 'visitor:biometric_enroll'
    VISITOR_BIOMETRIC_VERIFY = 'visitor:biometric_verify'
    
    # Visit Management
    VISIT_VIEW = 'visit:view'
    VISIT_CREATE = 'visit:create'
    VISIT_APPROVE = 'visit:approve'
    VISIT_DENY = 'visit:deny'
    
    # AI & Analytics
    AI_VIEW_ALERTS = 'ai:view_alerts'
    AI_REVIEW_ALERTS = 'ai:review_alerts'
    AI_VIEW_DASHBOARD = 'ai:view_dashboard'
    AI_EXPORT_REPORTS = 'ai:export_reports'
    
    # Reports
    REPORT_VIEW = 'report:view'
    REPORT_GENERATE = 'report:generate'
    REPORT_EXPORT = 'report:export'
    
    # User Management
    USER_VIEW = 'user:view'
    USER_CREATE = 'user:create'
    USER_EDIT = 'user:edit'
    USER_DELETE = 'user:delete'
    USER_RESET_PASSWORD = 'user:reset_password'
    
    # System Administration
    SYSTEM_SETTINGS = 'system:settings'
    SYSTEM_AUDIT_LOG = 'system:audit_log'
    SYSTEM_BACKUP = 'system:backup'
    SYSTEM_MAINTENANCE = 'system:maintenance'


# Define role-permission mappings
ROLE_PERMISSIONS = {
    'System Administrator': [
        # All permissions
        Permissions.INMATE_VIEW, Permissions.INMATE_CREATE, Permissions.INMATE_EDIT,
        Permissions.INMATE_DELETE, Permissions.INMATE_BIOMETRIC_ENROLL, Permissions.INMATE_BIOMETRIC_VERIFY,
        Permissions.VISITOR_VIEW, Permissions.VISITOR_CREATE, Permissions.VISITOR_EDIT,
        Permissions.VISITOR_BLACKLIST, Permissions.VISITOR_BIOMETRIC_ENROLL, Permissions.VISITOR_BIOMETRIC_VERIFY,
        Permissions.VISIT_VIEW, Permissions.VISIT_CREATE, Permissions.VISIT_APPROVE, Permissions.VISIT_DENY,
        Permissions.AI_VIEW_ALERTS, Permissions.AI_REVIEW_ALERTS, Permissions.AI_VIEW_DASHBOARD, Permissions.AI_EXPORT_REPORTS,
        Permissions.REPORT_VIEW, Permissions.REPORT_GENERATE, Permissions.REPORT_EXPORT,
        Permissions.USER_VIEW, Permissions.USER_CREATE, Permissions.USER_EDIT,
        Permissions.USER_DELETE, Permissions.USER_RESET_PASSWORD,
        Permissions.SYSTEM_SETTINGS, Permissions.SYSTEM_AUDIT_LOG,
        Permissions.SYSTEM_BACKUP, Permissions.SYSTEM_MAINTENANCE
    ],
    
    'Warden': [
        # Read-only access to most, plus AI dashboard
        Permissions.INMATE_VIEW,
        Permissions.VISITOR_VIEW,
        Permissions.VISIT_VIEW, Permissions.VISIT_APPROVE, Permissions.VISIT_DENY,
        Permissions.AI_VIEW_ALERTS, Permissions.AI_REVIEW_ALERTS, Permissions.AI_VIEW_DASHBOARD,
        Permissions.REPORT_VIEW, Permissions.REPORT_GENERATE, Permissions.REPORT_EXPORT
    ],
    
    'Records Officer': [
        # Inmate records management
        Permissions.INMATE_VIEW, Permissions.INMATE_CREATE, Permissions.INMATE_EDIT,
        Permissions.VISITOR_VIEW,
        Permissions.VISIT_VIEW,
        Permissions.REPORT_VIEW, Permissions.REPORT_GENERATE
    ],
    
    'Receptionist': [
        # Intake and visitor processing
        Permissions.INMATE_VIEW, Permissions.INMATE_CREATE,
        Permissions.INMATE_BIOMETRIC_ENROLL, Permissions.INMATE_BIOMETRIC_VERIFY,
        Permissions.VISITOR_VIEW, Permissions.VISITOR_CREATE, Permissions.VISITOR_EDIT,
        Permissions.VISITOR_BIOMETRIC_ENROLL, Permissions.VISITOR_BIOMETRIC_VERIFY,
        Permissions.VISIT_VIEW, Permissions.VISIT_CREATE
    ],
    
    'Security Officer': [
        # Visitor verification and security
        Permissions.VISITOR_VIEW,
        Permissions.VISITOR_BIOMETRIC_VERIFY,
        Permissions.VISIT_VIEW, Permissions.VISIT_APPROVE, Permissions.VISIT_DENY,
        Permissions.AI_VIEW_ALERTS
    ]
}


def has_permission(permission):
    """
    Check if current user has a specific permission
    """
    if not current_user.is_authenticated:
        return False
    
    role_name = current_user.role.role_name
    role_permissions = ROLE_PERMISSIONS.get(role_name, [])
    
    return permission in role_permissions


def require_permission(permission):
    """
    Decorator to require a specific permission for a route
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json:
                    return jsonify({'error': 'Authentication required'}), 401
                abort(401)
            
            if not has_permission(permission):
                if request.is_json:
                    return jsonify({'error': 'Permission denied'}), 403
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_role(*roles):
    """
    Decorator to require specific role(s) for a route
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json:
                    return jsonify({'error': 'Authentication required'}), 401
                abort(401)
            
            if current_user.role.role_name not in roles:
                if request.is_json:
                    return jsonify({'error': 'Insufficient privileges'}), 403
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# =====================================================
# auth_decorators.py - Convenience decorators
# =====================================================

def admin_required(f):
    """Require System Administrator role"""
    return require_role('System Administrator')(f)


def warden_required(f):
    """Require Warden or Admin role"""
    return require_role('System Administrator', 'Warden')(f)


def receptionist_required(f):
    """Require Receptionist role"""
    return require_role('Receptionist', 'System Administrator')(f)


def can_manage_inmates(f):
    """Require inmate management permission"""
    return require_permission(Permissions.INMATE_CREATE)(f)


def can_enroll_biometrics(f):
    """Require biometric enrollment permission"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not has_permission(Permissions.INMATE_BIOMETRIC_ENROLL) and \
           not has_permission(Permissions.VISITOR_BIOMETRIC_ENROLL):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function