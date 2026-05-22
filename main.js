// -- THEME --
const html   = document.documentElement;
const toggle = document.getElementById("themeToggle");

function applyTheme(theme) {
  html.setAttribute("data-theme", theme);
  if (toggle) toggle.innerHTML = theme === "dark" ? "&#9728;" : "&#9790;";
  localStorage.setItem("plain-theme", theme);
}

// Default to light — user can toggle to dark
applyTheme(localStorage.getItem("plain-theme") || "light");

if (toggle) {
  toggle.addEventListener("click", () => {
    applyTheme(html.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });
}

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
    try {
      document.querySelectorAll(".cat-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const cat = btn.dataset.cat;

      // Switch hero sections
      document.querySelectorAll("[data-cat-hero]").forEach(hero => {
        hero.style.display = hero.dataset.catHero === cat ? "block" : "none";
      });

      // Filter article cards (skip support card)
      document.querySelectorAll(".article-card").forEach(card => {
        if (card.classList.contains("support-card")) return;
        const matchesCat  = cat === "all" || card.dataset.cat === cat;
        const isDupeInCat = cat !== "all" && card.dataset.isHero === "true" && card.dataset.cat === cat;
        card.style.display = (matchesCat && !isDupeInCat) ? "block" : "none";
      });

      // Reposition support card to 3rd visible slot
      const grid        = document.getElementById("articlesGrid");
      const supportCard = grid ? grid.querySelector(".support-card") : null;
      if (supportCard && grid) {
        const visible = Array.from(grid.querySelectorAll(".article-card:not(.support-card)"))
          .filter(c => c.style.display !== "none");
        const insertAfter = visible.length >= 2 ? visible[1] : visible[visible.length - 1];
        if (insertAfter) insertAfter.insertAdjacentElement("afterend", supportCard);
        supportCard.style.display = "block";
      }
    } catch(e) {
      console.error("Category filter error:", e);
    }
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
