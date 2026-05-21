// ── THEME ──
const html   = document.documentElement;
const toggle = document.getElementById("themeToggle");

function getSystemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  html.setAttribute("data-theme", theme);
  if (toggle) toggle.innerHTML = theme === "dark" ? "&#9728;" : "&#9790;";
  localStorage.setItem("plain-theme", theme);
}

applyTheme(localStorage.getItem("plain-theme") || getSystemTheme());

if (toggle) {
  toggle.addEventListener("click", () => {
    applyTheme(html.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });
}

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", e => {
  if (!localStorage.getItem("plain-theme")) applyTheme(e.matches ? "dark" : "light");
});

// ── CATEGORY FILTER ──
document.querySelectorAll(".cat-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".cat-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const cat = btn.dataset.cat;

    // Switch hero
    document.querySelectorAll("[data-cat-hero]").forEach(hero => {
      hero.style.display = hero.dataset.catHero === cat ? "block" : "none";
    });

    // Filter cards
    document.querySelectorAll(".article-card").forEach(card => {
      card.style.display = (cat === "all" || card.dataset.cat === cat) ? "block" : "none";
    });
  });
});

// ── COUNTDOWN TO NEXT UPDATE ──
function updateCountdown() {
  const now  = new Date();
  const next = new Date(now);
  next.setHours(now.getHours() + 1, 0, 0, 0);
  const el = document.getElementById("countdown");
  if (el) el.textContent = Math.floor((next - now) / 60000) + " min";
}
updateCountdown();
setInterval(updateCountdown, 60000);
