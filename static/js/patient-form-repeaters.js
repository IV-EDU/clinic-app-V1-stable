// Patient forms (New/Edit): add/remove extra phone/page rows.
// Must work inside modals (HTML injected via innerHTML), so use event delegation.

(function () {
  'use strict';

  function closest(el, selector) {
    if (!el) return null;
    if (el.closest) return el.closest(selector);
    // Very old fallback (shouldn't be needed in modern browsers)
    while (el) {
      if (el.matches && el.matches(selector)) return el;
      el = el.parentElement;
    }
    return null;
  }

  function getTemplateContent(templateId) {
    if (!templateId) return null;
    var tpl = document.getElementById(templateId);
    if (!tpl || tpl.tagName !== 'TEMPLATE') return null;
    return tpl.content ? tpl.content.cloneNode(true) : null;
  }

  function appendFromTemplate(containerId, templateId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var fragment = getTemplateContent(templateId);
    if (!fragment) return;
    container.appendChild(fragment);
  }

  function syncColorPicker(colorInput) {
    // Any color picker should update a nearby hidden input marked with data-color-hidden.
    // (We intentionally do not show color codes in the UI.)
    var row = closest(colorInput, '[data-repeater-row]') || closest(colorInput, '.page-number-input-wrap') || null;
    var scope = row || colorInput.parentElement || document;
    var hidden = scope.querySelector ? scope.querySelector('input[data-color-hidden]') : null;
    if (!hidden) return;
    hidden.value = (colorInput.value || '').toLowerCase();
  }

  document.addEventListener('click', function (e) {
    var addBtn = closest(e.target, '[data-repeater-add]');
    if (addBtn) {
      e.preventDefault();
      var containerId = addBtn.getAttribute('data-container-id') || '';
      var templateId = addBtn.getAttribute('data-template-id') || '';
      appendFromTemplate(containerId, templateId);
      return;
    }

    var removeBtn = closest(e.target, '[data-repeater-remove]');
    if (removeBtn) {
      e.preventDefault();
      var row = closest(removeBtn, '[data-repeater-row]') || closest(removeBtn, '.extra-phone-row') || closest(removeBtn, '.extra-page-row');
      if (row && row.parentNode) row.parentNode.removeChild(row);
      return;
    }
  });

  document.addEventListener('input', function (e) {
    var t = e.target;
    if (!t) return;
    if (t.matches && t.matches('input[type="color"][data-color-picker]')) {
      syncColorPicker(t);
    }
  });

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (!t) return;
    if (t.matches && t.matches('input[type="color"][data-color-picker]')) {
      syncColorPicker(t);
    }
  });
})();
