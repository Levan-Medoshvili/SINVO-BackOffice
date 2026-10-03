'use strict';
const menu = document.querySelector('[data-menu]');
const sidebar = document.querySelector('#sidebar');
const scrim = document.querySelector('[data-close-menu]');
function closeMenu() {
  sidebar?.classList.remove('open');
  menu?.setAttribute('aria-expanded', 'false');
  if (scrim) scrim.hidden = true;
}
menu?.addEventListener('click', () => {
  const open = sidebar.classList.toggle('open');
  menu.setAttribute('aria-expanded', String(open));
  scrim.hidden = !open;
});
scrim?.addEventListener('click', closeMenu);
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); });
document.querySelectorAll('[data-language]').forEach(select => select.addEventListener('change', () => select.form.requestSubmit()));
document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
  if (!window.confirm(form.dataset.confirm)) event.preventDefault();
}));
