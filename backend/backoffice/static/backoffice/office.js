'use strict';
const category = document.querySelector('#id_category');
const subcategory = document.querySelector('#id_subcategory');
if (category && subcategory) {
  function filterSubcategories() {
    for (const option of subcategory.options) {
      const available = !option.value || option.dataset.parent === category.value;
      option.hidden = !available; option.disabled = !available;
    }
  }
  filterSubcategories();
  category.addEventListener('change', () => {
    filterSubcategories();
    if (subcategory.selectedOptions[0]?.disabled) subcategory.value = '';
  });
}
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
if (document.querySelector('[data-live-refresh]')) setInterval(() => {
  if (document.hidden || document.activeElement?.matches('input,select,textarea') ||
      [...document.querySelectorAll('.removal-form input[name="reason"]')].some(input => input.value)) return;
  window.location.reload();
}, 10000);
document.querySelector('.branch-picker select')?.addEventListener('change', event => { if (event.target.value) event.target.form.requestSubmit(); });
