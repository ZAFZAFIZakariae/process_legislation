(function() {
  const root = document.documentElement;
  const storedTheme = localStorage.getItem('theme') || 'dark';
  root.setAttribute('data-theme', storedTheme);

  // Drawer
  const drawer = document.getElementById('settings-drawer');
  const openBtn = document.getElementById('settings-button');
  const closeBtn = document.getElementById('drawer-close');
  openBtn && openBtn.addEventListener('click', () => drawer.classList.add('open'));
  closeBtn && closeBtn.addEventListener('click', () => drawer.classList.remove('open'));

  const themeSelect = document.getElementById('theme-select');
  if (themeSelect) {
    themeSelect.value = storedTheme;
    themeSelect.addEventListener('change', () => {
      const t = themeSelect.value;
      root.setAttribute('data-theme', t);
      localStorage.setItem('theme', t);
    });
  }

  // Save settings
  const form = document.getElementById('settings-form');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const formData = new FormData(form);
      await fetch('/settings', { method: 'POST', body: formData });
      drawer.classList.remove('open');
      showToast('Settings saved');
    });
  }

  // Command palette
  const palette = document.getElementById('command-palette');
  const cmdInput = document.getElementById('command-input');
  const cmdList = document.getElementById('command-list');
  const commands = [
    {name: 'Home', url: '/'},
    {name: 'Entities', url: '/entities'},
    {name: 'Structure', url: '/structure'},
    {name: 'Decision', url: '/decision'},
    {name: 'SQL', url: '/query'},
    {name: 'Legislation', url: '/legislation'},
    {name: 'Settings', action: () => drawer.classList.add('open')}
  ];
  function openPalette() {
    palette.classList.remove('hidden');
    cmdInput.value = '';
    renderCommands('');
    cmdInput.focus();
  }
  function closePalette() {
    palette.classList.add('hidden');
  }
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      if (palette.classList.contains('hidden')) openPalette(); else closePalette();
    } else if (e.key === 'Escape') {
      closePalette();
    }
  });
  function renderCommands(filter) {
    cmdList.innerHTML = '';
    commands.filter(c => c.name.toLowerCase().includes(filter.toLowerCase())).forEach(c => {
      const li = document.createElement('li');
      li.textContent = c.name;
      li.addEventListener('click', () => execute(c));
      cmdList.appendChild(li);
    });
  }
  function execute(cmd) {
    closePalette();
    if (cmd.url) window.location.href = cmd.url; else if (cmd.action) cmd.action();
  }
  cmdInput && cmdInput.addEventListener('input', () => renderCommands(cmdInput.value));
  cmdInput && cmdInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const first = cmdList.querySelector('li');
      if (first) first.click();
    }
  });

  // Toasts
  window.showToast = function(msg) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.classList.add('hide'), 10);
    setTimeout(() => toast.remove(), 3100);
  };
})();
