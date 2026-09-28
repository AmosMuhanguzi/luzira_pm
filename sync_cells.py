from app import create_app
from extensions import db
from models.inmate import Inmate
from models.cell import CellBlock
from sqlalchemy import func

app = create_app()

with app.app_context():
    print("Syncing cell blocks from inmate records...")
    
    # 1. Get unique cell_block names and occupancy counts directly from imported inmates
    cell_counts = db.session.query(
        Inmate.cell_block, 
        func.count(Inmate.inmate_id)
    ).group_by(Inmate.cell_block).all()
    
    # 2. Clear old predefined hardcoded blocks if necessary or update existing ones
    for block_name, count in cell_counts:
        if not block_name or block_name.strip() in ['', 'N/A', 'None']:
            continue
            
        clean_name = block_name.strip()
        cell = CellBlock.query.filter_by(name=clean_name).first()
        
        # Estimate reasonable capacity based on actual counts (e.g., count + 20% room or min 1000)
        estimated_capacity = max(1000, int(count * 1.25))
        
        if cell:
            cell.current_occupancy = count
            cell.capacity = max(cell.capacity, estimated_capacity)
        else:
            cell = CellBlock(
                name=clean_name,
                capacity=estimated_capacity,
                current_occupancy=count
            )
            db.session.add(cell)
            
    db.session.commit()
    print("Successfully synchronized all cell blocks with database counts!")