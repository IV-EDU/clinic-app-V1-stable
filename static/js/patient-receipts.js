// Patient Receipt Print Functionality

document.addEventListener('DOMContentLoaded', function() {
    initializeReceiptPrint();
    initializePrintModal();
    initializeViewReceiptModal();
    initializeFormModal();
});

function initializeReceiptPrint() {
    // Direct print buttons
    document.addEventListener('click', function(e) {
        if (e.target.matches('.print-receipt-btn') || e.target.closest('.print-receipt-btn')) {
            e.preventDefault();
            const button = e.target.matches('.print-receipt-btn') ? e.target : e.target.closest('.print-receipt-btn');
            const paymentId = button.dataset.paymentId;
            const patientId = button.dataset.patientId;
            
            showPrintModal(paymentId, patientId);
        }
    });
}

function initializePrintModal() {
    const modal = document.getElementById('printReceiptModal');
    if (!modal) return;

    const confirmBtn = document.getElementById('confirmPrintReceiptBtn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', function() {
            const patientId = modal.dataset.patientId;
            const includeTreatmentNotes = document.getElementById('include-notes')?.checked ?? false;
            const includePaymentNotes = document.getElementById('include-payment-notes')?.checked ?? false;
            const langChoice = document.querySelector('input[name="receipt-lang"]:checked')?.value || 'current';
            const targetType = modal.dataset.targetType || 'payment';
            if (targetType === 'treatment') {
                const treatmentId = modal.dataset.treatmentId;
                if (!treatmentId || !patientId) return;
                openTreatmentForPrint(treatmentId, patientId, {
                    includeTreatmentNotes,
                    includePaymentNotes,
                    language: langChoice
                });
                return;
            }
            const paymentId = modal.dataset.paymentId;
            if (!paymentId || !patientId) {
                return;
            }
            const scope = document.querySelector('input[name="receipt-scope"]:checked')?.value || 'payment_only';
            openReceiptForPrint(paymentId, patientId, {
                includeTreatmentNotes,
                includePaymentNotes,
                language: langChoice,
                scope
            });
        });
    }

    const closeButtons = modal.querySelectorAll('.close, [data-dismiss="modal"], .modal-close');
    closeButtons.forEach(button => {
        button.addEventListener('click', hidePrintModal);
    });

    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            hidePrintModal();
        }
    });
}

function showPrintModal(paymentId, patientId) {
    const modal = document.getElementById('printReceiptModal');
    if (!modal) return;
    
    // Store payment and patient IDs in modal
    modal.dataset.targetType = 'payment';
    modal.dataset.paymentId = paymentId;
    modal.dataset.patientId = patientId;
    delete modal.dataset.treatmentId;
    configurePrintModal('payment');
    
    // Show modal using modern approach
    modal.classList.add('active');
    
    // Prevent body scroll
    document.body.style.overflow = 'hidden';
}

