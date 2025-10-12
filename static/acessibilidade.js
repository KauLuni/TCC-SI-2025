
(() => {
  const LS_KEY = "acc_prefs";

  // Carrega/salva preferências
  const prefs = (() => {
    try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; }
    catch { return {}; }
  })();
  const save = () => localStorage.setItem(LS_KEY, JSON.stringify(prefs));

  // Aplica tamanho base no <html>
  function applyFont() {
    const size = prefs.fontSizePx || 16; // base
    document.documentElement.style.fontSize = `${size}px`;

    // Anúncio "invisível" para tecnologias assistivas
    const live = document.getElementById("acc-font-live");
    if (live) live.textContent = `Tamanho da fonte: ${size} pixels`;
  }

  // Limita valores entre 12 e 22 px
  const clamp = (n, min = 12, max = 22) => Math.min(Math.max(n, min), max);

  function incFont() {
    prefs.fontSizePx = clamp((prefs.fontSizePx || 16) + 1);
    save(); applyFont();
  }
  function decFont() {
    prefs.fontSizePx = clamp((prefs.fontSizePx || 16) - 1);
    save(); applyFont();
  }

  // Cria a barra com A- / A+
  function buildToolbar() {
    const bar = document.createElement("div");
    bar.className = "acess-toolbar";
    bar.setAttribute("role", "region");
    bar.setAttribute("aria-label", "Ajuste de tamanho do texto");
    bar.innerHTML = `
      <button type="button" class="acc-btn" id="acc-dec" title="Diminuir tamanho do texto">A-</button>
      <button type="button" class="acc-btn" id="acc-inc" title="Aumentar tamanho do texto">A+</button>
      <span id="acc-font-live" aria-live="polite"
            style="position:absolute;left:-9999px;top:auto;width:1px;height:1px;overflow:hidden;">
      </span>
    `;
    document.body.appendChild(bar);

    document.getElementById("acc-inc")?.addEventListener("click", incFont);
    document.getElementById("acc-dec")?.addEventListener("click", decFont);
  }

  // Inicializa
  applyFont();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildToolbar);
  } else {
    buildToolbar();
  }
})();
