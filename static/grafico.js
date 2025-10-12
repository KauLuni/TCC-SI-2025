// static/grafico.js
(() => {
  "use strict";

  // ===== Debug OFF =====
  const DEBUG = false;

  // ---------- (no-op) helpers de log ----------
  function statusBox() { if (!DEBUG) return null; /* nunca cria a caixa */ }
  function logLine(_msg, _ok = true) { /* não faz nada quando DEBUG=false */ }

  // ---------- garante seção/canvases, se faltarem ----------
  function ensureGraphSection() {
    let sec = document.getElementById("graficos");
    if (!sec) {
      sec = document.createElement("section");
      sec.id = "graficos";
      sec.style.margin = "40px 0";
      sec.innerHTML = `
        <h2>Gráficos do TCC</h2>

        <article style="margin:24px 0;">
          <h3>Histórico de Incidências (2000–2023)</h3>
          <canvas id="graficoHistorico"></canvas>
        </article>

        <article style="margin:24px 0;">
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
            <h3 style="margin:0;">Modelo Preditivo até 2033</h3>
            <label><strong>Modelo:</strong></label>
            <select id="modelo">
              <option>ARIMA</option>
              <option>ETS</option>
            </select>
          </div>
          <canvas id="graficoPreditivo" style="margin-top:12px;"></canvas>
        </article>

        <article style="margin:24px 0;">
          <h3>Correlação: Índice UV × Casos</h3>
          <canvas id="graficoCorrelacao"></canvas>
        </article>
      `;
      const main = document.querySelector("main");
      (main || document.body).appendChild(sec);
    } else {
      if (!document.getElementById("graficoHistorico")) {
        const a = document.createElement("article");
        a.innerHTML = `<h3>Histórico de Incidências (2000–2023)</h3><canvas id="graficoHistorico"></canvas>`;
        sec.appendChild(a);
      }
      if (!document.getElementById("graficoPreditivo")) {
        const a = document.createElement("article");
        a.innerHTML = `
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
            <h3 style="margin:0;">Modelo Preditivo até 2033</h3>
            <label><strong>Modelo:</strong></label>
            <select id="modelo">
              <option>ARIMA</option>
              <option>ETS</option>
            </select>
          </div>
          <canvas id="graficoPreditivo" style="margin-top:12px;"></canvas>
        `;
        sec.appendChild(a);
      }
      if (!document.getElementById("graficoCorrelacao")) {
        const a = document.createElement("article");
        a.innerHTML = `<h3>Correlação: Índice UV × Casos</h3><canvas id="graficoCorrelacao"></canvas>`;
        sec.appendChild(a);
      }
    }
  }

  // ---------- base da API (sempre o host/porta atual; permite override via window.API_BASE) ----------
  const API = (window.API_BASE ?? window.location.origin).replace(/\/$/, "");
  logLine(`API base: ${API}`);

  // ---------- Chart.js ----------
  if (typeof Chart === "undefined") {
    console.error("Chart.js NÃO está carregado.");
    return;
  } else {
    // deixa o Chart respeitar o tamanho do CSS
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.elements.point.radius = 2;
    Chart.defaults.elements.line.tension = 0.25;
  }

  // ---------- helpers ----------
  async function getJSON(path) {
    const url = `${API}${path}`;
    const res = await fetch(url);
    if (!res.ok) {
      console.error(`GET ${url} -> ${res.status}`);
      throw new Error(`GET ${url} -> ${res.status}`);
    }
    return res.json();
  }
  const el = (id) => document.getElementById(id);
  function showError(where, err) {
    console.error(`[ERRO] ${where}:`, err);
  }

  // ---------- 1) Histórico ----------
  async function renderHistorico() {
    const canvas = el("graficoHistorico");
    if (!canvas) return;
    try {
      const data = await getJSON(`/api/incidencia/anual?start=2000&end=2023`);
      if (!Array.isArray(data) || data.length === 0)
        throw new Error("Sem dados para 2000–2023.");

      const anos = data.map(d => d.ano);
      const casos = data.map(d => d.casos);

      new Chart(canvas, {
        type: "bar",
        data: { labels: anos, datasets: [{ label: "Casos/ano", data: casos }] },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { title: { display: true, text: "Ano" } },
            y: { title: { display: true, text: "Casos" }, beginAtZero: true },
          },
        },
      });
    } catch (err) { showError("Histórico (2000–2023)", err); }
  }

  // ---------- 2) Preditivo ----------
  let chartPreditivo;
  async function tryModelo(modelo) {
    const data = await getJSON(`/api/preditivo/anual?modelo=${encodeURIComponent(modelo)}`);
    if (!Array.isArray(data) || data.length === 0)
      throw new Error(`Sem dados para o modelo '${modelo}'.`);
    return { modelo, data };
  }
  async function renderPreditivo() {
    const canvas = el("graficoPreditivo");
    if (!canvas) return;
    try {
      let got = null;
      for (const m of ["ARIMA", "ETS"]) {
        try { got = await tryModelo(m); break; } catch {}
      }
      if (!got) throw new Error("Nenhum modelo (ARIMA/ETS) retornou dados.");

      const { modelo, data } = got;
      const anos = data.map(d => d.ano);
      const ponto = data.map(d => d.point);
      const lo95 = data.map(d => d.lo95);
      const hi95 = data.map(d => d.hi95);

      if (chartPreditivo) chartPreditivo.destroy();
      chartPreditivo = new Chart(canvas, {
        type: "line",
        data: {
          labels: anos,
          datasets: [
            { label: `Previsão (${modelo})`, data: ponto, borderWidth: 2 },
            { label: "Intervalo 95% (baixo)", data: lo95, borderWidth: 1, pointRadius: 0 },
            { label: "Intervalo 95% (alto)",  data: hi95, borderWidth: 1, pointRadius: 0 },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          scales: {
            x: { title: { display: true, text: "Ano" } },
            y: { title: { display: true, text: "Casos (previstos)" } },
          },
        },
      });

      const sel = el("modelo");
      if (sel && !sel._bound) {
        sel._bound = true;
        sel.addEventListener("change", async (e) => {
          const chosen = e.target.value || "ARIMA";
          try {
            const d = await getJSON(`/api/preditivo/anual?modelo=${encodeURIComponent(chosen)}`);
            if (!Array.isArray(d) || d.length === 0)
              throw new Error(`Sem dados para o modelo '${chosen}'.`);

            chartPreditivo.destroy();
            chartPreditivo = new Chart(canvas, {
              type: "line",
              data: {
                labels: d.map(r => r.ano),
                datasets: [
                  { label: `Previsão (${chosen})`, data: d.map(r => r.point), borderWidth: 2 },
                  { label: "Intervalo 95% (baixo)", data: d.map(r => r.lo95), borderWidth: 1, pointRadius: 0 },
                  { label: "Intervalo 95% (alto)",  data: d.map(r => r.hi95), borderWidth: 1, pointRadius: 0 },
                ],
              },
              options: { responsive: true, maintainAspectRatio: false },
            });
          } catch (err2) { showError(`Troca de modelo (${chosen})`, err2); }
        });
      }
    } catch (err) { showError("Preditivo", err); }
  }

  // ---------- 3) Correlação ----------
  async function renderCorrelacao() {
    const canvas = el("graficoCorrelacao");
    if (!canvas) return;
    try {
      const data = await getJSON(`/api/correlacao/uv-incidencia?start=2000&end=2023`);
      if (!Array.isArray(data) || data.length === 0)
        throw new Error("Sem dados para correlação.");

      const temUV = data.some(d => d.uv_medio != null);

      if (temUV) {
        const pontos = data
          .filter(d => d.uv_medio != null)
          .map(d => ({ x: Number(d.uv_medio), y: Number(d.casos), _ano: d.ano }));

        new Chart(canvas, {
          type: "scatter",
          data: { datasets: [{ label: "Ano (UV × Casos)", data: pontos, pointRadius: 4 }] },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { tooltip: { callbacks: { label: (ctx) => {
              const p = ctx.raw; return `Ano ${p._ano}: UV=${p.x.toFixed(2)}, Casos=${p.y}`;
            }}}},
            scales: {
              x: { title: { display: true, text: "Índice UV (média anual)" } },
              y: { title: { display: true, text: "Casos (total anual)" }, beginAtZero: true },
            },
          },
        });
      } else {
        const anos = data.map(d => d.ano);
        const casos = data.map(d => d.casos);
        new Chart(canvas, {
          type: "line",
          data: { labels: anos, datasets: [{ label: "Casos/ano", data: casos }] },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { title: { display: true, text: "Ano" } },
              y: { title: { display: true, text: "Casos" }, beginAtZero: true },
            },
          },
        });
      }
    } catch (err) { showError("Correlação UV × Casos", err); }
  }

  // ---------- boot ----------
  document.addEventListener("DOMContentLoaded", () => {
    ensureGraphSection();
    renderHistorico();
    renderPreditivo();
    renderCorrelacao();
  });
})();