function showTreatmentPrintModal(treatmentId, patientId) {
    const modal = document.getElementById('printReceiptModal');
    if (!modal) return;
    modal.dataset.targetType = 'treatment';
    modal.dataset.treatmentId = treatmentId;
    modal.dataset.patientId = patientId;
    delete modal.dataset.paymentId;
    configurePrintModal('treatment');
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function hidePrintModal() {
    const modal = document.getElementById('printReceiptModal');
    if (!modal) return;
    
    modal.classList.remove('active');
    
    // Restore body scroll
    document.body.style.overflow = '';
    
    // Clear stored data
    delete modal.dataset.targetType;
    delete modal.dataset.paymentId;
    delete modal.dataset.patientId;
    delete modal.dataset.treatmentId;
}

function configurePrintModal(mode) {
    const modal = document.getElementById('printReceiptModal');
    if (!modal) return;
    const scopeBlock = document.getElementById('paymentPrintScopeBlock');
    const treatmentNotesOption = document.getElementById('treatmentNotesOption');
    const includeTreatmentNotesInput = document.getElementById('include-notes');
    const titleEl = modal.querySelector('.modal-title');
    const confirmBtn = document.getElementById('confirmPrintReceiptBtn');
    const titlePayment = modal.dataset.titlePayment || 'Print Payment Receipt';
    const titleTreatment = modal.dataset.titleTreatment || 'Print Summary';
    const confirmPayment = modal.dataset.confirmPayment || 'Print Receipt';
    const confirmTreatment = modal.dataset.confirmTreatment || 'Print Summary';

    if (scopeBlock) {
        scopeBlock.style.display = mode === 'payment' ? '' : 'none';
    }
    if (treatmentNotesOption) {
        treatmentNotesOption.style.display = mode === 'treatment' ? '' : 'none';
    }
    if (mode === 'payment' && includeTreatmentNotesInput) {
        includeTreatmentNotesInput.checked = false;
    }
    if (titleEl) {
        titleEl.textContent = mode === 'treatment' ? titleTreatment : titlePayment;
    }
    if (confirmBtn) {
        confirmBtn.innerHTML = `<i class="fa fa-print"></i> ${mode === 'treatment' ? confirmTreatment : confirmPayment}`;
    }
    if (mode === 'payment') {
        const defaultScope = document.querySelector('input[name="receipt-scope"][value="payment_only"]');
        if (defaultScope) defaultScope.checked = true;
    }
}

// Unified close modal function for consistency
function closeModal() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.classList.remove('active');
    });
    document.body.style.overflow = '';
}

function initializeViewReceiptModal() {
    document.addEventListener('click', function(e) {
        const link = e.target.closest('.view-receipt-btn');
        if (!link) return;

        e.preventDefault();

        const paymentId = link.dataset.paymentId;
        const patientId = link.dataset.patientId;
        if (!paymentId || !patientId) {
            return;
        }

        showViewReceiptModal(paymentId, patientId);
    });

    const modal = document.getElementById('viewReceiptModal');
    if (modal) {
        const closeButtons = modal.querySelectorAll('.close, [data-dismiss="modal"], .modal-close');
        closeButtons.forEach(btn => {
            btn.addEventListener('click', hideViewReceiptModal);
        });
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                hideViewReceiptModal();
            }
        });
    }
}

async function showViewReceiptModal(paymentId, patientId) {
    const modal = document.getElementById('viewReceiptModal');
    const content = document.getElementById('viewReceiptContent');
    if (!modal || !content) return;

    content.innerHTML = '<p>Loading receipt...</p>';
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    const url = `/patients/${encodeURIComponent(patientId)}/payments/${encodeURIComponent(paymentId)}/view-modal`;
    try {
        const response = await fetch(url, { method: 'GET' });
        if (!response.ok) {
            throw new Error('Failed to load receipt view');
        }
        const html = await response.text();
        content.innerHTML = html;
    } catch (err) {
        console.error('Error loading receipt modal:', err);
        content.innerHTML = '<div class="alert alert-error">Unable to load receipt.</div>';
    }
}

function hideViewReceiptModal() {
    const modal = document.getElementById('viewReceiptModal');
    const content = document.getElementById('viewReceiptContent');
    if (!modal) return;

    modal.classList.remove('active');
    document.body.style.overflow = '';

    if (content) {
        content.innerHTML = '';
    }
}

