// Expense Management JavaScript

document.addEventListener('DOMContentLoaded', function() {
    const L = window.EXPENSES_I18N || {};
    initializeExpenseSearch(L);
    wireTotals(L);
});

function wireTotals(L) {
    const totalInput = document.querySelector('input[name="total_amount"]');
    if (totalInput) {
        totalInput.addEventListener('input', () => {
            const totalVal = parseFloat(totalInput.value) || 0;
            const display = document.getElementById('totalAmountDisplay');
            if (display) {
                display.textContent = `${totalVal.toFixed(2)} EGP`;
            }
        });
        const display = document.getElementById('totalAmountDisplay');
        if (display) {
            const totalVal = parseFloat(totalInput.value) || 0;
            display.textContent = `${totalVal.toFixed(2)} EGP`;
        }
    }
}

// Form validation
function validateExpenseForm() {
    const form = document.getElementById('expenseForm');
    if (!form) return true;
    const L = window.EXPENSES_I18N || {};
    
    let isValid = true;

    const totalAmountInput = document.querySelector('input[name="total_amount"]');
    const totalVal = parseFloat(totalAmountInput?.value) || 0;
    if (!totalVal || totalVal <= 0) {
        showError(L.enter_total || 'Please enter how much you paid.');
        isValid = false;
    }
    
    return isValid;
}

function showError(message) {
    let errorDiv = document.querySelector('.form-error');
    if (!errorDiv) {
        errorDiv = document.createElement('div');
        errorDiv.className = 'form-error alert alert-danger';
        errorDiv.style.marginBottom = '15px';
        
        const form = document.getElementById('expenseForm');
        form.insertBefore(errorDiv, form.firstChild);
    }
    
    errorDiv.textContent = message;
    
    setTimeout(() => {
        if (errorDiv && errorDiv.parentNode) {
            errorDiv.remove();
        }
    }, 5000);
}

// Search and filter functionality
function initializeExpenseSearch(L) {
    const searchForm = document.querySelector('.expense-search-form');
    
    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> ' + (L.searching || 'Searching...');
                submitBtn.disabled = true;
            }
        });
    }
}
