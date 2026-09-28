import openpyxl
from app import create_app
from extensions import db
from models.visitor import Visitor

app = create_app()

def generate_visitor_number(seq_num):
    """Generates sequential visitor numbers like VIS-2026-00001"""
    return f"VIS-2026-{seq_num:05d}"

def import_visitors(file_path):
    with app.app_context():
        # Load Excel workbook
        wb = openpyxl.load_workbook(file_path, data_only=True)
        sheet = wb.active

        # Read headers from row 1
        headers = [str(cell.value).strip() if cell.value else "" for cell in sheet[1]]
        
        # Map header names to column index
        try:
            name_idx = headers.index("VISITOR'S NAME")
            district_idx = headers.index("District OF ORIGIN") if "District OF ORIGIN" in headers else None
            flag_idx = headers.index("Visitation Status / Contraband Flag") if "Visitation Status / Contraband Flag" in headers else None
        except ValueError as e:
            print(f"Error: Could not find required column 'VISITOR'S NAME' in header row. Found headers: {headers}")
            return

        # Get starting sequence for visitor_number
        last_visitor = Visitor.query.order_by(Visitor.visitor_id.desc()).first()
        start_seq = (last_visitor.visitor_id + 1) if last_visitor else 1

        imported_count = 0
        skipped_count = 0

        # Iterate rows starting from row 2
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not row:
                continue

            visitor_name = str(row[name_idx]).strip() if row[name_idx] is not None else ""
            
            # Skip empty rows
            if not visitor_name or visitor_name.upper() == 'NONE' or visitor_name.upper() == 'NAN':
                continue

            # Skip duplicates based on full name
            existing = Visitor.query.filter_by(full_name=visitor_name).first()
            if existing:
                skipped_count += 1
                continue

            # District / Address extraction
            district_val = str(row[district_idx]).strip() if district_idx is not None and row[district_idx] is not None else "Unknown"
            address_val = district_val if district_val.upper() not in ['NONE', 'NAN', ''] else "Unknown"

            # Contraband / Flag status checking
            flag_status = str(row[flag_idx]).strip() if flag_idx is not None and row[flag_idx] is not None else ""
            is_flagged = False
            flag_reason = None

            if any(term in flag_status.upper() for term in ["DENIED", "CONTRABAND", "FLAG"]):
                is_flagged = True
                flag_reason = flag_status

            # Create visitor entry
            visitor = Visitor(
                visitor_number=generate_visitor_number(start_seq + imported_count),
                full_name=visitor_name,
                address=address_val,
                phone_number="N/A",  # Non-nullable placeholder; can be updated later via forms
                is_flagged=is_flagged,
                flag_reason=flag_reason,
                risk_rating="High" if is_flagged else "Low",
                # Unpopulated fields remain None for future updates:
                national_id_number=None,
                passport_number=None,
                gender=None,
                date_of_birth=None,
                relationship_type=None
            )

            db.session.add(visitor)
            imported_count += 1

        db.session.commit()
        print(f"Import complete! {imported_count} visitors created, {skipped_count} duplicates skipped.")

if __name__ == '__main__':
    import_visitors('FINAL_VISITORS_DATA.xlsx')