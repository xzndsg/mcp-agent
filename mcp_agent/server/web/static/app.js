// mcp-agent 控制台（原生 JS，无构建依赖）
const state = { sessionId: null, tab: 'chat' };

const $ = (sel) => document.querySelector(sel);
const api = async (url, options = {}) => {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok || body.code !== 0) {
    throw new Error(body.message || `HTTP ${resp.status}`);
  }
  return body.data;
};

// ----------------------------------------------------------- 标签切换
document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach((p) => p.classList.remove('active'));
    tab.classList.add('active');
    $(`#tab-${tab.dataset.tab}`).classList.add('active');
    state.tab = tab.dataset.tab;
    if (state.tab === 'servers') loadServers();
    if (state.tab === 'tools') loadTools();
    if (state.tab === 'human') loadHuman();
    if (state.tab === 'voice') loadVoiceVoices();
    if (state.tab === 'platform') loadPlatform();
  });
});

// ----------------------------------------------------------- 运行时信息
async function loadRuntime() {
  try {
    const info = await api('/api/runtime');
    const llm = info.llm;
    $('#runtime-info').textContent =
      `LLM: ${llm.provider} / ${llm.model} ${llm.ready ? '✓' : '（未配置 Key · 演示模式）'}` +
      `　在线服务器: ${info.servers.filter((s) => s.status === 'online').length}/${info.servers.length}` +
      `　可用工具: ${info.tool_count}`;
  } catch (e) {
    $('#runtime-info').textContent = `运行时不可用: ${e.message}`;
  }
}

// ----------------------------------------------------------- 对话
function appendMessage(role, text, meta = '') {
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;
  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta';
    m.textContent = meta;
    wrap.appendChild(m);
  }
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  wrap.appendChild(bubble);
  $('#chat-box').appendChild(wrap);
  $('#chat-box').scrollTop = $('#chat-box').scrollHeight;
  return bubble;
}

function appendToolNote(text) {
  const note = document.createElement('div');
  note.className = 'tool-note';
  note.textContent = text;
  $('#chat-box').appendChild(note);
  $('#chat-box').scrollTop = $('#chat-box').scrollHeight;
}

function sendChat() {
  const input = $('#chat-message');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  appendMessage('user', message);

  const bubble = appendMessage('bot', '');
  let answer = '';

  const params = new URLSearchParams({ message });
  if (state.sessionId) params.set('session_id', state.sessionId);
  const es = new EventSource(`/api/chat/stream?${params.toString()}`);

  es.onmessage = (ev) => {
    const event = JSON.parse(ev.data);
    if (event.type === 'token') {
      answer += event.content;
      bubble.textContent = answer;
      $('#chat-box').scrollTop = $('#chat-box').scrollHeight;
    } else if (event.type === 'tool_start') {
      appendToolNote(`🔧 调用工具：${event.tool} ${event.args ? JSON.stringify(event.args) : ''}`);
    } else if (event.type === 'tool_end') {
      appendToolNote(`🔧 ${event.tool} 返回：${String(event.output).slice(0, 200)}`);
    } else if (event.type === 'done') {
      state.sessionId = event.session_id;
      if (!answer) bubble.textContent = event.reply;
      es.close();
      loadRuntime();
    } else if (event.type === 'error') {
      bubble.textContent = `[错误] ${event.error}`;
      es.close();
    }
  };
  es.onerror = () => {
    if (!answer) bubble.textContent = '[连接中断]';
    es.close();
  };
}

$('#chat-send').addEventListener('click', sendChat);
$('#chat-message').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendChat();
});
$('#chat-clear').addEventListener('click', () => {
  state.sessionId = null;
  $('#chat-box').innerHTML = '';
});

// ----------------------------------------------------------- 服务器管理
$('#transport-select').addEventListener('change', (e) => {
  const isStdio = e.target.value === 'stdio';
  $('#url-field').classList.toggle('hidden', isStdio);
  $('#command-field').classList.toggle('hidden', !isStdio);
  $('#args-field').classList.toggle('hidden', !isStdio);
});

function parseHeaders(text) {
  const headers = {};
  text.split('\n').forEach((line) => {
    const idx = line.indexOf(':');
    if (idx > 0) headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  });
  return headers;
}

