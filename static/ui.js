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

  // Sidebar toggle for mobile
  const menuBtn = document.getElementById('menu-button');
  const sidebar = document.getElementById('sidebar');
  menuBtn && sidebar && menuBtn.addEventListener('click', () => sidebar.classList.toggle('open'));

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

  const syncForm = document.getElementById('sync-db-form');
  if (syncForm) {
    syncForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const resp = await fetch('/sync_db', { method: 'POST' });
      const msg = await resp.text();
      showToast(msg);
    });
  }

  // Command palette
  const palette = document.getElementById('command-palette');
  const cmdInput = document.getElementById('command-input');
  const cmdList = document.getElementById('command-list');
  const commands = [
    {name: 'Home', url: '/'},
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

  // Help modal
  const helpBtn = document.getElementById('help-button');
  const helpModal = document.getElementById('help-modal');
  const helpClose = document.getElementById('help-close');
  helpBtn && helpModal && helpBtn.addEventListener('click', () => helpModal.classList.remove('hidden'));
  helpClose && helpModal && helpClose.addEventListener('click', () => helpModal.classList.add('hidden'));
  helpModal && helpModal.addEventListener('click', (e) => { if (e.target === helpModal) helpModal.classList.add('hidden'); });

  // File drag and drop
  const dropZone = document.getElementById('upload-drop');
  const fileInput = document.getElementById('file-input');
  if (dropZone && fileInput) {
    showToast('Step 1: Drag & drop a file or click to browse.');
    setTimeout(() => showToast('Step 1: Alternatively, enter an SQL query below.'), 3500);
    ['dragenter','dragover'].forEach(ev => dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.add('hover'); }));
    ['dragleave','drop'].forEach(ev => dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.remove('hover'); }));
    dropZone.addEventListener('drop', e => {
      fileInput.files = e.dataTransfer.files;
      fileInput.dispatchEvent(new Event('change'));
    });
    dropZone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', () => {
      const msg = fileInput.files.length
        ? `File uploaded: ${fileInput.files[0].name}`
        : 'Drag & drop file here or click to browse';
      const p = dropZone.querySelector('p');
      if (p) p.textContent = msg;
    });
    fileInput.addEventListener('change', () => showToast('Step 2: Adjust options then press "Upload & Process".'), { once: true });
    const processForm = fileInput.closest('form');
    processForm && processForm.addEventListener('submit', () => showToast('Uploading file...'));
  }

  // SQL query guidance
  const queryFormInput = document.querySelector('input[name="action"][value="query"]');
  const queryForm = queryFormInput ? queryFormInput.closest('form') : null;
  if (queryForm) {
    const sqlArea = queryForm.querySelector('textarea[name="sql"]');
    sqlArea && sqlArea.addEventListener('focus', () => showToast('Step 1: Enter an SQL query, then press "Run Query".'), { once: true });
    queryForm.addEventListener('submit', () => showToast('Running query...'));
  }
})();
