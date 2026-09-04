(function () {
  const video = document.getElementById("cameraPreview");
  const canvas = document.getElementById("captureCanvas");
  const resultBox = document.getElementById("faceResult");
  const facePanel = document.querySelector(".attendance-face-panel");
  const livenessHint = document.getElementById("livenessHint");
  const livenessHintText = document.getElementById("livenessHintText");
  const livenessProgressBar = document.getElementById("livenessProgressBar");
  const manualForm = document.getElementById("manualAttendanceForm");
  const stageBadge = document.getElementById("faceStageBadge");
  const commandHeadline = document.getElementById("faceCommandHeadline");
  const commandSubtext = document.getElementById("faceCommandSubtext");
  const cameraShell = document.getElementById("attendanceCameraShell");
  const cameraIdlePrompt = document.getElementById("cameraIdlePrompt");
  const stepNodes = document.querySelectorAll("[data-face-step]");
  const countdownOverlay = document.getElementById("faceCountdownOverlay");
  const countdownValue = document.getElementById("faceCountdownValue");
  const qualityBrightness = document.getElementById("qualityBrightness");
  const qualityFraming = document.getElementById("qualityFraming");
  const qualityStability = document.getElementById("qualityStability");
  const voiceGuideToggle = document.getElementById("voiceGuideToggle");
  const successEnding = document.getElementById("faceSuccessEnding");
  const successDetail = document.getElementById("faceSuccessDetail");
  const successTitleEl = document.getElementById("faceSuccessTitle");
  const successAction = document.getElementById("faceSuccessAction");
  const successTime = document.getElementById("faceSuccessTime");
  const btnFaceFinish = document.getElementById("btnFaceFinish");
  const btnFaceReload = document.getElementById("btnFaceReload");
  const btnFaceShowEnding = document.getElementById("btnFaceShowEnding");
  const successAutoHide = document.getElementById("faceSuccessAutoHide");
  const successRailSteps = document.querySelectorAll("[data-success-rail-step]");
  const successTransition = document.getElementById("faceSuccessTransition");
  const successLoader = document.getElementById("faceSuccessLoader");
  const successCheckmark = document.getElementById("faceSuccessCheckmark");
  const successTransitionTitle = document.getElementById("faceSuccessTransitionTitle");
  const successTransitionSub = document.getElementById("faceSuccessTransitionSub");

  let stream = null;
  let qualityLoopId = null;
  let lastBrightness = null;
  let successAutoHideTimer = null;
  let successAutoHideTick = null;
  let latestSuccessSnapshot = null;

  // Multi-frame motion liveness: short enough for daily use while retaining motion checks.
  const LIVENESS_FRAMES = 5;
  const LIVENESS_INTERVAL_MS = 180;
  const LIVENESS_THRESHOLD = 5.5;

  const TRANSITION_STYLE_SCALE = {
    fast: 0.85,
    normal: 1,
    slow: 1.22,
  };

  const configuredStyle = facePanel && facePanel.dataset.transitionStyle
    ? String(facePanel.dataset.transitionStyle).toLowerCase()
    : "normal";
  const transitionStyle = TRANSITION_STYLE_SCALE[configuredStyle] ? configuredStyle : "normal";
  const transitionScale = TRANSITION_STYLE_SCALE[transitionStyle];

  const configuredAutoHide = facePanel && facePanel.dataset.successAutoHideSeconds
    ? Number(facePanel.dataset.successAutoHideSeconds)
    : 9;
  const SUCCESS_AUTO_HIDE_SECONDS = Number.isFinite(configuredAutoHide)
    ? Math.max(3, Math.min(20, Math.round(configuredAutoHide)))
    : 9;

  const SUCCESS_TRANSITION_CONFIG = {
    register: {
      processingMs: 300,
      revealMs: 350,
      firstTitle: "Menyimpan data wajah...",
      firstSub: "Profil wajah sedang diamankan untuk proses absensi berikutnya.",
      secondTitle: "Registrasi selesai",
      secondSub: "Data wajah berhasil disimpan.",
    },
    checkin: {
      processingMs: 250,
      revealMs: 350,
      firstTitle: "Memproses check-in...",
      firstSub: "Sistem sedang memvalidasi dan menyimpan absensi masuk.",
      secondTitle: "Check-in berhasil",
      secondSub: "Selamat datang, absensi masuk sudah tercatat.",
    },
    checkout: {
      processingMs: 350,
      revealMs: 450,
      firstTitle: "Memproses check-out...",
      firstSub: "Sistem sedang menutup sesi absensi hari ini.",
      secondTitle: "Check-out berhasil",
      secondSub: "Terima kasih, absensi pulang sudah tercatat.",
    },
    default: {
      processingMs: 650,
      revealMs: 900,
      firstTitle: "Memproses verifikasi absensi...",
      firstSub: "Mohon tunggu, sistem sedang menyimpan hasil absensi.",
      secondTitle: "Verifikasi selesai",
      secondSub: "Absensi berhasil dicatat.",
    },
  };

  function scaledMs(ms) {
    return Math.max(120, Math.round(ms * transitionScale));
  }

  const GUIDE_STAGES = {
    idle: {
      badge: "Siap",
      title: "Aktifkan kamera untuk mulai absensi.",
      text: "Pastikan wajah terlihat jelas, pencahayaan cukup, dan kamera berada setinggi mata.",
      step: "camera",
      tone: "idle",
    },
    camera: {
      badge: "Kamera Aktif",
      title: "Posisikan wajah di tengah frame panduan.",
      text: "Jaga kepala tetap stabil 1-2 detik agar sistem bisa membaca kontur wajah dengan baik.",
      step: "position",
      tone: "camera",
    },
    register: {
      badge: "Registrasi",
      title: "Tahan posisi, sistem sedang menyimpan data wajah.",
      text: "Wajah harus menghadap kamera langsung dan tidak tertutup masker atau bayangan berat.",
      step: "verify",
      tone: "verify",
    },
    checkin: {
      badge: "Check-in",
      title: "Siapkan wajah untuk check-in.",
      text: "Setelah liveness lolos, absensi masuk akan dikirim otomatis ke sistem.",
      step: "verify",
      tone: "verify",
    },
    checkout: {
      badge: "Check-out",
      title: "Siapkan wajah untuk check-out.",
      text: "Ikuti panduan gerakan singkat, lalu sistem akan memproses absensi pulang.",
      step: "verify",
      tone: "verify",
    },
    liveness: {
      badge: "Liveness",
      title: "Gerakkan kepala sedikit atau kedipkan mata sekarang.",
      text: "Panel akan membaca perubahan gerak alami wajah untuk memastikan ini bukan foto statis.",
      step: "liveness",
      tone: "liveness",
    },
    success: {
      badge: "Berhasil",
      title: "Verifikasi wajah berhasil.",
      text: "Data absensi sudah diterima. Selesaikan proses untuk melihat ringkasan hasil.",
      step: "verify",
      tone: "success",
    },
    error: {
      badge: "Perlu Ulang",
      title: "Absensi belum berhasil diverifikasi.",
      text: "Periksa posisi wajah, pencahayaan, dan gerakan liveness lalu coba lagi.",
      step: "liveness",
      tone: "error",
    },
  };

  function sleep(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }

  function speakGuide(text) {
    if (!text || !voiceGuideToggle || !voiceGuideToggle.checked || !("speechSynthesis" in window)) {
      return;
    }
    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "id-ID";
      utterance.rate = 1;
      utterance.pitch = 1;
      window.speechSynthesis.speak(utterance);
    } catch (_) {
      // Ignore unsupported speech synthesis errors.
    }
  }

  function setQualityChip(node, state, text) {
    if (!node) {
      return;
    }
    node.className = "face-quality-chip state-" + state;
    node.textContent = text;
  }

  function setGuideStage(stageKey, overrides) {
    const stage = Object.assign({}, GUIDE_STAGES[stageKey] || GUIDE_STAGES.idle, overrides || {});

    if (stageBadge) {
      stageBadge.textContent = stage.badge;
      stageBadge.className = "face-stage-badge stage-" + stage.tone;
    }
    if (commandHeadline) {
      commandHeadline.textContent = stage.title;
    }
    if (commandSubtext) {
      commandSubtext.textContent = stage.text;
    }
    if (cameraShell) {
      cameraShell.setAttribute("data-guide-stage", stage.tone);
    }

    if (overrides && overrides.speak) {
      speakGuide(stage.title);
    }

    stepNodes.forEach(function (node) {
      const nodeStep = node.getAttribute("data-face-step");
      const order = ["camera", "position", "liveness", "verify"];
      const activeIndex = order.indexOf(stage.step);
      const nodeIndex = order.indexOf(nodeStep);
      node.classList.toggle("is-active", nodeStep === stage.step);
      node.classList.toggle("is-done", activeIndex > -1 && nodeIndex > -1 && nodeIndex < activeIndex);
    });
  }

  function analyzeFrameQuality() {
    if (!video || !video.srcObject || !video.videoWidth || !video.videoHeight) {
      return;
    }

    const tmp = document.createElement("canvas");
    tmp.width = 96;
    tmp.height = 72;
    const ctx = tmp.getContext("2d");
    ctx.drawImage(video, 0, 0, tmp.width, tmp.height);
    const image = ctx.getImageData(0, 0, tmp.width, tmp.height).data;

    let totalLuma = 0;
    let centerLuma = 0;
    let centerCount = 0;
    for (let y = 0; y < tmp.height; y++) {
      for (let x = 0; x < tmp.width; x++) {
        const idx = (y * tmp.width + x) * 4;
        const luma = image[idx] * 0.299 + image[idx + 1] * 0.587 + image[idx + 2] * 0.114;
        totalLuma += luma;
        if (x > 24 && x < 72 && y > 16 && y < 56) {
          centerLuma += luma;
          centerCount += 1;
        }
      }
    }

    const avgLuma = totalLuma / (tmp.width * tmp.height);
    const avgCenter = centerCount ? centerLuma / centerCount : avgLuma;
    const brightnessDelta = lastBrightness === null ? 0 : Math.abs(avgLuma - lastBrightness);
    lastBrightness = avgLuma;

    if (avgLuma < 70) {
      setQualityChip(qualityBrightness, "warn", "Cahaya: terlalu gelap, tambah pencahayaan");
    } else if (avgLuma > 190) {
      setQualityChip(qualityBrightness, "warn", "Cahaya: terlalu terang, kurangi backlight");
    } else {
      setQualityChip(qualityBrightness, "good", "Cahaya: cukup untuk verifikasi");
    }

    if (Math.abs(avgCenter - avgLuma) < 8) {
      setQualityChip(qualityFraming, "good", "Framing: wajah diperkirakan sudah di tengah");
    } else {
      setQualityChip(qualityFraming, "warn", "Framing: geser wajah ke tengah frame");
    }

    if (brightnessDelta > 18) {
      setQualityChip(qualityStability, "warn", "Stabilitas: kamera atau kepala terlalu banyak bergerak");
    } else {
      setQualityChip(qualityStability, "good", "Stabilitas: posisi sudah cukup tenang");
    }
  }

  function startQualityLoop() {
    if (qualityLoopId) {
      window.clearInterval(qualityLoopId);
    }
    qualityLoopId = window.setInterval(analyzeFrameQuality, 700);
  }

  function stopQualityLoop() {
    if (qualityLoopId) {
      window.clearInterval(qualityLoopId);
      qualityLoopId = null;
    }
  }

  async function runCaptureCountdown() {
    if (!countdownOverlay || !countdownValue) {
      return;
    }
    countdownOverlay.classList.remove("d-none");
    for (let count = 3; count >= 1; count--) {
      countdownValue.textContent = String(count);
      countdownValue.classList.remove("tick");
      void countdownValue.offsetWidth;
      countdownValue.classList.add("tick");
      speakGuide(String(count));
      await sleep(250);
    }
    countdownValue.textContent = "GO";
    countdownValue.classList.remove("tick");
    void countdownValue.offsetWidth;
    countdownValue.classList.add("tick");
    speakGuide("Ambil verifikasi");
    await sleep(150);
    countdownOverlay.classList.add("d-none");
  }

  function getCurrentLocation() {
    return new Promise(function(resolve, reject) {
      if (!navigator.geolocation) {
        reject(new Error("Perangkat tidak mendukung GPS/geolocation."));
        return;
      }

      const GOOD_ENOUGH_ACCURACY_M = 60;
      const WATCH_TIMEOUT_MS = 7000;
      let best = null;
      let watchId = null;
      let settled = false;

      function toResult(pos) {
        return {
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy,
        };
      }

      function finish(result, err) {
        if (settled) return;
        settled = true;
        if (watchId !== null) navigator.geolocation.clearWatch(watchId);
        if (result) resolve(result);
        else reject(err);
      }

      function mapError(err) {
        if (err && err.code === 1) {
          return new Error("Izin lokasi ditolak. Aktifkan GPS dan izinkan akses lokasi untuk absensi.");
        }
        if (err && err.code === 2) {
          return new Error("Lokasi tidak tersedia. Pastikan GPS aktif dan sinyal cukup.");
        }
        if (err && err.code === 3) {
          return new Error("Pengambilan lokasi timeout. Coba lagi di area dengan sinyal GPS lebih baik.");
        }
        return new Error("Gagal mendapatkan lokasi GPS.");
      }

      // Watch (not single getCurrentPosition) so we can keep refining accuracy for a few
      // seconds instead of settling for the first — often poor — fix, especially indoors.
      watchId = navigator.geolocation.watchPosition(
        function (pos) {
          if (!best || pos.coords.accuracy < best.coords.accuracy) best = pos;
          if (pos.coords.accuracy <= GOOD_ENOUGH_ACCURACY_M) {
            finish(toResult(pos));
          }
        },
        function (err) {
          if (best) {
            finish(toResult(best));
            return;
          }
          finish(null, mapError(err));
        },
        { enableHighAccuracy: true, timeout: WATCH_TIMEOUT_MS, maximumAge: 0 }
      );

      setTimeout(function () {
        if (best) finish(toResult(best));
        else finish(null, new Error("Sinyal GPS lemah dan belum presisi. Coba pindah ke area terbuka lalu ulangi."));
      }, WATCH_TIMEOUT_MS);
    });
  }

  function setLivenessUI(visible, text) {
    if (!livenessHint) return;
    livenessHint.classList.toggle("d-none", !visible);
    if (visible && text && livenessHintText) livenessHintText.textContent = text;
  }

  function updateLivenessProgress(ratio) {
    if (livenessProgressBar) livenessProgressBar.style.width = Math.round(ratio * 100) + "%";
  }

  function captureSmallFrame() {
    const tmp = document.createElement("canvas");
    tmp.width = 160;
    tmp.height = 120;
    const ctx = tmp.getContext("2d");
    ctx.drawImage(video, 0, 0, 160, 120);
    return ctx.getImageData(0, 0, 160, 120);
  }

  async function runLivenessChallenge() {
    const frames = [];
    for (let i = 0; i < LIVENESS_FRAMES; i++) {
      frames.push(captureSmallFrame());
      updateLivenessProgress((i + 1) / LIVENESS_FRAMES);
      if (i < LIVENESS_FRAMES - 1) await sleep(LIVENESS_INTERVAL_MS);
    }

    const ref = frames[0].data;
    let maxAvgDiff = 0;
    for (let fi = 1; fi < frames.length; fi++) {
      const cmp = frames[fi].data;
      let total = 0;
      for (let p = 0; p < ref.length; p += 4) {
        total += (Math.abs(ref[p] - cmp[p]) + Math.abs(ref[p + 1] - cmp[p + 1]) + Math.abs(ref[p + 2] - cmp[p + 2])) / 3;
      }
      const avg = total / (ref.length / 4);
      if (avg > maxAvgDiff) maxAvgDiff = avg;
    }

    return { passed: maxAvgDiff >= LIVENESS_THRESHOLD, score: parseFloat(maxAvgDiff.toFixed(2)) };
  }

  function notify(variant, title, message, delay) {
    if (window.AppUI && typeof window.AppUI.showToast === "function") {
      window.AppUI.showToast({
        variant,
        title,
        message,
        delay: delay || 3000,
      });
    }
  }

  function setButtonBusy(button, busy, loadingLabel) {
    if (!button) {
      return;
    }

    if (!button.dataset.originalLabel) {
      button.dataset.originalLabel = button.textContent.trim();
    }

    button.disabled = busy;
    button.classList.toggle("is-loading", busy);
    if (busy) {
      button.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>' +
        '<span class="btn-loading-label">' + (loadingLabel || "Memproses...") + "</span>";
      return;
    }

    button.textContent = button.dataset.originalLabel;
  }

  function setMessage(kind, text) {
    if (!resultBox) {
      return;
    }
    resultBox.className = `alert alert-${kind} small mb-0`;
    resultBox.textContent = text;
  }

  function setFaceButtonsDisabled(disabled) {
    [btnStart, btnRegister, btnCheckin, btnCheckout].forEach(function (btn) {
      if (btn) {
        // Never force-enable checkin/checkout if the server already disabled them (face not registered yet).
        if (!disabled && btn !== btnRegister && btn !== btnStart && btn.dataset.serverDisabled === "true") {
          return;
        }
        btn.disabled = disabled;
      }
    });
  }

  function showSuccessEndingPanel(data, action) {
    if (!successEnding) {
      return;
    }
    const actionLabel = action === "checkout" ? "Check-out" : action === "checkin" ? "Check-in" : "Registrasi Wajah";
    const titleLabel = action === "checkout" ? "Check-out Berhasil" : action === "checkin" ? "Check-in Berhasil" : "Registrasi Wajah Berhasil";
    const ts = data && data.timestamp ? new Date(data.timestamp) : new Date();
    const timeLabel = Number.isNaN(ts.getTime())
      ? "-"
      : ts.toLocaleString("id-ID", {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        });

    successEnding.classList.remove("d-none");
    if (btnFaceShowEnding) {
      btnFaceShowEnding.classList.add("d-none");
    }
    if (successTitleEl) {
      successTitleEl.textContent = titleLabel;
    }
    if (successDetail) {
      successDetail.textContent = data && data.message
        ? data.message + (action === "register" ? " Silakan lanjut ke Langkah 2 untuk absensi." : " Silakan lanjutkan ke riwayat atau selesai.")
        : "Data sudah terekam dengan aman.";
    }
    if (successAction) {
      successAction.textContent = "Aksi: " + actionLabel;
    }
    if (successTime) {
      successTime.textContent = "Waktu: " + timeLabel;
    }
    updateSuccessRail("done");
    setFaceButtonsDisabled(true);
    speakGuide(titleLabel);
    latestSuccessSnapshot = { data: data || {}, action: action || "checkin" };
    scheduleSuccessAutoHide();
  }

  function clearSuccessAutoHide() {
    if (successAutoHideTimer) {
      window.clearTimeout(successAutoHideTimer);
      successAutoHideTimer = null;
    }
    if (successAutoHideTick) {
      window.clearInterval(successAutoHideTick);
      successAutoHideTick = null;
    }
  }

  function updateSuccessRail(activeStep) {
    const order = ["camera", "liveness", "verify", "done"];
    const activeIdx = order.indexOf(activeStep);
    successRailSteps.forEach(function (node) {
      const step = node.getAttribute("data-success-rail-step");
      const idx = order.indexOf(step);
      node.classList.toggle("is-active", step === activeStep);
      node.classList.toggle("is-done", idx > -1 && activeIdx > -1 && idx < activeIdx);
    });
  }

  function hideSuccessEndingPanel(autoHidden) {
    if (!successEnding || successEnding.classList.contains("d-none")) {
      return;
    }
    successEnding.classList.add("d-none");
    if (btnFaceShowEnding) {
      btnFaceShowEnding.classList.remove("d-none");
    }
    if (autoHidden && successAutoHide) {
      successAutoHide.textContent = "Ringkasan disembunyikan otomatis.";
    }
    clearSuccessAutoHide();
    setFaceButtonsDisabled(false);
  }

  function scheduleSuccessAutoHide() {
    clearSuccessAutoHide();
    let remaining = SUCCESS_AUTO_HIDE_SECONDS;
    if (successAutoHide) {
      successAutoHide.textContent = "Ringkasan menutup otomatis dalam " + remaining + " detik.";
    }
    successAutoHideTick = window.setInterval(function () {
      remaining -= 1;
      if (remaining <= 0) {
        return;
      }
      if (successAutoHide) {
        successAutoHide.textContent = "Ringkasan menutup otomatis dalam " + remaining + " detik.";
      }
    }, 1000);
    successAutoHideTimer = window.setTimeout(function () {
      hideSuccessEndingPanel(true);
    }, SUCCESS_AUTO_HIDE_SECONDS * 1000);
  }

  async function playSuccessTransition(action) {
    if (!successTransition) {
      return;
    }

    const cfg = SUCCESS_TRANSITION_CONFIG[action] || SUCCESS_TRANSITION_CONFIG.default;
    updateSuccessRail("verify");

    successTransition.classList.remove("d-none");
    if (successLoader) successLoader.classList.remove("d-none");
    if (successCheckmark) successCheckmark.classList.add("d-none");
    if (successTransitionTitle) successTransitionTitle.textContent = cfg.firstTitle;
    if (successTransitionSub) successTransitionSub.textContent = cfg.firstSub;

    await sleep(scaledMs(cfg.processingMs));

    if (successLoader) successLoader.classList.add("d-none");
    if (successCheckmark) successCheckmark.classList.remove("d-none");
    if (successTransitionTitle) successTransitionTitle.textContent = cfg.secondTitle;
    if (successTransitionSub) successTransitionSub.textContent = cfg.secondSub;

    await sleep(scaledMs(cfg.revealMs));
    successTransition.classList.add("d-none");
  }

  async function startCamera() {
    if (!video) {
      notify("warning", "Panel Kamera", "Panel kamera tidak tersedia pada halaman ini.", 3200);
      return;
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "user" }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      video.srcObject = stream;
      if (cameraIdlePrompt) cameraIdlePrompt.classList.add("d-none");
      setGuideStage("camera", { speak: true });
      setQualityChip(qualityBrightness, "wait", "Cahaya: membaca kondisi kamera");
      setQualityChip(qualityFraming, "wait", "Framing: arahkan wajah ke tengah");
      setQualityChip(qualityStability, "wait", "Stabilitas: tahan posisi sejenak");
      startQualityLoop();
      setMessage("info", "Kamera aktif. Arahkan wajah ke kamera dengan pencahayaan cukup.");
      notify("info", "Kamera Aktif", "Arahkan wajah ke kamera dengan pencahayaan cukup.", 2500);
    } catch (err) {
      if (cameraIdlePrompt) cameraIdlePrompt.classList.remove("d-none");
      const errText = err && err.message ? err.message : String(err);
      setGuideStage("error", { text: errText });
      setMessage("danger", `Gagal mengakses kamera: ${errText}`);
      notify("danger", "Kamera Gagal", errText, 4200);
    }
  }

  function captureFrame() {
    if (!video || !canvas) {
      throw new Error("Panel kamera tidak tersedia");
    }

    if (!video.srcObject) {
      throw new Error("Kamera belum aktif");
    }
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.9);
  }

  async function postFace(url, action, button, guideStage) {
    setGuideStage(guideStage || (action === "checkout" ? "checkout" : action === "checkin" ? "checkin" : "register"), { speak: true });
    setButtonBusy(button, true, "Memeriksa liveness…");
    let locationPromise = null;
    if (url.indexOf("/face/verify") !== -1) {
      setMessage("info", "Mengambil GPS sambil memeriksa liveness...");
      locationPromise = getCurrentLocation().then(
        function (value) { return { ok: true, value: value }; },
        function (error) { return { ok: false, error: error }; }
      );
    }

    try {
      await runCaptureCountdown();
    } catch (_) {
      // Ignore countdown issues and continue to verification.
    }

    // Client-side liveness gate: static photo → near-zero inter-frame motion
    try {
      setGuideStage("liveness", { speak: true });
      setLivenessUI(true, "Kedipkan mata atau gerakkan kepala sedikit…");
      setMessage("info", "Liveness check — kedipkan mata atau gerakkan kepala sedikit…");
      updateLivenessProgress(0);

      const liveness = await runLivenessChallenge();
      setLivenessUI(false);

      if (!liveness.passed) {
        setGuideStage("error", { text: "Gerakan wajah terlalu minim. Ulangi sambil berkedip atau miringkan kepala sedikit." });
        setMessage("danger", "Terdeteksi gambar statis (score: " + liveness.score + "). Pastikan wajah nyata di depan kamera, bukan foto.");
        notify("danger", "Liveness Gagal", "Terdeteksi gambar statis. Kedipkan mata atau gerakkan wajah.", 5000);
        setButtonBusy(button, false);
        return false;
      }
    } catch (_) {
      setLivenessUI(false);
      // Lanjutkan jika error capture (misal kamera baru aktif)
    }

    setButtonBusy(button, true, "Memverifikasi…");
    try {
      const imageBase64 = captureFrame();
      const payload = { image_base64: imageBase64, action };
      if (url.indexOf("/face/verify") !== -1) {
        const locationResult = await locationPromise;
        if (!locationResult.ok) throw locationResult.error;
        const geo = locationResult.value;
        payload.latitude = geo.latitude;
        payload.longitude = geo.longitude;
        payload.accuracy_m = geo.accuracy_m;
      }
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Proses gagal");
      }
      const confidenceText = data.confidence ? ` | confidence: ${data.confidence}` : "";
      const distanceText = typeof data.distance_m === "number"
        ? ` | jarak kantor: ${Math.round(data.distance_m)}m`
        : "";
      const reviewText = data.location_review_required ? " | status: perlu review lokasi" : "";
      const sourceText = data.geofence_source === "institution" && data.geofence_institution
        ? ` | geofence: instansi ${data.geofence_institution}`
        : "";
      const riskText = data.location_risk_detected && data.location_risk_message
        ? ` | ${data.location_risk_message}`
        : "";
      const successText = action === "register"
        ? "Foto wajah tersimpan. Lanjut ke Langkah 2 untuk melakukan Check-in / Check-out."
        : GUIDE_STAGES.success.text;
      const notifyTitle = action === "register" ? "Registrasi Berhasil" : "Verifikasi Berhasil";
      setGuideStage("success", { title: data.message || GUIDE_STAGES.success.title, text: successText, speak: true });
      setMessage("success", `${data.message}${confidenceText}${distanceText}${reviewText}${sourceText}${riskText}`);
      if (action === "register" && data.thumbnail) {
        applyRegisteredPhoto(data.thumbnail);
      }
      await playSuccessTransition(action);
      showSuccessEndingPanel(data, action);
      notify("success", notifyTitle, `${data.message}${confidenceText}${distanceText}${reviewText}${sourceText}${riskText}`, 3800);
      return true;
    } catch (err) {
      setGuideStage("error", { text: err.message });
      setMessage("danger", err.message);
      notify("danger", "Verifikasi Gagal", err.message, 4500);
      return false;
    } finally {
      setButtonBusy(button, false);
    }
  }

  async function submitManualAttendance(event) {
    event.preventDefault();
    const submitButton = manualForm ? manualForm.querySelector('button[type="submit"], input[type="submit"]') : null;
    setButtonBusy(submitButton, true, "Menyimpan...");
    try {
      const formData = new FormData(manualForm);
      const payload = {
        user_id: Number(formData.get("user_id")),
        status: String(formData.get("status") || "hadir")
      };
      const response = await fetch("/api/attendance/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Gagal simpan absensi manual");
      }
      setMessage("success", data.message || "Absensi manual berhasil disimpan.");
      notify("success", "Absensi Tersimpan", data.message || "Absensi manual berhasil disimpan.", 2600);
      setTimeout(() => window.location.reload(), 700);
    } catch (err) {
      setMessage("danger", err.message);
      notify("danger", "Absensi Gagal", err.message, 4200);
    } finally {
      setButtonBusy(submitButton, false);
    }
  }

  const btnStart = document.getElementById("btnStartCamera");
  const btnRegister = document.getElementById("btnRegisterFace");
  const btnCheckin = document.getElementById("btnCheckinFace");
  const btnCheckout = document.getElementById("btnCheckoutFace");
  const registeredPhotoImg = document.getElementById("faceRegisteredPhoto");
  const registeredPhotoWrap = document.getElementById("faceRegisteredPhotoWrap");

  function applyRegisteredPhoto(dataUrl) {
    if (!registeredPhotoImg || !registeredPhotoWrap || !dataUrl) return;
    registeredPhotoImg.src = dataUrl;
    registeredPhotoImg.classList.remove("d-none");
    registeredPhotoWrap.classList.add("has-photo");
  }

  if (registeredPhotoImg && registeredPhotoWrap) {
    fetch("/api/face/thumbnail")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.thumbnail) applyRegisteredPhoto(data.thumbnail);
      })
      .catch(() => {});
  }

  [btnCheckin, btnCheckout].forEach(function (btn) {
    if (btn && btn.disabled) btn.dataset.serverDisabled = "true";
  });

  setGuideStage("idle");

  if (btnStart) btnStart.addEventListener("click", startCamera);
  if (btnRegister) {
    btnRegister.addEventListener("click", () =>
      postFace("/api/face/register", "register", btnRegister, "register").then(function (success) {
        // Navigate with a flag so the reloaded page shows a persistent confirmation banner
        // and unlocks check-in/out (instead of feeling like a blank reload).
        if (success) {
          setTimeout(() => {
            window.location.assign(window.location.pathname + "?registered=1");
          }, 900);
        }
      })
    );
  }
  if (btnCheckin) btnCheckin.addEventListener("click", () => postFace("/api/face/verify", "checkin", btnCheckin, "checkin"));
  if (btnCheckout) btnCheckout.addEventListener("click", () => postFace("/api/face/verify", "checkout", btnCheckout, "checkout"));
  if (btnFaceReload) btnFaceReload.addEventListener("click", () => window.location.reload());
  if (btnFaceFinish) btnFaceFinish.addEventListener("click", () => window.location.assign("/dashboard"));
  if (btnFaceShowEnding) {
    btnFaceShowEnding.addEventListener("click", function () {
      if (!latestSuccessSnapshot) {
        return;
      }
      showSuccessEndingPanel(latestSuccessSnapshot.data, latestSuccessSnapshot.action);
    });
  }
  if (manualForm) manualForm.addEventListener("submit", submitManualAttendance);
  window.addEventListener("beforeunload", function () {
    stopQualityLoop();
    clearSuccessAutoHide();
  });
})();
