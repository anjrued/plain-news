// -- THEME --
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

// -- EXPAND / COLLAPSE --
function toggleExpand(btn) {
  const expand = btn.closest(".hero, .article-card").querySelector(".article-expand");
  const isOpen = expand.classList.contains("open");
  if (isOpen) {
    expand.classList.remove("open");
    btn.innerHTML = "Continue reading &darr;";
  } else {
    expand.classList.add("open");
    btn.innerHTML = "Close &uarr;";
    // Smooth scroll so expanded content is visible
    setTimeout(() => expand.scrollIntoView({ behavior: "smooth", block: "nearest" }), 50);
  }
}

function collapseThis(collapseBtn) {
  const parent = collapseBtn.closest(".hero, .article-card");
  const expand = parent.querySelector(".article-expand");
  const expandBtn = parent.querySelector(".expand-btn");
  expand.classList.remove("open");
  if (expandBtn) expandBtn.innerHTML = "Continue reading &darr;";
}

// -- CATEGORY FILTER --
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

// -- COUNTDOWN --
function updateCountdown() {
  const now = new Date(), next = new Date(now);
  next.setHours(now.getHours() + 1, 0, 0, 0);
  const el = document.getElementById("countdown");
  if (el) el.textContent = Math.floor((next - now) / 60000) + " min";
}
updateCountdown();
setInterval(updateCountdown, 60000);