$('#server-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const transport = form.get('transport');
  const payload = {
    name: form.get('name'),
    transport,
    autostart: form.get('autostart') === 'on',
    headers: parseHeaders(form.get('headers') || ''),
  };
  if (transport === 'stdio') {
    payload.command = form.get('command');
    payload.args = (form.get('args') || '').split(/\s+/).filter(Boolean);
  } else {
    payload.url = form.get('url');
  }
  $('#server-error').classList.add('hidden');
  try {
    await api('/api/servers', { method: 'POST', body: JSON.stringify(payload) });
    e.target.reset();
    await loadServers();
  } catch (err) {
    showServerError(err.message);
  }
});

function showServerError(msg) {
  const box = $('#server-error');
  box.textContent = msg;
  box.classList.remove('hidden');
}

async function loadServers() {
  const servers = await api('/api/servers');
  const tbody = $('#servers-tbody');
  tbody.innerHTML = '';
  servers.forEach((s) => {
    const tr = document.createElement('tr');
    const target = s.transport === 'stdio'
      ? `${s.command || ''} ${(s.args || []).join(' ')}`
      : s.url || '';
    tr.innerHTML = `
      <td>${s.name}${s.autostart ? ' <small>⚡</small>' : ''}</td>
      <td>${s.transport}</td>
      <td title="${s.last_error || ''}">${target}</td>
      <td class="status-${s.status}">${s.status}${s.last_error ? ` <small>(${s.last_error})</small>` : ''}</td>
      <td>${s.latency_ms ? s.latency_ms + 'ms' : '-'}</td>
      <td>${s.tool_count}</td>
      <td></td>`;
    const actions = tr.lastElementChild;
    const connectBtn = document.createElement('button');
    connectBtn.className = 'mini';
    connectBtn.textContent = '连接';
    connectBtn.onclick = async () => {
      connectBtn.disabled = true;
      try {
        await api(`/api/servers/${s.id}/connect`, { method: 'POST' });
      } catch (e) {
        showServerError(e.message);
      }
      await loadServers();
      await loadRuntime();
    };
    const disconnectBtn = document.createElement('button');
    disconnectBtn.className = 'mini secondary';
    disconnectBtn.textContent = '断开';
    disconnectBtn.onclick = async () => {
      await api(`/api/servers/${s.id}/disconnect`, { method: 'POST' });
      await loadServers();
      await loadRuntime();
    };
    const delBtn = document.createElement('button');
    delBtn.className = 'mini danger';
    delBtn.textContent = '删除';
    delBtn.onclick = async () => {
      if (!confirm(`确认删除服务器 ${s.name}？`)) return;
      await api(`/api/servers/${s.id}`, { method: 'DELETE' });
      await loadServers();
      await loadRuntime();
    };
    actions.append(connectBtn, disconnectBtn, delBtn);
    tbody.appendChild(tr);
  });
}

