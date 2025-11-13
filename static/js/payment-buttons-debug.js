// Payment Button Functionality Debug Script
// Enhanced button functionality with proper error handling and validation

document.addEventListener('DOMContentLoaded', function() {
    console.log('Payment button debug script loaded');
    initializePaymentButtons();
});

function initializePaymentButtons() {
    // Test print receipt buttons
    const printButtons = document.querySelectorAll('.print-receipt-btn');
    console.log(`Found ${printButtons.length} print receipt buttons`);
    
    printButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Print button clicked:', {
                paymentId: this.dataset.paymentId,
                patientId: this.dataset.patientId
            });
            
            // Validate data attributes
            if (!this.dataset.paymentId || !this.dataset.patientId) {
                console.error('Missing payment or patient ID');
                showError('Invalid button data');
                return;
            }
            
            // Show print modal
            showPrintModal(this.dataset.paymentId, this.dataset.patientId, 'full');
        });
    });
    
    // Test format buttons
    const formatButtons = document.querySelectorAll('.format-btn');
    console.log(`Found ${formatButtons.length} format buttons`);
    
    formatButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Format button clicked:', {
                paymentId: this.dataset.paymentId,
                patientId: this.dataset.patientId,
                format: this.dataset.format
            });
            
            // Validate and call print function
            if (!this.dataset.paymentId || !this.dataset.patientId || !this.dataset.format) {
                console.error('Missing format button data');
                showError('Invalid format button data');
                return;
            }
            
            printReceipt(this.dataset.paymentId, this.dataset.patientId, this.dataset.format);
        });
    });
    
    // Test view toggle buttons
    const viewButtons = document.querySelectorAll('.view-toggle-btn');
    console.log(`Found ${viewButtons.length} view toggle buttons`);
    
    viewButtons.forEach(button => {
        const originalClick = button.getAttribute('onclick');
        if (originalClick) {
            console.log('Original onclick found:', originalClick);
        }
    });
}

function showPrintModal(paymentId, patientId, defaultFormat = 'full') {
    console.log('Showing print modal:', { paymentId, patientId, defaultFormat });
    
    const modal = document.getElementById('printReceiptModal');
    if (!modal) {
        console.error('Print receipt modal not found');
        showError('Print modal not found');
        return;
    }
    
    // Store IDs in modal dataset
    modal.dataset.paymentId = paymentId;
    modal.dataset.patientId = patientId;
    
    // Set default format
    const formatRadio = document.querySelector(`input[name="format"][value="${defaultFormat}"]`);
    if (formatRadio) {
        formatRadio.checked = true;
    }
    
    // Show modal
    modal.style.display = 'block';
    modal.classList.add('show');
    document.body.style.overflow = 'hidden';
    
    console.log('Print modal displayed successfully');
}

function printReceipt(paymentId, patientId, format) {
    console.log('Starting print receipt:', { paymentId, patientId, format });
    
    // Show loading state
    showPrintLoading();
    
    // Make API call
    fetch(`/patients/${patientId}/payments/${paymentId}/print/${format}`, {
        method: 'GET',
        headers: {
            'Accept': 'application/pdf'
        }
    })
    .then(response => {
        console.log('Response status:', response.status);
        console.log('Response headers:', response.headers);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return response.blob();
    })
    .then(pdfBlob => {
        console.log('PDF blob received:', pdfBlob.size, 'bytes');
        
        // Create download
        const url = window.URL.createObjectURL(pdfBlob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `receipt_${paymentId}_${format}.pdf`;
        
        document.body.appendChild(a);
        a.click();
        
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        hidePrintLoading();
        showSuccess('Receipt downloaded successfully');
    })
    .catch(error => {
        console.error('Error printing receipt:', error);
        hidePrintLoading();
        showError('Failed to generate receipt: ' + error.message);
    });
}

function showPrintLoading() {
    console.log('Showing print loading');
    let loading = document.querySelector('.print-loading');
    if (!loading) {
        loading = createPrintLoading();
    }
    loading.style.display = 'block';
}

function hidePrintLoading() {
    console.log('Hiding print loading');
    const loading = document.querySelector('.print-loading');
    if (loading) {
        loading.style.display = 'none';
    }
}

function createPrintLoading() {
    const loading = document.createElement('div');
    loading.className = 'print-loading';
    loading.innerHTML = `
        <div class="loading-overlay">
            <div class="loading-content">
                <div class="spinner"></div>
                <h4>Generating receipt...</h4>
                <p>Please wait while we generate your receipt.</p>
            </div>
        </div>
    `;
    document.body.appendChild(loading);
    return loading;
}

function showSuccess(message) {
    console.log('Showing success:', message);
    showMessage(message, 'success');
}

function showError(message) {
    console.error('Showing error:', message);
    showMessage(message, 'error');
}

function showMessage(message, type) {
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
    
    document.body.appendChild(messageEl);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (messageEl.parentNode) {
            messageEl.remove();
        }
    }, 5000);
}

// Test function to validate all buttons work
function testPaymentButtons() {
    console.log('=== Payment Button Test ===');
    
    const results = {
        printButtons: 0,
        formatButtons: 0,
        viewButtons: 0,
        modalExists: false,
        jsLoaded: true
    };
    
    // Count buttons
    results.printButtons = document.querySelectorAll('.print-receipt-btn').length;
    results.formatButtons = document.querySelectorAll('.format-btn').length;
    results.viewButtons = document.querySelectorAll('.view-toggle-btn').length;
    
    // Check modal
    results.modalExists = !!document.getElementById('printReceiptModal');
    
    // Check JS loaded
    results.jsLoaded = typeof initializePaymentButtons === 'function';
    
    console.table(results);
    
    if (results.modalExists && results.jsLoaded) {
        console.log('✅ Payment button system ready');
    } else {
        console.log('❌ Payment button system issues detected');
    }
    
    return results;
}

// Export for debugging
window.testPaymentButtons = testPaymentButtons;
window.showPrintModal = showPrintModal;
window.printReceipt = printReceipt;