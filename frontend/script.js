const STORAGE_KEY_SETTINGS = "avatar_studio_settings_v1";
const STORAGE_KEY_HISTORY = "avatar_studio_history_v1";

const form = document.getElementById("generate-form");
const textInput = document.getElementById("text-input");
const imageInput = document.getElementById("image-input");
const voiceSelect = document.getElementById("voice-select");
const styleSelect = document.getElementById("style-select");
const previewImage = document.getElementById("preview-image");

const musicEnabled = document.getElementById("music-enabled");
const musicVolume = document.getElementById("music-volume");
const musicVolumeLabel = document.getElementById("music-volume-label");

const subtitlesEnabled = document.getElementById("subtitles-enabled");
const subtitleColor = document.getElementById("subtitle-color");
const subtitleSize = document.getElementById("subtitle-size");

const addSceneBtn = document.getElementById("add-scene-btn");
const scenesList = document.getElementById("scenes-list");

const generateBtn = document.getElementById("generate-btn");
const statusContainer = document.getElementById("status-container");
const statusText = document.getElementById("status-text");
const progressFill = document.getElementById("progress-fill");
const videoPlayer = document.getElementById("video-player");
const downloadButton = document.getElementById("download-button");
const shareButton = document.getElementById("share-button");
const errorContainer = document.getElementById("error-container");
const historyList = document.getElementById("history-list");
const charCounter = document.getElementById("char-counter");
const durationEstimate = document.getElementById("duration-estimate");

let pollTimer = null;
let sceneCounter = 0;

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "00:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function estimateDuration(text) {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return words / 2.4;
}

function showError(message) {
  errorContainer.style.display = "block";
  errorContainer.textContent = message;
}

function hideError() {
  errorContainer.style.display = "none";
  errorContainer.textContent = "";
}

function setLoadingState(visible) {
  statusContainer.style.display = visible ? "grid" : "none";
  generateBtn.disabled = visible;
  generateBtn.classList.toggle("is-loading", visible);
}

function updateTextMeta() {
  const value = textInput.value || "";
  charCounter.textContent = `${value.length} символов`;
  durationEstimate.textContent = `~ ${formatTime(estimateDuration(value))}`;
}

function buildSceneItem(initialStart = "00:00", initialPrompt = "", initialBackground = "") {
  const row = document.createElement("div");
  row.className = "scene-row";
  row.dataset.sceneId = String(sceneCounter++);
  row.innerHTML = `
    <input type="text" class="scene-start" value="${initialStart}" placeholder="мм:сс" />
    <input type="text" class="scene-prompt" value="${initialPrompt}" placeholder="Описание сцены" />
    <input type="text" class="scene-background" value="${initialBackground}" placeholder="Описание фона (опц.)" />
    <input type="file" class="scene-image" accept="image/png,image/jpeg,image/webp" />
    <button type="button" class="secondary-button scene-delete">Удалить</button>
  `;
  row.querySelector(".scene-delete").addEventListener("click", () => row.remove());
  return row;
}

function mmssToSeconds(value) {
  const [mm, ss] = value.split(":").map((part) => Number(part));
  if (!Number.isFinite(mm) || !Number.isFinite(ss)) return 0;
  return Math.max(0, mm * 60 + ss);
}

function collectScenes() {
  return Array.from(scenesList.querySelectorAll(".scene-row")).map((row) => ({
    start_label: row.querySelector(".scene-start").value.trim() || "00:00",
    start_time: mmssToSeconds(row.querySelector(".scene-start").value.trim() || "00:00"),
    scene_description: row.querySelector(".scene-prompt").value.trim(),
    background: row.querySelector(".scene-background").value.trim(),
    text: "",
  }));
}

function validateBeforeSubmit(text) {
  if (!text.trim()) {
    showError("Текст не должен быть пустым.");
    return false;
  }
  const estimated = estimateDuration(text);
  if (estimated > 60) {
    showError("Оценка длительности превышает 60 секунд. Сократите текст.");
    return false;
  }
  for (const scene of collectScenes()) {
    if (!/^\d{2}:\d{2}$/.test(scene.start)) {
      showError(`Некорректный тайм-код сцены: ${scene.start}. Используйте мм:сс.`);
      return false;
    }
  }
  return true;
}

