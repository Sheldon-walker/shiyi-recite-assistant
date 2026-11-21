/* ===========================================================
   拾忆 · WebView2 版前端逻辑
   ===========================================================
   所有业务数据都来自 Python 的 window.pywebview.api；
   这里只负责渲染、表单交互、弹窗和快捷键。
   =========================================================== */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const contentEl = $('#content');
const modalLayer = $('#modal-layer');
const toastHost = $('#toast-host');
const appearanceSelect = $('#appearance-select');

let state = null;
let currentView = 'today';
let appearancePreference = 'system';
let warningShown = false;
let previewTimer = null;
let typeFilter = '全部';
let planSearch = '';
// 解析面板的展开状态按内容 id 记住，重新渲染后仍然保持。
const expandedAnalyses = new Set();
// 划词引用：按内容 id 暂存，发送后清空。
const pendingQuotes = new Map();
// 正在编辑的用户消息：值为消息序号，发送后清除其后的对话。
const pendingEdits = new Map();

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

const EBBINGHAUS_INTERVALS = [1, 2, 4, 7, 15, 30, 60, 120, 240, 365, 730, 1095, 1825, 3650];
const MAX_INTERVAL_DAY = 3650;
const MAX_NODES = 10;
const DEFAULT_INTERVALS = ['1', '2', '4', '7', '15'];

/* ---------------- 基础工具 ---------------- */

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);
}

async function call(name, ...args) {
  if (!window.pywebview || !window.pywebview.api) {
    throw new Error('WebView2 接口尚未就绪');
  }
  return await window.pywebview.api[name](...args);
}

function todayIso() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function showToast(message, kind = 'success') {
  if (!message) return;
  const dot = kind === 'success' ? '✓' : '●';
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = `<span class="toast-dot">${dot}</span><span>${esc(message)}</span>`;
  // 与旧版一致：同一时间只显示一条提示。
  toastHost.replaceChildren(el);
  window.setTimeout(() => el.remove(), 3000);
}

function applyTheme() {
  const resolved = appearancePreference === 'system'
    ? (darkQuery.matches ? 'dark' : 'light')
    : appearancePreference;
  document.documentElement.dataset.theme = resolved;
  appearanceSelect.value = appearancePreference;
}

darkQuery.addEventListener('change', () => {
  if (appearancePreference === 'system') applyTheme();
});

/* ---------------- 渲染 ---------------- */

function renderSidebar() {
  const { stats } = state;
  const progress = $('#side-progress');
  progress.innerHTML = `
    <div class="side-card-title"><span>今日进度</span><strong>${stats.percent}%</strong></div>
    <div class="side-card-ratio">${stats.completed} / ${stats.total}</div>
    <div class="progress-track"><div class="progress-fill ${stats.total && stats.pending === 0 ? 'green' : ''}" style="width:${stats.percent}%"></div></div>
    <div class="side-card-detail">${esc(stats.detail)}</div>`;

  const save = $('#save-status');
  save.textContent = state.saveStatus.text;
  save.classList.toggle('failed', !state.saveStatus.ok);
}

function renderHeader() {
  const isToday = currentView === 'today';
  $('#page-title').textContent = isToday ? '今日复习' : '全部计划';
  $('#page-subtitle').textContent = isToday
    ? '在遗忘发生前，再记一次。'
    : '所有背诵内容与完整的复习时间轴，按添加时间排列。';
  $$('#side-nav .nav-item').forEach((button) => {
    button.classList.toggle('active', button.dataset.view === currentView);
  });
}

function renderHero() {
  const { stats, today } = state;
  let title, subtitle;
  if (stats.pending > 0) {
    title = `今天还有 ${stats.pending} 项复习`;
    subtitle = '不用贪多，按计划完成几项，记忆就会更牢。';
  } else if (stats.completed > 0) {
    title = '今天的复习已完成';
    subtitle = '每一次按时回顾，都在给长期记忆加固。';
  } else {
    title = '今天还没有复习安排';
    subtitle = '添加一项背诵内容，让遗忘曲线替你安排时间。';
  }
  return `
    <section class="hero">
      <div class="hero-left">
        <div class="hero-eyebrow">TODAY · ${esc(today.monthDay)}</div>
        <h2 class="hero-title">${esc(title)}</h2>
        <p class="hero-subtitle">${esc(subtitle)}</p>
      </div>
      <div class="hero-right">
        <span class="hero-right-title">今日进度</span>
        <span class="hero-right-percent">${stats.percent}%</span>
        <div class="hero-right-ratio">${stats.completed} / ${stats.total} 项</div>
        <div class="progress-track"><div class="progress-fill ${stats.total && stats.pending === 0 ? 'green' : ''}" style="width:${stats.percent}%"></div></div>
      </div>
    </section>`;
}

function formatAnalysisTime(value) {
  const text = String(value || '');
  return text ? text.slice(0, 16).replace('T', ' ') : '';
}

