document.querySelectorAll('[data-fingerprint-enrollment]').forEach((panel) => {
    const button = panel.querySelector('[data-enroll-button]');
    const status = panel.querySelector('[data-enroll-status]');
    const form = panel.closest('form');

    button.addEventListener('click', async () => {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Scanning…';
        status.classList.remove('text-success', 'text-danger');
        status.classList.add('text-muted');
        status.textContent = "Place the person's finger on the scanner and hold still.";

        try {
            const response = await fetch(panel.dataset.enrollUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enrollment_id: panel.dataset.enrollmentId })
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || 'Fingerprint scan failed.');
            }

            button.classList.remove('btn-outline-primary');
            button.classList.add('btn-success');
            button.innerHTML = '<i class="bi bi-check-circle"></i> Scan again';
            status.classList.remove('text-muted', 'text-danger');
            status.classList.add('text-success');
            const sampleCount = result.samples_captured || 1;
            status.textContent =
                `Fingerprint captured (${sampleCount} sample${sampleCount === 1 ? '' : 's'}, quality ${result.quality}%). Submit the form to save enrollment.`;
        } catch (error) {
            button.classList.remove('btn-success');
            button.classList.add('btn-outline-primary');
            button.innerHTML = '<i class="bi bi-fingerprint"></i> Scan fingerprint';
            status.classList.remove('text-muted', 'text-success');
            status.classList.add('text-danger');
            status.textContent = error.message;
        } finally {
            button.disabled = false;
        }
    });

    form.addEventListener('submit', () => {
        button.disabled = true;
    });
});
