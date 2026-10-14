import unittest
from datetime import date

from flask import Flask
from werkzeug.datastructures import MultiDict

from extensions import db
from models import Role, UserAccount
from models.inmate import InmateProperty
from services.inmate_property_service import InmatePropertyService
from services.inmate_service import InmateService


class InmatePropertyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SECRET_KEY='test-secret',
            SQLALCHEMY_DATABASE_URI='sqlite://',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        import models  # noqa: F401
        db.drop_all()
        db.create_all()
        role = Role(role_name='System Administrator')
        db.session.add(role)
        db.session.flush()
        self.actor = UserAccount(
            username='test-admin', email='a@example.invalid', password_hash='x',
            full_name='Test Administrator', role_id=role.role_id,
        )
        db.session.add(self.actor)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def _register(self, items):
        inmate, error = InmateService.create_inmate(self.actor, {
            'full_name': 'Test Inmate',
            'date_of_birth': date(1990, 1, 1).isoformat(),
            'gender': 'Male',
            'nationality': 'Ugandan',
            'property_items': items,
        })
        self.assertIsNone(error)
        return inmate

    def test_parse_pairs_items_and_skips_blank_rows(self):
        form = MultiDict([
            ('property_item', 'Phone'), ('property_description', 'Black Tecno'),
            ('property_item', ''), ('property_description', ''),
            ('property_item', 'Watch'), ('property_description', ''),
        ])
        self.assertEqual(
            InmatePropertyService.parse_form_items(form),
            [{'item_name': 'Phone', 'description': 'Black Tecno'},
             {'item_name': 'Watch', 'description': ''}],
        )

    def test_no_property_defaults_to_none(self):
        inmate = self._register([])
        self.assertEqual(InmatePropertyService.claims_text(inmate.inmate_id), 'None')

    def test_handed_over_item_leaves_list_and_claims(self):
        inmate = self._register([
            {'item_name': 'Phone', 'description': 'Black Tecno'},
            {'item_name': 'Watch', 'description': ''},
        ])
        self.assertEqual(
            InmatePropertyService.claims_text(inmate.inmate_id),
            '1. Phone - Black Tecno\n2. Watch',
        )
        phone = InmatePropertyService.in_custody(inmate.inmate_id)[0]
        item, error = InmatePropertyService.hand_over(
            self.actor, phone.property_id, inmate.inmate_id, 'Jane', 'Sister')
        self.assertIsNone(error)
        db.session.commit()
        self.assertEqual(InmatePropertyService.claims_text(inmate.inmate_id), '1. Watch')
        _, error = InmatePropertyService.hand_over(
            self.actor, phone.property_id, inmate.inmate_id, 'Jane', 'Sister')
        self.assertIsNotNone(error)

    def test_release_clears_remaining_items(self):
        inmate = self._register([{'item_name': 'Belt', 'description': ''}])
        InmatePropertyService.mark_returned_on_release(inmate.inmate_id, self.actor)
        db.session.commit()
        self.assertEqual(InmatePropertyService.in_custody(inmate.inmate_id), [])
        self.assertEqual(
            InmateProperty.query.one().status, InmateProperty.STATUS_RETURNED)

    def test_weight_is_saved(self):
        inmate, error = InmateService.create_inmate(self.actor, {
            'full_name': 'W', 'date_of_birth': '1990-01-01', 'gender': 'Male',
            'nationality': 'Ugandan', 'weight_kg': '63', 'height_m': '1.70',
        })
        self.assertIsNone(error)
        self.assertEqual((inmate.weight_kg, inmate.height_cm), (63, 170))


if __name__ == '__main__':
    unittest.main()
