import unittest
from datetime import date

from services.sentence import offence_status, split_sentence
from services.inmate_service import InmateService
from services.edit_request_service import _resolve_legal_fields


class FakeInmate:
    offence_status = 'Convict'
    expected_release_date = date(2030, 1, 1)
    sentence_parts = ('2', 'year')


class LegalRulesTest(unittest.TestCase):
    def test_legacy_mapping(self):
        self.assertEqual(offence_status('REMAND', None), 'Remand')
        self.assertEqual(offence_status(None, 'N/A (Remand)'), 'Remand')
        self.assertEqual(offence_status('None', '120'), 'Convict')
        self.assertEqual(offence_status(None, None), '')
        self.assertEqual(split_sentence('120'), ('120', 'month'))
        self.assertEqual(split_sentence('2 years'), ('2', 'year'))

    def test_remand_requires_court_date(self):
        self.assertIsNotNone(InmateService.validate_legal_status({'sentence_type': 'Remand'}))

    def test_unchanged_sentence_keeps_release(self):
        data, err = _resolve_legal_fields(FakeInmate(), {
            'sentence_type': 'Convict', 'sentence_value': '2', 'sentence_unit': 'year'})
        self.assertIsNone(err)
        self.assertNotIn('expected_release_date', data)

    def test_changed_sentence_recalculates(self):
        data, err = _resolve_legal_fields(FakeInmate(), {
            'sentence_type': 'Convict', 'sentence_value': '1', 'sentence_unit': 'year'})
        self.assertEqual(data['sentence_duration'], '1 year')
        start = date.today()
        self.assertEqual((date.fromisoformat(data['expected_release_date']) - start).days, 324)

    def test_remand_clears_sentence(self):
        data, err = _resolve_legal_fields(FakeInmate(), {
            'sentence_type': 'Remand', 'next_court_date': '2030-01-01'})
        self.assertEqual(data['expected_release_date'], '')


if __name__ == '__main__':
    unittest.main()