function readSettingsFromUi() {
  return {
    text: textInput.value,
    voice: voiceSelect.value,
    style: styleSelect.value,
    use_background_music: musicEnabled.checked,
    music_volume: Number(musicVolume.value),
    add_subtitles: subtitlesEnabled.checked,
    subtitle_color: subtitleColor.value,
    subtitle_size: Number(subtitleSize.value),
    scenes: collectScenes(),
  };
}

function saveSettings() {
  localStorage.setItem(STORAGE_KEY_SETTINGS, JSON.stringify(readSettingsFromUi()));
}

function loadSettings() {
  const raw = localStorage.getItem(STORAGE_KEY_SETTINGS);
  if (!raw) return;
  try {
    const data = JSON.parse(raw);
    textInput.value = data.text || "";
    voiceSelect.value = data.voice || "ru";
    styleSelect.value = data.style || "cartoon_furry";
    musicEnabled.checked = Boolean(data.use_background_music);
    musicVolume.value = String(data.music_volume ?? 30);
    subtitlesEnabled.checked = Boolean(data.add_subtitles);
    subtitleColor.value = data.subtitle_color || "#ffffff";
    subtitleSize.value = String(data.subtitle_size ?? 42);
    scenesList.innerHTML = "";
    (data.scenes || []).forEach((scene) => {
      scenesList.appendChild(
        buildSceneItem(scene.start_label || "00:00", scene.scene_description || "", scene.background || ""),
      );
    });
  } catch {
    // Ignore broken localStorage payload and keep defaults.
  }
}

function loadHistory() {
  const raw = localStorage.getItem(STORAGE_KEY_HISTORY);
  if (!raw) return [];
  try {
    const list = JSON.parse(raw);
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function saveHistory(list) {
  localStorage.setItem(STORAGE_KEY_HISTORY, JSON.stringify(list));
}

function renderHistory() {
  const history = loadHistory();
  historyList.innerHTML = "";
  if (!history.length) {
    historyList.innerHTML = "<p class='muted'>История пуста.</p>";
    return;
  }
  history.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "history-row";
    row.innerHTML = `
      <div>
        <strong>${item.createdAt}</strong>
        <p>${item.textPreview}</p>
      </div>
      <div class="history-actions">
        <a href="${item.videoUrl}" download>Скачать</a>
        <button type="button" data-remove="${index}" class="secondary-button">Удалить</button>
      </div>
    `;
    row.querySelector("[data-remove]").addEventListener("click", () => {
      const next = loadHistory();
      next.splice(index, 1);
      saveHistory(next);
      renderHistory();
    });
    historyList.appendChild(row);
  });
}

function addToHistory(text, videoUrl) {
  const history = loadHistory();
  history.unshift({
    createdAt: new Date().toLocaleString("ru-RU"),
    textPreview: text.slice(0, 80),
    videoUrl,
  });
  saveHistory(history.slice(0, 20));
  renderHistory();
}

async function pollStatus(taskId, text) {
  const startedAt = Date.now();
  async function poll() {
    try {
      const response = await fetch(`/api/status/${taskId}`);
      if (!response.ok) throw new Error(`Ошибка запроса статуса: ${response.status}`);
      const data = await response.json();
      const progress = Number(data.progress ?? 0);
      const step = data.step || data.current_step || "Обработка...";
      const elapsedSec = (Date.now() - startedAt) / 1000;
      const remainingSec = progress > 0 ? (elapsedSec * (100 - progress)) / progress : 0;
      progressFill.style.width = `${Math.max(0, Math.min(100, progress))}%`;
      statusText.textContent = `${data.status}: ${step} (${progress}%) ${
        remainingSec > 0 ? `~ осталось ${formatTime(remainingSec)}` : ""
      }`;

      if (data.status === "SUCCESS") {
        clearInterval(pollTimer);
        setLoadingState(false);
        const videoUrl = `/api/download/${taskId}`;
        videoPlayer.src = videoUrl;
        downloadButton.href = videoUrl;
        addToHistory(text, videoUrl);
      }
      if (data.status === "FAILURE") {
        clearInterval(pollTimer);
        setLoadingState(false);
        showError(data.error || "Генерация завершилась с ошибкой.");
      }
    } catch (error) {
      clearInterval(pollTimer);
      setLoadingState(false);
      showError(`Не удалось получить статус задачи: ${error.message}`);
    }
  }
  await poll();
  pollTimer = setInterval(poll, 2000);
}

