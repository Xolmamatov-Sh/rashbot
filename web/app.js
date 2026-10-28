(() => {
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    try { tg.expand(); } catch (_) {}
    try { tg.setHeaderColor?.('secondary_bg_color'); } catch (_) {}
    try { tg.setBackgroundColor?.('bg_color'); } catch (_) {}
  }

  const app = document.getElementById('app');
  const warning = document.getElementById('telegram-warning');
  const toastEl = document.getElementById('toast');
  const initData = tg?.initData || '';
  const localDemo = !initData && ['localhost', '127.0.0.1'].includes(location.hostname);
  const page = new URLSearchParams(location.search).get('page') || 'home';
  let toastTimer;

  if (localDemo) {
    warning.classList.remove('hidden');
    warning.textContent = 'Lokal sinov rejimi: Telegram ulanmagan. Bu yerda soxta profil bilan funksiyalarni sinab ko‘rishingiz mumkin.';
  } else if (!initData) {
    warning.classList.remove('hidden');
  }

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const dateStr = (unix) => unix ? new Date(unix * 1000).toLocaleString('uz-UZ') : '—';
  const normalizeOptionLabel = (option, index) => {
    const letter = String.fromCharCode(65 + index);
    return String(option).trim().toUpperCase() === letter ? '' : esc(option);
  };
  const pageTitle = {
    home: 'Asosiy menyu', check: 'Javoblarni tekshirish', results: 'Mening natijalarim',
    profile: 'Profilim', create: 'Test yaratish', finish: 'Faol testlarni yakunlash'
  }[page] || 'RASH Test';
  document.title = `${pageTitle} — RASH Test`;

  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), 3300);
  }
  function setLoading(message = 'Yuklanmoqda...') {
    app.innerHTML = `<div class="loading-card"><div class="spinner"></div><span>${esc(message)}</span></div>`;
  }
  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData, ...(options.headers || {}) };
    const response = await fetch(path, { ...options, headers });
    let payload;
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) {
      const detail = payload.detail || `So'rov bajarilmadi (${response.status})`;
      throw new Error(Array.isArray(detail) ? detail.map(x => x.msg || x).join(', ') : detail);
    }
    return payload;
  }
  function emptyState(icon, title, text) {
    return `<div class="empty-state"><div class="empty-icon">${icon}</div><strong>${esc(title)}</strong><span class="small">${esc(text)}</span></div>`;
  }
  function pageHeader(title, subtitle) {
    return `<h1 class="page-heading">${esc(title)}</h1><p class="page-subtitle">${esc(subtitle)}</p>`;
  }
  function goHome() { location.href = `${location.pathname}?page=home`; }
  function footerActions() {
    return `<div class="btn-row" style="margin-top:16px"><button class="btn btn-ghost" id="go-home">← Asosiy menyu</button></div>`;
  }
  function bindHomeButton() {
    document.getElementById('go-home')?.addEventListener('click', goHome);
  }

  async function renderHome() {
    app.innerHTML = `
      <section class="hero">
        <div class="eyebrow">Bilimingizni sinab ko'ring</div>
        <h1>RASH modeli asosidagi test platformasi</h1>
        <p>Test kodi orqali qatnashing, javoblarni yuboring va natijalaringizni bir joyda kuzating.</p>
      </section>
      <div class="section-heading"><h2>Kerakli bo'limni tanlang</h2><p>Asosiy menyu</p></div>
      <div class="menu-grid">
        <button class="menu-card" data-go="check"><span class="menu-icon">📝</span><strong>Javoblarni tekshirish</strong><small>Test kodi bilan kirish</small></button>
        <button class="menu-card" data-go="results"><span class="menu-icon">📊</span><strong>Mening natijalarim</strong><small>Ball va Rasch bahosi</small></button>
        <button class="menu-card" data-go="profile"><span class="menu-icon">👤</span><strong>Profilim</strong><small>Hisob ma'lumotlari</small></button>
        <button class="menu-card" data-go="create"><span class="menu-icon">➕</span><strong>Test yaratish</strong><small>O'qituvchi uchun</small></button>
        <button class="menu-card" data-go="finish" style="grid-column:1/-1"><span class="menu-icon">✅</span><strong>Faol testlarni yakunlash</strong><small>Testni yopish va natijalarni hisoblash</small></button>
      </div>
      <div class="info-strip">🔐 Foydalanuvchi Telegram orqali tasdiqlanadi. Test yaratish va yakunlash administrator ruxsati bilan ishlaydi.</div>`;
    app.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => {
      location.href = `${location.pathname}?page=${button.dataset.go}`;
    }));
  }

  async function renderCheck() {
    app.innerHTML = `${pageHeader('Javoblarni tekshirish', 'Test kodini kiriting va barcha savollarga javob bering.')}
      <form id="load-test-form" class="card">
        <div class="field"><label for="test-code">Test kodi</label><input id="test-code" class="input" placeholder="Masalan: 275" required autocomplete="off" maxlength="20"></div>
        <button class="btn btn-primary btn-block" type="submit">Testni ochish →</button>
      </form>
      <div id="test-area"></div>${footerActions()}`;
    bindHomeButton();
    document.getElementById('load-test-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const code = document.getElementById('test-code').value.trim();
      const area = document.getElementById('test-area');
      area.innerHTML = `<div class="loading-card"><div class="spinner"></div><span>Test topilmoqda...</span></div>`;
      try {
        const test = await api(`/api/tests/by-code/${encodeURIComponent(code)}`);
        area.innerHTML = `<div class="section-heading"><h2>${esc(test.title)}</h2><span class="status status-active">Faol</span></div>
          <div class="info-strip">Kod: <strong>${esc(test.code)}</strong> · ${test.questions.length} ta savol · Javobni bir marta yuborish mumkin.</div>
          <form id="answer-form"><div id="question-list"></div><button type="submit" class="btn btn-primary btn-block">Javoblarni yuborish ✓</button></form>`;
        const list = document.getElementById('question-list');
        test.questions.forEach((question) => {
          let answerControl = '';
          if (question.kind === 'mcq') {
            answerControl = `<div class="option-list">${question.options.map((option, index) => `
              <label class="option"><input required type="radio" name="q-${question.id}" value="${esc(option)}"><span><b>${String.fromCharCode(65 + index)}.</b> ${normalizeOptionLabel(option, index)}</span></label>`).join('')}</div>`;
          } else {
            answerControl = `<input class="input" name="q-${question.id}" required placeholder="Javobingizni kiriting" autocomplete="off">`;
          }
          list.insertAdjacentHTML('beforeend', `<section class="card question-card"><div class="question-top">${question.position}-savol</div><p class="question-text">${esc(question.text)}</p>${answerControl}</section>`);
        });
        document.getElementById('answer-form').addEventListener('submit', async (submitEvent) => {
          submitEvent.preventDefault();
          const button = submitEvent.currentTarget.querySelector('button[type="submit"]');
          button.disabled = true; button.textContent = 'Javoblar yuborilmoqda...';
          const answers = test.questions.map(q => {
            const field = submitEvent.currentTarget.elements[`q-${q.id}`];
            let value = '';
            if (field instanceof RadioNodeList) value = field.value;
            else if (field && field.length && field[0]?.type === 'radio') value = [...field].find(el => el.checked)?.value || '';
            else value = field?.value || '';
            return { question_id: q.id, answer: value };
          });
          try {
            const result = await api('/api/submit', { method: 'POST', body: JSON.stringify({ code: test.code, answers }) });
            area.innerHTML = `<section class="card"><div class="eyebrow" style="color:var(--muted)">Javoblar qabul qilindi</div><h2 style="margin:8px 0">${esc(result.title)}</h2>
              <div class="result-score">${result.raw_score}/${result.total_questions}</div><div class="muted small">To'g'ri javoblar soni</div>
              <div class="result-metrics"><div class="metric"><span>Foiz</span><strong>${result.percent}%</strong></div><div class="metric"><span>Rasch theta</span><strong>Keyinroq</strong></div></div>
              <p class="small muted">${esc(result.message)} Foiz — oddiy to'g'ri javoblar ulushi; bu hali rasmiy sertifikat balli emas.</p>
              <button class="btn btn-primary btn-block" id="see-results">Mening natijalarim</button></section>`;
            document.getElementById('see-results').addEventListener('click', () => location.href = `${location.pathname}?page=results`);
          } catch (error) { toast(error.message); button.disabled = false; button.textContent = 'Javoblarni yuborish ✓'; }
        });
      } catch (error) {
        area.innerHTML = '';
        toast(error.message);
      }
    });
  }

  async function renderResults() {
    setLoading();
    try {
      const rows = await api('/api/results');
      app.innerHTML = `${pageHeader('Mening natijalarim', 'Topshirgan testlaringiz va hisoblangan natijalar.')}
        ${rows.length ? `<section class="card">${rows.map(row => `<div class="list-row"><div><h3>${esc(row.title)}</h3><p>Kod: ${esc(row.code)} · ${dateStr(row.submitted_at)}</p><p>${row.raw_score}/${row.total_questions} to'g'ri javob · ${row.percent}%</p>${row.theta !== null ? `<p>Rasch theta: <b>${Number(row.theta).toFixed(3)}</b></p>` : `<p>Rasch theta: test yakunlangandan so'ng chiqadi</p>`}</div><span class="status ${row.status === 'active' ? 'status-active' : 'status-closed'}">${row.status === 'active' ? 'Faol' : 'Yopilgan'}</span></div>`).join('')}</section>` : emptyState('📊', 'Hozircha natija yo‘q', 'Test kodini olib, birinchi testingizni topshiring.')}
        ${footerActions()}`;
      bindHomeButton();
    } catch (error) { app.innerHTML = `${pageHeader('Mening natijalarim', 'Natijalarni yuklashda xatolik.') }<div class="card">${esc(error.message)}</div>${footerActions()}`; bindHomeButton(); }
  }

  async function renderProfile() {
    setLoading();
    try {
      const profile = await api('/api/profile');
      const fullName = [profile.first_name, profile.last_name].filter(Boolean).join(' ') || 'Telegram foydalanuvchisi';
      app.innerHTML = `${pageHeader('Profilim', 'Telegram hisobingiz bo‘yicha ma’lumotlar.')}
        <section class="card"><div class="menu-icon" style="width:58px;height:58px;font-size:27px">👤</div><h2 style="margin:5px 0 2px">${esc(fullName)}</h2><p class="muted">${profile.username ? '@' + esc(profile.username) : 'Username ko‘rsatilmagan'}</p>
          <div class="result-metrics"><div class="metric"><span>Telegram ID</span><strong style="font-size:14px">${esc(profile.id)}</strong></div><div class="metric"><span>Topshirilgan testlar</span><strong>${profile.attempts}</strong></div></div>
          <p class="small muted">Ruxsat darajasi: <b>${profile.is_admin ? 'Administrator / o‘qituvchi' : 'Ishtirokchi'}</b></p>
        </section>${footerActions()}`;
      bindHomeButton();
    } catch (error) { app.innerHTML = `${pageHeader('Profilim', 'Profilni yuklashda xatolik.') }<div class="card">${esc(error.message)}</div>${footerActions()}`; bindHomeButton(); }
  }

  function questionEditor(number) {
    return `<section class="question-editor" data-question-editor>
      <div class="question-editor-header"><strong>${number}-savol</strong><button type="button" class="btn btn-ghost remove-question" style="min-height:30px;padding:4px 8px">O'chirish</button></div>
      <div class="field"><label>Savol matni</label><textarea class="textarea q-text" required placeholder="Savol matnini kiriting..."></textarea></div>
      <div class="field"><label>Savol turi</label><select class="select q-kind"><option value="mcq">Variantli (A/B/C/D)</option><option value="short">Yozma javob</option></select></div>
      <div class="field q-options-wrap"><label>Javob variantlari (har birini yangi qatordan yozing)</label><textarea class="textarea q-options" placeholder="A\nB\nC\nD">A\nB\nC\nD</textarea></div>
      <div class="field"><label>To'g'ri javob (variant matni yoki yozma javob)</label><input class="input q-correct" value="A" required placeholder="A"></div>
      <p class="small muted">Rasch qiyinligi test javoblari yig'ilib, test yopilganda baholanadi.</p>
    </section>`;
  }

  async function renderCreate() {
    try {
      const profile = await api('/api/profile');
      if (!profile.is_admin) {
        app.innerHTML = `${pageHeader('Test yaratish', 'Bu bo‘lim o‘qituvchi/administrator uchun.')}
          <section class="card"><div class="menu-icon">🔒</div><h3>Ruxsat kerak</h3><p class="muted small">Telegram ID: <b>${esc(profile.id)}</b>. Shu ID ni serverdagi <code>ADMIN_IDS</code> sozlamasiga qo‘shing, so‘ng botni qayta ishga tushiring.</p><button class="btn btn-secondary" id="copy-id">ID ni nusxalash</button></section>${footerActions()}`;
        document.getElementById('copy-id').addEventListener('click', async () => { try { await navigator.clipboard.writeText(String(profile.id)); toast('ID nusxalandi'); } catch (_) { toast(`Telegram ID: ${profile.id}`); } });
        bindHomeButton(); return;
      }
      app.innerHTML = `${pageHeader('Test yaratish', 'Test savollarini kiriting. Test kodi avtomatik yaratiladi.')}
        <form id="create-test-form">
          <section class="card"><div class="field"><label for="test-title">Test nomi</label><input id="test-title" class="input" required maxlength="200" placeholder="Masalan: Matematika MOCK-01"></div></section>
          <div class="section-heading"><h2>Savollar</h2><p id="question-count">1 ta savol</p></div>
          <div id="editor-list">${questionEditor(1)}</div>
          <button id="add-question" type="button" class="btn btn-secondary btn-block" style="margin-bottom:12px">＋ Savol qo'shish</button>
          <button type="submit" class="btn btn-primary btn-block">Testni yaratish ✓</button>
        </form>${footerActions()}`;
      bindHomeButton();
      const editorList = document.getElementById('editor-list');
      const addButton = document.getElementById('add-question');
      function refreshEditors() {
        const all = [...editorList.querySelectorAll('[data-question-editor]')];
        all.forEach((el, i) => { el.querySelector('.question-editor-header strong').textContent = `${i + 1}-savol`; el.querySelector('.remove-question').disabled = all.length === 1; });
        document.getElementById('question-count').textContent = `${all.length} ta savol`;
      }
      function attachEditor(editor) {
        editor.querySelector('.remove-question').addEventListener('click', () => { editor.remove(); refreshEditors(); });
        editor.querySelector('.q-kind').addEventListener('change', (event) => {
          const isMcq = event.target.value === 'mcq';
          editor.querySelector('.q-options-wrap').classList.toggle('hidden', !isMcq);
          editor.querySelector('.q-correct').placeholder = isMcq ? 'A' : 'Masalan: 12';
          if (!isMcq) editor.querySelector('.q-correct').value = '';
          else if (!editor.querySelector('.q-correct').value) editor.querySelector('.q-correct').value = 'A';
        });
      }
      attachEditor(editorList.querySelector('[data-question-editor]'));
      addButton.addEventListener('click', () => {
        editorList.insertAdjacentHTML('beforeend', questionEditor(editorList.children.length + 1));
        attachEditor(editorList.lastElementChild); refreshEditors();
      });
      document.getElementById('create-test-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true; button.textContent = 'Test yaratilmoqda...';
        const questions = [...editorList.querySelectorAll('[data-question-editor]')].map(editor => {
          const kind = editor.querySelector('.q-kind').value;
          return {
            text: editor.querySelector('.q-text').value.trim(), kind,
            options: kind === 'mcq' ? editor.querySelector('.q-options').value.split('\n').map(x => x.trim()).filter(Boolean) : [],
            correct_answer: editor.querySelector('.q-correct').value.trim()
          };
        });
        try {
          const created = await api('/api/tests', { method: 'POST', body: JSON.stringify({ title: document.getElementById('test-title').value.trim(), questions }) });
          app.innerHTML = `${pageHeader('Test yaratildi!','Test ishtirokchilarga yuborish uchun tayyor.')}
            <section class="card"><div class="menu-icon">✅</div><h2 style="margin:0 0 4px">${esc(created.title)}</h2><p class="muted small">Test kodi</p><div class="result-score" id="created-code">${esc(created.code)}</div><p class="muted small">${created.questions} ta savol · Ishtirokchilar shu kodni kiritib testni ochadi.</p>
            <div class="btn-row"><button class="btn btn-primary" id="copy-code">Kodni nusxalash</button><button class="btn btn-secondary" id="view-tests">Testlarim</button></div></section>${footerActions()}`;
          document.getElementById('copy-code').addEventListener('click', async () => { try { await navigator.clipboard.writeText(String(created.code)); toast('Test kodi nusxalandi'); } catch (_) { toast(`Test kodi: ${created.code}`); } });
          document.getElementById('view-tests').addEventListener('click', () => location.href = `${location.pathname}?page=finish`);
          bindHomeButton();
        } catch (error) { toast(error.message); button.disabled = false; button.textContent = 'Testni yaratish ✓'; }
      });
    } catch (error) {
      app.innerHTML = `${pageHeader('Test yaratish', 'Bo‘limni ochishda xatolik.') }<section class="card">${esc(error.message)}</section>${footerActions()}`; bindHomeButton();
    }
  }

  async function renderFinish() {
    setLoading();
    try {
      const profile = await api('/api/profile');
      if (!profile.is_admin) {
        app.innerHTML = `${pageHeader('Faol testlarni yakunlash', 'Bu bo‘lim o‘qituvchi/administrator uchun.')}
          <section class="card"><div class="menu-icon">🔒</div><h3>Ruxsat kerak</h3><p class="small muted">Telegram ID: <b>${esc(profile.id)}</b>. Serverdagi <code>ADMIN_IDS</code> ro'yxatiga qo'shing.</p></section>${footerActions()}`; bindHomeButton(); return;
      }
      const tests = await api('/api/tests/mine');
      app.innerHTML = `${pageHeader('Testlarni boshqarish', 'Faol testni yoping va to‘plangan javoblardan Rasch bahosini hisoblang.')}
        ${tests.length ? `<div id="tests-list">${tests.map(test => `<section class="card" data-test-id="${test.id}"><div class="list-row" style="padding-top:0"><div><h3>${esc(test.title)}</h3><p>Kod: <b>${esc(test.code)}</b></p><p>${test.question_count} ta savol · ${test.participant_count} ta ishtirokchi</p><p class="small">Yaratilgan: ${dateStr(test.created_at)}</p></div><span class="status ${test.status === 'active' ? 'status-active' : 'status-closed'}">${test.status === 'active' ? 'Faol' : 'Yopilgan'}</span></div>
          <div class="btn-row" style="margin-top:12px">${test.status === 'active' ? `<button class="btn btn-danger close-test" data-id="${test.id}">Testni yakunlash</button>` : ''}<button class="btn btn-secondary show-test-results" data-id="${test.id}">Natijalar / javoblar</button></div><div class="test-detail" id="detail-${test.id}"></div></section>`).join('')}</div>` : emptyState('➕','Hali test yaratilmadi','Avval “Test yaratish” bo‘limidan test yarating.')}
        <div class="info-strip">Eslatma: Rasch parametrlarini ishonchli kalibrlash uchun yetarli va xilma-xil javoblar kerak. Juda kam ishtirokchi bo‘lsa, parametrlar beqaror bo‘lishi mumkin.</div>${footerActions()}`;
      bindHomeButton();
      document.querySelectorAll('.close-test').forEach(button => button.addEventListener('click', async () => {
        const id = button.dataset.id;
        if (!confirm('Testni yakunlaysizmi? Ishtirokchilar bundan keyin javob yubora olmaydi.')) return;
        button.disabled = true; button.textContent = 'Hisoblanmoqda...';
        try {
          const outcome = await api(`/api/tests/${id}/close`, { method: 'POST', body: '{}' });
          toast(outcome.calibration_warning ? `Test yopildi. Ishtirokchilar: ${outcome.participants}. Kalibrlash uchun namuna kichik.` : `Test yopildi. Ishtirokchilar: ${outcome.participants}.`);
          await renderFinish();
        } catch (error) { toast(error.message); button.disabled = false; button.textContent = 'Testni yakunlash'; }
      }));
      document.querySelectorAll('.show-test-results').forEach(button => button.addEventListener('click', async () => {
        const detail = document.getElementById(`detail-${button.dataset.id}`);
        if (!detail.classList.contains('hidden') && detail.innerHTML) { detail.classList.add('hidden'); return; }
        detail.classList.remove('hidden'); detail.innerHTML = `<div class="loading-card" style="margin-top:12px"><div class="spinner"></div><span>Javoblar olinmoqda...</span></div>`;
        try {
          const data = await api(`/api/tests/${button.dataset.id}/responses`);
          detail.innerHTML = `<h3 style="margin-top:16px">Ishtirokchilar (${data.participants.length})</h3>
            ${data.calibration_warning ? `<p class="small muted">Namuna 30 kishidan kam. Qiyinlik va theta baholarini ehtiyotkorlik bilan talqin qiling.</p>` : ''}
            ${data.participants.length ? `<div class="table-scroll"><table><thead><tr><th>Ishtirokchi</th><th>Ball</th><th>%</th><th>Theta</th></tr></thead><tbody>${data.participants.map(p => `<tr><td>${esc([p.first_name,p.last_name].filter(Boolean).join(' ') || p.username || p.user_id)}</td><td>${p.raw_score}/${p.total_questions}</td><td>${p.percent}%</td><td>${p.theta == null ? '—' : Number(p.theta).toFixed(3)}</td></tr>`).join('')}</tbody></table></div>` : `<p class="small muted">Hali javob topshirilmagan.</p>`}
            <h3 style="margin-top:18px">Savol qiyinliklari</h3><div class="table-scroll"><table><thead><tr><th>№</th><th>Savol</th><th>Difficulty (b)</th></tr></thead><tbody>${data.questions.map(q => `<tr><td>${q.position}</td><td>${esc(q.text)}</td><td>${q.difficulty == null ? 'Test yopilgach hisoblanadi' : Number(q.difficulty).toFixed(3)}</td></tr>`).join('')}</tbody></table></div>`;
        } catch (error) { detail.innerHTML = `<p class="small">${esc(error.message)}</p>`; }
      }));
    } catch (error) {
      app.innerHTML = `${pageHeader('Testlarni boshqarish', 'Ro‘yxatni yuklashda xatolik.') }<section class="card">${esc(error.message)}</section>${footerActions()}`; bindHomeButton();
    }
  }

  (async () => {
    const renderers = { home: renderHome, check: renderCheck, results: renderResults, profile: renderProfile, create: renderCreate, finish: renderFinish };
    try { await (renderers[page] || renderHome)(); }
    catch (error) { app.innerHTML = `<section class="card"><h2>Xatolik</h2><p>${esc(error.message)}</p></section>`; }
  })();
})();
