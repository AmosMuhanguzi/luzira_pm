import pandas as pd
from datetime import datetime
from app import create_app
from extensions import db
from models.inmate import Inmate

app = create_app()

def parse_date(val):
    if pd.isna(val) or str(val).strip() in ['N/A', 'Pending Trial', '', 'None']:
        return None
    if isinstance(val, datetime):
        return val.date()
    try:
        return datetime.strptime(str(val).strip(), '%Y-%m-%d').date()
    except Exception:
        return None

def import_data(file_path):
    with app.app_context():
        df = pd.read_excel(file_path)
        print(f"Loaded {len(df)} rows from {file_path}.")

        imported_count = 0
        for idx, row in df.iterrows():
            surname_val = str(row.get('Surname', '')).strip()
            given_val = str(row.get('Given Name', '')).strip()

            if not surname_val and not given_val:
                continue

            full_name = f"{given_val} {surname_val}".strip()
            cell_block_name = str(row.get('Assigned Cell / Block', '')).strip()

            inmate = Inmate(
                inmate_number=Inmate.generate_number(),
                full_name=full_name,
                gender=str(row.get('Gender', '')).strip(),
                nationality='Ugandan',  # Fixes NOT NULL constraint
                national_id_number=str(row.get('NIN', '')).strip(),
                date_of_birth=parse_date(row.get('Date of Birth')),
                next_of_kin_name=str(row.get('Next of Kin Name', '')).strip(),
                next_of_kin_relationship=str(row.get('Next of Kin Relationship', '')).strip(),
                next_of_kin_phone=str(row.get('Next of Kin Contact', '')).strip(),
                current_admission_date=parse_date(row.get('Admission Date')),
                court_case_number=str(row.get('CRB / Case File No.', '')).strip(),
                sentencing_court=str(row.get('Committing Court', '')).strip(),
                crime_category=str(row.get('Offence Category', '')).strip(),
                crime_description=str(row.get('Specific Offence Description', '')).strip(),
                status=str(row.get('Custody Status', 'Remand')).strip(),
                security_classification=str(row.get('Security Level', 'Medium')).strip(),
                sentence_duration=str(row.get('Sentence Length (Months)', '')).strip(),
                expected_release_date=parse_date(row.get('Expected Release Date')),
                cell_block=cell_block_name,
                medical_alert=str(row.get('Medical Status', '')).strip(),
                distinguishing_marks=str(row.get('Physical Appearance', '')).strip(),
                total_admissions=1,
                biometric_enrolled=False,
                has_medical_condition=False,
                violence_history=False,
                escape_attempt_history=False
            )

            db.session.add(inmate)
            imported_count += 1

            if imported_count % 500 == 0:
                db.session.commit()
                print(f"Committed {imported_count} records...")

        db.session.commit()
        print(f"Successfully imported all {imported_count} inmate records!")

if __name__ == '__main__':
    import_data('INMATES_DATA.xlsx')