function initializeFormModal() {
    const modal = document.getElementById('formModal');
    if (!modal) return;

    const titleEl = document.getElementById('formModalTitle');
    const bodyEl = document.getElementById('formModalBody');

    function openFormModal(url, title) {
        if (!bodyEl || !titleEl) return;
        titleEl.textContent = title || '';
        bodyEl.innerHTML = '<p>Loading...</p>';
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';

        fetch(url, { method: 'GET' })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to load form');
                }
                return response.text();
            })
            .then(html => {
                bodyEl.innerHTML = html;
                if (window.initializePaymentForm) {
                    try {
                        window.initializePaymentForm(bodyEl);
                    } catch (e) {
                        console.warn('initializePaymentForm failed', e);
                    }
                }
                if (window.initConsultationTreatmentForm) {
                    try {
                        window.initConsultationTreatmentForm(bodyEl.querySelector('form#editTreatmentModalForm'));
                    } catch (e) {
                        console.warn('initConsultationTreatmentForm failed', e);
                    }
                }
            })
            .catch(err => {
                console.error('Error loading form modal:', err);
                bodyEl.innerHTML = '<div class="alert alert-error">Unable to load form.</div>';
            });
    }

    async function submitModalForm(form) {
        if (!form || !bodyEl) return;
        if (typeof form.reportValidity === 'function' && !form.reportValidity()) {
            return;
        }

        const action = form.getAttribute('action');
        if (!action) return;

        const formData = new FormData(form);
        try {
            const response = await fetch(action, {
                method: (form.getAttribute('method') || 'POST').toUpperCase(),
                body: formData,
                headers: {
                    'X-Modal': '1',
                },
            });

            if (response.status === 204) {
                hideFormModal();
                try {
                    const m = window.location.pathname.match(/\/patients\/([^/]+)/);
                    const patientId = m ? m[1] : null;
                    if (patientId) {
                        const key = `treatments_ui_state:${patientId}`;
                        const restoreKey = `treatments_ui_restore_once:${patientId}`;
                        const raw = localStorage.getItem(key);
                        const curr = raw ? (JSON.parse(raw) || {}) : {};
                        curr.scrollY = window.scrollY || 0;
                        localStorage.setItem(key, JSON.stringify(curr));
                        sessionStorage.setItem(restoreKey, '1');
                    }
                } catch (e) {
                    // ignore
                }
                window.location.reload();
                return;
            }

            const html = await response.text();
            if (response.status === 422) {
                bodyEl.innerHTML = html;
                if (window.initializePaymentForm) {
                    try {
                        window.initializePaymentForm(bodyEl);
                    } catch (e) {
                        console.warn('initializePaymentForm failed', e);
                    }
                }
                if (window.initConsultationTreatmentForm) {
                    try {
                        window.initConsultationTreatmentForm(bodyEl.querySelector('form#editTreatmentModalForm'));
                    } catch (e) {
                        console.warn('initConsultationTreatmentForm failed', e);
                    }
                }
                return;
            }

            if (response.redirected) {
                window.location.href = response.url;
                return;
            }

            if (!response.ok) {
                throw new Error('Failed to submit form');
            }

            bodyEl.innerHTML = html;
            if (window.initializePaymentForm) {
                try {
                    window.initializePaymentForm(bodyEl);
                } catch (e) {
                    console.warn('initializePaymentForm failed', e);
                }
            }
            if (window.initConsultationTreatmentForm) {
                try {
                    window.initConsultationTreatmentForm(bodyEl.querySelector('form#editTreatmentModalForm'));
                } catch (e) {
                    console.warn('initConsultationTreatmentForm failed', e);
                }
            }
        } catch (err) {
            console.error('Error submitting form modal:', err);
            bodyEl.insertAdjacentHTML('afterbegin', '<div class="alert alert-error">Unable to save form.</div>');
        }
    }

    document.addEventListener('click', function(e) {
        const newPaymentLink = e.target.closest('.new-payment-btn');
        if (newPaymentLink) {
            e.preventDefault();
            const patientId = newPaymentLink.href.split('/patients/')[1]?.split('/')[0];
            if (!patientId) return;
            const url = `/patients/${encodeURIComponent(patientId)}/excel-entry/modal`;
            openFormModal(url, newPaymentLink.textContent.trim() || 'Add Payment');
            return;
        }

        const editPaymentLink = e.target.closest('.edit-payment-btn');
        if (editPaymentLink) {
            e.preventDefault();
            const paymentId = editPaymentLink.dataset.paymentId;
            const patientId = editPaymentLink.dataset.patientId;
            if (!paymentId || !patientId) return;
            const url = `/patients/${encodeURIComponent(patientId)}/payments/${encodeURIComponent(paymentId)}/edit-modal`;
            openFormModal(url, editPaymentLink.textContent.trim() || 'Edit Payment');
            return;
        }

        const editTreatmentLink = e.target.closest('.edit-treatment-btn');
        if (editTreatmentLink) {
            e.preventDefault();
            const treatmentId = editTreatmentLink.dataset.treatmentId;
            const patientId = editTreatmentLink.dataset.patientId;
            if (!treatmentId || !patientId) return;
            const url = `/patients/${encodeURIComponent(patientId)}/treatments/${encodeURIComponent(treatmentId)}/edit-modal`;
            openFormModal(url, editTreatmentLink.textContent.trim() || 'Edit Treatment');
            return;
        }

        const editPatientLink = e.target.closest('.edit-patient-btn');
        if (editPatientLink) {
            e.preventDefault();
            const patientIdMatch = editPatientLink.href.match(/\/patients\/([^/]+)/);
            const patientId = patientIdMatch ? patientIdMatch[1] : null;
            if (!patientId) return;
            const url = `/patients/${encodeURIComponent(patientId)}/edit/modal`;
            openFormModal(url, editPatientLink.textContent.trim() || 'Edit Patient');
            return;
        }
    });

    const closeButtons = modal.querySelectorAll('.modal-close');
    closeButtons.forEach(btn => {
        btn.addEventListener('click', hideFormModal);
    });
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            hideFormModal();
        }
    });

    document.addEventListener('submit', function(e) {
        const form = e.target;
        if (!form || !bodyEl || !bodyEl.contains(form)) return;
        e.preventDefault();
        submitModalForm(form);
    });
}

