function renderInmateList(inmates) {
    const listContainer = document.getElementById('cell-inmates-list');
    
    if (!inmates || inmates.length === 0) {
        listContainer.innerHTML = '<p class="text-muted">No active inmates currently assigned to this block.</p>';
        return;
    }

    let html = '<ul class="list-group">';
    inmates.forEach(inmate => {
        html += `
            <li class="list-group-item list-group-item-action d-flex justify-content-between align-items-center cursor-pointer" 
                onclick="window.location.href='/inmates/${inmate.inmate_id}'">
                <div>
                    <strong>${inmate.full_name}</strong> 
                    <span class="badge bg-secondary ms-2">${inmate.inmate_number}</span>
                    <br>
                    <small class="text-muted">Offense: ${inmate.crime} | Cell: ${inmate.cell_number}</small>
                </div>
                <span class="btn btn-sm btn-outline-primary">View Profile</span>
            </li>
        `;
    });
    html += '</ul>';

    listContainer.innerHTML = html;
}