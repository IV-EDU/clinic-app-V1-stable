// Expense Management JavaScript

document.addEventListener('DOMContentLoaded', function() {
    initializeExpenseForm();
    initializeExpenseCalculations();
    initializeMaterialAutocomplete();
});

function initializeExpenseForm() {
    const addItemBtn = document.getElementById('addItemBtn');
    const itemsContainer = document.getElementById('itemsContainer');
    
    if (addItemBtn && itemsContainer) {
        addItemBtn.addEventListener('click', function() {
            addNewExpenseItem();
        });
    }
}

function initializeExpenseCalculations() {
    // Listen for changes in quantity and unit price inputs
    document.addEventListener('input', function(e) {
        if (e.target.classList.contains('quantity-input') || e.target.classList.contains('unit-price')) {
            updateItemTotal(e.target.closest('.expense-item'));
            updateFormTotals();
        }
    });
}

function initializeMaterialAutocomplete() {
    const materialInputs = document.querySelectorAll('.material-name');
    
    materialInputs.forEach(input => {
        let timeoutId;
        
        input.addEventListener('input', function() {
            clearTimeout(timeoutId);
            const query = this.value;
            
            if (query.length >= 2) {
                timeoutId = setTimeout(() => {
                    fetchMaterialsAutocomplete(query, this);
                }, 300);
            }
        });
    });
}

function addNewExpenseItem() {
    const itemsContainer = document.getElementById('itemsContainer');
    const template = document.getElementById('itemTemplate');
    
    if (!itemsContainer || !template) return;
    
    const currentItems = itemsContainer.querySelectorAll('.expense-item');
    const newIndex = currentItems.length;
    
    // Clone template
    const newItem = template.content.cloneNode(true);
    
    // Update item index and names
    updateItemNames(newItem, newIndex);
    
    // Update item title
    const title = newItem.querySelector('.item-title');
    if (title) {
        title.textContent = `Item ${newIndex + 1}`;
    }
    
    // Add event listeners
    const removeBtn = newItem.querySelector('.remove-item-btn');
    if (removeBtn) {
        removeBtn.addEventListener('click', function() {
            removeExpenseItem(this);
        });
    }
    
    // Add to container
    itemsContainer.appendChild(newItem);
    
    // Focus on first input
    const firstInput = newItem.querySelector('input[name$="-material_name"]');
    if (firstInput) {
        firstInput.focus();
    }
    
    updateItemTitles();
}

function updateItemNames(itemElement, index) {
    // Update all name attributes and IDs
    const inputs = itemElement.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
        const oldName = input.getAttribute('name');
        if (oldName) {
            const newName = oldName.replace(/items-\d+-/, `items-${index}-`);
            input.setAttribute('name', newName);
        }
        
        const oldId = input.getAttribute('id');
        if (oldId) {
            const newId = oldId.replace(/items-\d+-/, `items-${index}-`);
            input.setAttribute('id', newId);
        }
    });
    
    itemElement.setAttribute('data-item-index', index);
}

function removeExpenseItem(button) {
    const item = button.closest('.expense-item');
    const itemsContainer = document.getElementById('itemsContainer');
    
    if (itemsContainer && item) {
        item.remove();
        updateItemTitles();
        updateFormTotals();
    }
}

function updateItemTitles() {
    const items = document.querySelectorAll('.expense-item');
    items.forEach((item, index) => {
        const title = item.querySelector('.item-title');
        if (title) {
            title.textContent = `Item ${index + 1}`;
        }
    });
}

function updateItemTotal(itemElement) {
    const quantityInput = itemElement.querySelector('.quantity-input');
    const unitPriceInput = itemElement.querySelector('.unit-price');
    const totalDisplay = itemElement.querySelector('.total-price-display');
    
    if (!quantityInput || !unitPriceInput || !totalDisplay) return;
    
    const quantity = parseFloat(quantityInput.value) || 0;
    const unitPrice = parseFloat(unitPriceInput.value) || 0;
    const total = quantity * unitPrice;
    
    totalDisplay.textContent = `${total.toFixed(2)} EGP`;
}

