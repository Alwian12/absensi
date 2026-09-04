(function () {
  const roleData = {
    admin: {
      title: "Dashboard Admin",
      desc: "Monitoring statistik global, manajemen master data, audit verifikasi wajah, dan ekspor laporan.",
      bullets: [
        "Kelola peserta, pembimbing, dan instansi",
        "Pantau log verifikasi wajah dan status keamanan",
        "Ekspor laporan absensi (PDF/Excel)",
      ],
    },
    pembimbing: {
      title: "Dashboard Pembimbing",
      desc: "Fokus pada pembinaan peserta, verifikasi jurnal, evaluasi progres, dan pemantauan disiplin absensi.",
      bullets: [
        "Review jurnal harian peserta",
        "Input penilaian dan catatan pembimbing",
        "Pantau absensi untuk tindak lanjut", 
      ],
    },
    peserta: {
      title: "Dashboard Peserta",
      desc: "Akses personal untuk absensi wajah, jurnal harian, dan pemantauan nilai hasil pembimbing.",
      bullets: [
        "Registrasi wajah lalu check-in/check-out",
        "Isi jurnal harian kegiatan PKL",
        "Lihat nilai dan status evaluasi", 
      ],
    },
  };

  const roleTabs = document.querySelectorAll(".role-tab");
  const roleTitle = document.getElementById("roleTitle");
  const roleDesc = document.getElementById("roleDesc");
  const roleBullets = document.getElementById("roleBullets");

  function renderRole(role) {
    const payload = roleData[role];
    if (!payload || !roleTitle || !roleDesc || !roleBullets) {
      return;
    }

    roleTitle.textContent = payload.title;
    roleDesc.textContent = payload.desc;
    roleBullets.innerHTML = "";
    payload.bullets.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      roleBullets.appendChild(li);
    });

    roleTabs.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.role === role);
    });
  }

  roleTabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      renderRole(btn.dataset.role || "admin");
    });
  });

  const statValues = document.querySelectorAll(".stat-value[data-target]");
  function animateStat(el) {
    const target = Number(el.getAttribute("data-target"));
    if (!Number.isFinite(target)) {
      return;
    }
    const duration = 700;
    const start = performance.now();
    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      const current = Math.floor(progress * target);
      el.textContent = String(current);
      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    }
    requestAnimationFrame(tick);
  }

  statValues.forEach((el) => animateStat(el));

  const reveals = document.querySelectorAll(".reveal-item");
  if (reveals.length > 0 && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.2 }
    );
    reveals.forEach((item) => observer.observe(item));
  } else {
    reveals.forEach((item) => item.classList.add("is-visible"));
  }
})();