function hideFormModal() {
    const modal = document.getElementById('formModal');
    const bodyEl = document.getElementById('formModalBody');
    if (!modal) return;
    modal.classList.remove('active');
    document.body.style.overflow = '';
    if (bodyEl) {
        bodyEl.innerHTML = '';
    }
}

async function openReceiptForPrint(paymentId, patientId, options) {
    hidePrintModal();
    const receiptCard = await buildReceiptCard(paymentId, patientId, {
        trimHeader: false,
        includeTreatmentNotes: options?.includeTreatmentNotes === true,
        includePaymentNotes: options?.includePaymentNotes === true,
        language: options?.language || 'current',
        scope: options?.scope || 'payment_only'
    });

    if (!receiptCard) {
        showErrorMessage('Unable to load receipt for printing.');
        return;
    }

    const printHost = getPrintHost();
    printHost.innerHTML = '';

    const pageWrapper = document.createElement('div');
    pageWrapper.className = 'receipt-page';
    const lang = options?.language || 'current';
    if (lang === 'ar') {
        pageWrapper.setAttribute('dir', 'rtl');
    } else if (lang === 'en') {
        pageWrapper.setAttribute('dir', 'ltr');
    } else {
        // current_language: follow the app's current direction
        const docDir = document.documentElement.getAttribute('dir') || 'ltr';
        pageWrapper.setAttribute('dir', docDir);
    }
    pageWrapper.appendChild(receiptCard);
    printHost.appendChild(pageWrapper);

    await waitForPrintAssets(pageWrapper);
    setTimeout(function() {
        window.print();
    }, 100);
}

async function openTreatmentForPrint(treatmentId, patientId, options) {
    hidePrintModal();
    const treatmentCard = await buildTreatmentPrintCard(treatmentId, patientId, {
        includeTreatmentNotes: options?.includeTreatmentNotes === true,
        includePaymentNotes: options?.includePaymentNotes === true,
        language: options?.language || 'current'
    });
    if (!treatmentCard) {
        showErrorMessage('Unable to load treatment summary for printing.');
        return;
    }

    const printHost = getPrintHost();
    printHost.innerHTML = '';

    const pageWrapper = document.createElement('div');
    pageWrapper.className = 'receipt-page';
    const lang = options?.language || 'current';
    if (lang === 'ar') {
        pageWrapper.setAttribute('dir', 'rtl');
    } else if (lang === 'en') {
        pageWrapper.setAttribute('dir', 'ltr');
    } else {
        const docDir = document.documentElement.getAttribute('dir') || 'ltr';
        pageWrapper.setAttribute('dir', docDir);
    }
    pageWrapper.appendChild(treatmentCard);
    printHost.appendChild(pageWrapper);

    await waitForPrintAssets(pageWrapper);
    setTimeout(function() {
        window.print();
    }, 100);
}

