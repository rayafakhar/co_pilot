/* theme-toggle.js
   Reads the saved preference from localStorage (or the OS preference if none
   is saved), applies it immediately on every page load, and wires up the
   #theme-toggle button to switch between dark and light mode.
*/
(function () {
  'use strict';

  /* ── SVG path data ── */
  const SUN_PATH =
    'M12 4.5V2m0 20v-2.5M5.64 5.64l-1.77-1.77M20.13 20.13l-1.77-1.77' +
    'M4.5 12H2m20 0h-2.5M5.64 18.36l-1.77 1.77M20.13 3.87l-1.77 1.77' +
    'M12 7a5 5 0 100 10 5 5 0 000-10z';

  const MOON_PATH =
    'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z';

  /* ── Helpers ── */
  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('northstar-theme', theme);

    // Swap the icon path
    const icon = document.getElementById('theme-icon');
    if (icon) {
      icon.innerHTML =
        '<path d="' + (theme === 'dark' ? MOON_PATH : SUN_PATH) + '"/>';
    }

    // Keep the meta color-scheme in sync so the browser chrome matches
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.setAttribute('content', theme);
  }

  /* ── 1. Apply saved or OS preference immediately (before paint) ── */
  var saved = localStorage.getItem('northstar-theme');
  if (saved === 'dark' || saved === 'light') {
    setTheme(saved);
  } else {
    // Respect the user's OS dark-mode preference as the default
    var prefersDark =
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches;
    setTheme(prefersDark ? 'dark' : 'light');
  }

  /* ── 2. Wire the button once the DOM is ready ── */
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    btn.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme');
      setTheme(current === 'dark' ? 'light' : 'dark');
    });
  });
})();
