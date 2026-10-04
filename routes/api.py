from flask import Blueprint, jsonify
from models.cell import CellBlock
from models.inmate import Inmate

api_bp = Blueprint('api_routes', __name__)

@api_bp.route('/cells/<int:cell_id>/inmates')
def get_cell_inmates(cell_id):
    # Retrieve the selected CellBlock object by primary key
    cell = CellBlock.query.get_or_404(cell_id)

    inmates = Inmate.query.filter(
        Inmate.cell_block == cell.name,
        Inmate.status == 'Active',
    ).order_by(Inmate.full_name.asc()).all()

    # Calculate occupancy stats
    occupancy = len(inmates)
    capacity = getattr(cell, 'capacity', 100) or 100
    percentage = round((occupancy / capacity) * 100, 1) if capacity > 0 else 0

    inmate_list = []
    for inmate in inmates:
        # Crime category fallback
        crime = inmate.crime_category or inmate.crime_description or 'N/A'
        
        # Format admission/intake date
        adm_date = inmate.current_admission_date
        intake_str = adm_date.strftime('%Y-%m-%d') if adm_date and hasattr(adm_date, 'strftime') else 'N/A'

        inmate_list.append({
            'inmate_id': inmate.inmate_id,
            'inmate_number': inmate.inmate_number,
            'full_name': inmate.full_name,
            'crime': crime,
            'intake_date': intake_str,
            'cell_number': inmate.cell_number or 'N/A'
        })

    return jsonify({
        'cell_id': cell.id,
        'cell_name': cell.name,
        'capacity': capacity,
        'occupancy': occupancy,
        'percentage': percentage,
        'inmates': inmate_list
    })