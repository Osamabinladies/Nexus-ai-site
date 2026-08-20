/* ---- shared motion/interaction layer, loaded on every page ---- */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- language toggle: EN by default, JA on request, remembered site-wide.
     Elements are tagged data-i18n="ns.key" (textContent) or
     data-i18n-html="ns.key" (innerHTML, for entries with nested tags) —
     see translations.js for the dictionary. ---- */
  if (window.NEXUS_I18N) {
    var LANG_KEY = "nexus-lang";
    var lang = localStorage.getItem(LANG_KEY) === "ja" ? "ja" : "en";

    var lookup = function (key) {
      var parts = key.split(".");
      var entry = NEXUS_I18N[parts[0]] && NEXUS_I18N[parts[0]][parts[1]];
      return entry ? entry[lang] : null;
    };

    var applyLang = function () {
      document.documentElement.setAttribute("lang", lang);
      document.querySelectorAll("[data-i18n]").forEach(function (el) {
        var v = lookup(el.getAttribute("data-i18n"));
        if (v != null) el.textContent = v;
      });
      document.querySelectorAll("[data-i18n-html]").forEach(function (el) {
        var v = lookup(el.getAttribute("data-i18n-html"));
        if (v != null) el.innerHTML = v;
      });
      document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
        var v = lookup(el.getAttribute("data-i18n-placeholder"));
        if (v != null) el.setAttribute("placeholder", v);
      });
      document.querySelectorAll("[data-i18n-aria-label]").forEach(function (el) {
        var v = lookup(el.getAttribute("data-i18n-aria-label"));
        if (v != null) el.setAttribute("aria-label", v);
      });
      document.querySelectorAll("[data-i18n-alt]").forEach(function (el) {
        var v = lookup(el.getAttribute("data-i18n-alt"));
        if (v != null) el.setAttribute("alt", v);
      });
      var toggle = document.getElementById("lang-toggle");
      if (toggle) {
        toggle.textContent = lang === "en" ? "JA" : "EN";
        toggle.setAttribute("aria-label", lookup("common.langToggleLabel") || "Switch language");
      }
    };

    var actions = document.querySelector(".header-actions");
    if (actions && !document.getElementById("lang-toggle")) {
      var btn = document.createElement("button");
      btn.id = "lang-toggle";
      btn.className = "lang-toggle";
      btn.type = "button";
      var navToggleEl = actions.querySelector(".nav-toggle");
      if (navToggleEl) {
        actions.insertBefore(btn, navToggleEl);
      } else {
        actions.appendChild(btn);
      }
      btn.addEventListener("click", function () {
        lang = lang === "en" ? "ja" : "en";
        localStorage.setItem(LANG_KEY, lang);
        applyLang();
      });
    }

    applyLang();
  }

  /* ---- auth state: swap the header's Log In / Sign Up links for a
     greeting + Log Out once /me confirms a session. Runs on every page,
     since the nav links are shared across all of them. ---- */
  (function () {
    var loginLink = document.querySelector('[data-auth-link="login"]');
    var signupLink = document.querySelector('[data-auth-link="signup"]');
    if (!loginLink || !signupLink) return;

    var tCommon = function (key, fallback) {
      var lang = localStorage.getItem("nexus-lang") === "ja" ? "ja" : "en";
      var entry = window.NEXUS_I18N && NEXUS_I18N.common[key];
      return entry ? entry[lang] : fallback;
    };

    fetch("/me")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.loggedIn) return;

        var userSpan = document.createElement("span");
        userSpan.className = "nav-user";
        userSpan.textContent = data.name;

        var logoutLink = document.createElement("a");
        logoutLink.href = "#";
        logoutLink.textContent = tCommon("navLogout", "Log Out");
        logoutLink.addEventListener("click", function (e) {
          e.preventDefault();
          logoutLink.textContent = tCommon("navLoggingOut", "Logging out...");
          fetch("/logout", { method: "POST" }).then(function () {
            window.location.href = "index.html";
          });
        });

        loginLink.replaceWith(userSpan);
        signupLink.replaceWith(logoutLink);
      })
      .catch(function () {});
  })();

  /* ---- header: adds a solid/blurred background once the page scrolls ---- */
  var header = document.querySelector(".site-header");
  if (header) {
    var onScrollHeader = function () {
      header.classList.toggle("scrolled", window.scrollY > 40);
    };
    onScrollHeader();
    window.addEventListener("scroll", onScrollHeader, { passive: true });
  }

  /* ---- mobile nav toggle ---- */
  var navToggle = document.querySelector(".nav-toggle");
  var siteNav = document.querySelector(".site-nav");
  if (navToggle && siteNav) {
    navToggle.addEventListener("click", function () {
      var open = siteNav.classList.toggle("open");
      navToggle.classList.toggle("open", open);
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    siteNav.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () {
        siteNav.classList.remove("open");
        navToggle.classList.remove("open");
      });
    });
  }

  /* ---- scroll reveal: fade/rise elements in as they enter the viewport ---- */
  var revealEls = document.querySelectorAll("[data-reveal]");
  if (revealEls.length) {
    if (reduceMotion || !("IntersectionObserver" in window)) {
      revealEls.forEach(function (el) { el.classList.add("in-view"); });
    } else {
      revealEls.forEach(function (el, i) {
        if (!el.style.getPropertyValue("--reveal-delay")) {
          el.style.setProperty("--reveal-delay", (i % 6) * 90 + "ms");
        }
      });
      var io = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add("in-view");
              io.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
      );
      revealEls.forEach(function (el) { io.observe(el); });
    }
  }

  /* ---- animated stat counters (about page) ---- */
  var counters = document.querySelectorAll("[data-count-to]");
  if (counters.length && !reduceMotion && "IntersectionObserver" in window) {
    var countIo = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          countIo.unobserve(entry.target);
          var el = entry.target;
          var target = parseFloat(el.getAttribute("data-count-to"));
          var suffix = el.getAttribute("data-count-suffix") || "";
          var decimals = el.getAttribute("data-count-decimals") ? parseInt(el.getAttribute("data-count-decimals"), 10) : 0;
          var duration = 1400;
          var start = null;
          function step(ts) {
            if (start === null) start = ts;
            var progress = Math.min((ts - start) / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3);
            var value = target * eased;
            el.textContent = value.toFixed(decimals) + suffix;
            if (progress < 1) requestAnimationFrame(step);
          }
          requestAnimationFrame(step);
        });
      },
      { threshold: 0.4 }
    );
    counters.forEach(function (el) { countIo.observe(el); });
  }

  /* ---- hero parallax: gradient orbs drift toward the cursor ---- */
  var heroes = document.querySelectorAll("[data-parallax]");
  if (heroes.length && !reduceMotion) {
    heroes.forEach(function (hero) {
      hero.addEventListener("pointermove", function (e) {
        var rect = hero.getBoundingClientRect();
        var mx = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
        var my = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
        hero.style.setProperty("--mx", mx.toFixed(3));
        hero.style.setProperty("--my", my.toFixed(3));
      });
      hero.addEventListener("pointerleave", function () {
        hero.style.setProperty("--mx", 0);
        hero.style.setProperty("--my", 0);
      });
    });
  }

  /* ---- hero background zoom, tied directly to scroll position: scrolling
     down zooms the scene in, scrolling back up zooms it back out. Applies to
     the home hero's skyline and the smaller page-hero banners alike. ---- */
  var zoomTargets = document.querySelectorAll(".home-bg");
  if (zoomTargets.length && !reduceMotion) {
    var zoomTicking = false;
    var updateZoom = function () {
      zoomTicking = false;
      var range = window.innerHeight * 0.9;
      var progress = Math.min(Math.max(window.scrollY / range, 0), 1);
      var zoom = (progress * 0.28).toFixed(4);
      zoomTargets.forEach(function (el) {
        el.style.setProperty("--scroll-zoom", zoom);
      });
    };
    updateZoom();
    window.addEventListener(
      "scroll",
      function () {
        if (!zoomTicking) {
          zoomTicking = true;
          requestAnimationFrame(updateZoom);
        }
      },
      { passive: true }
    );
  }

  /* ---- content-section backdrops: each section's wireframe/skyline
     background zooms in and drifts sideways as that section travels
     through the viewport, then eases back as you scroll past or back up.
     Progress is per-element (via getBoundingClientRect), not global scroll
     position, so every section gets its own fresh 0-to-1 sweep. ---- */
  var bgZoomEls = document.querySelectorAll(
    "main, .features-section, .pricing-section, .about-section"
  );
  if (bgZoomEls.length && !reduceMotion) {
    var bgTicking = false;
    var updateBgZoom = function () {
      bgTicking = false;
      var vh = window.innerHeight;
      bgZoomEls.forEach(function (el) {
        var rect = el.getBoundingClientRect();
        var total = rect.height + vh;
        var traveled = vh - rect.top;
        var progress = total > 0 ? Math.min(Math.max(traveled / total, 0), 1) : 0;
        el.style.setProperty("--scroll-zoom-2", (progress * 0.22).toFixed(4));
        el.style.setProperty("--scroll-pan-2", ((progress - 0.5) * 2).toFixed(4));
      });
    };
    updateBgZoom();
    window.addEventListener(
      "scroll",
      function () {
        if (!bgTicking) {
          bgTicking = true;
          requestAnimationFrame(updateBgZoom);
        }
      },
      { passive: true }
    );
    window.addEventListener("resize", updateBgZoom);
  }

  /* ---- glowing cursor trail (desktop pointer only) ---- */
  if (!reduceMotion && window.matchMedia("(pointer: fine)").matches) {
    var glow = document.createElement("div");
    glow.className = "cursor-glow";
    document.body.appendChild(glow);
    var gx = window.innerWidth / 2, gy = window.innerHeight / 2;
    var tx = gx, ty = gy;
    var active = false;
    window.addEventListener("pointermove", function (e) {
      tx = e.clientX;
      ty = e.clientY;
      if (!active) {
        active = true;
        glow.classList.add("visible");
      }
    });
    function raf() {
      gx += (tx - gx) * 0.15;
      gy += (ty - gy) * 0.15;
      glow.style.transform = "translate3d(" + gx + "px," + gy + "px,0)";
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);
    document.querySelectorAll("a, button, .plan-card, .feature-card").forEach(function (el) {
      el.addEventListener("pointerenter", function () { glow.classList.add("big"); });
      el.addEventListener("pointerleave", function () { glow.classList.remove("big"); });
    });
  }

  /* ---- hero title line-reveal: kick off once fonts/layout settle ---- */
  document.documentElement.classList.add("motion-ready");
})();
