import unittest
from datetime import date

from flask import Flask

from extensions import db
from models import Inmate, Role, UserAccount
from services.edit_request_service import EditRequestService
from services.inmate_service import InmateService


class InmateMaritalStatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SECRET_KEY='test-secret',
            SQLALCHEMY_DATABASE_URI='sqlite://',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        with cls.app.app_context():
            import models  # noqa: F401
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()

        role = Role(role_name='System Administrator')
        db.session.add(role)
        db.session.flush()
        self.actor = UserAccount(
            username='test-admin',
            email='test-admin@example.invalid',
            password_hash='test',
            full_name='Test Administrator',
            role_id=role.role_id,
        )
        db.session.add(self.actor)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def test_marital_status_persists_through_registration_readmission_and_edit(self):
        inmate, error = InmateService.create_inmate(
            self.actor,
            {
                'full_name': 'Test Inmate',
                'date_of_birth': date(1990, 1, 1).isoformat(),
                'gender': 'Female',
                'nationality': 'Ugandan',
                'marital_status': 'Single',
            },
        )
        self.assertIsNone(error)
        self.assertEqual(inmate.marital_status, 'Single')
        self.assertEqual(inmate.to_dict()['marital_status'], 'Single')

        inmate, error = InmateService.readmit_inmate(
            self.actor, inmate.inmate_id, {'marital_status': 'Married'}
        )
        self.assertIsNone(error)
        self.assertEqual(inmate.marital_status, 'Married')

        edit_request, error = EditRequestService.submit_inmate_edit(
            self.actor, inmate.inmate_id, {'marital_status': 'Widowed'}
        )
        self.assertIsNone(error)
        approved, error = EditRequestService.approve(
            self.actor, edit_request.request_id
        )
        self.assertTrue(approved, error)
        self.assertEqual(inmate.marital_status, 'Widowed')

        inmate, error = InmateService.readmit_inmate(
            self.actor, inmate.inmate_id, {'marital_status': ''}
        )
        self.assertIsNone(error)
        self.assertIsNone(inmate.marital_status)


if __name__ == '__main__':
    unittest.main()
