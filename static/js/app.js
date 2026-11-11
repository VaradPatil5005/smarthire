// A failed partial load shows a named error with a retry control. No inline scripts anywhere.
document.addEventListener("htmx:responseError", (event) => {
  const target = event.detail.target;
  target.removeAttribute("aria-busy");
  const path = event.detail.pathInfo.requestPath;
  target.textContent = "";
  const message = document.createElement("p");
  message.textContent = "This could not be loaded.";
  const retry = document.createElement("a");
  retry.href = path;
  retry.textContent = "Retry";
  retry.className = "btn btn-outline-secondary btn-sm";
  target.append(message, retry);
});

// These states follow the real request. Existing evidence remains readable until its replacement arrives.
document.addEventListener("htmx:beforeRequest", (event) => {
  const target = event.detail.target;
  if (target && target.id === "drawer") target.setAttribute("aria-busy", "true");
});
document.addEventListener("htmx:afterRequest", (event) => {
  const target = event.detail.target;
  if (target && target.id === "drawer") target.removeAttribute("aria-busy");
});

// Keyboard and phone users land on the evidence they just asked for.
document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (target.id !== "drawer") return;
  target.removeAttribute("aria-busy");
  target.focus({ preventScroll: true });
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches && target.animate) {
    target.getAnimations().forEach((animation) => animation.cancel());
    target.animate(
      [{ opacity: .35, transform: "translateY(12px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 360, easing: "cubic-bezier(.22, 1, .36, 1)" },
    );
  }
  if (window.matchMedia("(max-width: 991px)").matches) {
    target.scrollIntoView({ block: "start" });
  }
});

// Show or hide a password. The button's name changes with its state.
document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-toggle-password]");
  if (!toggle) return;
  const field = document.getElementById(toggle.dataset.togglePassword);
  const showing = field.type === "text";
  field.type = showing ? "password" : "text";
  toggle.setAttribute("aria-pressed", String(!showing));
  toggle.setAttribute("aria-label", showing ? "Show characters" : "Hide characters");
});

// A link to #section opens that folded section.
function openTargetSection() {
  if (!window.location.hash) return;
  let sectionId;
  try {
    sectionId = decodeURIComponent(window.location.hash.slice(1));
  } catch {
    // A malformed or externally supplied fragment must not break the other controls.
    return;
  }
  const target = document.getElementById(sectionId);
  if (target && target.tagName === "DETAILS") target.open = true;
}
window.addEventListener("hashchange", openTargetSection);
openTargetSection();

// Ask before a step that is awkward to undo. The server rules still apply without JavaScript.
document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

// Carry only the previous menu position across a normal page load. Links, history and
// server-rendered active state keep working when storage or animation is unavailable.
const navigationHintKey = "smarthire.navigation.previous";
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
function cancelMotionWhenReduced(event) {
  if (!event.matches) return;
  document.querySelectorAll(".pillnav-link, #drawer").forEach((node) => {
    if (node.getAnimations) node.getAnimations().forEach((animation) => animation.cancel());
  });
}
if (motionPreference.addEventListener) {
  motionPreference.addEventListener("change", cancelMotionWhenReduced);
} else if (motionPreference.addListener) {
  motionPreference.addListener(cancelMotionWhenReduced);
}
document.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  if (motionPreference.matches) return;
  const link = event.target.closest(".pillnav-link");
  if (!link || (link.target && link.target !== "_self")) return;
  const menu = link.closest(".pillnav");
  const active = menu && menu.querySelector('[aria-current="page"]');
  if (!active) return;
  try {
    window.sessionStorage.setItem(navigationHintKey, active.getAttribute("href"));
  } catch {
    // Private browsing and restrictive storage policies must not affect navigation.
  }
});

function animateCurrentNavigation() {
  let previousPath;
  try {
    previousPath = window.sessionStorage.getItem(navigationHintKey);
    window.sessionStorage.removeItem(navigationHintKey);
  } catch {
    return;
  }
  if (!previousPath || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const menu = document.querySelector(".pillnav");
  const active = menu && menu.querySelector('[aria-current="page"]');
  if (!active || !active.animate) return;
  const previous = Array.from(menu.querySelectorAll(".pillnav-link"))
    .find((link) => link.getAttribute("href") === previousPath);
  if (!previous || previous === active) return;
  menu.classList.add("nav-shifting");
  const distance = previous.getBoundingClientRect().left - active.getBoundingClientRect().left;
  active.animate(
    [{ transform: `translateX(${distance}px)` }, { transform: "translateX(0)" }],
    { duration: 420, easing: "cubic-bezier(.22, 1, .36, 1)" },
  );
}
animateCurrentNavigation();
