# services/auth_service.py
"""
Authentication logic: credential check, lockout, and audit logging.
"""
from datetime import datetime
from extensions import db
from models.user import UserAccount
from models.audit import AuditEvent

MAX_FAILED_ATTEMPTS = 5


class AuthService:

    @staticmethod
    def authenticate(username: str, password: str, ip: str = None,
                     user_agent: str = None) -> tuple:
        """
        Returns (user, error_message).
        user is None on failure; error_message is None on success.
        """
        username = (username or '').strip()
        user = UserAccount.query.filter_by(username=username).first()

        # -- user not found --
        if not user:
            AuthService._audit(
                event_type='Login',
                description=f'Login attempt for unknown user "{username}"',
                user=None, ip=ip, user_agent=user_agent, success=False,
                error_message='Invalid credentials'
            )
            return None, 'Invalid username or password.'

        # -- account locked --
        if user.account_locked:
            AuthService._audit(
                event_type='Login',
                description=f'Login attempt on locked account "{username}"',
                user=user, ip=ip, user_agent=user_agent, success=False,
                error_message='Account locked'
            )
            return None, 'Account is locked. Contact the administrator.'

        # -- inactive --
        if not user.is_active:
            return None, 'Account is inactive.'

        # -- wrong password --
        if not user.check_password(password):
            user.register_failed_login(MAX_FAILED_ATTEMPTS)
            db.session.commit()

            remaining = MAX_FAILED_ATTEMPTS - (user.failed_login_attempts or 0)
            if user.account_locked:
                msg = 'Too many failed attempts. Account locked.'
            else:
                msg = f'Invalid username or password. {remaining} attempt(s) left.'

            AuthService._audit(
                event_type='Login',
                description=f'Failed login for "{username}"',
                user=user, ip=ip, user_agent=user_agent, success=False,
                error_message='Wrong password'
            )
            return None, msg

        # -- success --
        user.register_login(ip)
        db.session.commit()

        AuthService._audit(
            event_type='Login',
            description=f'Successful login for "{username}"',
            user=user, ip=ip, user_agent=user_agent, success=True
        )
        return user, None

    @staticmethod
    def change_password(user: UserAccount, current_password: str,
                        new_password: str) -> tuple:
        """
        Returns (success: bool, error_message: str | None).
        """
        if not user.check_password(current_password):
            return False, 'Current password is incorrect.'

        if len(new_password) < 8:
            return False, 'New password must be at least 8 characters.'

        if current_password == new_password:
            return False, 'New password must be different from the current one.'

        user.set_password(new_password)
        db.session.commit()

        AuthService._audit(
            event_category='Authentication',
            event_type='PasswordChange',
            description=f'Password changed for "{user.username}"',
            user=user,
            success=True
        )
        return True, None

    @staticmethod
    def _audit(event_type, description, user=None, ip=None, user_agent=None,
               success=True, error_message=None, event_category='Authentication'):
        try:
            AuditEvent.log_event(
                event_category=event_category,
                event_type=event_type,
                event_description=description,
                entity_type='UserAccount',
                entity_id=user.user_id if user else None,
                user_id=user.user_id if user else None,
                username=user.username if user else None,
                user_role=user.role_name if user else None,
                ip_address=ip,
                user_agent=(user_agent or '')[:500] if user_agent else None,
                success=success,
                error_message=error_message,
            )
            db.session.commit()
        except Exception:
            # Never let audit failure break login
            db.session.rollback()

    # services/auth_service.py — add these methods to AuthService

    # ---------- Pending-login session helpers ----------
    @staticmethod
    def set_pending_login(session_obj, user, timeout_seconds):
        """
        Store a short-lived marker saying 'password OK, awaiting fingerprint'.
        Does NOT log the user in.
        """
        import secrets, time
        session_obj['pending_login'] = {
            'user_id': user.user_id,
            'token': secrets.token_urlsafe(24),
            'expires_at': time.time() + timeout_seconds,
        }
        return session_obj['pending_login']['token']

    @staticmethod
    def get_pending_user(session_obj, token=None):
        """
        Return the UserAccount referenced by the pending session, or None.
        Verifies token (if provided) and expiry.
        """
        import time
        data = session_obj.get('pending_login')
        if not data:
            return None
        if time.time() > data.get('expires_at', 0):
            session_obj.pop('pending_login', None)
            return None
        if token and data.get('token') != token:
            return None
        return UserAccount.query.get(data['user_id'])

    @staticmethod
    def clear_pending_login(session_obj):
        session_obj.pop('pending_login', None)

    # ---------- Fingerprint verification (1:1) ----------
    @staticmethod
    def verify_staff_fingerprint(user, probe_template, ip=None, user_agent=None):
        """
        Compare probe template against THIS user's stored template only (1:1).
        Returns (ok: bool, error: str | None, score: float).
        """
        if not user.has_biometric():
            return False, 'No fingerprint enrolled for this account.', 0.0

        try:
            from services.biometric_matcher import compare_templates
            score = compare_templates(probe_template, user.fingerprint_template)
        except Exception as e:
            return False, f'Fingerprint comparison failed: {e}', 0.0

        from flask import current_app
        threshold = current_app.config.get('BIOMETRIC_MATCH_THRESHOLD', 75)

        if score >= threshold:
            AuthService._audit(
                event_type='StaffFingerprintOK',
                description=f'Fingerprint verified for "{user.username}" (score={score:.1f})',
                user=user, ip=ip, user_agent=user_agent, success=True
            )
            return True, None, score

        AuthService._audit(
            event_type='StaffFingerprintFAIL',
            description=f'Fingerprint mismatch for "{user.username}" (score={score:.1f})',
            user=user, ip=ip, user_agent=user_agent, success=False,
            error_message='Fingerprint mismatch'
        )
        return False, 'Fingerprint did not match.', score

    # ---------- First-time enrolment ----------
    @staticmethod
    def enroll_staff_fingerprint(user, template, quality, ip=None, user_agent=None):
        """
        Store the fingerprint template for this user. Returns (ok, error).
        """
        from flask import current_app
        min_quality = current_app.config.get('BIOMETRIC_QUALITY_MIN', 60)

        if not template:
            return False, 'No fingerprint template received.'

        if quality is not None and quality < min_quality:
            return False, f'Fingerprint quality too low ({quality} < {min_quality}). Try again.'

        try:
            template_bytes = template if isinstance(template, bytes) else __import__('base64').b64decode(template)
        except Exception as e:
            return False, f'Invalid template format: {e}'

        user.enroll_biometric(template_bytes, quality or 0)
        db.session.commit()

        AuthService._audit(
            event_type='StaffFingerprintENROLL',
            description=f'Fingerprint enrolled for "{user.username}"',
            user=user, ip=ip, user_agent=user_agent, success=True
        )
        return True, None