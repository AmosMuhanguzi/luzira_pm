document.querySelectorAll('[data-photo-capture]').forEach((capture) => {
    const video = capture.querySelector('[data-photo-video]');
    const image = capture.querySelector('[data-photo-image]');
    const placeholder = capture.querySelector('[data-photo-placeholder]');
    const photoValue = capture.querySelector('[data-photo-value]');
    const captureButton = capture.querySelector('[data-photo-button]');
    const status = capture.querySelector('[data-photo-status]');
    let stream;

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach((track) => track.stop());
            stream = null;
        }
        video.srcObject = null;
    }

    function showCapturedPhoto(dataUrl) {
        photoValue.value = dataUrl;
        image.src = dataUrl;
        image.classList.remove('d-none');
        video.classList.add('d-none');
        placeholder.classList.add('d-none');
        captureButton.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i> Retake photo';
        status.textContent = 'Photo captured. It will be saved when you submit the form.';
        stopCamera();
    }

    function waitForVideo(videoElement) {
        if (videoElement.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
            return Promise.resolve();
        }
        return new Promise((resolve, reject) => {
            videoElement.addEventListener('loadeddata', resolve, { once: true });
            videoElement.addEventListener('error', reject, { once: true });
        });
    }

    if (photoValue.value) {
        image.src = photoValue.value;
        image.classList.remove('d-none');
        placeholder.classList.add('d-none');
        captureButton.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i> Retake photo';
        status.textContent = 'Photo captured. It will be saved when you submit the form.';
    }

    captureButton.addEventListener('click', async () => {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            status.textContent = 'Camera access is unavailable. Use HTTPS or a supported browser.';
            return;
        }

        captureButton.disabled = true;
        status.textContent = 'Opening camera…';
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: {
                    facingMode: { ideal: 'environment' },
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                }
            });
            video.srcObject = stream;
            video.classList.remove('d-none');
            image.classList.add('d-none');
            placeholder.classList.add('d-none');
            await video.play();
            await waitForVideo(video);
            status.textContent = 'Hold still. Capturing photo…';
            await new Promise((resolve) => window.setTimeout(resolve, 900));

            const scale = Math.min(1, 1280 / video.videoWidth);
            const canvas = document.createElement('canvas');
            canvas.width = Math.round(video.videoWidth * scale);
            canvas.height = Math.round(video.videoHeight * scale);
            const context = canvas.getContext('2d');
            if (!context) throw new Error('Photo capture is unavailable.');
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            showCapturedPhoto(canvas.toDataURL('image/jpeg', 0.82));
        } catch (error) {
            stopCamera();
            video.classList.add('d-none');
            if (photoValue.value) {
                image.classList.remove('d-none');
                placeholder.classList.add('d-none');
            } else {
                placeholder.classList.remove('d-none');
            }
            status.textContent = error.name === 'NotAllowedError'
                ? 'Camera permission was denied. Allow access and try again.'
                : 'Could not capture a photo. Check the camera and try again.';
        } finally {
            captureButton.disabled = false;
        }
    });

    capture.closest('form').addEventListener('submit', stopCamera);
});
