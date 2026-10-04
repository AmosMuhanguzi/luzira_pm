# models/cell.py
from extensions import db

class CellBlock(db.Model):
    __tablename__ = 'cell_blocks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    capacity = db.Column(db.Integer, default=100, nullable=False)
    current_occupancy = db.Column(db.Integer, default=0, nullable=False)
    security_classification = db.Column(db.String(20), nullable=True)

    @staticmethod
    def generate_next_name():
        """Generates the next available cell block name (A-Z, A1-Z1, etc.)"""
        total_existing = CellBlock.query.count()
        letter = chr(65 + (total_existing % 26))
        cycle = total_existing // 26
        return f"{letter}{cycle}" if cycle > 0 else letter

    
from flask import Blueprint, jsonify
from models.cell import CellBlock
from models.inmate import Inmate

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/cells/<int:cell_id>/inmates')
def get_cell_inmates(cell_id):
    cell = CellBlock.query.get_or_404(cell_id)
    inmates = Inmate.query.filter_by(cell_id=cell.id, status='Active').all()

    occupancy = cell.current_occupancy or len(inmates)
    capacity = cell.capacity or 100
    percentage = round((occupancy / capacity) * 100, 1) if capacity > 0 else 0

    inmate_list = [
        {
            'inmate_number': f"INM-{i.id:04d}",
            'full_name': i.full_name,
            'crime': getattr(i, 'crime', getattr(i, 'offense', 'N/A')),
            'intake_date': i.admission_date.strftime('%Y-%m-%d') if getattr(i, 'admission_date', None) else 'N/A'
        }
        for i in inmates
    ]

    return jsonify({
        'cell_name': cell.name,
        'capacity': capacity,
        'occupancy': occupancy,
        'percentage': percentage,
        'inmates': inmate_list
    })