document.getElementById("tabs").addEventListener("click", (event) => {
  const button = event.target.closest(".tab-button");
  if (!button) return;
  document.querySelectorAll(".tab-button").forEach((el) => el.classList.remove("active"));
  button.classList.add("active");
  const tab = button.dataset.tab;
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === tab);
  });
});

musicVolume.addEventListener("input", () => {
  musicVolumeLabel.textContent = `${musicVolume.value}%`;
  saveSettings();
});
textInput.addEventListener("input", () => {
  updateTextMeta();
  saveSettings();
});
[voiceSelect, styleSelect, musicEnabled, subtitlesEnabled, subtitleColor, subtitleSize].forEach((el) => {
  el.addEventListener("change", saveSettings);
});

imageInput.addEventListener("change", () => {
  const file = imageInput.files && imageInput.files[0];
  if (!file) return;
  const url = URL.createObjectURL(file);
  previewImage.src = url;
});

addSceneBtn.addEventListener("click", () => {
  scenesList.appendChild(buildSceneItem());
  saveSettings();
});

shareButton.addEventListener("click", async () => {
  const url = downloadButton.getAttribute("href");
  if (!url) {
    showError("Сначала сгенерируйте видео.");
    return;
  }
  const shareUrl = `${window.location.origin}${url}`;
  await navigator.clipboard.writeText(shareUrl);
  statusText.textContent = "Ссылка скопирована в буфер обмена.";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError();
  const text = textInput.value.trim();
  if (!validateBeforeSubmit(text)) return;

  const formData = new FormData();
  formData.append("text", text);
  formData.append("voice", voiceSelect.value);
  formData.append("style", styleSelect.value);
  formData.append("use_background_music", String(musicEnabled.checked));
  formData.append("music_volume", String(musicVolume.value));
  formData.append("add_subtitles", String(subtitlesEnabled.checked));
  formData.append("subtitle_color", subtitleColor.value);
  formData.append("subtitle_font_size", String(subtitleSize.value));
  formData.append("scenes_json", JSON.stringify(collectScenes()));

  const file = imageInput.files && imageInput.files[0];
  if (file) formData.append("image", file);
  Array.from(scenesList.querySelectorAll(".scene-row")).forEach((row) => {
    const sceneImageInput = row.querySelector(".scene-image");
    const sceneFile = sceneImageInput?.files?.[0];
    if (sceneFile) {
      formData.append("scene_media", sceneFile);
    }
  });

  setLoadingState(true);
  statusText.textContent = "Отправка задачи...";
  progressFill.style.width = "0%";

  try {
    const response = await fetch("/api/generate", { method: "POST", body: formData });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || `Ошибка: ${response.status}`);
    }
    const data = await response.json();
    if (!data.task_id) throw new Error("Сервер не вернул task_id.");
    statusText.textContent = "Задача создана, ожидаем обработку...";
    saveSettings();
    await pollStatus(data.task_id, text);
  } catch (error) {
    setLoadingState(false);
    showError(`Ошибка при запуске генерации: ${error.message}`);
  }
});

loadSettings();
if (!scenesList.children.length) scenesList.appendChild(buildSceneItem("00:00", ""));
updateTextMeta();
musicVolumeLabel.textContent = `${musicVolume.value}%`;
renderHistory();

