/**
 * Modal System – Clinic-App-Local
 * Pure Vanilla JS Modal Manager
 */

(function() {
  const ModalSystem = {
    openModals: [],

    init: function() {
      // Close on escape
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.openModals.length > 0) {
          const topModalId = this.openModals[this.openModals.length - 1];
          this.close(topModalId);
        }
      });

      // Close on backdrop click and setup close buttons
      document.addEventListener('click', (e) => {
        // Backdrop click
        if (e.target.classList.contains('modal-container')) {
          this.close(e.target.id);
        }

        // Close button click
        const closeBtn = e.target.closest('[data-modal-close]');
        if (closeBtn) {
          const container = closeBtn.closest('.modal-container');
          if (container) {
            this.close(container.id);
          }
        }
      });
    },

    open: function(modalId) {
      const modal = document.getElementById(modalId);
      if (!modal) {
        console.warn(`Modal System: Cannot find modal with id "${modalId}"`);
        return;
      }

      modal.classList.add('active');
      this.openModals.push(modalId);
      document.body.style.overflow = 'hidden'; // Prevent background scrolling
    },

    close: function(modalId) {
      const modal = document.getElementById(modalId);
      if (!modal) return;

      modal.classList.remove('active');
      this.openModals = this.openModals.filter(id => id !== modalId);

      if (this.openModals.length === 0) {
        document.body.style.overflow = '';
      }
    }
  };

  // Expose globally
  window.openModal = ModalSystem.open.bind(ModalSystem);
  window.closeModal = ModalSystem.close.bind(ModalSystem);

  // Initialize on load
  document.addEventListener('DOMContentLoaded', ModalSystem.init.bind(ModalSystem));
})();
