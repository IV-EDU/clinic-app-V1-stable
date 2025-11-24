// Simple, in-page helpers for the one-page expenses flow

document.addEventListener("DOMContentLoaded", () => {
  const monthInput = document.getElementById("month");
  if (monthInput && monthInput.form) {
    monthInput.addEventListener("change", () => monthInput.form.submit());
  }

  const amountInput = document.querySelector('input[name="amount"]');
  if (amountInput) {
    amountInput.addEventListener("blur", () => {
      const value = parseFloat(amountInput.value);
      if (!isNaN(value)) {
        amountInput.value = value.toFixed(2);
      }
    });
  }

  const form = document.querySelector(".expense-form");
  if (form) {
    form.addEventListener("submit", () => {
      form.classList.add("submitting");
    });
  }

  setupModal();
});

function setupModal() {
  const modal = document.getElementById("expenseModal");
  if (!modal) return;

  const backdrop = modal.querySelector(".modal-backdrop");
  const closeButtons = modal.querySelectorAll("#closeModal, #closeModalBottom, .modal-backdrop");
  const amountEl = modal.querySelector("#modalAmount");
  const dateEl = modal.querySelector("#modalDate");
  const descEl = modal.querySelector("#modalDesc");

  document.querySelectorAll(".view-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const date = btn.getAttribute("data-date") || "";
      const amount = btn.getAttribute("data-amount") || "";
      const desc = btn.getAttribute("data-desc") || "";

      amountEl.textContent = amount;
      dateEl.textContent = date;

      // Render bullet list
      descEl.innerHTML = "";
      const lines = desc.split("\n").map((l) => l.trim()).filter((l) => l.length);
      if (lines.length === 0) {
        const li = document.createElement("li");
        li.textContent = "No description provided.";
        descEl.appendChild(li);
      } else {
        lines.forEach((line) => {
          const li = document.createElement("li");
          li.textContent = line;
          descEl.appendChild(li);
        });
      }

      modal.classList.add("open");
    });
  });

  closeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      modal.classList.remove("open");
    });
  });
}