// ----------------------------------------------------------- 工具
async function loadTools() {
  const tools = await api('/api/tools');
  const tbody = $('#tools-tbody');
  tbody.innerHTML = '';
  tools.forEach((t) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="checkbox" ${t.enabled ? 'checked' : ''} ${t.available ? '' : 'disabled'}></td>
      <td>${t.name}</td>
      <td class="origin-${t.origin}">${t.origin === 'local' ? '本地' : t.server_id}</td>
      <td>${t.description || ''}${t.available ? '' : ' <span class="status-offline">(离线)</span>'}</td>`;
    const checkbox = tr.querySelector('input');
    checkbox.addEventListener('change', async () => {
      await api('/api/tools/enable', {
        method: 'POST',
        body: JSON.stringify({ server_id: t.server_id, name: t.name, enabled: checkbox.checked }),
      });
      await loadRuntime();
    });
    tbody.appendChild(tr);
  });
}

loadRuntime();
setInterval(loadRuntime, 10000);

// =========================================================== 通用 TTS 调用
async function synthTTS(text, voice, rate) {
  const resp = await fetch('/api/v1/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice, rate }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.message || `HTTP ${resp.status}`);
  }
  return resp.blob();
}

async function loadVoiceVoices() {
  try {
    const info = await api('/api/v1/tts/voices');
    fillVoiceSelect($('#tts-voice'), info.voices);
    fillVoiceSelect($('#human-voice'), info.voices);
  } catch (e) { /* TTS 不可用时静默 */ }
}

function fillVoiceSelect(select, voices) {
  if (!select || select.options.length) return;
  voices.forEach((v) => {
    const opt = document.createElement('option');
    opt.value = v.id;
    opt.textContent = v.label || v.id;
    select.appendChild(opt);
  });
}

// =========================================================== 语音页
$('#tts-play').addEventListener('click', async () => {
  const text = $('#tts-text').value.trim();
  if (!text) return alert('请输入要合成的文本');
  const btn = $('#tts-play');
  btn.disabled = true; btn.textContent = '合成中…';
  try {
    const blob = await synthTTS(text, $('#tts-voice').value, $('#tts-rate').value);
    $('#tts-audio').src = URL.createObjectURL(blob);
    $('#tts-audio').play();
  } catch (e) { alert(`合成失败: ${e.message}`); }
  btn.disabled = false; btn.textContent = '合成试听';
});

// 浏览器原生 ASR（Chrome / Edge）
let asr = null, asrActive = false;
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  asr = new SpeechRecognition();
  asr.lang = 'zh-CN';
  asr.interimResults = true;
  asr.continuous = false;
  asr.onresult = (ev) => {
    let text = '';
    for (const res of ev.results) text += res[0].transcript;
    $('#asr-result').value = text;
  };
  asr.onend = () => {
    asrActive = false;
    $('#asr-start').textContent = '🎤 开始识别';
  };
  asr.onerror = () => {
    asrActive = false;
    $('#asr-start').textContent = '🎤 开始识别';
  };
} else {
  $('#asr-start').disabled = true;
  $('#asr-start').textContent = '当前浏览器不支持 ASR';
}

$('#asr-start').addEventListener('click', () => {
  if (!asr) return;
  if (asrActive) { asr.stop(); return; }
  $('#asr-result').value = '';
  asr.start();
  asrActive = true;
  $('#asr-start').textContent = '⏹ 停止识别';
});

$('#asr-to-chat').addEventListener('click', () => {
  const text = $('#asr-result').value.trim();
  if (!text) return alert('还没有识别结果');
  document.querySelector('.tab[data-tab="chat"]').click();
  $('#chat-message').value = text;
  $('#chat-message').focus();
});

// =========================================================== 数字人
const human = { amp: 0, swing: 2.0, playing: false };

async function loadHuman() {
  try {
    const cfg = await api('/api/v1/digital_human');
    applyHumanConfig(cfg);
  } catch (e) { /* 忽略 */ }
}

function applyHumanConfig(cfg) {
  const stage = $('#human-stage');
  const avatar = $('#human-avatar');
  if (cfg.image_url) {
    avatar.src = cfg.image_url;
    avatar.classList.remove('hidden');
    $('#human-placeholder').classList.add('hidden');
  }
  $('#breath-speed').value = cfg.breath_speed;
  $('#breath-val').textContent = `${cfg.breath_speed}s`;
  stage.style.setProperty('--breath', `${cfg.breath_speed}s`);
  $('#swing-amplitude').value = cfg.swing_amplitude;
  $('#swing-val').textContent = `${cfg.swing_amplitude}deg`;
  human.swing = Number(cfg.swing_amplitude) || 0;
  $('#human-blink').checked = !!cfg.blink;
  $('#human-eyelid').style.display = cfg.blink ? 'block' : 'none';
  setHumanStatus(cfg.speaking ? '说话中' : '待机中');
}

function setHumanStatus(text) {
  $('#human-status').textContent = text;
  $('#human-status').classList.toggle('speaking', text === '说话中');
}

$('#human-image').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('image', file);
  try {
    const resp = await fetch('/api/v1/digital_human/image', { method: 'POST', body: fd });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok || body.code !== 0) throw new Error(body.message || `HTTP ${resp.status}`);
    await loadHuman();
  } catch (err) {
    alert(`上传失败: ${err.message}`);
  }
  e.target.value = '';
});

$('#breath-speed').addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('#breath-val').textContent = `${v}s`;
  $('#human-stage').style.setProperty('--breath', `${v}s`);
});
$('#breath-speed').addEventListener('change', () => saveHumanConfig());
$('#swing-amplitude').addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('#swing-val').textContent = `${v}deg`;
  human.swing = v;
});
$('#swing-amplitude').addEventListener('change', () => saveHumanConfig());
$('#human-blink').addEventListener('change', () => {
  $('#human-eyelid').style.display = $('#human-blink').checked ? 'block' : 'none';
  saveHumanConfig();
});

async function saveHumanConfig() {
  await api('/api/v1/digital_human', {
    method: 'POST',
    body: JSON.stringify({
      breath_speed: Number($('#breath-speed').value),
      swing_amplitude: Number($('#swing-amplitude').value),
      blink: $('#human-blink').checked,
    }),
  }).catch(() => {});
}

// 播放音频并逐帧回调振幅（0~1），驱动数字人"说话"
function playWithAmplitude(blob, onAmp) {
  return new Promise((resolve, reject) => {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    blob.arrayBuffer()
      .then((buf) => ctx.decodeAudioData(buf))
      .then((audioBuf) => {
        const src = ctx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(analyser);
        analyser.connect(ctx.destination);
        const data = new Uint8Array(analyser.fftSize);
        src.onended = () => { ctx.close().catch(() => {}); onAmp(0); resolve(); };
        src.start();
        (function loop() {
          if (ctx.state === 'closed') return;
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (const v of data) { const d = (v - 128) / 128; sum += d * d; }
          onAmp(Math.min(1, Math.sqrt(sum / data.length) * 6));
          requestAnimationFrame(loop);
        })();
      })
      .catch(reject);
  });
}

$('#human-speak').addEventListener('click', async () => {
  if (human.playing) return;
  const text = $('#human-text').value.trim();
  if (!text) return alert('请输入要让数字人说的话');
  human.playing = true;
  const btn = $('#human-speak');
  btn.disabled = true; btn.textContent = '合成中…';
  try {
    const blob = await synthTTS(text, $('#human-voice').value, '+0%');
    $('#human-stage').classList.add('speaking');
    setHumanStatus('说话中');
    btn.textContent = '说话中…';
    const sway = $('#human-sway');
    await playWithAmplitude(blob, (amp) => {
      sway.style.transform =
        `rotate(${(amp * human.swing).toFixed(2)}deg) translateY(${(-amp * 4).toFixed(1)}px)`;
    });
    sway.style.transform = '';
    $('#human-stage').classList.remove('speaking');
    setHumanStatus('待机中');
    api('/api/v1/digital_human/state', {
      method: 'POST', body: JSON.stringify({ speaking: false }),
    }).catch(() => {});
  } catch (e) {
    setHumanStatus(`出错: ${e.message}`);
    $('#human-stage').classList.remove('speaking');
  }
  btn.disabled = false; btn.textContent = '开口说话';
  human.playing = false;
});

// =========================================================== 平台接口页
async function loadPlatform() {
  try {
    const caps = await api('/api/v1/capabilities');
    const grid = $('#caps-grid');
    grid.innerHTML = '';
    caps.forEach((c) => {
      const card = document.createElement('div');
      card.className = 'cap-card';
      const badges = c.providers.map((p) =>
        `<span class="badge ${p.available ? 'on' : 'off'}">${p.title || p.name}${p.available ? ' ✓' : '（未启用）'}</span>`
      ).join('');
      card.innerHTML = `<h3>${c.title}</h3><p>${c.description}</p><div class="badges">${badges}</div>`;
      grid.appendChild(card);
    });

    const base = location.origin;
    $('#openai-doc').textContent =
`# Dify / Coze / OpenAI SDK 通用接入
BASE_URL = ${base}/v1
API_KEY  = ${'未配置 MCP_AGENT_API_TOKEN 时任意值均可（如 sk-anything）'}

curl ${base}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"mcp-agent","messages":[{"role":"user","content":"你好"}],"stream":true}'`;
    $('#api-doc').textContent =
`GET  /api/v1/capabilities                  能力发现（多模态能力清单）
GET  /api/v1/tts/voices?provider=edge-tts  TTS 音色列表
POST /api/v1/tts                           {"text","voice","rate"} → audio/mpeg
GET  /api/v1/digital_human                 数字人配置与状态
POST /api/v1/digital_human                 更新动画参数 {breath_speed, swing_amplitude, blink}
GET  /api/v1/digital_human/image           获取形象图
POST /api/v1/digital_human/image           multipart 上传形象图（字段 image）
POST /api/v1/digital_human/speak           {"text","voice"} → audio/mpeg（自动标记说话状态）
POST /api/v1/digital_human/state           {"speaking": false} 更新说话状态
POST /v1/chat/completions                  OpenAI 兼容对话（支持 stream）`;
  } catch (e) { /* 忽略 */ }
}
