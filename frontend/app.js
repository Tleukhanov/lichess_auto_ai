// Federation Board — vanilla JS, те же классы что Chess Trainer (без разрыва).

const state = { view: 'top', board: null, speed: 'overall' };

// --- API ---

async function api(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

// --- Тема (как в тренере) ---

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.querySelector('[data-theme-toggle]');
  if (btn) btn.textContent = theme === 'dark' ? '☀' : '☾';
}

function setupTheme() {
  let theme = 'light';
  try { if (localStorage.getItem('theme') === 'dark') theme = 'dark'; } catch { /* приватный режим */ }
  applyTheme(theme);
  document.querySelector('[data-theme-toggle]').addEventListener('click', () => {
    theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(theme);
    try { localStorage.setItem('theme', theme); } catch { /* приватный режим */ }
  });
}

// --- Навигация ---

const views = ['top', 'tournaments', 'activity'];

function navigate(view) {
  if (!views.includes(view)) view = 'top';
  state.view = view;
  document.querySelectorAll('#nav a').forEach((link) => {
    link.classList.toggle('active', link.dataset.view === view);
  });
  render();
}

function setupNav() {
  document.querySelectorAll('[data-view]').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      navigate(link.dataset.view);
    });
  });
}

// --- Вьюхи ---

const SPEED_NAMES = { rapid: 'Рапид', blitz: 'Блиц', bullet: 'Пуля', overall: 'Общий' };

async function renderTop(app) {
  if (!state.board) {
    try {
      state.board = await api('/api/month');
    } catch {
      app.innerHTML = '<div class="alert alert-error">Нет связи с API.</div>';
      return;
    }
  }
  const board = state.board;
  const speeds = ['overall', 'rapid', 'blitz', 'bullet'].filter((key) => (board[key] || []).length);
  if (!speeds.length) {
    app.innerHTML = '<div class="card"><div class="card-title">Топ месяца</div><p>В этом месяце пока пусто — играйте турниры!</p></div>';
    return;
  }
  if (!board[state.speed] || !board[state.speed].length) state.speed = speeds[0];
  const rows = (board[state.speed] || [])
    .map(([nick, points], i) => `<tr><td>${i + 1}</td><td>${nick}</td><td>${points}</td></tr>`)
    .join('');
  const tabs = speeds
    .map((key) => `<button class="btn btn-secondary${key === state.speed ? ' btn-active' : ''}" data-speed="${key}">${SPEED_NAMES[key]}</button>`)
    .join(' ');
  app.innerHTML = `
    <h1>Топ месяца</h1>
    <p>${tabs}</p>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Игрок</th><th>Очки</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div></div>`;
  app.querySelectorAll('[data-speed]').forEach((btn) => {
    btn.addEventListener('click', () => { state.speed = btn.dataset.speed; render(); });
  });
}

async function renderTournaments(app) {
  let items = [];
  try {
    items = await api('/api/tournaments');
  } catch {
    app.innerHTML = '<div class="alert alert-error">Нет связи с API.</div>';
    return;
  }
  if (!items.length) {
    app.innerHTML = '<div class="card"><div class="card-title">Турниры</div><p>Пока пусто.</p></div>';
    return;
  }
  const cards = items.map((item) => {
    const top = (item.top || []).map((row) => `${row.rank}. ${row.nick} (${row.score})`).join('<br>');
    const pinned = item.is_need ? ' <span class="badge badge-good">Рекомендую</span>' : '';
    return `<div class="card">
      <div class="card-header"><span class="card-title"><a href="${item.link}" target="_blank" rel="noopener">${item.name}</a>${pinned}</span>
      <span class="badge badge-blue">${item.clock}</span></div>
      <div>Участников: ${item.nb_players}</div>
      <div>${top || 'Результатов пока нет'}</div>
    </div>`;
  }).join('');
  app.innerHTML = `<h1>Турниры</h1><div class="grid">${cards}</div>
    <p><button class="btn btn-secondary" id="past-btn">Прошедшие турниры</button></p>
    <div id="past-list"></div>`;
  app.querySelector('#past-btn').addEventListener('click', async (event) => {
    const list = app.querySelector('#past-list');
    const btn = event.currentTarget;
    if (list.dataset.loaded) {
      const hidden = list.style.display === 'none';
      list.style.display = hidden ? '' : 'none';
      btn.textContent = hidden ? 'Скрыть прошедшие' : 'Прошедшие турниры';
      return;
    }
    const past = await api('/api/tournaments?past=true');
    list.dataset.loaded = '1';
    list.innerHTML = past.length
      ? past.map((item) => `<div class="card">
          <div class="card-header"><span class="card-title"><a href="${item.link}" target="_blank" rel="noopener">${item.name}</a></span></div>
          <div>Участников: ${item.nb_players}</div>
        </div>`).join('')
      : '<p>Прошедших пока нет.</p>';
    btn.textContent = 'Скрыть прошедшие';
  });
}

const TIER_BADGE = { core: 'badge-good', regular: 'badge-blue', casual: 'badge-neutral', dormant: 'badge-bad' };

async function renderActivity(app) {
  let members = [];
  try {
    members = await api('/api/activity');
  } catch {
    app.innerHTML = '<div class="alert alert-error">Нет связи с API.</div>';
    return;
  }
  const rows = members.map((member) => {
    const badge = TIER_BADGE[member.tier] || 'badge-neutral';
    const active = member.is_active ? '<span class="badge badge-good">active</span>' : '';
    return `<tr><td>${member.nick}</td><td>${member.rapid ?? '—'}</td><td>${member.blitz ?? '—'}</td><td>${member.bullet ?? '—'}</td><td><span class="badge ${badge}">${member.tier}</span> ${active}</td></tr>`;
  }).join('');
  app.innerHTML = `<h1>Клубная активность</h1>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>Игрок</th><th>Rapid</th><th>Blitz</th><th>Bullet</th><th>Тир</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div></div>`;
}

function render() {
  const app = document.getElementById('app');
  if (state.view === 'tournaments') return renderTournaments(app);
  if (state.view === 'activity') return renderActivity(app);
  return renderTop(app);
}

setupTheme();
setupNav();
navigate('top');