async function buildReceiptCard(paymentId, patientId, options = {}) {
    const {
        trimHeader = false,
        includeTreatmentNotes = false,
        includePaymentNotes = false,
        language = 'current',
        scope = 'payment_only'
    } = options;

    try {
        const params = new URLSearchParams();
        if (language && language !== 'current') {
            params.set('lang', language);
        }
        params.set('scope', scope);
        let url = `/patients/${patientId}/payments/${paymentId}/view-modal`;
        const query = params.toString();
        if (query) {
            url += `?${query}`;
        }
        const response = await fetch(url, { method: 'GET' });
        if (!response.ok) {
            throw new Error('Failed to load receipt');
        }
        const htmlText = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(htmlText, 'text/html');
        let receiptCard = doc.querySelector('.receipt-card');

        if (!receiptCard) {
            console.error('Receipt card element not found in response');
            return null;
        }

        const clone = receiptCard.cloneNode(true);

        if (trimHeader) {
            clone.querySelectorAll('.receipt-header').forEach(el => el.remove());
            clone.querySelectorAll('.receipt-footer').forEach(el => el.remove());
        }

        if (!includePaymentNotes) {
            clone.querySelectorAll('[data-section="notes"]').forEach(el => el.remove());
        }
        if (!includeTreatmentNotes) {
            clone.querySelectorAll('[data-section="treatment"]').forEach(el => el.remove());
        }

        return clone;
    } catch (err) {
        console.error('Error loading receipt view:', err);
        return null;
    }
}

async function buildTreatmentPrintCard(treatmentId, patientId, options = {}) {
    const { includeTreatmentNotes = false, includePaymentNotes = false, language = 'current' } = options;
    try {
        const params = new URLSearchParams();
        if (language && language !== 'current') {
            params.set('lang', language);
        }
        let url = `/patients/${patientId}/treatments/${treatmentId}/print-modal`;
        const query = params.toString();
        if (query) {
            url += `?${query}`;
        }
        const response = await fetch(url, { method: 'GET' });
        if (!response.ok) {
            throw new Error('Failed to load treatment print card');
        }
        const htmlText = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(htmlText, 'text/html');
        const treatmentCard = doc.querySelector('.receipt-card');
        if (!treatmentCard) {
            return null;
        }
        const clone = treatmentCard.cloneNode(true);
        if (!includeTreatmentNotes) {
            clone.querySelectorAll('[data-section="notes"]').forEach(el => el.remove());
        }
        if (!includePaymentNotes) {
            clone.querySelectorAll('.payment-note-text').forEach(el => el.remove());
        }
        return clone;
    } catch (err) {
        console.error('Error loading treatment print view:', err);
        return null;
    }
}

async function waitForPrintAssets(rootEl, timeoutMs = 1500) {
    if (!rootEl) return;
    const images = Array.from(rootEl.querySelectorAll('img'));
    if (!images.length) return;

    function applyFallback(img) {
        const wrap = img.closest('.clinic-logo-wrapper');
        if (wrap) {
            wrap.style.display = 'none';
        }
        const brand = img.closest('.clinic-brand');
        if (!brand) return;
        const fallback = brand.querySelector('.clinic-name-fallback');
        if (fallback) {
            fallback.style.display = 'block';
        }
    }

    const waits = images.map((img) => new Promise((resolve) => {
        if (img.complete) {
            if (!img.naturalWidth) {
                applyFallback(img);
            }
            resolve();
            return;
        }
        img.addEventListener('load', () => resolve(), { once: true });
        img.addEventListener('error', () => {
            applyFallback(img);
            resolve();
        }, { once: true });
    }));

    await Promise.race([
        Promise.all(waits),
        new Promise((resolve) => setTimeout(resolve, timeoutMs))
    ]);
}

function getPrintHost() {
    let host = document.getElementById('printReceiptHost');
    if (!host) {
        host = document.createElement('div');
        host.id = 'printReceiptHost';
        host.setAttribute('aria-hidden', 'true');
        const wrap = document.querySelector('.wrap');
        if (wrap) {
            wrap.appendChild(host);
        } else {
            document.body.appendChild(host);
        }
    }
    return host;
}

