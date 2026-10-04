'use strict';
(() => {
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { preference = localStorage.getItem('simplepos-appearance') || 'system'; } catch {}
  if (!['system','light','dark'].includes(preference)) preference = 'system';
  function apply() { document.documentElement.dataset.appearance = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference; }
  apply();
  system.addEventListener('change', apply);
  document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('[data-appearance]').forEach(select => {
    select.value = preference;
    select.addEventListener('change', () => {
      preference = select.value;
      try { localStorage.setItem('simplepos-appearance', preference); } catch {}
      apply();
    });
  }));
})();
