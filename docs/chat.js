(function() {
  const chatHTML = `
  <style>
    #chat-fab {
      position: fixed; bottom: 28px; right: 28px;
      width: 54px; height: 54px;
      background: #4d9fff; border: none; border-radius: 50%;
      cursor: pointer; display: flex; align-items: center; justify-content: center;
      z-index: 9999;
      box-shadow: 0 4px 24px rgba(77,159,255,0.45);
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #chat-fab:hover { transform: scale(1.08); }
    #chat-fab svg { width: 24px; height: 24px; fill: white; pointer-events: none; }
    #chat-panel {
      position: fixed; bottom: 96px; right: 28px;
      width: 400px; max-height: 560px;
      background: #0e1118; border: 1px solid #2a3045; border-radius: 14px;
      display: flex; flex-direction: column; z-index: 9998;
      box-shadow: 0 16px 48px rgba(0,0,0,0.7);
      transform: translateY(20px); opacity: 0; pointer-events: none;
      transition: transform 0.25s ease, opacity 0.25s ease;
    }
    #chat-panel.open { transform: translateY(0); opacity: 1; pointer-events: all; }
    .ch-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #1e2330; flex-shrink: 0; }
    .ch-header-left { display: flex; align-items: center; gap: 10px; }
    .ch-icon { width: 28px; height: 28px; background: rgba(77,159,255,0.15); border: 1px solid rgba(77,159,255,0.3); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 14px; }
    .ch-title { font-family: monospace; font-size: 12px; font-weight: 700; color: #eef2ff; }
    .ch-sub { font-family: monospace; font-size: 10px; color: #5a6480; }
    .ch-close { background: none; border: none; color: #5a6480; cursor: pointer; font-size: 18px; padding: 4px; }
    .ch-close:hover { color: #eef2ff; }
    #ch-key-prompt { padding: 16px; display: flex; flex-direction: column; gap: 10px; }
    #ch-key-prompt p { font-size: 12px; color: #8090b0; line-height: 1.6; }
    #ch-key-input { background: #111318; border: 1px solid #1e2330; border-radius: 8px; color: #eef2ff; font-family: monospace; font-size: 12px; padding: 9px 12px; outline: none; width: 100%; }
    #ch-key-input:focus { border-color: #4d9fff; }
    #ch-key-save { background: #4d9fff; border: none; border-radius: 8px; color: white; cursor: pointer; padding: 10px; font-family: monospace; font-size: 12px; font-weight: 700; width: 100%; }
    #ch-messages { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; min-height: 180px; }
    .ch-msg { max-width: 90%; padding: 9px 13px; border-radius: 10px; font-size: 13px; line-height: 1.6; }
    .ch-msg.user { background: rgba(77,159,255,0.12); border: 1px solid rgba(77,159,255,0.2); color: #eef2ff; align-self: flex-end; }
    .ch-msg.assistant { background: #111318; border: 1px solid #1e2330; color: #c8d0e0; align-self: flex-start; }
    .ch-msg.thinking { background: #111318; border: 1px solid #1e2330; color: #5a6480; align-self: flex-start; font-family: monospace; font-size: 11px; display: flex; align-items: center; gap: 8px; }
    .ch-dots span { display: inline-block; width: 5px; height: 5px; background: #4d9fff; border-radius: 50%; animation: chDot 1.2s ease-in-out infinite; }
    .ch-dots span:nth-child(2) { animation-delay: 0.2s; }
    .ch-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes chDot { 0%,80%,100%{transform:scale(0.6);opacity:0.4;} 40%{transform:scale(1);opacity:1;} }
    .ch-suggestions { display: flex; flex-wrap: wrap; gap: 5px; padding: 0 14px 10px; }
    .ch-suggest { background: rgba(77,159,255,0.07); border: 1px solid rgba(77,159,255,0.2); border-radius: 20px; color: #4d9fff; font-family: monospace; font-size: 10px; padding: 4px 9px; cursor: pointer; }
    .ch-input-row { display: flex; gap: 8px; padding: 10px 14px 14px; border-top: 1px solid #1e2330; flex-shrink: 0; }
    #ch-input { flex: 1; background: #111318; border: 1px solid #1e2330; border-radius: 8px; color: #eef2ff; font-size: 13px; padding: 8px 11px; outline: none; resize: none; }
    #ch-input:focus { border-color: #4d9fff; }
    #ch-input::placeholder { color: #3a4060; }
    #ch-send { background: #4d9fff; border: none; border-radius: 8px; color: white; cursor: pointer; padding: 8px 13px; font-family: monospace; font-size: 12px; font-weight: 700; flex-shrink: 0; }
    #ch-send:disabled { opacity: 0.35; cursor: not-allowed; }
  </style>
  <button id="chat-fab" title="Ask Claude about today's market">
    <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12c0 1.85.5 3.58 1.37 5.07L2 22l4.93-1.37A9.94 9.94 0 0012 22c5.52 0 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
  </button>
  <div id="chat-panel">
    <div class="ch-header">
      <div class="ch-header-left">
        <div class="ch-icon">📊</div>
        <div><div class="ch-title">Market Analyst</div><div class="ch-sub">Loaded with today's report</div></div>
      </div>
      <button class="ch-close" id="ch-close-btn">✕</button>
    </div>
    <div id="ch-key-prompt" style="display:none">
      <p>Enter your Anthropic API key to enable live chat. Stored only in your browser.</p>
      <input id="ch-key-input" type="password" placeholder="sk-ant-..." />
      <button id="ch-key-save">Save & Start Chatting</button>
    </div>
    <div id="ch-main" style="display:none;flex-direction:column;flex:1;overflow:hidden">
      <div id="ch-messages"></div>
      <div class="ch-suggestions">
        <button class="ch-suggest" data-q="Why are ES and YM diverging?">ES/YM diverging?</button>
        <button class="ch-suggest" data-q="Re-analyze my ES long setup">Re-analyze ES setup</button>
        <button class="ch-suggest" data-q="Should I fade this open or let it run?">Fade or run?</button>
        <button class="ch-suggest" data-q="What is the key level to watch right now?">Key level now?</button>
      </div>
      <div class="ch-input-row">
        <textarea id="ch-input" rows="1" placeholder="Ask anything about today's market..."></textarea>
        <button id="ch-send">Send</button>
      </div>
    </div>
  </div>`;

  const wrapper = document.createElement('div');
  wrapper.innerHTML = chatHTML;
  document.body.appendChild(wrapper);

  let isOpen = false, isLoading = false, chatHistory = [];

  var contextEl = document.getElementById('morning-context');
  var dateEl = document.getElementById('report-date');
  var morningContext = contextEl ? JSON.parse(contextEl.textContent) : '';
  var reportDate = dateEl ? JSON.parse(dateEl.textContent) : new Date().toDateString();
  var SYSTEM_PROMPT = "You are an expert futures trading analyst in a trader's morning dashboard. Today is " + reportDate + ". Morning report context: " + morningContext + " Trader style: breakout/breakdown of key levels, mean reversion, VWAP structural breaks. ES and YM primary instruments. Answer like a sharp desk analyst — concise, specific, under 200 words.";

  document.getElementById('chat-fab').addEventListener('click', toggleChat);
  document.getElementById('ch-close-btn').addEventListener('click', toggleChat);
  document.getElementById('ch-key-save').addEventListener('click', saveKey);
  document.getElementById('ch-send').addEventListener('click', sendMessage);
  document.getElementById('ch-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  document.querySelectorAll('.ch-suggest').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.getElementById('ch-input').value = this.dataset.q;
      sendMessage();
    });
  });

  function toggleChat() {
    isOpen = !isOpen;
    document.getElementById('chat-panel').classList.toggle('open', isOpen);
    if (isOpen) { initChat(); setTimeout(function(){ var i=document.getElementById('ch-input'); if(i) i.focus(); }, 300); }
  }

  function initChat() {
    var key = localStorage.getItem('anthropic_key');
    document.getElementById('ch-key-prompt').style.display = key ? 'none' : 'flex';
    document.getElementById('ch-main').style.display = key ? 'flex' : 'none';
    if (key && chatHistory.length === 0) addMsg('assistant', "Morning. Full report loaded — futures, setups, earnings, econ calendar. What do you need?");
  }

  function saveKey() {
    var val = document.getElementById('ch-key-input').value.trim();
    if (!val.startsWith('sk-ant-')) { alert('Invalid key — should start with sk-ant-'); return; }
    localStorage.setItem('anthropic_key', val);
    document.getElementById('ch-key-prompt').style.display = 'none';
    document.getElementById('ch-main').style.display = 'flex';
    if (chatHistory.length === 0) addMsg('assistant', "Morning. Full report loaded — futures, setups, earnings, econ calendar. What do you need?");
  }

  function addMsg(role, content) {
    var msgs = document.getElementById('ch-messages');
    var div = document.createElement('div');
    div.className = 'ch-msg ' + role;
    div.innerHTML = content.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function addThinking() {
    var msgs = document.getElementById('ch-messages');
    var div = document.createElement('div');
    div.className = 'ch-msg thinking'; div.id = 'ch-thinking';
    div.innerHTML = 'Analyzing <span class="ch-dots"><span></span><span></span><span></span></span>';
    msgs.appendChild(div); msgs.scrollTop = msgs.scrollHeight;
  }

  function removeThinking() { var el = document.getElementById('ch-thinking'); if(el) el.remove(); }

  async function sendMessage() {
    var input = document.getElementById('ch-input');
    var sendBtn = document.getElementById('ch-send');
    var text = input.value.trim();
    if (!text || isLoading) return;
    var key = localStorage.getItem('anthropic_key');
    if (!key) { initChat(); return; }
    input.value = ''; isLoading = true; sendBtn.disabled = true;
    addMsg('user', text);
    chatHistory.push({ role: 'user', content: text });
    addThinking();
    try {
      var response = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model: 'claude-sonnet-4-20250514', max_tokens: 600, system: SYSTEM_PROMPT, messages: chatHistory })
      });
      removeThinking();
      if (!response.ok) {
        var err = await response.json();
        if (response.status === 401) { localStorage.removeItem('anthropic_key'); addMsg('assistant', 'API key invalid. Re-enter your key.'); }
        else { addMsg('assistant', 'Error: ' + (err && err.error ? err.error.message : response.statusText)); }
        chatHistory.pop();
      } else {
        var data = await response.json();
        var reply = data.content[0].text;
        addMsg('assistant', reply);
        chatHistory.push({ role: 'assistant', content: reply });
        if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);
      }
    } catch(e) { removeThinking(); addMsg('assistant', 'Network error — try again.'); chatHistory.pop(); }
    isLoading = false; sendBtn.disabled = false;
    document.getElementById('ch-input').focus();
  }
})();