window.addEventListener('afterprint', function() {
    const host = document.getElementById('printReceiptHost');
    if (host) {
        host.innerHTML = '';
    }
});

function gatherPrintOptions() {
    const lang = document.querySelector('input[name="receipt-lang"]:checked')?.value || 'current';
    const includeTreatmentNotes = document.getElementById('include-notes')?.checked ?? false;
    const includePaymentNotes = document.getElementById('include-payment-notes')?.checked ?? false;
    return {
        lang,
        include_qr: document.getElementById('include-qr')?.checked ?? true,
        include_notes: includePaymentNotes,
        include_payment_notes: includePaymentNotes,
        include_treatment_notes: includeTreatmentNotes,
        include_treatment: includeTreatmentNotes,
        watermark: document.getElementById('watermark')?.checked ?? false
    };
}

function buildParams(options) {
    const params = new URLSearchParams();
    if (options.lang && options.lang !== 'current') {
        params.set('lang', options.lang);
    }
    params.set('include_qr', (!!options.include_qr).toString());
    params.set('include_notes', (!!options.include_notes).toString());
    params.set('include_payment_notes', (!!options.include_payment_notes).toString());
    params.set('include_treatment_notes', (!!options.include_treatment_notes).toString());
    params.set('include_treatment', (!!options.include_treatment).toString());
    params.set('watermark', (!!options.watermark).toString());
    return params.toString();
}

async function printReceipt(paymentId, patientId, format = 'full', options = {}) {
    try {
        // Show loading indicator
        showPrintLoading();

        const query = buildParams(options);
        const url = `/patients/${patientId}/payments/${paymentId}/print/${format}` + (query ? `?${query}` : '');
        
        // Generate PDF via API with print options
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'Accept': 'application/pdf'
            }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const pdfBlob = await response.blob();
        
        // Create download link
        const downloadUrl = window.URL.createObjectURL(pdfBlob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = downloadUrl;
        a.download = `receipt_${paymentId}_${format}.pdf`;
        
        // Trigger download
        document.body.appendChild(a);
        a.click();
        
        // Clean up
        window.URL.revokeObjectURL(downloadUrl);
        document.body.removeChild(a);
        
        hidePrintLoading();
        showSuccessMessage('Receipt downloaded successfully with selected options');
        
    } catch (error) {
        console.error('Error printing receipt:', error);
        hidePrintLoading();
        showErrorMessage('Failed to generate receipt. Please try again.');
    }
}

function showPrintLoading() {
    // Create or update loading indicator
    let loading = document.querySelector('.print-loading');
    if (!loading) {
        loading = document.createElement('div');
        loading.className = 'print-loading';
        loading.innerHTML = `
            <div class="loading-overlay">
                <div class="loading-content">
                    <i class="fa fa-spinner fa-spin fa-2x"></i>
                    <p>Generating receipt...</p>
                </div>
            </div>
        `;
        document.body.appendChild(loading);
    }
    loading.style.display = 'block';
}

function hidePrintLoading() {
    const loading = document.querySelector('.print-loading');
    if (loading) {
        loading.style.display = 'none';
    }
}

function showSuccessMessage(message) {
    showMessage(message, 'success');
}

function showErrorMessage(message) {
    showMessage(message, 'error');
}

function showMessage(message, type) {
    // Create message element
    const messageEl = document.createElement('div');
    messageEl.className = `print-message print-message-${type}`;
    messageEl.innerHTML = `
        <div class="message-content">
            <i class="fa fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
            <span>${message}</span>
            <button class="message-close" onclick="this.parentNode.parentNode.remove()">
                <i class="fa fa-times"></i>
            </button>
        </div>
    `;
    
    // Add to page
    document.body.appendChild(messageEl);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (messageEl.parentNode) {
            messageEl.remove();
        }
    }, 5000);
}

// Print preview functionality
function printPreview(paymentId, patientId, options = {}, format = 'full') {
    const query = buildParams(options);
    const previewUrl = `/patients/${patientId}/payments/${paymentId}/print/${format}/preview` + (query ? `?${query}` : '');
    window.open(previewUrl, '_blank', 'width=900,height=700');
}

