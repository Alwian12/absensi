(function () {
  function ensureToastContainer() {
    let container = document.getElementById("appToastStack");
    if (container) {
      return container;
    }

    container = document.createElement("div");
    container.id = "appToastStack";
    container.className = "toast-container position-fixed top-0 end-0 p-3 app-toast-stack";
    document.body.appendChild(container);
    return container;
  }

  function showToast(options) {
    const message = options && options.message ? options.message : "Aksi diproses";
    const title = options && options.title ? options.title : "Notifikasi";
    const variant = options && options.variant ? options.variant : "primary";
    const delay = options && options.delay ? options.delay : 3600;

    if (!window.bootstrap || !window.bootstrap.Toast) {
      return;
    }

    const container = ensureToastContainer();
    const wrapper = document.createElement("div");
    wrapper.className = "toast align-items-center border-0 text-bg-" + variant;
    wrapper.setAttribute("role", "alert");
    wrapper.setAttribute("aria-live", "assertive");
    wrapper.setAttribute("aria-atomic", "true");
    wrapper.innerHTML =
      '<div class="d-flex">' +
      '<div class="toast-body">' +
      '<strong class="d-block mb-1">' + title + '</strong>' +
      '<span>' + message + '</span>' +
      '</div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
      '</div>';

    container.appendChild(wrapper);
    const toast = new window.bootstrap.Toast(wrapper, { delay: delay });
    wrapper.addEventListener("hidden.bs.toast", () => {
      wrapper.remove();
    });
    toast.show();
  }

  function setLoadingState(form) {
    const submitButton = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!submitButton || submitButton.disabled) {
      return;
    }

    submitButton.disabled = true;
    submitButton.classList.add("is-loading");
    submitButton.setAttribute("aria-busy", "true");

    if (submitButton.tagName.toLowerCase() === "input") {
      submitButton.value = "Memproses...";
      return;
    }

    submitButton.innerHTML =
      '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>' +
      '<span class="btn-loading-label">Memproses...</span>';
  }

  const toggleButtons = document.querySelectorAll(".toggle-password");
  toggleButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-target");
      const field = targetId ? document.getElementById(targetId) : null;
      if (!field) {
        return;
      }
      const show = field.type === "password";
      field.type = show ? "text" : "password";
      button.textContent = show ? "Sembunyi" : "Lihat";
    });
  });

  const forms = document.querySelectorAll("form:not([data-no-loading])");
  forms.forEach((form) => {
    form.addEventListener("submit", () => {
      setLoadingState(form);
      showToast({
        title: "Mengirim",
        message: "Permintaan login/registrasi sedang diproses.",
        variant: "primary",
        delay: 2200,
      });
    });
  });

  const errorAlert = document.querySelector(".alert.alert-danger");
  if (errorAlert && errorAlert.textContent.trim()) {
    showToast({
      title: "Gagal",
      message: errorAlert.textContent.trim(),
      variant: "danger",
      delay: 4500,
    });
  }
})();
