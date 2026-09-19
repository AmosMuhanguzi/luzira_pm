# services/user_service.py
"""
Staff account management: CRUD, password reset, unlock, biometric reset.
All write operations write to the audit trail.
"""
from datetime import datetime
from sqlalchemy import or_
from extensions import db
from models.user import UserAccount, Role
from models.audit import AuditEvent


class UserService:

    # ---------- Read ----------
    @staticmethod
    def list_users(search=None, role_id=None, page=1, per_page=15):
        q = UserAccount.query

        if search:
            like = f'%{search.strip()}%'
            q = q.filter(or_(
                UserAccount.username.ilike(like),
                UserAccount.full_name.ilike(like),
                UserAccount.email.ilike(like),
            ))

        if role_id:
            q = q.filter(UserAccount.role_id == role_id)

        return q.order_by(UserAccount.full_name).paginate(
            page=page, per_page=per_page, error_out=False
        )

    @staticmethod
    def get(user_id) -> UserAccount:
        return UserAccount.query.get(user_id)

    @staticmethod
    def list_roles():
        return Role.query.order_by(Role.role_name).all()

    # ---------- Create ----------
    @staticmethod
    def create_user(actor, username, email, full_name, role_id,
                    password, phone_number=None, is_active=True):
        """
        Returns (user, error).
        """
        username = (username or '').strip().lower()
        email    = (email or '').strip().lower()

        if not username or not email or not full_name or not password:
            return None, 'All required fields must be provided.'
        if len(password) < 8:
            return None, 'Password must be at least 8 characters.'
        if UserAccount.query.filter_by(username=username).first():
            return None, f'Username "{username}" is already taken.'
        if UserAccount.query.filter_by(email=email).first():
            return None, f'Email "{email}" is already registered.'

        role = Role.query.get(role_id)
        if not role:
            return None, 'Invalid role selected.'

        user = UserAccount(
            username=username,
            email=email,
            full_name=full_name.strip(),
            phone_number=phone_number,
            role_id=role_id,
            is_active=is_active,
            biometric_enrolled=False,      # staff enrol on first login
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        UserService._audit(
            actor, 'Create', f'Created staff user "{user.username}" '
                             f'({role.role_name})', user
        )
        return user, None

    # ---------- Update ----------
    @staticmethod
    def update_user(actor, user_id, full_name=None, email=None,
                    phone_number=None, role_id=None, is_active=None):
        user = UserAccount.query.get(user_id)
        if not user:
            return None, 'User not found.'

        changed = []

        if full_name and full_name.strip() != user.full_name:
            changed.append(f'name: "{user.full_name}" -> "{full_name}"')
            user.full_name = full_name.strip()

        if email and email.strip().lower() != user.email:
            new_email = email.strip().lower()
            clash = UserAccount.query.filter(
                UserAccount.email == new_email,
                UserAccount.user_id != user.user_id,
            ).first()
            if clash:
                return None, f'Email "{new_email}" is already used by another user.'
            changed.append(f'email: "{user.email}" -> "{new_email}"')
            user.email = new_email

        if phone_number is not None and phone_number != user.phone_number:
            changed.append(f'phone: "{user.phone_number}" -> "{phone_number}"')
            user.phone_number = phone_number

        if role_id and role_id != user.role_id:
            role = Role.query.get(role_id)
            if not role:
                return None, 'Invalid role selected.'
            changed.append(f'role: "{user.role_name}" -> "{role.role_name}"')
            user.role_id = role_id

        if is_active is not None and is_active != user.is_active:
            changed.append(f'active: {user.is_active} -> {is_active}')
            user.is_active = is_active

        if not changed:
            return user, None   # no-op is not an error

        db.session.commit()
        UserService._audit(
            actor, 'Update', f'Updated user "{user.username}": {"; ".join(changed)}', user
        )
        return user, None

    # ---------- Password reset by admin ----------
    @staticmethod
    def admin_reset_password(actor, user_id, new_password):
        if len(new_password or '') < 8:
            return False, 'Password must be at least 8 characters.'
        user = UserAccount.query.get(user_id)
        if not user:
            return False, 'User not found.'

        user.set_password(new_password)
        user.failed_login_attempts = 0
        user.account_locked = False
        db.session.commit()

        UserService._audit(
            actor, 'PasswordReset',
            f'Admin reset password for "{user.username}"', user
        )
        return True, None

    # ---------- Unlock / activate ----------
    @staticmethod
    def unlock_account(actor, user_id):
        user = UserAccount.query.get(user_id)
        if not user:
            return False, 'User not found.'
        if not user.account_locked:
            return True, None
        user.account_locked = False
        user.failed_login_attempts = 0
        db.session.commit()
        UserService._audit(actor, 'Unlock', f'Unlocked account "{user.username}"', user)
        return True, None

    @staticmethod
    def toggle_active(actor, user_id, actor_id):
        if user_id == actor_id:
            return False, 'You cannot deactivate your own account.'
        user = UserAccount.query.get(user_id)
        if not user:
            return False, 'User not found.'
        user.is_active = not user.is_active
        db.session.commit()
        state = 'activated' if user.is_active else 'deactivated'
        UserService._audit(
            actor, 'ToggleActive', f'{state.capitalize()} user "{user.username}"', user
        )
        return True, None

    # ---------- Biometric reset ----------
    @staticmethod
    def reset_biometric(actor, user_id):
        user = UserAccount.query.get(user_id)
        if not user:
            return False, 'User not found.'
        user.fingerprint_template = None
        user.biometric_enrolled = False
        user.biometric_enrollment_date = None
        user.biometric_quality_score = None
        db.session.commit()
        UserService._audit(
            actor, 'BiometricReset',
            f'Fingerprint reset for "{user.username}" — must re-enrol on next login',
            user
        )
        return True, None

    # ---------- Delete ----------
    @staticmethod
    def delete_user(actor, user_id, actor_id):
        if user_id == actor_id:
            return False, 'You cannot delete your own account.'
        user = UserAccount.query.get(user_id)
        if not user:
            return False, 'User not found.'

        username = user.username
        db.session.delete(user)
        db.session.commit()

        # audit after delete (entity_id kept for record)
        AuditEvent.log_event(
            event_category='UserManagement',
            event_type='Delete',
            event_description=f'Deleted user "{username}"',
            entity_type='UserAccount',
            entity_id=user_id,
            user_id=actor.user_id,
            username=actor.username,
            user_role=actor.role_name,
            success=True,
        )
        db.session.commit()
        return True, None

    # ---------- Internal audit helper ----------
    @staticmethod
    def _audit(actor, event_type, description, target_user=None):
        AuditEvent.log_event(
            event_category='UserManagement',
            event_type=event_type,
            event_description=description,
            entity_type='UserAccount',
            entity_id=target_user.user_id if target_user else None,
            user_id=actor.user_id,
            username=actor.username,
            user_role=actor.role_name,
            success=True,
        )
        db.session.commit()