// Batch print functionality
function batchPrintPayments(paymentIds, format = 'full') {
    if (!paymentIds || paymentIds.length === 0) {
        showErrorMessage('No payments selected for printing');
        return;
    }
    
    let printedCount = 0;
    let errorCount = 0;
    
    paymentIds.forEach((paymentId, index) => {
        setTimeout(async () => {
            try {
                await printReceipt(paymentId, '', format); // Patient ID not needed for batch
                printedCount++;
                
                // Show progress
                showMessage(`Printed ${printedCount}/${paymentIds.length} receipts`, 'info');
                
            } catch (error) {
                errorCount++;
                console.error(`Error printing payment ${paymentId}:`, error);
            }
            
            // Complete batch
            if (index === paymentIds.length - 1) {
                setTimeout(() => {
                    if (errorCount === 0) {
                        showSuccessMessage(`Successfully printed all ${printedCount} receipts`);
                    } else {
                        showErrorMessage(`Printed ${printedCount} receipts, ${errorCount} failed`);
                    }
                }, 1000);
            }
        }, index * 500); // Stagger by 500ms to avoid overwhelming the server
    });
}

// Print settings and preferences
function savePrintPreferences(format, options = {}) {
    const preferences = {
        format: format,
        options: options,
        timestamp: new Date().toISOString()
    };
    
    localStorage.setItem('printPreferences', JSON.stringify(preferences));
}

function getPrintPreferences() {
    try {
        const saved = localStorage.getItem('printPreferences');
        return saved ? JSON.parse(saved) : null;
    } catch (error) {
        console.error('Error reading print preferences:', error);
        return null;
    }
}

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl+P for print (override default)
    if (e.ctrlKey && e.key === 'p') {
        e.preventDefault();
        
        // Find first visible print button
        const printBtn = document.querySelector('.print-receipt-btn');
        if (printBtn) {
            const paymentId = printBtn.dataset.paymentId;
            const patientId = printBtn.dataset.patientId;
            showPrintModal(paymentId, patientId);
        }
    }
    
    // Escape to close modal
    if (e.key === 'Escape') {
        hidePrintModal();
    }
});

// Mobile-friendly print
function initializeMobilePrint() {
    // Detect mobile devices
    if (/Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)) {
        // Add mobile-specific print handlers
        document.addEventListener('touchstart', function(e) {
            if (e.target.matches('.print-receipt-btn')) {
                e.preventDefault();
                // Show format selection for mobile
                const paymentId = e.target.dataset.paymentId;
                const patientId = e.target.dataset.patientId;
                showMobilePrintOptions(paymentId, patientId);
            }
        });
    }
}

function showMobilePrintOptions(paymentId, patientId) {
    // Create mobile-friendly format selection
    const modal = document.createElement('div');
    modal.className = 'mobile-print-modal';
    modal.innerHTML = `
        <div class="modal-content">
            <h4>Select Receipt Format</h4>
            <div class="format-buttons">
                <button class="btn format-option" data-format="full">Full Receipt</button>
                <button class="btn format-option" data-format="summary">Summary</button>
                <button class="btn format-option" data-format="treatment">Treatment</button>
                <button class="btn format-option" data-format="payment">Payment Only</button>
            </div>
            <button class="btn secondary cancel-btn">Cancel</button>
        </div>
    `;
    
    // Add event listeners
    modal.addEventListener('click', function(e) {
        if (e.target.matches('.format-option')) {
            const format = e.target.dataset.format;
            printReceipt(paymentId, patientId, format);
            document.body.removeChild(modal);
        }
        if (e.target.matches('.cancel-btn') || e.target === modal) {
            document.body.removeChild(modal);
        }
    });
    
    document.body.appendChild(modal);
}

// Initialize mobile print on load
document.addEventListener('DOMContentLoaded', initializeMobilePrint);

// Close modal on outside click
document.addEventListener('click', function(event) {
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => {
        if (event.target === modal) {
            closeModal();
        }
    });
});

// Close modal on Escape key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeModal();
    }
});