function updateFormTotals() {
    const items = document.querySelectorAll('.expense-item');
    let subtotal = 0;
    
    items.forEach(item => {
        const quantityInput = item.querySelector('.quantity-input');
        const unitPriceInput = item.querySelector('.unit-price');
        
        if (quantityInput && unitPriceInput) {
            const quantity = parseFloat(quantityInput.value) || 0;
            const unitPrice = parseFloat(unitPriceInput.value) || 0;
            subtotal += quantity * unitPrice;
        }
    });
    
    const taxRateInput = document.querySelector('input[name="tax_rate"]');
    const taxRate = parseFloat(taxRateInput?.value) || 14;
    
    const taxAmount = subtotal * (taxRate / 100);
    const totalAmount = subtotal + taxAmount;
    
    // Update display elements
    const subtotalDisplay = document.getElementById('subtotalDisplay');
    const taxAmountDisplay = document.getElementById('taxAmountDisplay');
    const totalAmountDisplay = document.getElementById('totalAmountDisplay');
    
    if (subtotalDisplay) subtotalDisplay.textContent = `${subtotal.toFixed(2)} EGP`;
    if (taxAmountDisplay) taxAmountDisplay.textContent = `${taxAmount.toFixed(2)} EGP`;
    if (totalAmountDisplay) totalAmountDisplay.textContent = `${totalAmount.toFixed(2)} EGP`;
}

async function fetchMaterialsAutocomplete(query, inputElement) {
    try {
        const response = await fetch(`/api/expenses/autocomplete/materials?q=${encodeURIComponent(query)}`);
        const materials = await response.json();
        
        showMaterialDropdown(inputElement, materials);
    } catch (error) {
        console.error('Error fetching materials:', error);
    }
}

function showMaterialDropdown(input, materials) {
    // Remove existing dropdown
    const existingDropdown = input.parentNode.querySelector('.material-dropdown');
    if (existingDropdown) {
        existingDropdown.remove();
    }
    
    if (materials.length === 0) return;
    
    const dropdown = document.createElement('div');
    dropdown.className = 'material-dropdown';
    
    materials.forEach(material => {
        const item = document.createElement('div');
        item.className = 'dropdown-item';
        item.textContent = `${material.name} (${material.unit})`;
        item.addEventListener('click', () => {
            input.value = material.name;
            
            // Auto-fill unit price if available
            const unitPriceInput = input.closest('.expense-item').querySelector('.unit-price');
            if (unitPriceInput && material.price_per_unit) {
                unitPriceInput.value = material.price_per_unit;
                updateItemTotal(input.closest('.expense-item'));
                updateFormTotals();
            }
            
            dropdown.remove();
        });
        dropdown.appendChild(item);
    });
    
    input.parentNode.appendChild(dropdown);
}

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    if (!e.target.closest('.material-dropdown') && !e.target.closest('.material-name')) {
        const dropdowns = document.querySelectorAll('.material-dropdown');
        dropdowns.forEach(dropdown => dropdown.remove());
    }
});

// Form validation
function validateExpenseForm() {
    const form = document.getElementById('expenseForm');
    if (!form) return true;
    
    let isValid = true;
    
    // Check if at least one item has material name
    const items = document.querySelectorAll('.expense-item');
    let hasItems = false;
    
    items.forEach(item => {
        const materialName = item.querySelector('.material-name')?.value.trim();
        if (materialName) {
            hasItems = true;
        }
    });
    
    if (!hasItems) {
        showError('At least one expense item is required');
        isValid = false;
    }
    
    return isValid;
}

function showError(message) {
    // Create or update error message
    let errorDiv = document.querySelector('.form-error');
    if (!errorDiv) {
        errorDiv = document.createElement('div');
        errorDiv.className = 'form-error alert alert-danger';
        errorDiv.style.marginBottom = '15px';
        
        const form = document.getElementById('expenseForm');
        form.insertBefore(errorDiv, form.firstChild);
    }
    
    errorDiv.textContent = message;
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (errorDiv && errorDiv.parentNode) {
            errorDiv.remove();
        }
    }, 5000);
}

// Search and filter functionality
function initializeExpenseSearch() {
    const searchForm = document.querySelector('.expense-search-form');
    
    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            // Add loading state
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Searching...';
                submitBtn.disabled = true;
            }
        });
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeExpenseSearch();
    
    // Update totals when tax rate changes
    const taxRateInput = document.querySelector('input[name="tax_rate"]');
    if (taxRateInput) {
        taxRateInput.addEventListener('input', updateFormTotals);
    }
});