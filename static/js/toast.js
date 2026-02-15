/**
 * Toast Notification System
 * Usage:
 *   Toast.success('Patient saved!')
 *   Toast.error('Something went wrong')
 *   Toast.warning('Please check the form')
 *   Toast.info('New feature available')
 */

class ToastSystem {
  constructor() {
    this.container = null;
    this.toasts = new Map();
    this.init();
  }

  init() {
    // Create toast container if it doesn't exist
    if (!document.querySelector('.toast-container')) {
      this.container = document.createElement('div');
      this.container.className = 'toast-container';
      document.body.appendChild(this.container);
    } else {
      this.container = document.querySelector('.toast-container');
    }
  }

  show(message, type = 'info', duration = 5000) {
    const id = Date.now() + Math.random();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('data-toast-id', id);

    const icon = this.getIcon(type);

    toast.innerHTML = `
      <div class="toast-icon">${icon}</div>
      <div class="toast-message">${this.escapeHtml(message)}</div>
      <button class="toast-close" aria-label="Close">×</button>
    `;

    // Add to container
    this.container.appendChild(toast);
    this.toasts.set(id, toast);

    // Trigger animation
    setTimeout(() => toast.classList.add('toast-show'), 10);

    // Auto-dismiss
    if (duration > 0) {
      setTimeout(() => this.dismiss(id), duration);
    }

    // Click to dismiss
    toast.querySelector('.toast-close').addEventListener('click', () => {
      this.dismiss(id);
    });

    return id;
  }

  dismiss(id) {
    const toast = this.toasts.get(id);
    if (!toast) return;

    toast.classList.remove('toast-show');
    toast.classList.add('toast-hide');

    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
      this.toasts.delete(id);
    }, 300);
  }

  success(message, duration = 5000) {
    return this.show(message, 'success', duration);
  }

  error(message, duration = 7000) {
    return this.show(message, 'error', duration);
  }

  warning(message, duration = 6000) {
    return this.show(message, 'warning', duration);
  }

  info(message, duration = 5000) {
    return this.show(message, 'info', duration);
  }

  getIcon(type) {
    const icons = {
      success: '✓',
      error: '✕',
      warning: '⚠',
      info: 'ⓘ'
    };
    return icons[type] || icons.info;
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  clearAll() {
    Array.from(this.toasts.keys()).forEach(id => this.dismiss(id));
  }
}

// Global instance
const Toast = new ToastSystem();

// Expose globally
window.Toast = Toast;
