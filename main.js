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
  const hero    = btn.closest(".hero, .article-card");
  const expand  = hero.querySelector(".article-expand");
  const summary = hero.querySelector(".hero-summary, .card-summary");
  const foot    = hero.querySelector(".hero-foot, .card-foot");
  const isOpen  = expand.classList.contains("open");

  if (isOpen) {
    expand.classList.remove("open");
    if (summary) summary.style.display = "";
    if (foot)    foot.style.display    = "";
  } else {
    expand.classList.add("open");
    if (summary) summary.style.display = "none";
    if (foot)    foot.style.display    = "none";
    setTimeout(() => expand.scrollIntoView({ behavior: "smooth", block: "nearest" }), 50);
  }
}

function collapseThis(collapseBtn) {
  const hero    = collapseBtn.closest(".hero, .article-card");
  const expand  = hero.querySelector(".article-expand");
  const summary = hero.querySelector(".hero-summary, .card-summary");
  const foot    = hero.querySelector(".hero-foot, .card-foot");

  expand.classList.remove("open");
  if (summary) summary.style.display = "";
  if (foot)    foot.style.display    = "";
}

// -- CATEGORY FILTER --
document.querySelectorAll(".cat-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".cat-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const cat = btn.dataset.cat;

    document.querySelectorAll("[data-cat-hero]").forEach(hero => {
      hero.style.display = hero.dataset.catHero === cat ? "block" : "none";
    });

    document.querySelectorAll(".article-card").forEach(card => {
      const isSupport  = card.dataset.supportCard === "true";
      const matchesCat = cat === "all" || card.dataset.cat === cat;
      const isDupeInCat = cat !== "all" && card.dataset.isHero === "true" && card.dataset.cat === cat;
      card.style.display = (isSupport || (matchesCat && !isDupeInCat)) ? "block" : "none";
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
