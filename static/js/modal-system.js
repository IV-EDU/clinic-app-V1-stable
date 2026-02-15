/**
 * Modal System — Reusable modal component
 * Usage:
 *   Modal.open('modal-id')
 *   Modal.close('modal-id')
 *   Modal.closeAll()
 */

class ModalSystem {
  constructor() {
    this.activeModals = new Set();
    this.init();
  }

  init() {
    // Close modal on backdrop click
    document.addEventListener('click', (e) => {
      if (e.target.classList.contains('modal-backdrop')) {
        const modalId = e.target.getAttribute('data-modal-id');
        if (modalId) this.close(modalId);
      }
    });

    // Close modal on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.activeModals.size > 0) {
        const lastModal = Array.from(this.activeModals).pop();
        this.close(lastModal);
      }
    });

    // Close button handler
    document.addEventListener('click', (e) => {
      if (e.target.classList.contains('modal-close') || e.target.closest('.modal-close')) {
        const modal = e.target.closest('.modal');
        if (modal) {
          const modalId = modal.id;
          this.close(modalId);
        }
      }
    });
  }

  open(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) {
      console.error(`Modal not found: ${modalId}`);
      return;
    }

    // Show modal
    modal.classList.add('is-active');
    this.activeModals.add(modalId);

    // Prevent body scroll
    if (this.activeModals.size === 1) {
      document.body.style.overflow = 'hidden';
    }

    // Auto-focus first input
    setTimeout(() => {
      const firstInput = modal.querySelector('input, textarea, select, button');
      if (firstInput) firstInput.focus();
    }, 100);

    // Dispatch event
    modal.dispatchEvent(new CustomEvent('modal:opened', { detail: { modalId } }));
  }

  close(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;

    // Hide modal
    modal.classList.remove('is-active');
    this.activeModals.delete(modalId);

    // Restore body scroll if no modals are open
    if (this.activeModals.size === 0) {
      document.body.style.overflow = '';
    }

    // Dispatch event
    modal.dispatchEvent(new CustomEvent('modal:closed', { detail: { modalId } }));
  }

  closeAll() {
    Array.from(this.activeModals).forEach(id => this.close(id));
  }
}

// Global instance
const Modal = new ModalSystem();

// Expose globally
window.Modal = Modal;