/* AI 返回的是 Markdown，这里做一个极简渲染：先整体转义，再还原粗体、标题和列表。 */
function inlineMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function renderMarkdown(text) {
  const lines = esc(text).split(/\r?\n/);
  const html = [];
  let inList = false;
  const closeList = () => {
    if (inList) {
      html.push('</ul>');
      inList = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/, '');
    if (!line.trim()) {
      closeList();
      continue;
    }
    const heading = line.match(/^\s*#{1,6}\s+(.+)$/);
    if (heading) {
      closeList();
      html.push(`<h4 class="md-heading">${inlineMarkdown(heading[1])}</h4>`);
      continue;
    }
    const boldOnly = line.match(/^\s*\*\*(.+?)\*\*\s*[:：]?\s*$/);
    if (boldOnly) {
      closeList();
      html.push(`<h4 class="md-heading">${inlineMarkdown(boldOnly[1])}</h4>`);
      continue;
    }
    const bullet = line.match(/^\s*[-*+]\s+(.+)$/);
    if (bullet) {
      if (!inList) {
        html.push('<ul class="md-list">');
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }
    const ordered = line.match(/^\s*\d+[.、)）]\s+(.+)$/);
    if (ordered) {
      if (!inList) {
        html.push('<ul class="md-list">');
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(ordered[1])}</li>`);
      continue;
    }
    closeList();
    html.push(`<p class="md-p">${inlineMarkdown(line)}</p>`);
  }

  closeList();
  return html.join('');
}

function analysisMessages(analysis) {
  if (Array.isArray(analysis.messages) && analysis.messages.length) {
    return analysis.messages;
  }
  return [{ role: 'assistant', content: String(analysis.text || '') }];
}

function analysisPanelHtml(id, analysis) {
  if (!analysis || !analysis.text) return '';
  const open = expandedAnalyses.has(id);
  const meta = [analysis.model || 'DeepSeek', formatAnalysisTime(analysis.createdAt)]
    .filter(Boolean).map(esc).join(' · ');
  const messages = analysisMessages(analysis);
  const quote = pendingQuotes.get(id) || '';
  const editIndex = pendingEdits.get(id);
  const messageHtml = messages.map((msg, index) => {
    const isUser = msg.role === 'user';
    return `
    <div class="chat-row ${isUser ? 'user' : 'assistant'}" data-msg-role="${esc(msg.role)}" data-index="${index}">
      <div class="chat-msg ${isUser ? 'user' : 'assistant'}">
        ${msg.quote ? `<div class="chat-quote">${esc(msg.quote)}</div>` : ''}
        <div class="chat-content">${renderMarkdown(msg.content)}</div>
      </div>
      <div class="msg-actions">
        ${isUser
          ? `<button class="msg-action" type="button" data-action="msg-edit" data-id="${esc(id)}" data-index="${index}">编辑</button>
             <button class="msg-action danger" type="button" data-action="msg-delete" data-id="${esc(id)}" data-index="${index}">删除</button>`
          : `<button class="msg-action" type="button" data-action="msg-regenerate" data-id="${esc(id)}" data-index="${index}">重新生成</button>
             <button class="msg-action danger" type="button" data-action="clear-analysis" data-id="${esc(id)}">清除缓存</button>`}
      </div>
    </div>`;
  }).join('');

  return `
    <div class="analysis-card ${open ? 'open' : ''}" data-analysis-id="${esc(id)}">
      <button class="analysis-head" type="button" data-action="toggle-analysis" data-id="${esc(id)}" aria-expanded="${open}">
        <span class="analysis-title">AI 解析</span>
        <span class="analysis-meta">${meta}</span>
        <span class="analysis-chevron">▾</span>
      </button>
      <div class="analysis-body" ${open ? '' : 'hidden'}>
        <div class="chat-messages">${messageHtml}</div>
        <div class="chat-compose">
          <div class="chat-edit-notice" ${editIndex === undefined ? 'hidden' : ''}>
            <span>正在编辑第 <b class="edit-index">${editIndex === undefined ? '' : editIndex + 1}</b> 条追问，发送后其后的对话会清除并重来</span>
            <button type="button" data-action="cancel-edit">取消</button>
          </div>
          <div class="chat-quote-preview" ${quote ? '' : 'hidden'}>
            <span class="quote-label">引用</span>
            <span class="chat-quote-text">${esc(quote)}</span>
            <button class="quote-clear" type="button" data-action="clear-quote" aria-label="取消引用">×</button>
          </div>
          <div class="chat-input-row">
            <textarea class="chat-input" rows="1" placeholder="就这段解析追问…"></textarea>
            <button class="btn btn-primary btn-sm" type="button" data-action="chat-send" data-id="${esc(id)}">发送</button>
          </div>
          <p class="field-help">划选 AI 回复可直接引用并追问。追问会调用 DeepSeek 接口，按用量计费。</p>
        </div>
      </div>
    </div>`;
}

function showQuoteToolbar(rect, text, id) {
  const bar = $('#quote-toolbar');
  if (!bar) return;
  bar.dataset.quote = text;
  bar.dataset.id = id;
  bar.hidden = false;
  const x = Math.min(window.innerWidth - 70, Math.max(70, rect.left + rect.width / 2));
  bar.style.left = `${x}px`;
  bar.style.top = `${Math.max(52, rect.top - 6)}px`;
}

function renderToday() {
  const { stats, pending } = state;
  // 同一内容可能有多个待复习节点，解析是内容级的，只在第一张卡展示入口和面板。
  const seenItems = new Set();
  const cards = pending.map((task) => {
    const firstOfItem = !seenItems.has(task.itemId);
    seenItems.add(task.itemId);
    return `
    <article class="task-card">
      <div class="task-main">
        <h3 class="task-title">${esc(task.title)}</h3>
        <div class="task-meta">
          <span class="badge badge-type">${esc(task.type)}</span>
          <span class="badge badge-accent">第 ${task.day} 天</span>
          <span class="badge ${task.overdueDays > 0 ? 'badge-orange' : 'badge-green'}">${esc(task.dueText)}</span>
          <span class="meta-text">${esc(task.createdText)}</span>
          <button class="btn btn-ghost btn-sm" type="button" data-action="edit" data-id="${esc(task.itemId)}">编辑</button>
          ${firstOfItem && !task.analysis ? `<button class="btn btn-sm" type="button" data-action="analyze" data-id="${esc(task.itemId)}">AI 解析</button>` : ''}
        </div>
        ${task.note ? `<p class="task-note">${esc(task.note)}</p>` : ''}
      </div>
      <div class="task-actions">
        <label class="check-button" data-action="complete" data-id="${esc(task.itemId)}" data-date="${esc(task.date)}">
          <input type="checkbox" aria-label="完成"><span class="check-box">✓</span><span class="check-label">完成</span>
        </label>
      </div>
      ${firstOfItem ? analysisPanelHtml(task.itemId, task.analysis) : ''}
    </article>`;
  }).join('');

  let empty = '';
  if (!cards) {
    if (stats.total > 0) {
      empty = `
        <section class="empty-card">
          <div class="empty-icon green">✓</div>
          <h3>今天全部完成，做得漂亮</h3>
          <p>已完成的复习会自动从今日待办中移除，可以去全部计划查看进度。</p>
          <div class="empty-actions">
            <button class="btn btn-primary" type="button" data-action="add">＋  添加背诵内容</button>
            <button class="btn" type="button" data-action="switch-all">查看全部计划</button>
          </div>
        </section>`;
    } else {
      empty = `
        <section class="empty-card">
          <div class="empty-icon accent">＋</div>
          <h3>今天还没有复习内容</h3>
          <p>添加一项背诵内容，系统会自动排好复习时间轴。</p>
          <div class="empty-actions">
            <button class="btn btn-primary" type="button" data-action="add">＋  添加背诵内容</button>
          </div>
        </section>`;
    }
  }

  return `
    ${renderHero()}
    <div class="list-heading">
      <h2>待复习内容 <span class="badge badge-accent">${pending.length}</span></h2>
      <span class="list-heading-right">按到期先后排序</span>
    </div>
    <div class="task-list">${cards || empty}</div>`;
}

function filterPlans(plans) {
  const keyword = planSearch.trim().toLowerCase();
  return plans.filter((plan) => {
    if (typeFilter !== '全部' && plan.type !== typeFilter) return false;
    if (!keyword) return true;
    return [plan.title, plan.note || '', plan.type]
      .some((field) => String(field).toLowerCase().includes(keyword));
  });
}

// 搜索/筛选只重绘卡片列表，避免整页刷新让输入框失焦。
function refreshPlanList() {
  if (!state || currentView !== 'all') return;
  const list = $('#plan-list');
  const heading = $('#plan-heading-count');
  if (!list) return;
  const plans = state.plans || [];
  const visible = filterPlans(plans);

  const cardHtml = visible.map((plan) => {
    const nodes = plan.nodes.map((node) => `
      <div class="timeline-node ${node.status}">
        <div class="node-day">第 ${node.day} 天</div>
        <div class="node-date">${esc(node.dateText)}</div>
        <div class="node-status">${esc(node.statusText)}</div>
      </div>`).join('');
    const analysisHtml = analysisPanelHtml(plan.id, plan.analysis);
    return `
      <article class="plan-card">
        <div class="plan-head">
          <div class="plan-title-area">
            <div class="plan-title-row">
              <h3 class="plan-title">${esc(plan.title)}</h3>
              <span class="badge badge-type">${esc(plan.type)}</span>
              <span class="badge ${plan.allDone ? 'badge-green' : 'badge-accent'}">${plan.allDone ? '✓ 已完成' : `${plan.done} / ${plan.total}`}</span>
            </div>
            <p class="plan-meta">${esc(plan.meta)}</p>
            ${plan.note ? `<p class="plan-note">${esc(plan.note)}</p>` : ''}
          </div>
          <div class="plan-actions">
            <button class="btn btn-sm" type="button" data-action="edit" data-id="${esc(plan.id)}">编辑</button>
            <button class="btn btn-sm" type="button" data-action="timeline" data-id="${esc(plan.id)}">时间轴</button>
            ${plan.analysis ? '' : `<button class="btn btn-sm" type="button" data-action="analyze" data-id="${esc(plan.id)}">AI 解析</button>`}
            <button class="btn btn-sm btn-danger-ghost" type="button" data-action="delete" data-id="${esc(plan.id)}">删除</button>
          </div>
        </div>
        <div class="timeline ${plan.total > 6 ? 'compact' : ''}">${nodes}</div>
        ${analysisHtml}
      </article>`;
  }).join('');

  const searching = Boolean(planSearch.trim()) || typeFilter !== '全部';
  list.innerHTML = cardHtml || (searching ? `
    <section class="empty-card">
      <div class="empty-icon accent">⌕</div>
      <h3>没有匹配的内容</h3>
      <p>试试别的关键词，或清除搜索与筛选。</p>
      <div class="empty-actions">
        <button class="btn" type="button" data-action="reset-filters">清除筛选</button>
      </div>
    </section>` : `
    <section class="empty-card">
      <div class="empty-icon accent">▤</div>
      <h3>还没有背诵计划</h3>
      <p>添加第一项内容后，这里会展示每一条复习时间轴。</p>
      <div class="empty-actions">
        <button class="btn btn-primary" type="button" data-action="add">＋  添加背诵内容</button>
      </div>
    </section>`);
  if (heading) heading.textContent = `共 ${visible.length} 项`;
}

function renderAll() {
  const { plans, planStats } = state;
  const configuredTypes = (state && state.types) || [];
  const usedTypes = Array.from(new Set(plans.map((plan) => plan.type)));
  const availableTypes = [
    '全部',
    ...configuredTypes,
    ...usedTypes.filter((type) => !configuredTypes.includes(type)),
  ];
  if (!availableTypes.includes(typeFilter)) typeFilter = '全部';

  const statsBar = `
    <section class="stats-bar">
      <div class="stat-item"><div class="stat-label">全部计划</div><div class="stat-value">${planStats.total}</div></div>
      <div class="stat-divider"></div>
      <div class="stat-item"><div class="stat-label">进行中</div><div class="stat-value">${planStats.ongoing}</div></div>
      <div class="stat-divider"></div>
      <div class="stat-item"><div class="stat-label">已完成</div><div class="stat-value">${planStats.finished}</div></div>
    </section>`;

  const cards = filterPlans(plans).map((plan) => {
    const nodes = plan.nodes.map((node) => `
      <div class="timeline-node ${node.status}">
        <div class="node-day">第 ${node.day} 天</div>
        <div class="node-date">${esc(node.dateText)}</div>
        <div class="node-status">${esc(node.statusText)}</div>
      </div>`).join('');

    const analysis = plan.analysis;
    const analysisHtml = analysisPanelHtml(plan.id, analysis);

    return `
      <article class="plan-card">
        <div class="plan-head">
          <div class="plan-title-area">
            <div class="plan-title-row">
              <h3 class="plan-title">${esc(plan.title)}</h3>
              <span class="badge badge-type">${esc(plan.type)}</span>
              <span class="badge ${plan.allDone ? 'badge-green' : 'badge-accent'}">${plan.allDone ? '✓ 已完成' : `${plan.done} / ${plan.total}`}</span>
            </div>
            <p class="plan-meta">${esc(plan.meta)}</p>
            ${plan.note ? `<p class="plan-note">${esc(plan.note)}</p>` : ''}
          </div>
          <div class="plan-actions">
            <button class="btn btn-sm" type="button" data-action="edit" data-id="${esc(plan.id)}">编辑</button>
            <button class="btn btn-sm" type="button" data-action="timeline" data-id="${esc(plan.id)}">时间轴</button>
            ${plan.analysis ? '' : `<button class="btn btn-sm" type="button" data-action="analyze" data-id="${esc(plan.id)}">AI 解析</button>`}
            <button class="btn btn-sm btn-danger-ghost" type="button" data-action="delete" data-id="${esc(plan.id)}">删除</button>
          </div>
        </div>
        <div class="timeline ${plan.total > 6 ? 'compact' : ''}">${nodes}</div>
        ${analysisHtml}
      </article>`;
  }).join('');

  const searching = Boolean(planSearch.trim()) || typeFilter !== '全部';
  const empty = cards ? '' : searching ? `
    <section class="empty-card">
      <div class="empty-icon accent">⌕</div>
      <h3>没有匹配的内容</h3>
      <p>试试别的关键词，或清除搜索与筛选。</p>
      <div class="empty-actions">
        <button class="btn" type="button" data-action="reset-filters">清除筛选</button>
      </div>
    </section>` : `
    <section class="empty-card">
      <div class="empty-icon accent">▤</div>
      <h3>还没有背诵计划</h3>
      <p>添加第一项内容后，这里会展示每一条复习时间轴。</p>
      <div class="empty-actions">
        <button class="btn btn-primary" type="button" data-action="add">＋  添加背诵内容</button>
      </div>
    </section>`;

  return `
    ${statsBar}
    <div class="list-heading">
      <h2>复习时间轴 <span class="badge badge-accent" id="plan-heading-count">共 ${filterPlans(plans).length} 项</span></h2>
      <span class="list-heading-right">
        <label class="plan-search" for="plan-search">
          <span class="search-icon" aria-hidden="true">⌕</span>
          <input id="plan-search" type="search" placeholder="搜索背诵内容" value="${esc(planSearch)}" autocomplete="off">
          ${planSearch ? '<button class="search-clear" type="button" data-action="clear-search" aria-label="清除搜索">×</button>' : ''}
        </label>
        <select class="type-filter" id="type-filter" aria-label="按类型筛选">
          ${availableTypes.map((type) => `<option value="${esc(type)}" ${type === typeFilter ? 'selected' : ''}>${esc(type === '全部' ? '全部类型' : type)}</option>`).join('')}
        </select>
      </span>
    </div>
    <div class="plan-list" id="plan-list">${cards || empty}</div>`;
}

function render({ preserveScroll = true } = {}) {
  if (!state) return;
  const scrollTop = contentEl.scrollTop;
  renderHeader();
  renderSidebar();
  contentEl.innerHTML = currentView === 'today' ? renderToday() : renderAll();
  contentEl.scrollTop = preserveScroll ? scrollTop : 0;
}

/* ---------------- 数据加载与结果处理 ---------------- */

async function loadState({ preserveScroll = true, switchView = null, toast = null } = {}) {
  const result = await call('get_state');
  if (!result.ok) {
    showToast(result.message || '读取数据失败', 'error');
    return;
  }
  state = result.state;
  appearancePreference = state.appearance;
  applyTheme();
  if (switchView) currentView = switchView;
  render({ preserveScroll });

  if (state.loadWarning && !warningShown) {
    warningShown = true;
    window.setTimeout(() => showToast(state.loadWarning, 'warning'), 650);
  }
  if (toast) showToast(toast.message, toast.kind || 'success');
}

async function handleResult(result, { preserveScroll = true, switchView = null } = {}) {
  if (!result) return false;
  if (!result.ok) {
    showToast(result.message || '操作失败', result.kind || 'error');
    return false;
  }
  if (result.view) switchView = result.view;
  if (result.message) showToast(result.message, 'success');
  await loadState({ preserveScroll, switchView });
  return true;
}

async function refreshAll() {
  try {
    const result = await call('refresh');
    await loadState({ preserveScroll: true });
    if (result.ok && result.message) showToast(result.message, 'success');
  } catch (error) {
    showToast(String(error.message || error), 'error');
  }
}

/* ---------------- 时间轴编辑器 ---------------- */

function validateIntervals(values) {
  if (!Array.isArray(values)) return { ok: false, message: '复习节点必须是数字列表' };
  if (values.length < 1) return { ok: false, message: '至少需要 1 个复习节点' };
  if (values.length > MAX_NODES) return { ok: false, message: `最多支持 ${MAX_NODES} 个复习节点` };

  const numbers = [];
  for (const raw of values) {
    if (typeof raw !== 'string' && typeof raw !== 'number') {
      return { ok: false, message: '复习节点必须是正整数' };
    }
    const text = String(raw).trim();
    if (!/^[0-9]+$/.test(text)) return { ok: false, message: '复习节点必须是正整数' };
    const number = Number(text);
    if (!Number.isSafeInteger(number)) {
      return { ok: false, message: `复习节点应在 1 ~ ${MAX_INTERVAL_DAY} 天之间` };
    }
    if (number < 1 || number > MAX_INTERVAL_DAY) {
      return { ok: false, message: `复习节点应在 1 ~ ${MAX_INTERVAL_DAY} 天之间` };
    }
    numbers.push(number);
  }
  if (new Set(numbers).size !== numbers.length) {
    return { ok: false, message: '复习节点不能重复' };
  }
  for (let i = 1; i < numbers.length; i += 1) {
    if (numbers[i] <= numbers[i - 1]) {
      return { ok: false, message: '复习节点必须从小到大排列' };
    }
  }
  return { ok: true, numbers };
}

function nextEbbinghausDay(values) {
  const numbers = values
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value));
  const last = numbers.length ? Math.max(...numbers) : 0;
  const found = EBBINGHAUS_INTERVALS.find((value) => value > last);
  return found ?? Math.min(Math.max(last * 2, last + 1), MAX_INTERVAL_DAY);
}

function addDaysToIso(iso, days) {
  const [year, month, day] = String(iso).split('-').map(Number);
  if (!year || !month || !day) return '';
  const date = new Date(year, month - 1, day + days);
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

function syncTimeline(root) {
  root._values = $$('input', root).map((input) => input.value);
}

function updateTimelinePreview(root) {
  const check = validateIntervals(root._values);
  $$('.preview', root).forEach((preview, index) => {
    preview.textContent = check.ok
      ? addDaysToIso(root.dataset.baseDay, check.numbers[index])
      : '—';
  });
}

function scheduleTimelinePreview(root) {
  window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(() => updateTimelinePreview(root), 80);
}

function renderTimeline(root) {
  root.innerHTML = `
    <div class="timeline-grid">
      ${root._values.map((value, index) => `
        <div class="timeline-cell">
          <label for="timeline-${index}">第 ${index + 1} 次</label>
          <input id="timeline-${index}" type="text" inputmode="numeric" autocomplete="off" value="${esc(value)}" data-index="${index}">
          <span class="preview">—</span>
        </div>`).join('')}
    </div>
    <div class="timeline-toolbar">
      <button class="btn btn-sm" type="button" data-timeline-action="add">＋ 增加节点</button>
      <button class="btn btn-sm" type="button" data-timeline-action="remove">－ 删除节点</button>
      <span class="spacer"></span>
      <span class="count">共 ${root._values.length} 个节点（1 ~ 10）</span>
    </div>`;

  $$('input', root).forEach((input) => {
    input.addEventListener('input', () => {
      root._values[Number(input.dataset.index)] = input.value;
      scheduleTimelinePreview(root);
    });
  });
  updateTimelinePreview(root);
}

function initTimeline(root, values, baseDay) {
  root._values = (values && values.length ? values : DEFAULT_INTERVALS).map(String);
  root.dataset.baseDay = baseDay || todayIso();
  renderTimeline(root);
}

function readTimeline(root) {
  syncTimeline(root);
  return root._values.slice();
}

function handleTimelineAction(action, root) {
  syncTimeline(root);
  if (action === 'add') {
    const check = validateIntervals(root._values);
    const current = check.ok ? check.numbers : root._values.map(Number).filter(Number.isFinite);
    const last = current.length ? Math.max(...current) : 0;
    const next = nextEbbinghausDay(current);
    if (root._values.length >= MAX_NODES || last >= MAX_INTERVAL_DAY || next > MAX_INTERVAL_DAY) return;
    root._values.push(String(next));
    renderTimeline(root);
    const lastInput = $$('input', root).pop();
    if (lastInput) lastInput.focus();
  } else if (action === 'remove') {
    if (root._values.length <= 1) return;
    root._values.pop();
    renderTimeline(root);
  } else if (action === 'default') {
    root._values = DEFAULT_INTERVALS.slice();
    renderTimeline(root);
  }
}

/* ---------------- 弹窗 ---------------- */

function showModal(html, { autofocus = true } = {}) {
  modalLayer.innerHTML = html;
  // 给每个弹窗右上角补一个常驻关闭按钮，避免 footer 被内容挤出视野时无法关闭。
  const header = modalLayer.querySelector('.modal-header');
  if (header && !header.querySelector('.modal-close')) {
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'modal-close';
    close.dataset.action = 'close-modal';
    close.setAttribute('aria-label', '关闭');
    close.textContent = '×';
    header.appendChild(close);
  }
  modalLayer.hidden = false;
  if (autofocus) {
    const target = $('[data-autofocus]', modalLayer);
    if (target) {
      window.setTimeout(() => {
        target.focus();
        if (target.select) target.select();
      }, 60);
    }
  }
}

function closeModal() {
  modalLayer.hidden = true;
  modalLayer.innerHTML = '';
}

function setDialogError(message) {
  const error = $('#dialog-error', modalLayer);
  if (!error) return;
  error.textContent = message || '';
  if (message) error.scrollIntoView({ block: 'nearest' });
}

async function submitDialog(result) {
  if (!result.ok) {
    setDialogError(result.message);
    showToast(result.message, result.kind || 'error');
    return;
  }
  closeModal();
  await loadState({
    preserveScroll: false,
    switchView: result.view || null,
    toast: result.message ? { message: result.message, kind: result.kind || 'success' } : null,
  });
}

function findPlan(id) {
  return state.plans.find((plan) => plan.id === id);
}

function typeSelectorHtml(selected = '') {
  const types = (state && state.types) || ['诗词', '古文', '英语单词'];
  const current = types.includes(selected) ? selected : (types[0] || '');
  return `
    <div class="type-options" id="type-options">
      ${types.map((type) => `
        <button type="button" class="type-chip ${type === current ? 'selected' : ''}" data-type="${esc(type)}">${esc(type)}</button>`).join('')}
    </div>`;
}

function readTypeSelection() {
  const chip = modalLayer.querySelector('.type-chip.selected');
  const types = (state && state.types) || [];
  return chip ? chip.dataset.type : (types[0] || '');
}

function openAddDialog() {
  showModal(`
    <div class="modal">
      <div class="modal-header">
        <div class="modal-icon">＋</div>
        <div><h2>添加背诵内容</h2><p>这条内容的复习时间轴可以单独设置</p></div>
      </div>
      <form id="dialog-form" novalidate>
        <div class="modal-body">
          <div class="field">
            <label class="field-label" for="add-title">背诵内容标题 <span class="required">*</span></label>
            <input id="add-title" type="text" maxlength="120" placeholder="例如：滕王阁序 / 英语 Unit 5 单词" data-autofocus>
          </div>
          <div class="field">
            <label class="field-label" for="add-note">备注（可选）</label>
            <textarea id="add-note" placeholder="可以写来源、章节或想记住的重点"></textarea>
          </div>
          <div class="field">
            <span class="field-label">背诵类型</span>
            ${typeSelectorHtml('')}
          </div>
          <div class="field">
            <span class="field-label">本次复习时间轴（距添加日的第几天）</span>
            <div class="timeline-editor" id="timeline-editor"></div>
            <button class="btn btn-sm" type="button" data-timeline-action="default" style="margin-top:10px">恢复默认</button>
            <p class="field-help">第 1 天即添加当天；第 2 天为次日。可增减节点，只作用于本条内容。</p>
          </div>
          <p class="form-error" id="dialog-error"></p>
        </div>
        <div class="modal-footer">
          <button class="btn" type="button" data-action="close-modal">取消</button>
          <button class="btn btn-primary" type="submit">添加并生成计划</button>
        </div>
      </form>
    </div>`);

  initTimeline($('#timeline-editor', modalLayer), state.defaults.intervals, todayIso());

  $('#dialog-form', modalLayer).addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = readTimeline($('#timeline-editor', modalLayer));
    const check = validateIntervals(values);
    if (!check.ok) {
      setDialogError(check.message);
      return;
    }
    try {
      const reciteType = readTypeSelection();
      const result = await call(
        'add_item',
        $('#add-title', modalLayer).value,
        $('#add-note', modalLayer).value,
        check.numbers,
        reciteType,
      );
      if (result.ok && result.itemId && state.autoAnalyze) {
        const ai = await call('generate_analysis', result.itemId);
        if (ai.ok && ai.message) showToast(ai.message, 'success');
        else if (!ai.ok) showToast(ai.message, 'error');
      }
      await submitDialog(result);
    } catch (error) {
      setDialogError(String(error.message || error));
    }
  });
}

function openEditDialog(id) {
  const plan = findPlan(id);
  if (!plan) {
    showToast('这条内容已经不存在，请刷新后重试', 'error');
    return;
  }
  showModal(`
    <div class="modal">
      <div class="modal-header">
        <div class="modal-icon">✎</div>
        <div><h2>编辑背诵内容</h2><p>只改标题和备注，复习进度与时间轴保持不变</p></div>
      </div>
      <form id="dialog-form" novalidate>
        <div class="modal-body">
          <div class="field">
            <label class="field-label" for="edit-title">背诵内容标题 <span class="required">*</span></label>
            <input id="edit-title" type="text" maxlength="120" value="${esc(plan.title)}" data-autofocus>
          </div>
          <div class="field">
            <label class="field-label" for="edit-note">备注（可选）</label>
            <textarea id="edit-note" class="tall">${esc(plan.note)}</textarea>
          </div>
          <div class="field">
            <span class="field-label">背诵类型</span>
            ${typeSelectorHtml(plan.reciteType || '')}
          </div>
          <div class="notice">当前复习时间轴：第 ${esc(plan.intervalText)} 天。需要调整节点，请回到「全部计划」点「时间轴」。</div>
          <p class="form-error" id="dialog-error"></p>
        </div>
        <div class="modal-footer">
          <button class="btn" type="button" data-action="close-modal">取消</button>
          <button class="btn btn-primary" type="submit">保存修改</button>
        </div>
      </form>
    </div>`);

  $('#dialog-form', modalLayer).addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const reciteType = readTypeSelection();
      const result = await call(
        'update_item',
        id,
        $('#edit-title', modalLayer).value,
        $('#edit-note', modalLayer).value,
        reciteType,
      );
      await submitDialog(result);
    } catch (error) {
      setDialogError(String(error.message || error));
    }
  });
}

function openTimelineDialog(id) {
  const plan = findPlan(id);
  if (!plan) {
    showToast('这条内容已经不存在，请刷新后重试', 'error');
    return;
  }
  showModal(`
    <div class="modal wide">
      <div class="modal-header">
        <div class="modal-icon">↻</div>
        <div><h2>调整复习时间轴</h2><p>只修改这一条背诵内容</p></div>
      </div>
      <form id="dialog-form" novalidate>
        <div class="modal-body">
          <div class="notice danger">正在调整「${esc(plan.title)}」。
修改后会从添加当天重新计算日期；已完成的节点如果仍在时间轴中会保留，被移除的节点会丢失完成记录。</div>
          <div class="field" style="margin-top:18px">
            <span class="field-label">复习节点（距添加日的第几天）</span>
            <div class="timeline-editor" id="timeline-editor"></div>
            <button class="btn btn-sm" type="button" data-timeline-action="default" style="margin-top:10px">恢复默认</button>
            <p class="field-help">例：1 = 添加当天，2 = 次日。可增减节点，节点必须递增。</p>
          </div>
          <p class="form-error" id="dialog-error"></p>
        </div>
        <div class="modal-footer">
          <button class="btn" type="button" data-action="close-modal">取消</button>
          <button class="btn btn-primary" type="submit">保存时间轴</button>
        </div>
      </form>
    </div>`);

  initTimeline($('#timeline-editor', modalLayer), plan.intervals, plan.baseDay);

  $('#dialog-form', modalLayer).addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = readTimeline($('#timeline-editor', modalLayer));
    const check = validateIntervals(values);
    if (!check.ok) {
      setDialogError(check.message);
      return;
    }
    try {
      const result = await call('save_intervals', id, check.numbers);
      await submitDialog(result);
    } catch (error) {
      setDialogError(String(error.message || error));
    }
  });
}

function openDeleteDialog(id) {
  const plan = findPlan(id);
  if (!plan) {
    showToast('这条内容已经不存在，请刷新后重试', 'error');
    return;
  }
  showModal(`
    <div class="modal small">
      <div class="modal-header">
        <div class="modal-icon danger">!</div>
        <div><h2>删除这项计划？</h2></div>
      </div>
      <div class="modal-body">
        <p class="confirm-message">「${esc(plan.title)}」的 ${plan.total} 个复习记录将一起删除，且无法撤销。
如果只是暂时不想背诵，可以保留计划，不必删除。</p>
        <p class="form-error" id="dialog-error"></p>
      </div>
      <div class="modal-footer">
        <button class="btn" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-danger" type="button" data-action="confirm-delete" data-id="${esc(id)}">确认删除</button>
      </div>
    </div>`, { autofocus: false });
}

function switchRow(id, label, hint, checked) {
  return `
    <div class="settings-row">
      <label for="${id}">${esc(label)}${hint ? `<span class="row-hint">${esc(hint)}</span>` : ''}</label>
      <label class="switch" for="${id}">
        <input id="${id}" type="checkbox" ${checked ? 'checked' : ''}>
        <span class="slider"></span>
      </label>
    </div>`;
}

function collectAiSettings() {
  const value = (selector) => $(selector, modalLayer)?.value ?? '';
  const number = (selector, fallback) => {
    const parsed = Number.parseFloat(value(selector));
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  return {
    apiKey: value('#ai-key').trim(),
    baseUrl: value('#ai-base').trim() || 'https://api.deepseek.com',
    model: value('#ai-model').trim() || 'deepseek-flash',
    temperature: number('#ai-temperature', 1),
    topP: number('#ai-topp', 1),
    maxTokens: Number.parseInt(value('#ai-maxtokens'), 10) || 2048,
    thinking: $('#ai-thinking', modalLayer)?.checked ?? true,
    reasoningEffort: value('#ai-effort') || 'high',
    webSearch: $('#ai-websearch', modalLayer)?.checked ?? false,
    systemPrompt: value('#ai-system'),
    autoAnalyze: $('#ai-auto', modalLayer)?.checked ?? false,
  };
}

function collectReciteTypes() {
  return $$('[data-type-row]', modalLayer).map((row) => ({
    id: row.dataset.id || '',
    name: $('.type-name-input', row).value.trim(),
    prompt: $('.type-prompt-input', row).value.trim(),
  }));
}

function updateAiHints() {
  const thinking = $('#ai-thinking', modalLayer)?.checked;
  const web = $('#ai-websearch', modalLayer)?.checked;
  $('#field-temperature', modalLayer)?.classList.toggle('inactive', Boolean(thinking || web));
  $('#field-topp', modalLayer)?.classList.toggle('inactive', Boolean(thinking || web));
  $('#field-effort', modalLayer)?.classList.toggle('inactive', !thinking);
  const hint = $('#ai-hint', modalLayer);
  if (hint) {
    hint.textContent = (thinking || web)
      ? '当前已开启深度思考或联网搜索：DeepSeek 服务端会忽略 temperature 与 top_p，设置仍会保存，但暂不生效。'
      : '非思考模式下 temperature / top_p 生效；思考强度仅在开启深度思考时有意义。';
  }
}

async function openSettingsDialog() {
  let response;
  try {
    response = await call('get_ai_settings');
  } catch (error) {
    showToast(String(error.message || error), 'error');
    return;
  }
  if (!response.ok) {
    showToast(response.message || '读取设置失败', 'error');
    return;
  }
  const ai = response.settings;
  const reciteTypes = response.reciteTypes || [];

  showModal(`
    <div class="modal wide settings-modal">
      <div class="modal-header">
        <div class="modal-icon">⚙</div>
        <div><h2>设置</h2><p>DeepSeek 参数、背诵类型与解析提示词，保存在本地数据文件中</p></div>
      </div>
      <form id="dialog-form" novalidate>
        <div class="modal-body">
          <div class="settings-grid">
            <div class="field full">
              <label class="field-label" for="ai-key">API Key</label>
              <div class="password-row">
                <input id="ai-key" type="password" autocomplete="off" placeholder="sk-..." value="${esc(ai.apiKey || '')}">
                <button class="btn btn-sm" type="button" id="toggle-key">显示</button>
              </div>
              <p class="field-help">请勿把 review_data.json 分享给他人，里面包含此密钥。</p>
            </div>
            <div class="field full">
              <label class="field-label" for="ai-base">API 地址</label>
              <input id="ai-base" type="text" value="${esc(ai.baseUrl || 'https://api.deepseek.com')}">
            </div>
            <div class="field full">
              <label class="field-label" for="ai-model">模型</label>
              <input id="ai-model" type="text" list="model-list" value="${esc(ai.model || 'deepseek-flash')}">
              <datalist id="model-list">
                <option value="deepseek-flash">DeepSeek V4.1 Flash（支持联网工具）</option>
                <option value="deepseek-v4-pro">DeepSeek V4 Pro（强推理）</option>
              </datalist>
            </div>
            <div class="field" id="field-temperature">
              <label class="field-label" for="ai-temperature">temperature</label>
              <div class="range-row">
                <input id="ai-temperature" type="range" min="0" max="2" step="0.05" value="${esc(ai.temperature)}">
                <span class="range-value" id="temperature-value">${esc(ai.temperature)}</span>
              </div>
            </div>
            <div class="field" id="field-topp">
              <label class="field-label" for="ai-topp">top_p</label>
              <div class="range-row">
                <input id="ai-topp" type="range" min="0" max="1" step="0.05" value="${esc(ai.topP)}">
                <span class="range-value" id="topp-value">${esc(ai.topP)}</span>
              </div>
            </div>
            <div class="field">
              <label class="field-label" for="ai-maxtokens">max_tokens</label>
              <input id="ai-maxtokens" type="number" min="256" max="32768" step="128" value="${esc(ai.maxTokens)}">
            </div>
            <div class="field" id="field-effort">
              <label class="field-label" for="ai-effort">思考强度</label>
              <select id="ai-effort">
                ${['low', 'high', 'max'].map((effort) => `<option value="${effort}" ${effort === ai.reasoningEffort ? 'selected' : ''}>${effort}</option>`).join('')}
              </select>
            </div>
            <div class="field full">
              ${switchRow('ai-thinking', '深度思考', '思考模式下 temperature / top_p 不生效', ai.thinking)}
              ${switchRow('ai-websearch', '联网搜索', '开启 deepseek_web_search，思考模式下可深度思考搜索', ai.webSearch)}
              ${switchRow('ai-auto', '添加后自动生成解析', '新增背诵内容时自动调用一次 AI 解析', ai.autoAnalyze)}
              <p class="ai-hint" id="ai-hint"></p>
            </div>
            <div class="field full">
              <label class="field-label" for="ai-system">系统提示词</label>
              <textarea id="ai-system" class="tall">${esc(ai.systemPrompt || '')}</textarea>
              <p class="field-help">整体设定：首次生成解析和后续所有追问都使用这一条。</p>
            </div>
            <div class="field full">
              <span class="field-label">背诵类型与解析提示词</span>
              <p class="field-help">这些类型会出现在「添加 / 编辑背诵内容」里。下面的提示词只在第一次点「AI 解析」时生效，后续对话追问不受它影响。</p>
              <div class="type-editor" id="type-editor">
                ${reciteTypes.map((entry) => `
                  <div class="type-editor-row" data-type-row data-id="${esc(entry.id)}">
                    <div class="type-editor-head">
                      <input class="type-name-input" type="text" maxlength="20" placeholder="类型名称" value="${esc(entry.name)}">
                      <button class="btn btn-sm btn-danger-ghost" type="button" data-remove-type>删除</button>
                    </div>
                    <textarea class="type-prompt-input" data-prompt placeholder="这个类型的解析提示词">${esc(entry.prompt || '')}</textarea>
                  </div>`).join('')}
              </div>
              <button class="btn btn-sm" type="button" id="btn-add-type">＋ 添加类型</button>
            </div>
          </div>
          <p class="form-error" id="dialog-error"></p>
        </div>
        <div class="modal-footer">
          <button class="btn" type="button" id="btn-test-ai">测试连接</button>
          <button class="btn" type="button" data-action="close-modal">取消</button>
          <button class="btn btn-primary" type="submit">保存设置</button>
        </div>
      </form>
    </div>`);

  $('#ai-temperature', modalLayer).addEventListener('input', (event) => {
    $('#temperature-value', modalLayer).textContent = event.target.value;
  });
  $('#ai-topp', modalLayer).addEventListener('input', (event) => {
    $('#topp-value', modalLayer).textContent = event.target.value;
  });
  ['#ai-thinking', '#ai-websearch'].forEach((selector) => {
    $(selector, modalLayer).addEventListener('change', updateAiHints);
  });
  updateAiHints();

  $('#toggle-key', modalLayer).addEventListener('click', (event) => {
    const input = $('#ai-key', modalLayer);
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    event.target.textContent = show ? '隐藏' : '显示';
  });

  const typeEditor = $('#type-editor', modalLayer);
  $('#btn-add-type', modalLayer).addEventListener('click', () => {
    if ($$('[data-type-row]', typeEditor).length >= 30) {
      showToast('背诵类型最多 30 个', 'warning');
      return;
    }
    const row = document.createElement('div');
    row.className = 'type-editor-row';
    row.dataset.typeRow = '';
    row.dataset.id = '';
    row.innerHTML = `
      <div class="type-editor-head">
        <input class="type-name-input" type="text" maxlength="20" placeholder="类型名称">
        <button class="btn btn-sm btn-danger-ghost" type="button" data-remove-type>删除</button>
      </div>
      <textarea class="type-prompt-input" data-prompt placeholder="这个类型的解析提示词"></textarea>`;
    typeEditor.appendChild(row);
    row.querySelector('.type-name-input').focus();
    row.scrollIntoView({ block: 'nearest' });
  });

  typeEditor.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-type]');
    if (!button) return;
    if ($$('[data-type-row]', typeEditor).length <= 1) {
      showToast('至少保留一个背诵类型', 'warning');
      return;
    }
    button.closest('[data-type-row]').remove();
  });

  $('#btn-test-ai', modalLayer).addEventListener('click', async (event) => {
    const button = event.target;
    button.disabled = true;
    button.textContent = '测试中…';
    try {
      // 类型编辑也要一起落盘，避免点了“测试连接”后关闭弹窗导致类型改动丢失。
      const typesSaved = await call('save_recite_types', collectReciteTypes());
      if (!typesSaved.ok) {
        setDialogError(typesSaved.message);
        showToast(typesSaved.message, 'error');
        return;
      }
      const saved = await call('save_ai_settings', collectAiSettings());
      if (!saved.ok) {
        showToast(saved.message, 'error');
        return;
      }
      const result = await call('test_ai_connection');
      showToast(result.message || '测试失败', result.ok ? 'success' : 'error');
    } catch (error) {
      showToast(String(error.message || error), 'error');
    } finally {
      button.disabled = false;
      button.textContent = '测试连接';
    }
  });

  $('#dialog-form', modalLayer).addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const typesResult = await call('save_recite_types', collectReciteTypes());
      if (!typesResult.ok) {
        setDialogError(typesResult.message);
        return;
      }
      const result = await call('save_ai_settings', collectAiSettings());
      await submitDialog(result.ok ? { ...result, message: '设置已保存' } : result);
    } catch (error) {
      setDialogError(String(error.message || error));
    }
  });
}

/* ---------------- 关于 / 检查更新 ---------------- */

// 最近一次检查结果，供「下载更新」「查看更新日志」按钮取用。
let updateInfo = null;

function versionText(value) {
  const text = String(value || '').trim();
  return text ? (text.startsWith('v') ? text : `v${text}`) : '—';
}

function setAboutStatus(kind, icon, text) {
  const card = $('#about-status-card', modalLayer);
  const ico = $('#about-status-icon', modalLayer);
  const hint = $('#about-hint', modalLayer);
  if (card) card.className = `about-status ${kind}`;
  if (ico) ico.textContent = icon;
  if (hint) hint.textContent = text;
}

function openAboutDialog() {
  updateInfo = null;
  showModal(`
    <div class="modal small about-modal">
      <div class="modal-header about-header">
        <div class="about-logo">忆</div>
        <div class="about-brand">
          <h2>拾忆</h2>
          <p>艾宾浩斯背诵助手 · 把遗忘曲线装进桌面</p>
        </div>
      </div>
      <div class="modal-body">
        <div class="about-version-cards">
          <div class="version-card">
            <span class="version-label">当前版本</span>
            <strong class="version-number">v${esc(state?.version || '0.1.0')}</strong>
          </div>
          <div class="version-card">
            <span class="version-label">可用版本</span>
            <strong class="version-number" id="about-latest">—</strong>
          </div>
        </div>
        <div class="about-status idle" id="about-status-card">
          <span class="status-icon" id="about-status-icon">i</span>
          <span class="status-text" id="about-hint">点「检查更新」查看是否有新版本。</span>
        </div>
        <div class="about-actions">
          <button class="btn btn-sm btn-primary" type="button" data-action="check-update" id="btn-check-update">检查更新</button>
          <button class="btn btn-sm" type="button" data-action="download-update" id="btn-download-update" disabled>下载更新</button>
          <button class="btn btn-sm" type="button" data-action="view-changelog" id="btn-view-changelog">查看更新日志</button>
        </div>
        <p class="about-footer">数据只保存在本地 · <a href="#" data-action="view-changelog">在 GitHub 上查看源码</a></p>
      </div>
    </div>`, { autofocus: false });
}

/* ---------------- 事件绑定 ---------------- */

// 划选 AI 回复 -> 浮出「追问」按钮（朗读不需要）。
// 用 selectionchange 而不是 mouseup：鼠标拖动结束时选区可能已经变化，
// 直接监听选区本身最可靠，也不会阻止文本被选中。
function detectQuoteSelection() {
  const bar = $('#quote-toolbar');
  if (!bar) return;
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) {
    bar.hidden = true;
    return;
  }
  const range = selection.getRangeAt(0);
  let text = String(range.toString() || '').trim();
  if (!text) text = String(range.cloneContents().textContent || '').trim();
  const node = range.commonAncestorContainer;
  const element = node && node.nodeType === 3 ? node.parentElement : node;
  const content = element && element.closest
    ? element.closest('.chat-msg.assistant .chat-content')
    : null;
  if (!text || text.length > 300 || !content) {
    bar.hidden = true;
    return;
  }
  const card = content.closest('.analysis-card');
  showQuoteToolbar(
    range.getBoundingClientRect(),
    text,
    card ? card.dataset.analysisId : '',
  );
}

document.addEventListener('selectionchange', detectQuoteSelection);

// 点浮层按钮时不要清掉选区
document.addEventListener('mousedown', (event) => {
  if (event.target.closest('#quote-toolbar')) event.preventDefault();
});

document.addEventListener('click', (event) => {
  const bar = $('#quote-toolbar');
  const ask = event.target.closest('[data-action="quote-ask"]');
  if (ask && bar) {
    const id = bar.dataset.id || '';
    const text = bar.dataset.quote || '';
    pendingQuotes.set(id, text);
    const card = Array.from(contentEl.querySelectorAll('.analysis-card'))
      .find((el) => el.dataset.analysisId === id);
    if (card) {
      const preview = $('.chat-quote-preview', card);
      const label = preview ? $('.chat-quote-text', preview) : null;
      if (label) label.textContent = text;
      if (preview) preview.hidden = false;
      const input = $('.chat-input', card);
      if (input) input.focus();
    }
    bar.hidden = true;
    const selection = window.getSelection();
    if (selection) selection.removeAllRanges();
    return;
  }
  if (
    bar &&
    !event.target.closest('#quote-toolbar') &&
    !event.target.closest('.chat-msg.assistant')
  ) {
    bar.hidden = true;
  }
});

// 输入框回车发送，Shift+Enter 换行
contentEl.addEventListener('keydown', (event) => {
  if (!event.target.matches('.chat-input')) return;
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    const card = event.target.closest('.analysis-card');
    const button = card ? $('[data-action="chat-send"]', card) : null;
    if (button) button.click();
  }
});

$('#side-nav').addEventListener('click', (event) => {
  const button = event.target.closest('[data-view]');
  if (!button) return;
  currentView = button.dataset.view;
  render({ preserveScroll: false });
});

$('#btn-add').addEventListener('click', openAddDialog);
$('#btn-settings').addEventListener('click', openSettingsDialog);
$('#btn-about').addEventListener('click', openAboutDialog);

appearanceSelect.addEventListener('change', async () => {
  appearancePreference = appearanceSelect.value;
  applyTheme();
  try {
    await call('set_appearance', appearancePreference);
    await loadState({ preserveScroll: true });
  } catch (error) {
    showToast(String(error.message || error), 'error');
  }
});

contentEl.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action, id } = button.dataset;

  switch (action) {
    case 'add':
      openAddDialog();
      break;
    case 'switch-all':
      currentView = 'all';
      render({ preserveScroll: false });
      break;
    case 'clear-search': {
      planSearch = '';
      const input = $('#plan-search');
      if (input) {
        input.value = '';
        input.focus();
      }
      const clear = event.target.closest('.search-clear');
      if (clear) clear.remove();
      refreshPlanList();
      break;
    }
    case 'reset-filters': {
      planSearch = '';
      typeFilter = '全部';
      render({ preserveScroll: false });
      break;
    }
    case 'edit':
      openEditDialog(id);
      break;
    case 'timeline':
      openTimelineDialog(id);
      break;
    case 'delete':
      openDeleteDialog(id);
      break;
    case 'toggle-analysis': {
      const card = button.closest('.analysis-card');
      if (!card) break;
      const open = card.classList.toggle('open');
      const body = $('.analysis-body', card);
      const actions = $('.analysis-actions', card);
      if (body) body.hidden = !open;
      if (actions) actions.hidden = !open;
      button.setAttribute('aria-expanded', String(open));
      if (open) expandedAnalyses.add(id);
      else expandedAnalyses.delete(id);
      break;
    }
    case 'msg-regenerate': {
      if (button.disabled) return;
      const index = Number(button.dataset.index);
      button.disabled = true;
      button.textContent = '生成中…';
      try {
        const result = await call('regenerate_message', id, index);
        if (!result.ok) {
          showToast(result.message || '重新生成失败', 'error');
        } else {
          expandedAnalyses.add(id);
          await loadState({ preserveScroll: true });
          if (result.message) showToast(result.message, 'success');
        }
      } catch (error) {
        showToast(String(error.message || error), 'error');
      } finally {
        if (document.body.contains(button)) {
          button.disabled = false;
          button.textContent = '重新生成';
        }
      }
      break;
    }
    case 'msg-delete': {
      if (button.disabled) return;
      button.disabled = true;
      try {
        const result = await call('delete_chat_message', id, Number(button.dataset.index));
        if (!result.ok) {
          showToast(result.message || '删除失败', 'error');
        } else {
          expandedAnalyses.add(id);
          await loadState({ preserveScroll: true });
          if (result.message) showToast(result.message, 'success');
        }
      } catch (error) {
        showToast(String(error.message || error), 'error');
      } finally {
        if (document.body.contains(button)) button.disabled = false;
      }
      break;
    }
    case 'msg-edit': {
      const card = button.closest('.analysis-card');
      const msg = button.closest('.chat-row');
      const content = msg ? $('.chat-content', msg) : null;
      const text = content ? content.textContent.trim() : '';
      const index = Number(button.dataset.index);
      pendingEdits.set(id, index);
      pendingQuotes.delete(id);
      const input = card ? $('.chat-input', card) : null;
      if (input) {
        input.value = text;
        input.focus();
      }
      const notice = card ? $('.chat-edit-notice', card) : null;
      if (notice) {
        notice.hidden = false;
        const label = $('.edit-index', notice);
        if (label) label.textContent = String(index + 1);
      }
      const preview = card ? $('.chat-quote-preview', card) : null;
      if (preview) preview.hidden = true;
      showToast('编辑后发送，该消息之后的对话会清除并重来', 'warning');
      break;
    }
    case 'cancel-edit': {
      const card = button.closest('.analysis-card');
      const cardId = card ? card.dataset.analysisId : '';
      pendingEdits.delete(cardId);
      const notice = card ? $('.chat-edit-notice', card) : null;
      if (notice) notice.hidden = true;
      const input = card ? $('.chat-input', card) : null;
      if (input) input.value = '';
      break;
    }
    case 'chat-send': {
      if (button.disabled) return;
      const card = button.closest('.analysis-card');
      const input = $('.chat-input', card);
      const text = input ? input.value.trim() : '';
      if (!text) {
        showToast('请输入追问内容', 'warning');
        return;
      }
      const preview = $('.chat-quote-preview:not([hidden])', card);
      const quote = preview ? ($('.chat-quote-text', preview)?.textContent || '') : '';
      button.disabled = true;
      button.textContent = '发送中…';
      try {
        const editIndex = pendingEdits.get(id);
        const result = editIndex === undefined
          ? await call('chat_analysis', id, text, quote)
          : await call('edit_chat', id, editIndex, text);
        if (!result.ok) {
          showToast(result.message || '发送失败', 'error');
        } else {
          pendingQuotes.delete(id);
          pendingEdits.delete(id);
          expandedAnalyses.add(id);
          await loadState({ preserveScroll: true });
          if (result.message) showToast(result.message, 'success');
        }
      } catch (error) {
        showToast(String(error.message || error), 'error');
      } finally {
        if (document.body.contains(button)) {
          button.disabled = false;
          button.textContent = '发送';
        }
      }
      break;
    }
    case 'clear-quote': {
      const card = button.closest('.analysis-card');
      if (card) {
        pendingQuotes.delete(card.dataset.analysisId);
        const preview = $('.chat-quote-preview', card);
        if (preview) preview.hidden = true;
      }
      break;
    }
    case 'analyze': {
      if (button.disabled) return;
      const force = button.dataset.force === '1';
      button.disabled = true;
      button.textContent = '生成中…';
      showToast('正在生成 AI 解析，请稍候…', 'warning');
      try {
        const result = await call('generate_analysis', id, force);
        if (!result.ok) {
          showToast(result.message || '生成失败', 'error');
        } else {
          // 生成后自动展开，今日复习与全部计划共用同一份缓存。
          expandedAnalyses.add(id);
          await loadState({ preserveScroll: true });
          if (result.message) showToast(result.message, 'success');
        }
      } catch (error) {
        showToast(String(error.message || error), 'error');
      } finally {
        if (document.body.contains(button)) {
          button.disabled = false;
          button.textContent = 'AI 解析';
        }
      }
      break;
    }
    case 'clear-analysis': {
      try {
        const result = await call('clear_analysis', id);
        expandedAnalyses.delete(id);
        await handleResult(result);
      } catch (error) {
        showToast(String(error.message || error), 'error');
      }
      break;
    }
    default:
      break;
  }
});

contentEl.addEventListener('input', (event) => {
  if (event.target.matches('#plan-search')) {
    planSearch = event.target.value;
    // 同步清除按钮：只在有内容时显示，不改整个页面结构。
    const label = event.target.closest('.plan-search');
    if (label) {
      let clear = $('.search-clear', label);
      if (planSearch && !clear) {
        clear = document.createElement('button');
        clear.className = 'search-clear';
        clear.type = 'button';
        clear.dataset.action = 'clear-search';
        clear.setAttribute('aria-label', '清除搜索');
        clear.textContent = '×';
        label.appendChild(clear);
      } else if (!planSearch && clear) {
        clear.remove();
      }
    }
    refreshPlanList();
  }
});

contentEl.addEventListener('change', async (event) => {
  if (event.target.matches('#type-filter')) {
    typeFilter = event.target.value;
    refreshPlanList();
    return;
  }
  const checkbox = event.target.closest('.check-button input[type="checkbox"]');
  if (!checkbox || !checkbox.checked) return;

  const label = checkbox.closest('.check-button');
  if (label.classList.contains('done')) return;

  // 先给出即时反馈，和旧版勾选后禁用复选框的体验一致。
  label.classList.add('done');
  $('.check-label', label).textContent = '已完成';
  checkbox.disabled = true;

  try {
    const result = await call('complete_review', label.dataset.id, label.dataset.date);
    if (!result.ok) {
      label.classList.remove('done');
      $('.check-label', label).textContent = '完成';
      checkbox.disabled = false;
      checkbox.checked = false;
      showToast(result.message || '保存失败，本次完成状态未记录', 'error');
      return;
    }
    if (result.message) showToast(result.message, 'success');
    window.setTimeout(() => loadState({ preserveScroll: true }), 220);
  } catch (error) {
    label.classList.remove('done');
    $('.check-label', label).textContent = '完成';
    checkbox.disabled = false;
    checkbox.checked = false;
    showToast(String(error.message || error), 'error');
  }
});

modalLayer.addEventListener('click', async (event) => {
  // 点击遮罩空白处也可以关闭弹窗。
  if (event.target === modalLayer) {
    closeModal();
    return;
  }
  if (event.target.closest('[data-action="close-modal"]')) {
    closeModal();
    return;
  }
  if (event.target.closest('[data-action="check-update"]')) {
    const button = $('#btn-check-update', modalLayer);
    if (!button || button.disabled) return;
    button.disabled = true;
    button.textContent = '检查中…';
    try {
      const result = await call('check_update');
      if (!result.ok) {
        setAboutStatus('error', '!', result.message || '检查更新失败');
        showToast(result.message || '检查更新失败', 'error');
        return;
      }
      updateInfo = result;
      const latestEl = $('#about-latest', modalLayer);
      if (latestEl) latestEl.textContent = versionText(result.latestVersion);
      const kind = result.hasUpdate ? 'update' : (result.latestVersion ? 'latest' : 'idle');
      const icon = result.hasUpdate ? '↑' : (result.latestVersion ? '✓' : 'i');
      setAboutStatus(kind, icon, result.message || '');
      const downloadBtn = $('#btn-download-update', modalLayer);
      const changelogBtn = $('#btn-view-changelog', modalLayer);
      if (downloadBtn) downloadBtn.disabled = !result.hasUpdate;
      if (changelogBtn) changelogBtn.disabled = false;
    } catch (error) {
      showToast(String(error.message || error), 'error');
    } finally {
      if (document.body.contains(button)) {
        button.disabled = false;
        button.textContent = '检查更新';
      }
    }
    return;
  }
  if (event.target.closest('[data-action="download-update"]')) {
    if (!updateInfo?.downloadUrl) return;
    try {
      const result = await call('open_external_url', updateInfo.downloadUrl);
      showToast(result.message || (result.ok ? '已打开下载页' : '打开失败'), result.ok ? 'success' : 'error');
    } catch (error) {
      showToast(String(error.message || error), 'error');
    }
    return;
  }
  if (event.target.closest('[data-action="view-changelog"]')) {
    event.preventDefault();
    try {
      const result = await call('open_release_page');
      showToast(result.message || (result.ok ? '已打开更新日志' : '打开失败'), result.ok ? 'success' : 'error');
    } catch (error) {
      showToast(String(error.message || error), 'error');
    }
    return;
  }
  const confirmDelete = event.target.closest('[data-action="confirm-delete"]');
  if (confirmDelete) {
    try {
      const result = await call('delete_item', confirmDelete.dataset.id);
      await submitDialog(result);
    } catch (error) {
      setDialogError(String(error.message || error));
    }
    return;
  }
  const typeChip = event.target.closest('[data-type]');
  if (typeChip) {
    $$('.type-chip', modalLayer).forEach((chip) => {
      chip.classList.toggle('selected', chip === typeChip);
    });
    return;
  }
  const timelineButton = event.target.closest('[data-timeline-action]');
  if (timelineButton) {
    const editor = timelineButton.closest('.modal-body').querySelector('.timeline-editor');
    if (editor) handleTimelineAction(timelineButton.dataset.timelineAction, editor);
  }
});

document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'n') {
    event.preventDefault();
    if (modalLayer.hidden) openAddDialog();
    return;
  }
  if (event.key === 'F5') {
    event.preventDefault();
    refreshAll();
    return;
  }
  if (event.key === 'Escape' && !modalLayer.hidden) {
    closeModal();
  }
});

/* ---------------- 启动 ---------------- */

async function boot() {
  applyTheme();
  try {
    await loadState({ preserveScroll: false });
  } catch (error) {
    contentEl.innerHTML = `<section class="empty-card"><h3>无法读取数据</h3><p>${esc(error.message || error)}</p></section>`;
  }
}

window.addEventListener('pywebviewready', boot);

// 方便在普通浏览器里检查静态样式：没有 WebView2 接口时给出明确提示。
window.setTimeout(() => {
  if (!window.pywebview) {
    contentEl.innerHTML = `
      <section class="empty-card">
        <div class="empty-icon accent">◷</div>
        <h3>请在桌面应用中打开</h3>
        <p>本页面由 WebView2 承载，需要通过 webview_app.py 启动后才能读写数据。</p>
      </section>`;
  }
}, 600);
