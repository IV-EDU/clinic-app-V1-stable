/**
 * Toast Notification System – Clinic-App-Local
 * Pure Vanilla JS Toast Manager
 */

(function() {
  const ToastSystem = {
    containerId: 'toast-container',
    defaultDuration: 5000,

    show: function(message, type = 'success') {
      const container = document.getElementById(this.containerId);
      if (!container) {
        console.warn('Toast System: Container #toast-container not found.');
        return;
      }

      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.setAttribute('role', 'alert');

      const content = document.createElement('div');
      content.className = 'toast-content';

      const msgText = document.createElement('p');
      msgText.className = 'toast-message';
      msgText.textContent = message;
      content.appendChild(msgText);

      const closeBtn = document.createElement('button');
      closeBtn.className = 'toast-close-btn';
      closeBtn.innerHTML = '&times;';
      closeBtn.setAttribute('aria-label', 'Close');

      toast.appendChild(content);
      toast.appendChild(closeBtn);

      container.appendChild(toast);

      // Trigger animation reliably
      setTimeout(() => {
        toast.classList.add('toast-entering');
      }, 10);

      // Setup removal
      const removeToast = () => {
        toast.classList.remove('toast-entering');
        toast.classList.add('toast-exiting');
        toast.addEventListener('transitionend', () => {
          if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
          }
        });
      };

      closeBtn.addEventListener('click', removeToast);

      setTimeout(removeToast, this.defaultDuration);
    }
  };

  // Expose globally
  window.showToast = ToastSystem.show.bind(ToastSystem);
})();
