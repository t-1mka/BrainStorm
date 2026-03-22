/* BrainStorm game.js v6 — полная версия */
"use strict";

/* ── Helpers ── */
const $ = id => document.getElementById(id);
const qs = sel => document.querySelector(sel);
const qsa = sel => document.querySelectorAll(sel);
const on = (el, ev, fn) => el && el.addEventListener(ev, fn);

let socket;
window.addEventListener("DOMContentLoaded", () => {
  _initDuplicateTabGuard();
  socket = io();
  initSocket();
  initUI();
  setTimeout(_tryRejoin, 400);
});

/* ══ DUPLICATE TAB GUARD ══ */
const _TAB_KEY = "bs_active_tab";
const _TAB_ID  = Math.random().toString(36).slice(2);
let _isDuplicate = false;

function _initDuplicateTabGuard() {
  // Объявляем себя активной вкладкой
  try { localStorage.setItem(_TAB_KEY, _TAB_ID); } catch(_) {}

  // Слушаем когда другая вкладка объявляет себя активной
  window.addEventListener("storage", e => {
    if (e.key !== _TAB_KEY) return;
    if (e.newValue && e.newValue !== _TAB_ID) {
      // Другая вкладка активна — показываем предупреждение только если мы в комнате
      if (roomCode) _showDuplicateWarning();
    }
  });

  // Кнопка «Использовать эту вкладку»
  on($("duplicate-take-over"), "click", () => {
    try { localStorage.setItem(_TAB_KEY, _TAB_ID); } catch(_) {}
    _isDuplicate = false;
    const ov = $("duplicate-tab-overlay");
    if (ov) ov.style.display = "none";
  });

  // Перед закрытием — освобождаем слот
  window.addEventListener("beforeunload", () => {
    try {
      if (localStorage.getItem(_TAB_KEY) === _TAB_ID)
        localStorage.removeItem(_TAB_KEY);
    } catch(_) {}
  });
}

function _showDuplicateWarning() {
  _isDuplicate = true;
  const ov = $("duplicate-tab-overlay");
  if (ov) ov.style.display = "flex";
}

/* ══ REJOIN — восстановление сессии после перезагрузки ══ */
function _saveSession(code, name) {
  try {
    sessionStorage.setItem("bs_room", code);
    sessionStorage.setItem("bs_nick", name);
  } catch(_) {}
}
function _clearSession() {
  try { sessionStorage.removeItem("bs_room"); sessionStorage.removeItem("bs_nick"); } catch(_) {}
}
function _tryRejoin() {
  try {
    const code = sessionStorage.getItem("bs_room");
    const name = sessionStorage.getItem("bs_nick");
    if (code && name) {
      toast("🔄 Восстанавливаем сессию...", 2000);
      socket.emit("rejoin_room", { room_code: code, player_name: name });
    }
  } catch(_) {}
}

/* ══ STATE ══ */
let myScore = 0, isHost = false, isSpectator = false, roomCode = "", isSandbox = false;
let currentQ = null, timerInterval = null, timerSec = 30;
let isTester = false, isAdmin = false;
let presentationOn = false;   // локальный режим презентации
let rephraseUsed = false;     // использована ли перефразировка на текущем вопросе
let cheatFreeRephrase = false;
let animationsOn = localStorage.getItem("bs_anim") !== "off";

const CHEAT_NICK   = "pasha1778";
const TEAM_COLORS  = ["","#60a5fa","#f472b6","#34d399","#fbbf24","#a78bfa","#fb923c","#94a3b8"];
const AVATARS      = ["🧠","🦊","🐉","🦄","🐙","👾","🎭","🤖","🦁","🐻","🐧","🦅","🌟","🔥","💎","🎮","🏆","🌊","⚡","🎯"];
const LETTERS      = ["A","B","C","D","E","F"];
const MODE_DESCS   = {
  classic:   "🏆 Классика — каждый за себя.",
  ffa:       "⚡ FFA — только первый правильный ответ!",
  team:      "🤝 Командный — лидеры набирают команды.",
  lives:     "❤️ На вылет — 3 жизни.",
  coop:      "🌟 Кооп — общая победа!",
  svoyaigra: "🎯 Своя игра — выбирай категорию и стоимость вопроса!",
};
const RT_FACTS = [
  "💡 Самый быстрый ответ набирает бонусные очки!",
  "🔥 Серия из 3+ правильных ответов даёт стриковый бонус!",
  "🃏 Джокер убирает 2 неверных варианта. Стоит 100 очков.",
  "💡 Подсказка от AI стоит 75 очков.",
  "🧠 Адаптивная сложность реагирует на процент верных ответов.",
  "👻 Невидимые игроки не видны другим — только читеру и хосту.",
  "⭐ Бонус-вопрос даёт двойные очки!",
  "🎯 В «Своей игре» каждая ячейка открывается только один раз.",
];

/* ── Cheat flags ── */
let cheatSeeAnswer  = localStorage.getItem("c_see")    === "1";
let cheatEditScores = localStorage.getItem("c_scores")  === "1";
let cheatInfLives   = false;
let cheatInvisible  = false;

/* ── Sound prefs ── */
let soundEnabled   = localStorage.getItem("bs_sound")    !== "off";
let tickEnabled    = localStorage.getItem("bs_tick")     !== "off";
let confettiEnabled= localStorage.getItem("bs_confetti") !== "off";
let particlesOn    = localStorage.getItem("bs_particles") !== "off";
let eventSoundOn   = localStorage.getItem("bs_evtsound") !== "off";

/* ── Teams state ── */
let teamsData = {}, draftActive = false, draftTurn = 1, playersData = [];

/* ── Своя игра state ── */
let siBoard = null, siBoardMeta = null;

/* ── Profile ── */
let profile = JSON.parse(localStorage.getItem("bs_profile") || "null") || {
  name:"", avatar:"🧠", xp:0, games:0, wins:0, totalScore:0, history:[]
};

/* ── Theme init ── */
(function(){ document.body.className = localStorage.getItem("bs_theme") || "dark"; })();

/* ════════════ NEURAL NETWORK BACKGROUND ════════════ */
const NeuralBg = (function(){
  const cv  = document.getElementById("neural-canvas");
  if(!cv) return { pulse:()=>{} };
  const ctx = cv.getContext("2d");
  let W, H, nodes=[], raf;

  // Цвета нейронов
  const COL_NODE  = "rgba(139,92,246,";
  const COL_LINE  = "rgba(139,92,246,";
  const LINK_DIST = 130;
  const NODE_CNT  = 55;

  function makeNode(){
    return {
      x:  Math.random()*W,
      y:  Math.random()*H,
      vx: (Math.random()-.5)*.35,
      vy: (Math.random()-.5)*.35,
      r:  Math.random()*1.4+.6,
      a:  Math.random()*.7+.3,
      pulse: 0   // 0..1, затухающая вспышка
    };
  }

  function resize(){
    W = cv.width  = window.innerWidth;
    H = cv.height = window.innerHeight;
  }

  function draw(){
    if(!particlesOn){ ctx.clearRect(0,0,W,H); raf=requestAnimationFrame(draw); return; }
    ctx.clearRect(0,0,W,H);

    // Обновляем позиции
    for(const n of nodes){
      n.x+=n.vx; n.y+=n.vy;
      if(n.x<0)n.x=W; if(n.x>W)n.x=0;
      if(n.y<0)n.y=H; if(n.y>H)n.y=0;
      if(n.pulse>0) n.pulse=Math.max(0,n.pulse-.025);
    }

    // Рисуем связи
    for(let i=0;i<nodes.length;i++){
      const a=nodes[i];
      for(let j=i+1;j<nodes.length;j++){
        const b=nodes[j];
        const dx=a.x-b.x, dy=a.y-b.y;
        const dist=Math.sqrt(dx*dx+dy*dy);
        if(dist>LINK_DIST) continue;
        const t  = 1-dist/LINK_DIST;
        const glow = Math.max(a.pulse, b.pulse);
        let alpha  = t*.18 + glow*.45;
        ctx.strokeStyle = COL_LINE+alpha+")";
        ctx.lineWidth   = t*.8 + glow*1.2;
        ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
      }
    }

    // Рисуем узлы
    for(const n of nodes){
      const glow = n.pulse;
      if(glow>0.05){
        ctx.beginPath(); ctx.arc(n.x,n.y,n.r+glow*8,0,Math.PI*2);
        ctx.fillStyle=COL_NODE+(glow*.25)+")"; ctx.fill();
      }
      ctx.beginPath(); ctx.arc(n.x,n.y,n.r+glow*2,0,Math.PI*2);
      ctx.fillStyle=COL_NODE+(n.a*.7+glow*.3)+")"; ctx.fill();
    }

    raf=requestAnimationFrame(draw);
  }

  function pulse(color="#8b5cf6", intensity=1.0){
    // Активируем случайный кластер узлов
    const count = Math.floor(5+Math.random()*8);
    const chosen = nodes.slice().sort(()=>Math.random()-.5).slice(0,count);
    chosen.forEach((n,i)=>{
      setTimeout(()=>{
        n.pulse = Math.min(1, intensity);
        // Распространяем на соседей
        for(const nb of nodes){
          const dx=n.x-nb.x,dy=n.y-nb.y;
          if(Math.sqrt(dx*dx+dy*dy)<LINK_DIST*1.2)
            setTimeout(()=>{ nb.pulse=Math.min(nb.pulse,intensity*.5); },80);
        }
      }, i*60);
    });
    // DOM-кольцо в случайной точке
    if(chosen.length){
      const n0=chosen[0];
      const ring=document.createElement("div");
      ring.className="event-ring";
      const sz=40; ring.style.cssText=`width:${sz}px;height:${sz}px;left:${n0.x-sz/2}px;top:${n0.y-sz/2}px;border:2px solid ${color};`;
      document.body.appendChild(ring);
      setTimeout(()=>ring.remove(),850);
    }
  }

  resize();
  window.addEventListener("resize", resize);
  for(let i=0;i<NODE_CNT;i++) nodes.push(makeNode());
  raf=requestAnimationFrame(draw);

  return { pulse };
})();

/* ════════════ SOUND ════════════ */
let _audioCtx = null;
function getAudio(){ if(!_audioCtx) _audioCtx=new(window.AudioContext||window.webkitAudioContext)(); return _audioCtx; }
function playTone(freq, dur=.12, type="sine", vol=.18){
  if(!soundEnabled) return;
  try{
    const ctx=getAudio(),o=ctx.createOscillator(),g=ctx.createGain();
    o.type=type; o.frequency.value=freq;
    g.gain.setValueAtTime(vol,ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+dur);
    o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime+dur);
  }catch(_){}
}
const Sounds = {
  correct:    ()=>{ playTone(523,.12); setTimeout(()=>playTone(659,.12),110); setTimeout(()=>playTone(784,.18),220); },
  wrong:      ()=>{ playTone(330,.12,"sawtooth",.14); setTimeout(()=>playTone(220,.18,"sawtooth",.1),110); },
  win:        ()=>{ [523,659,784,1046].forEach((f,i)=>setTimeout(()=>playTone(f,.2),i*130)); },
  bonus_q:    ()=>{ [880,1100,1320,1540].forEach((f,i)=>setTimeout(()=>playTone(f,.1,"triangle",.13),i*80)); },
  streak:     ()=>{ [660,880,1100].forEach((f,i)=>setTimeout(()=>playTone(f,.1,"triangle",.12),i*80)); },
  joker:      ()=>{ playTone(1100,.08,"triangle",.12); setTimeout(()=>playTone(880,.08,"triangle",.1),90); },
  hint:       ()=>{ playTone(600,.1,"sine",.1); setTimeout(()=>playTone(750,.12,"sine",.1),100); },
  join:       ()=>{ if(!eventSoundOn)return; playTone(880,.08,"sine",.1); setTimeout(()=>playTone(1046,.1,"sine",.1),110); },
  leave:      ()=>{ if(!eventSoundOn)return; playTone(440,.12,"sine",.08); setTimeout(()=>playTone(330,.15,"sine",.07),110); },
  start:      ()=>{ if(!eventSoundOn)return; [523,659,784,988].forEach((f,i)=>setTimeout(()=>playTone(f,.15),i*70)); },
  create:     ()=>{ if(!eventSoundOn)return; playTone(880,.1,"sine",.12); setTimeout(()=>playTone(1046,.15,"sine",.12),120); },
  copy:       ()=>{ if(!eventSoundOn)return; playTone(1200,.06,"sine",.1); },
  draft:      ()=>{ if(!eventSoundOn)return; playTone(660,.1,"triangle",.12); },
  tick:       ()=>{ if(!tickEnabled) return; playTone(440,.06,"square",.07); },
  timer_5:    ()=>{ if(!tickEnabled) return; playTone(880,.1,"square",.14); },
  timer_warn: ()=>{ if(!tickEnabled) return; playTone(660,.06,"square",.09); },
  kick:       ()=>{ if(!eventSoundOn)return; playTone(200,.3,"sawtooth",.18); },
  rename:     ()=>{ if(!eventSoundOn)return; playTone(900,.08,"triangle",.1); },
  eliminate:  ()=>{ if(!eventSoundOn)return; playTone(200,.35,"sawtooth",.2); },
  chat_msg:   ()=>{ if(!eventSoundOn)return; playTone(880,.05,"sine",.06); },
  si_buzz:    ()=>{ playTone(1200,.12,"triangle",.2); },
  si_correct: ()=>{ [523,659,784,1046].forEach((f,i)=>setTimeout(()=>playTone(f,.15),i*100)); },
  si_wrong:   ()=>{ playTone(220,.3,"sawtooth",.2); },
};

/* ════════════ CONFETTI ════════════ */
function fireConfetti(){ if(!confettiEnabled||typeof confetti==="undefined")return; confetti({particleCount:90,spread:75,origin:{y:.6},colors:["#8b5cf6","#c084fc","#ffd700","#22c55e","#f472b6"]}); }
function fireMega(){ if(!confettiEnabled||typeof confetti==="undefined")return; const end=Date.now()+1400;(function f(){confetti({particleCount:7,angle:60,spread:55,origin:{x:0}});confetti({particleCount:7,angle:120,spread:55,origin:{x:1}});if(Date.now()<end)requestAnimationFrame(f);})(); }

/* ════════════ TOAST ════════════ */
function toast(msg, dur=3000){ const el=document.createElement("div");el.className="toast";el.textContent=msg;$("toasts").appendChild(el);setTimeout(()=>el.remove(),dur); }

/* ════════════ VIEWS ════════════ */
function showView(id){
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active","anim-enter"));
  const el=$(id); if(!el) return;
  el.classList.add("active");
  if(animationsOn) el.classList.add("anim-enter");
}

/* ════════════ TRANSITION OVERLAY ════════════ */
function transitionTo(id, label="") {
  if(!animationsOn){ showView(id); return; }
  const ov = $("transition-overlay");
  ov.innerHTML = `<div class="tov-content"><div style="font-size:1.5rem;font-family:var(--font-head);color:var(--accent)">${label}</div></div>`;
  ov.style.display = "flex"; ov.classList.add("active");
  setTimeout(()=>{ showView(id); ov.classList.remove("active"); setTimeout(()=>ov.style.display="none",350); }, 350);
}

/* ════════════ TOGGLE HELPER ════════════ */
function makeToggle(btn, initOn, onChange){
  if(!btn) return;
  btn.classList.toggle("on", !!initOn);
  btn.onclick = () => { const v = btn.classList.toggle("on"); if(onChange) onChange(v); };
}

/* ════════════ PROFILE ════════════ */
function saveProfile(){ localStorage.setItem("bs_profile", JSON.stringify(profile)); }
function calcLevel(xp){ return Math.max(1,Math.floor(Math.sqrt(xp/100))); }
function xpForLevel(l){ return l*l*100; }

function renderProfileModal(){
  const lvl=calcLevel(profile.xp),curXP=profile.xp-xpForLevel(lvl-1),needed=xpForLevel(lvl)-xpForLevel(lvl-1);
  $("profile-avatar-display").textContent = profile.avatar||"🧠";
  $("profile-name-display").textContent   = profile.name||"Игрок";
  // Ник-редактор
  const btnEdit=$("btn-edit-nick"), nickRow=$("nick-edit-row"), nickInp=$("nick-edit-input"), btnSave=$("btn-nick-save"), btnCancel=$("btn-nick-cancel");
  if(btnEdit && !btnEdit._initDone){
    btnEdit._initDone=true;
    btnEdit.onclick=()=>{ nickRow.style.display=(nickRow.style.display==="none"||!nickRow.style.display)?"block":"none"; if(nickInp){nickInp.value=profile.name||"";nickInp.focus();} };
    if(btnCancel) btnCancel.onclick=()=>{ nickRow.style.display="none"; };
    if(btnSave) btnSave.onclick=()=>{
      const newNick=(nickInp?nickInp.value:"").trim();
      if(!newNick||newNick.length<2){ toast("⚠️ Ник слишком короткий"); return; }
      if(newNick.length>20){ toast("⚠️ Ник слишком длинный (макс 20)"); return; }
      profile.name=newNick; saveProfile();
      $("profile-name-display").textContent=newNick;
      // Обновляем поля ввода на главном экране
      ["create-name","join-name","public-name"].forEach(id=>{ const el=$(id); if(el&&el.value===profile.name||!el?.value){}; if(el) el.value=newNick; });
      nickRow.style.display="none";
      toast("✅ Ник изменён: "+newNick);
    };
    if(nickInp) nickInp.addEventListener("keydown",e=>{ if(e.key==="Enter") btnSave?.click(); if(e.key==="Escape") btnCancel?.click(); });
  }
  $("profile-level-val").textContent       = lvl;
  $("profile-xp-fill").style.width         = Math.min(100,Math.round(curXP/needed*100))+"%";
  $("pstat-games").textContent = profile.games;
  $("pstat-wins").textContent  = profile.wins;
  $("pstat-score").textContent = profile.totalScore;
  const grid=$("avatar-grid"); grid.innerHTML="";
  for(const a of AVATARS){
    const b=document.createElement("button"); b.className="avatar-choice"+(a===profile.avatar?" selected":""); b.textContent=a;
    b.onclick=()=>{ profile.avatar=a; saveProfile(); $("profile-avatar-display").textContent=a; grid.querySelectorAll(".avatar-choice").forEach(x=>x.classList.remove("selected")); b.classList.add("selected"); };
    grid.appendChild(b);
  }
  const hist=$("history-list"); hist.innerHTML="";
  const entries=[...(profile.history||[])].reverse().slice(0,10);
  if(!entries.length) hist.innerHTML='<p class="muted" style="font-size:.85rem">Нет игр</p>';
  else entries.forEach(h=>{ const d=document.createElement("div");d.className="history-item";d.innerHTML=`<span class="history-date">${h.date||"—"}</span><span class="history-topic">${h.topic||"Игра"}</span><span class="history-score">+${h.score}</span>`;hist.appendChild(d); });
}

/* ════════════ MODALS ════════════ */
function openModal(id){ const m=$(id);if(!m)return; m.style.display="flex"; document.body.style.overflow="hidden"; if(id==="modal-leaderboard")loadLeaderboard(); if(id==="modal-profile")renderProfileModal(); if(id==="modal-settings")syncSettingsUI(); }
function closeModal(id){ const m=$(id);if(m)m.style.display="none"; document.body.style.overflow=""; }
function closeAllModals(){ document.querySelectorAll(".modal").forEach(m=>m.style.display="none"); document.body.style.overflow=""; }

/* ════════════ LEADERBOARD ════════════ */
async function loadLeaderboard(){
  $("lb-content").innerHTML='<p class="muted center" style="padding:20px 0">Загрузка...</p>';
  try{
    const data = await fetch("/api/leaderboard?n=20").then(r=>r.json());
    if(!data.length){ $("lb-content").innerHTML='<p class="muted center" style="padding:20px 0">Пока нет игроков</p>'; return; }
    const medals=["🥇","🥈","🥉"];
    $("lb-content").innerHTML=data.map((p,i)=>`<div class="lb-global-item"><span style="font-size:${i<3?'1.4':'1'}rem;min-width:32px;text-align:center">${medals[i]||(i+1)}</span><span style="flex:1;font-weight:700">${p.username}</span><span style="color:var(--text-muted);font-size:.8rem">${p.games_played} игр</span><span style="font-family:var(--font-mono);font-weight:700;color:var(--accent)">${p.total_score}</span></div>`).join("");
    if(profile.name) try{
      const r=await fetch(`/api/rank/${encodeURIComponent(profile.name)}`).then(r=>r.json());
      if(r&&r.rank){const el=$("lb-my-rank");el.style.display="";el.textContent=`📍 Ваше место: #${r.rank} · ${r.total_score||0} очков`;}
    }catch(_){}
  }catch(e){ $("lb-content").innerHTML='<p style="color:var(--red);text-align:center;padding:16px">Ошибка загрузки</p>'; }
}

/* ════════════ SETTINGS SYNC ════════════ */
function syncSettingsUI(){
  makeToggle($("toggle-theme"), document.body.classList.contains("dark"), v=>{ document.body.className=v?"dark":"light"; localStorage.setItem("bs_theme",v?"dark":"light"); });
  makeToggle($("toggle-sound"), soundEnabled, v=>{ soundEnabled=v; localStorage.setItem("bs_sound",v?"on":"off"); });
  makeToggle($("toggle-tick"), tickEnabled, v=>{ tickEnabled=v; localStorage.setItem("bs_tick",v?"on":"off"); });
  makeToggle($("toggle-confetti"), confettiEnabled, v=>{ confettiEnabled=v; localStorage.setItem("bs_confetti",v?"on":"off"); });
  makeToggle($("toggle-particles"), particlesOn, v=>{ particlesOn=v; localStorage.setItem("bs_particles",v?"on":"off"); });
  makeToggle($("toggle-event-sound"), eventSoundOn, v=>{ eventSoundOn=v; localStorage.setItem("bs_evtsound",v?"on":"off"); });
  makeToggle($("toggle-animations"), animationsOn, v=>{ animationsOn=v; localStorage.setItem("bs_anim",v?"on":"off"); });
}

/* ════════════ INIT UI ════════════ */
function initUI(){
  /* Toolbar */
  on($("btn-leaderboard"),"click",()=>openModal("modal-leaderboard"));
  on($("btn-profile"),    "click",()=>openModal("modal-profile"));
  on($("btn-settings"),   "click",()=>openModal("modal-settings"));

  /* Modal close */
  qsa(".modal-close").forEach(b=>{ b.onclick=()=>closeModal(b.dataset.modal); });
  qsa(".modal").forEach(m=>{ m.addEventListener("click",e=>{ if(e.target===m)closeModal(m.id); }); });

  /* Settings sidebar nav */
  qsa(".snav-btn").forEach(btn=>{
    btn.onclick=()=>{
      qsa(".snav-btn").forEach(b=>b.classList.remove("active"));
      qsa(".spage").forEach(p=>p.classList.remove("active"));
      btn.classList.add("active");
      const pg=$(btn.dataset.spage); if(pg) pg.classList.add("active");
    };
  });

  /* Admin subnav */
  qsa(".admin-snav-btn").forEach(btn=>{
    btn.onclick=()=>{
      qsa(".admin-snav-btn").forEach(b=>b.classList.remove("active"));
      qsa(".apage").forEach(p=>{ p.classList.remove("active"); p.style.display="none"; });
      btn.classList.add("active");
      const pg=$(btn.dataset.atab); if(pg){ pg.classList.add("active"); pg.style.display=""; }
      if(btn.dataset.atab==="apage-rooms")   loadAdminRooms();
      if(btn.dataset.atab==="apage-users")   loadAdminUsers();
      if(btn.dataset.atab==="apage-bans")    loadAdminBans();
    };
  });

  /* Main tabs */
  qsa(".tab-btn").forEach(btn=>{
    btn.onclick=()=>{
      qsa(".tab-btn").forEach(b=>b.classList.remove("active"));
      qsa(".tab-panel").forEach(p=>p.style.display="none");
      btn.classList.add("active");
      const panel=$("tab-"+btn.dataset.tab); if(panel) panel.style.display="";
      if(btn.dataset.tab==="public") loadPublicRooms();
    };
  });

  /* Toggles на главном экране */
  makeToggle($("toggle-public"), false, null);
  makeToggle($("toggle-sandbox"), false, null);

  /* Create / Join */
  on($("btn-create"), "click", handleCreate);
  on($("btn-join"),   "click", handleJoin);
  on($("btn-refresh-public"), "click", loadPublicRooms);
  ["create-name","join-name","public-name"].forEach(id=>{ const inp=$(id); if(inp&&!inp.value&&profile.name) inp.value=profile.name; });

  /* Lobby */
  on($("s-mode"),"change",()=>{
    const m=$("s-mode").value;
    if($("mode-desc")) $("mode-desc").textContent=MODE_DESCS[m]||"";
    if($("teams-panel")) $("teams-panel").style.display=m==="team"?"":"none";
    if(m==="team") renderTeamNamesInputs();
    if($("si-settings")) $("si-settings").style.display=m==="svoyaigra"?"":"none";
  });
  on($("btn-apply"),"click",()=>{
    const mode = $("s-mode").value;
    const settings = {
      topic:          $("s-topic").value,
      question_count: parseInt($("s-count").value),
      difficulty:     $("s-diff").value,
      num_options:    parseInt($("s-options").value),
      game_mode:      mode,
    };
    if(mode==="svoyaigra"){
      settings.si_categories = ($("si-categories").value||"").split(",").map(s=>s.trim()).filter(Boolean);
      settings.si_rows = parseInt($("si-rows").value||"5");
    }
    socket.emit("update_settings", settings);
    toast("✅ Настройки применены");
  });

  /* Режим презентации для хоста */
  makeToggle($("toggle-presentation-host"), false, v=>{
    socket.emit("set_presentation_mode", {enabled: v});
  });

  on($("btn-start"),       "click", ()=>socket.emit("start_game",{}));
  on($("btn-leave-lobby"), "click", ()=>{ _clearSession(); socket.emit("leave_room"); transitionTo("view-main","🏠"); resetLobbyUI(); Sounds.leave(); });
  on($("btn-copy"),        "click", ()=>{ navigator.clipboard.writeText(roomCode).then(()=>{ toast("📋 Скопирован"); Sounds.copy(); }); });
  on($("btn-share"),       "click", ()=>{
    const url=location.origin+"?room="+roomCode;
    if(navigator.share) navigator.share({title:"BrainStorm",url}).catch(()=>{});
    else navigator.clipboard.writeText(url).then(()=>toast("🔗 Ссылка скопирована"));
  });

  /* Teams */
  on($("team-count-select"),"change", renderTeamNamesInputs);
  on($("btn-init-teams"),   "click",  handleInitTeams);

  /* Game */
  on($("btn-joker"),    "click", ()=>{ socket.emit("use_joker"); $("btn-joker").disabled=true; Sounds.joker(); });
  on($("btn-hint"),     "click", ()=>{ socket.emit("get_hint"); Sounds.hint(); toast("💡 Запрашиваем подсказку..."); });
  on($("btn-rephrase"), "click", ()=>{
    if(rephraseUsed && !cheatFreeRephrase){ toast("⚠️ Уже использована перефразировка"); return; }
    socket.emit("rephrase_question", {}); toast("🔄 Перефразируем...");
    if(!cheatFreeRephrase){ rephraseUsed=true; $("rephrase-used").style.display=""; }
  });
  on($("btn-leave-game"),"click", ()=>{
    if(confirm("Выйти из игры?")){ stopTimer(); _clearSession(); socket.emit("leave_room"); transitionTo("view-main","🏠"); resetLobbyUI(); Sounds.leave(); }
  });

  /* Презентация в игре */
  on($("btn-pres-toggle"),"click", ()=>{
    if(isHost || isTester){
      // Хост и читер управляют глобально
      const next = !presentationOn;
      socket.emit("set_presentation_mode", {enabled: next});
    } else {
      // Обычный игрок — только локально
      presentationOn = !presentationOn;
      if($("presentation-overlay")) $("presentation-overlay").style.display = presentationOn ? "flex" : "none";
      $("btn-pres-toggle").textContent = presentationOn ? "❌" : "📺";
    }
  });

  qsa(".react-btn").forEach(b=>b.onclick=()=>socket.emit("reaction",{emoji:b.dataset.emoji}));

  /* Results */
  on($("btn-continue-squad"), "click", ()=>{ socket.emit("restart_room",{keep_scores:false,same_squad:true}); });
  on($("btn-restart"),   "click", ()=>socket.emit("restart_room",{keep_scores:false}));
  on($("btn-tournament"),"click", ()=>socket.emit("restart_room",{keep_scores:true}));
  on($("btn-again"),     "click", ()=>{ transitionTo("view-main","🏠"); resetLobbyUI(); });

  /* Cheat score btns */
  on($("cheat-score-minus"),"click",()=>{ if(!isTester)return; myScore=Math.max(0,myScore-50); $("g-score").textContent=myScore; socket.emit("cheat_update_score",{score:myScore}); });
  on($("cheat-score-plus"), "click",()=>{ if(!isTester)return; myScore+=50; $("g-score").textContent=myScore; socket.emit("cheat_update_score",{score:myScore}); });

  /* Чат */
  initChat();

  /* Admin */
  initAdminUI();

  initBgAnimations();

  /* Своя игра */
  initSvoyaigra();

  /* URL param */
  const code=new URLSearchParams(location.search).get("room");
  if(code){ qs('[data-tab="join"]')?.click(); setTimeout(()=>{ const inp=$("join-code"); if(inp) inp.value=code.toUpperCase(); },100); }

  /* Heartbeat */
  setInterval(()=>{ if(socket) socket.emit("heartbeat"); }, 30000);

  console.log("🧠 BrainStorm v5 ready!");
}

/* ════════════ CREATE / JOIN ════════════ */
function handleCreate(){
  const name=($("create-name").value||"").trim();
  if(!name){ $("create-name-error").style.display=""; return; }
  $("create-name-error").style.display="none";
  profile.name=name; saveProfile(); initCheatMenu(name);
  socket.emit("create_room",{player_name:name, is_public:!!$("toggle-public")?.classList.contains("on"), is_sandbox:!!$("toggle-sandbox")?.classList.contains("on")});
  Sounds.create();
}
function handleJoin(){
  const name=($("join-name").value||"").trim();
  const code=($("join-code").value||"").trim().toUpperCase();
  if(!name||!code){ $("join-error").style.display=""; return; }
  $("join-error").style.display="none";
  profile.name=name; saveProfile(); initCheatMenu(name);
  joinRoom(code, name, !!$("join-spectator")?.checked);
}
function joinRoom(code, name, spec){ socket.emit("join_room",{room_code:code,player_name:name,spectator:spec}); }

/* ════════════ PUBLIC ROOMS ════════════ */
async function loadPublicRooms(){
  const list=$("public-rooms-list"); if(!list) return;
  list.innerHTML='<p class="muted" style="font-size:.85rem">Загрузка...</p>';
  try{
    const rooms=await fetch("/api/public_rooms").then(r=>r.json());
    if(!rooms.length){ list.innerHTML='<p class="muted" style="font-size:.85rem">Нет публичных комнат. Создай первую!</p>'; return; }
    list.innerHTML="";
    for(const room of rooms){
      const item=document.createElement("div"); item.className="public-room-item";
      item.innerHTML=`<span class="public-room-code">${room.code}</span><span class="public-room-info">${room.topic||"Общие знания"} · ${room.mode}</span><span class="public-room-cnt">👥 ${room.players} · ${room.state==="playing"?"Идёт игра":"Ожидание"}</span>`;
      item.onclick=()=>{
        const name=($("public-name").value||"").trim();
        if(!name){ toast("⚠️ Введите имя"); $("public-name").focus(); return; }
        profile.name=name; saveProfile(); initCheatMenu(name);
        if(room.state==="playing"){ if(confirm("Игра идёт. Войти зрителем?")) joinRoom(room.code,name,true); }
        else joinRoom(room.code,name,false);
      };
      list.appendChild(item);
    }
  }catch(_){ list.innerHTML='<p class="muted" style="font-size:.85rem">Ошибка загрузки</p>'; }
}

/* ════════════ CHEAT MENU ════════════ */
function initCheatMenu(nick){
  isTester = nick.toLowerCase()===CHEAT_NICK;
  const btn=$("snav-cheat"); if(btn) btn.classList.toggle("snav-hidden",!isTester);
  if($("sandbox-row")) $("sandbox-row").style.display=isTester?"":"none";
  if(!isTester) return;

  makeToggle($("cheat-show-answer"), cheatSeeAnswer, v=>{ cheatSeeAnswer=v; localStorage.setItem("c_see",v?"1":"0"); });
  makeToggle($("cheat-edit-scores"), cheatEditScores, v=>{
    cheatEditScores=v; localStorage.setItem("c_scores",v?"1":"0");
    if($("cheat-score-btns")) $("cheat-score-btns").style.display=v?"":"none";
  });
  if($("cheat-score-btns")) $("cheat-score-btns").style.display=cheatEditScores?"":"none";

  makeToggle($("cheat-infinite-lives"), false, v=>{ cheatInfLives=v; socket.emit("cheat_set_infinite_lives",{enabled:v}); toast(v?"♾️ Бесконечные жизни вкл":"♾️ выкл"); });
  makeToggle($("cheat-invisible"),      false, v=>{ cheatInvisible=v; socket.emit("cheat_set_invisible",{enabled:v}); toast(v?"👻 Невидимка вкл":"👻 выкл"); });
  makeToggle($("cheat-free-rephrase"),  false, v=>{ cheatFreeRephrase=v; toast(v?"🔄 Бесплатные перефразировки вкл":"🔄 выкл"); });

  makeToggle($("cheat-presentation-global"), false, v=>{
    socket.emit("set_presentation_mode",{enabled:v});
    toast(v?"📡 Презентация вкл для всех":"📡 выкл");
  });

  // ── Новые читы ──
  on($("cheat-skip-btn"),"click",()=>{
    if(!isTester)return;
    socket.emit("cheat_skip_question",{});
    toast("⏭️ Вопрос пропущен");
    NeuralBg.pulse("#fbbf24",0.9);
  });
  on($("cheat-set-lives-btn"),"click",()=>{
    if(!isTester)return;
    const name=($("cheat-lives-player").value||"").trim();
    const lives=parseInt($("cheat-lives-count").value||"3",10);
    if(!name){toast("⚠️ Введи ник");return;}
    socket.emit("cheat_set_lives",{name,lives});
  });
  on($("cheat-add-score-all-btn"),"click",()=>{
    if(!isTester)return;
    const amount=parseInt($("cheat-add-score-amount").value||"100",10);
    socket.emit("cheat_add_score_all",{amount});
    toast(`💰 +${amount} всем`);
    NeuralBg.pulse("#34d399",0.8);
  });

  // Существующие действия
  on($("cheat-force-start-btn"),"click",()=>{ if(!isTester)return; socket.emit("cheat_force_start",{}); toast("🚀 Принудительный старт..."); });
  on($("cheat-teleport-btn"),"click",()=>{
    if(!isTester)return;
    const code=($("cheat-room-code").value||"").trim().toUpperCase();
    if(!code){ toast("⚠️ Введите код"); return; }
    socket.emit("cheat_teleport",{room_code:code,name:profile.name||CHEAT_NICK,spectator:false});
    closeAllModals();
  });
  on($("cheat-reset-player-btn"),"click",()=>{
    if(!isTester)return;
    const name=($("cheat-target-player").value||"").trim(); if(!name){toast("⚠️ Ник?");return;}
    socket.emit("cheat_reset_player",{name});
  });
  on($("cheat-global-reset-btn"),"click",()=>{
    if(!isTester)return;
    const nick=($("cheat-global-reset-nick").value||"").trim(); if(!nick){toast("⚠️ Ник?");return;}
    if(!confirm(`Сбросить статистику ${nick}?`))return;
    socket.emit("cheat_reset_global_stats",{username:nick});
  });
}

/* Cheat stats */
let _cheatStatsTimer = null;
function startCheatStats(){ if(!isTester||!roomCode)return; stopCheatStats(); _cheatStatsTimer=setInterval(async()=>{ if(!roomCode)return; try{const d=await fetch(`/api/cheat/room_stats/${roomCode}`).then(r=>r.json());renderCheatStats(d);}catch(_){};},2000); }
function stopCheatStats(){ if(_cheatStatsTimer){clearInterval(_cheatStatsTimer);_cheatStatsTimer=null;} }
function renderCheatStats(d){
  const el=$("cheat-answer-stats"); if(!el||!isTester)return;
  if(!d||!Object.keys(d.answer_counts||{}).length){el.textContent="Нет ответов пока";return;}
  const L=["A","B","C","D","E","F"];
  let html='<div style="display:flex;flex-direction:column;gap:4px">';
  for(const[idx,cnt] of Object.entries(d.answer_counts)){
    const names=(d.answer_players||{})[idx]||[];
    html+=`<div style="font-size:.78rem"><b>${L[idx]||idx}:</b> ${cnt}× — ${names.join(", ")}</div>`;
  }
  html+=`<div style="font-size:.75rem;color:var(--text-muted);margin-top:3px">Ответили: ${d.total_answered}/${d.total_active}</div></div>`;
  el.innerHTML=html;
}

/* ════════════ ADMIN UI ════════════ */
function initAdminUI(){
  on($("btn-admin-activate"),"click",async()=>{
    const key=($("admin-key-input").value||"").trim(); if(!key)return;
    const d=await fetch("/verify_admin",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key})}).then(r=>r.json()).catch(()=>({}));
    if(d.ok){ isAdmin=true; $("admin-key-section").style.display="none"; $("admin-panel-section").style.display=""; loadAdminRooms(); toast("✅ Администратор"); }
    else $("admin-key-error").style.display="";
  });
  on($("btn-admin-logout"),"click",()=>{ isAdmin=false; $("admin-key-section").style.display=""; $("admin-panel-section").style.display="none"; $("admin-key-input").value=""; });
  on($("btn-admin-refresh"),  "click", loadAdminRooms);
  on($("btn-admin-cleanup"), "click", async()=>{
    const d=await fetch("/api/admin/reset_server",{method:"POST"}).then(r=>r.json()).catch(()=>({}));
    toast(d.ok?`🧹 Удалено комнат: ${d.removed_rooms||0}`:"❌ Ошибка"); loadAdminRooms();
  });
  on($("admin-user-search-btn"),"click",loadAdminUsers);
  on($("admin-bans-refresh-btn"),"click",loadAdminBans);
  on($("admin-history-btn"),"click",()=>{ const c=($("admin-history-code").value||"").trim().toUpperCase(); if(c)loadAdminHistory(c); });
  on($("admin-reset-server-btn"),"click",async()=>{
    if(!confirm("Очистить?"))return;
    const d=await fetch("/api/admin/reset_server",{method:"POST"}).then(r=>r.json());
    toast(d.ok?`✅ Удалено: ${d.removed_rooms||0}`:"❌"); loadAdminRooms();
  });
  on($("admin-ban-btn"),"click",async()=>{
    const nick=($("admin-ban-nick").value||"").trim();
    const reason=($("admin-ban-reason").value||"").trim();
    const dur=parseInt($("admin-ban-duration").value||"60");
    if(!nick){toast("⚠️ Ник?");return;}
    const d=await fetch("/api/admin/ban",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({identifier:nick,reason,duration_minutes:dur})}).then(r=>r.json());
    toast(d.ok?"🚫 Забанен: "+nick:"❌"); loadAdminBans();
  });
  on($("admin-unban-btn"),"click",async()=>{
    const nick=($("admin-ban-nick").value||"").trim(); if(!nick){toast("⚠️ Ник?");return;}
    adminUnban(nick);
  });
  on($("admin-chat-send-btn"),"click",()=>{
    const code=($("admin-chat-code").value||"").trim().toUpperCase();
    const text=($("admin-chat-text").value||"").trim();
    if(!code||!text){toast("⚠️ Код и текст?");return;}
    socket.emit("admin_chat_system",{room_code:code,text}); $("admin-chat-text").value="";
  });
  on($("admin-pres-on-btn"), "click",()=>{ const c=($("admin-pres-code").value||"").trim().toUpperCase(); if(!c)return; socket.emit("admin_set_presentation",{room_code:c,enabled:true}); });
  on($("admin-pres-off-btn"),"click",()=>{ const c=($("admin-pres-code").value||"").trim().toUpperCase(); if(!c)return; socket.emit("admin_set_presentation",{room_code:c,enabled:false}); });
}

async function loadAdminRooms(){
  const list=$("admin-rooms-list"); if(!list)return;
  list.innerHTML='<p class="muted" style="font-size:.85rem">Загрузка...</p>';
  try{
    const rooms=await fetch("/api/admin/rooms").then(r=>r.json());
    if(!rooms.length){list.innerHTML='<p class="muted" style="font-size:.85rem">Нет комнат</p>';return;}
    list.innerHTML="";
    for(const r of rooms){
      const item=document.createElement("div"); item.className="public-room-item";
      item.style.cssText="flex-direction:column;align-items:flex-start;gap:6px;cursor:default";
      item.innerHTML=`
        <div style="display:flex;gap:8px;align-items:center;width:100%">
          <span class="public-room-code">${r.code}</span>
          <span class="public-room-info">${r.mode}·${r.state}${r.is_sandbox?' 🏖':''}${r.is_public?' 🌐':''}</span>
          <span class="public-room-cnt">👥${r.players}</span>
          ${r.idle_secs>60?`<span style="font-size:.72rem;color:var(--red)">⏳${Math.round(r.idle_secs/60)}м</span>`:''}
        </div>
        <div style="font-size:.78rem;color:var(--text-muted)">Хост: ${r.host||"—"} · ${r.topic||"—"}</div>
        <div style="display:flex;gap:5px;flex-wrap:wrap">
          <button class="btn btn-sm btn-secondary" onclick="adminJoinRoom('${r.code}',true)">👁 Зритель</button>
          <button class="btn btn-sm btn-secondary" onclick="adminJoinRoom('${r.code}',false)">🎮 Войти</button>
          <button class="btn btn-sm btn-danger"    onclick="adminTakeHost('${r.code}')">👑 Хост</button>
          <button class="btn btn-sm btn-secondary" onclick="adminTransferHostUI('${r.code}')">↗ Передать</button>
          <button class="btn btn-sm btn-danger"    onclick="adminForceEnd('${r.code}')">⛔ Стоп</button>
          <button class="btn btn-sm btn-danger"    onclick="adminKickUI('${r.code}')">👢 Кик</button>
          <button class="btn btn-sm btn-secondary" onclick="adminBanRoomPlayerUI('${r.code}')">🚫 Бан</button>
          <button class="btn btn-sm btn-secondary" onclick="adminHistoryUI('${r.code}')">📜</button>
        </div>`;
      list.appendChild(item);
    }
  }catch(e){list.innerHTML='<p style="color:var(--red);font-size:.85rem">Ошибка</p>';}
}

async function loadAdminUsers(){
  const filter=($("admin-user-filter").value||"").trim();
  const list=$("admin-users-list"); if(!list)return;
  list.innerHTML='<p class="muted" style="font-size:.85rem">Загрузка...</p>';
  try{
    const users=await fetch(`/api/admin/users?nick=${encodeURIComponent(filter)}`).then(r=>r.json());
    if(!users.length){list.innerHTML='<p class="muted" style="font-size:.85rem">Нет</p>';return;}
    list.innerHTML="";
    for(const u of users.slice(0,30)){
      const item=document.createElement("div"); item.className="public-room-item";
      item.style.cssText="flex-direction:column;align-items:flex-start;gap:4px;cursor:default";
      const ls=u.last_seen?new Date(u.last_seen*1000).toLocaleDateString("ru-RU"):"—";
      const tt=u.total_time?Math.round(u.total_time/60)+"мин":"—";
      item.innerHTML=`<div style="display:flex;gap:8px;align-items:center;width:100%"><span style="flex:1;font-weight:700">${u.username}</span><span style="font-size:.75rem;color:var(--text-muted)">${u.wins}🏆 ${u.games_played}🎮</span><span style="font-family:var(--font-mono);color:var(--accent)">${u.total_score}</span></div><div style="font-size:.74rem;color:var(--text-muted)">Вход: ${ls} · Время: ${tt}</div><div style="display:flex;gap:5px"><button class="btn btn-sm btn-secondary" onclick="adminResetUser('${u.username}')">🗑 Сброс</button><button class="btn btn-sm btn-danger" onclick="adminBanFromList('${u.username}')">🚫 Бан</button></div>`;
      list.appendChild(item);
    }
  }catch(e){list.innerHTML='<p style="color:var(--red);font-size:.85rem">Ошибка</p>';}
}

async function loadAdminBans(){
  const list=$("admin-bans-list"); if(!list)return;
  list.innerHTML='<p class="muted" style="font-size:.85rem">Загрузка...</p>';
  try{
    const bans=await fetch("/api/admin/bans").then(r=>r.json());
    if(!bans.length){list.innerHTML='<p class="muted" style="font-size:.85rem">Нет банов</p>';return;}
    list.innerHTML="";
    for(const b of bans){
      const exp=new Date(b.expires_at*1000).toLocaleString("ru-RU");
      const item=document.createElement("div"); item.className="public-room-item";
      item.style.cssText="flex-direction:column;align-items:flex-start;gap:4px;cursor:default";
      item.innerHTML=`<div style="font-weight:700;color:var(--red)">${b.identifier}</div><div style="font-size:.75rem;color:var(--text-muted)">${b.reason||"—"} · до ${exp}</div><button class="btn btn-sm btn-secondary" onclick="adminUnban('${b.identifier}')">✅ Разбан</button>`;
      list.appendChild(item);
    }
  }catch(e){list.innerHTML='<p style="color:var(--red);font-size:.85rem">Ошибка</p>';}
}

async function loadAdminHistory(code){
  const list=$("admin-history-list"); if(!list)return;
  list.innerHTML='<p class="muted" style="font-size:.85rem">Загрузка...</p>';
  try{
    const hist=await fetch(`/api/admin/room_history/${code}`).then(r=>r.json());
    if(!hist.length){list.innerHTML='<p class="muted" style="font-size:.85rem">История не найдена</p>';return;}
    list.innerHTML="";
    for(const h of hist){
      const date=new Date(h.played_at*1000).toLocaleString("ru-RU");
      const dur=Math.round((h.duration||0)/60)+"мин";
      const ps=(h.players||[]).map(p=>`${p.name}:${p.score}`).join(", ");
      const item=document.createElement("div"); item.className="public-room-item";
      item.style.cssText="flex-direction:column;align-items:flex-start;gap:4px;cursor:default";
      item.innerHTML=`<div style="font-size:.78rem;color:var(--text-muted)">${date} · ${dur} · ${h.mode}</div><div style="font-size:.82rem"><b>Тема:</b> ${h.topic||"—"}</div><div style="font-size:.75rem;color:var(--text-muted)">${ps}</div><details style="width:100%"><summary style="cursor:pointer;font-size:.75rem;color:var(--accent)">Вопросы (${(h.questions||[]).length})</summary><div style="max-height:130px;overflow-y:auto;font-size:.73rem;color:var(--text-muted);margin-top:5px">${(h.questions||[]).map((q,i)=>`<div><b>${i+1}.</b> ${q.question||""}</div>`).join("")}</div></details>`;
      list.appendChild(item);
    }
  }catch(e){list.innerHTML='<p style="color:var(--red);font-size:.85rem">Ошибка</p>';}
}

async function adminUnban(nick){ const d=await fetch("/api/admin/unban",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({identifier:nick})}).then(r=>r.json()); toast(d.ok?"✅ Разбан: "+nick:"❌"); loadAdminBans(); }
async function adminResetUser(u){ if(!confirm(`Сбросить ${u}?`))return; const d=await fetch("/api/admin/reset_user",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:u})}).then(r=>r.json()); toast(d.ok?"✅ Сброс: "+u:"❌"); loadAdminUsers(); }
function adminBanFromList(nick){ if($("admin-ban-nick")) $("admin-ban-nick").value=nick; qs("[data-atab='apage-bans']")?.click(); }
function adminBanRoomPlayerUI(code){ const n=prompt(`Бан игрока из ${code}. Имя:`); if(!n)return; const r=prompt("Причина:")||""; const m=parseInt(prompt("Минут:")||"60"); socket.emit("admin_ban_player",{room_code:code,player_name:n.trim(),reason:r,duration_minutes:m}); }
function adminJoinRoom(code, asSpectator){
  // Сохраняем текущий ник — не меняем
  const name = profile.name || ("Admin_"+Math.floor(Math.random()*900+100));
  closeAllModals();
  socket.emit("join_room",{room_code:code, player_name:name, spectator:!!asSpectator, as_admin:true});
  toast(asSpectator ? "👁 Входим зрителем..." : "🔑 Входим игроком...");
}
function adminTakeHost(code){ socket.emit("admin_take_host",{room_code:code}); }
function adminForceEnd(code){ if(!confirm(`Завершить ${code}?`))return; socket.emit("admin_force_end_game",{room_code:code}); }
function adminKickUI(code){ const n=prompt(`Кик из ${code}. Имя:`); if(n) socket.emit("admin_kick_player",{room_code:code,player_name:n.trim()}); }
function adminTransferHostUI(code){ const n=prompt(`Передать хост в ${code}. Новый хост:`); if(n) socket.emit("admin_transfer_host",{room_code:code,player_name:n.trim()}); }
function adminHistoryUI(code){ qs("[data-atab='apage-history']")?.click(); if($("admin-history-code")) $("admin-history-code").value=code; loadAdminHistory(code); }

Object.assign(window,{adminUnban,adminResetUser,adminBanFromList,adminBanRoomPlayerUI,adminJoinRoom,adminTakeHost,adminForceEnd,adminKickUI,adminTransferHostUI,adminHistoryUI});

/* ════════════ LOBBY HELPERS ════════════ */
function resetLobbyUI(){
  roomCode=""; isHost=false; isSpectator=false; isSandbox=false; teamsData={}; draftActive=false; playersData=[];
  presentationOn=false; siBoard=null; siBoardMeta=null;
  if($("lobby-code")) $("lobby-code").textContent="------";
  if($("players-list")) $("players-list").innerHTML="";
  if($("players-count")) $("players-count").textContent="(0)";
  if($("host-settings")) $("host-settings").style.display="none";
  if($("guest-settings")) $("guest-settings").style.display="none";
  if($("btn-start")) $("btn-start").style.display="none";
  if($("btn-leave-lobby")) $("btn-leave-lobby").style.display="none";
  if($("teams-panel")) $("teams-panel").style.display="none";
  if($("sandbox-badge")) $("sandbox-badge").style.display="none";
  if($("team-board")) $("team-board").style.display="none";
  if($("presentation-overlay")) $("presentation-overlay").style.display="none";
  if($("chat-messages")) $("chat-messages").innerHTML="";
  stopCheatStats(); _stopWaitingTips();
}

/* ── Советы во время ожидания ── */
const LOBBY_TIPS = [
  "💡 Самый быстрый правильный ответ получает бонусные очки за скорость!",
  "🔥 3 правильных ответа подряд активируют стриковый бонус!",
  "🃏 Джокер убирает два неверных варианта — стоит 100 очков.",
  "💭 Подсказка от AI стоит 75 очков. Используй мудро!",
  "🔄 Перефразировка вопроса поможет, если формулировка непонятна.",
  "🧠 Адаптивная сложность подстраивается под процент верных ответов.",
  "⭐ Бонус-вопросы попадаются случайно — они дают двойные очки!",
  "👻 В режиме «Невидимка» тебя не видят другие игроки.",
  "🏆 В режиме «Кооп» все получают одинаковые очки за правильный ответ.",
  "❤️ В режиме «На вылет» три ошибки — и ты выбываешь!",
];
let _tipTimer = null, _tipIdx = 0;
function _startWaitingTips(){
  _stopWaitingTips();
  _tipIdx = Math.floor(Math.random() * LOBBY_TIPS.length);
  function showTip(){
    const el = $("waiting-tip"); if(!el) return;
    el.style.opacity="0";
    setTimeout(()=>{ el.textContent=LOBBY_TIPS[_tipIdx % LOBBY_TIPS.length]; el.style.opacity="1"; _tipIdx++; },300);
  }
  showTip();
  _tipTimer = setInterval(showTip, 6000);
}
function _stopWaitingTips(){ if(_tipTimer){ clearInterval(_tipTimer); _tipTimer=null; } }

/* ════════════ 🧠 BRAIN REFLEX MINI-GAME ════════════ */
(function(){
  let W=340, H=180, ctx, nodes=[], active=[], pts=0, streak=0, best=0;
  let gameRunning=false, spawnTimer=null, countdownTimer=null, timeLeft=30;

  const COLORS = ["#8b5cf6","#c084fc","#34d399","#fbbf24","#f472b6","#60a5fa"];
  const MAX_NODES = 7;

  function init(){
    const cv=$("reflex-canvas"); if(!cv) return;
    ctx=cv.getContext("2d");
    const rect=cv.getBoundingClientRect();
    W=rect.width||340; H=cv.offsetHeight||180;
    cv.width=Math.round(W*window.devicePixelRatio||1);
    cv.height=Math.round(H*window.devicePixelRatio||1);
    ctx.scale(window.devicePixelRatio||1, window.devicePixelRatio||1);
    cv.addEventListener("click",  e=>_onTap(e.offsetX, e.offsetY));
    cv.addEventListener("touchend",e=>{ e.preventDefault(); const t=e.changedTouches[0]; const r=cv.getBoundingClientRect(); _onTap(t.clientX-r.left, t.clientY-r.top); },{passive:false});
    on($("reflex-start-btn"),"click", startGame);
    _drawIdle();
  }

  function startGame(){
    if(gameRunning) return;
    gameRunning=true; pts=0; streak=0; timeLeft=30; active=[];
    const btn=$("reflex-start-btn"); if(btn) btn.textContent="⏱ "+timeLeft+"s";
    _updateUI();
    // Спавн нейрона каждые 900 мс
    spawnTimer = setInterval(()=>{
      if(active.length < MAX_NODES) _spawnNode();
      _tick();
    }, 900);
    // Обратный отсчёт
    countdownTimer = setInterval(()=>{
      timeLeft--;
      const btn=$("reflex-start-btn"); if(btn) btn.textContent="⏱ "+timeLeft+"s";
      if(timeLeft<=0) endGame();
    }, 1000);
    requestAnimationFrame(_loop);
  }

  function endGame(){
    gameRunning=false;
    clearInterval(spawnTimer); clearInterval(countdownTimer);
    if(pts > best){ best=pts; if($("reflex-best"))$("reflex-best").textContent=best; }
    const btn=$("reflex-start-btn"); if(btn) btn.textContent="▶ Ещё раз!";
    // Flash message
    toast(`🧠 Игра окончена! Очков: ${pts}`, 2500);
    NeuralBg.pulse("#fbbf24",1.0);
  }

  function _spawnNode(){
    const margin=30;
    active.push({
      x: margin + Math.random()*(W-margin*2),
      y: margin + Math.random()*(H-margin*2),
      r: 16+Math.random()*10,
      color: COLORS[Math.floor(Math.random()*COLORS.length)],
      life: 1.0,   // 1→0 за 2.5 сек
      decay: 0.012 + Math.random()*0.008,
      pulse: 0,
    });
  }

  function _tick(){
    active = active.filter(n => n.life > 0);
    active.forEach(n => { n.life -= n.decay; n.pulse = (n.pulse+0.12)%(Math.PI*2); });
  }

  function _onTap(x, y){
    if(!gameRunning) return;
    let hit=false;
    for(let i=active.length-1;i>=0;i--){
      const n=active[i];
      const d=Math.hypot(x-n.x, y-n.y);
      if(d < n.r+4){
        active.splice(i,1);
        // Score = base + speed bonus (faster click on fresh neuron = more pts)
        const bonus = Math.floor(n.life*100);
        const gained = 10 + bonus;
        pts += gained; streak++;
        _flashScore(x,y,"+"+gained);
        if(streak>=5) { pts+=20; toast("🔥 Серия "+streak+"! +20",1200); NeuralBg.pulse("#fbbf24",0.7); }
        hit=true; break;
      }
    }
    if(!hit){ streak=0; _flashScore(x,y,"miss",true); }
    _updateUI();
  }

  function _flashScore(x,y,text,miss=false){
    const cv=$("reflex-canvas"); if(!cv) return;
    // Draw a quick floating label via temporary DOM
    const el=document.createElement("div");
    const rect=cv.getBoundingClientRect();
    el.style.cssText=`position:fixed;left:${rect.left+x}px;top:${rect.top+y-10}px;font-size:.85rem;font-weight:700;color:${miss?"#f87171":"#34d399"};pointer-events:none;z-index:999;transition:transform .6s,opacity .6s`;
    el.textContent=text;
    document.body.appendChild(el);
    requestAnimationFrame(()=>{ el.style.transform="translateY(-30px)"; el.style.opacity="0"; });
    setTimeout(()=>el.remove(),650);
  }

  function _updateUI(){
    if($("reflex-pts"))    $("reflex-pts").textContent=pts;
    if($("reflex-streak")) $("reflex-streak").textContent=streak;
  }

  let _raf;
  function _loop(){
    if(!gameRunning) return;
    _draw();
    _raf=requestAnimationFrame(_loop);
  }

  function _drawIdle(){
    if(!ctx) return;
    ctx.clearRect(0,0,W,H);
    ctx.fillStyle="rgba(139,92,246,0.08)"; ctx.fillRect(0,0,W,H);
    ctx.fillStyle="rgba(139,92,246,0.3)";
    ctx.font="bold 13px var(--font-body,sans-serif)";
    ctx.textAlign="center"; ctx.textBaseline="middle";
    ctx.fillText("Нажми ▶ Старт",W/2,H/2);
  }

  function _draw(){
    if(!ctx) return;
    ctx.clearRect(0,0,W,H);
    ctx.fillStyle="rgba(11,7,32,0.6)"; ctx.fillRect(0,0,W,H);

    for(const n of active){
      const alpha=n.life;
      const glow=0.5+0.5*Math.sin(n.pulse);
      // Outer glow
      const g=ctx.createRadialGradient(n.x,n.y,0,n.x,n.y,n.r*2);
      g.addColorStop(0, n.color.replace(")",`,${alpha*0.5})`).replace("rgb","rgba"));
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.beginPath(); ctx.arc(n.x,n.y,n.r*2,0,Math.PI*2);
      ctx.fillStyle=g; ctx.fill();
      // Core circle
      ctx.beginPath(); ctx.arc(n.x,n.y,n.r*(0.8+0.2*glow),0,Math.PI*2);
      ctx.fillStyle=n.color+(Math.round(alpha*180).toString(16).padStart(2,"0"));
      ctx.fill();
      // Ring pulse
      ctx.beginPath(); ctx.arc(n.x,n.y,n.r*(1+glow*.4),0,Math.PI*2);
      ctx.strokeStyle=n.color+(Math.round(alpha*100).toString(16).padStart(2,"0"));
      ctx.lineWidth=2; ctx.stroke();
      // Life bar arc
      ctx.beginPath();
      ctx.arc(n.x,n.y,n.r+5,-Math.PI/2,-Math.PI/2+Math.PI*2*alpha);
      ctx.strokeStyle=n.color; ctx.lineWidth=2.5; ctx.stroke();
    }

    // Timer bar at top
    if(gameRunning){
      const tw=(timeLeft/30)*W;
      const tc=timeLeft>10?"#34d399":timeLeft>5?"#fbbf24":"#f87171";
      ctx.fillStyle=tc+(Math.round(0.35*255).toString(16));
      ctx.fillRect(0,0,tw,4);
    }
  }

  // Инициализируем после загрузки DOM
  if(document.readyState==="loading")
    document.addEventListener("DOMContentLoaded",init);
  else
    setTimeout(init,100);
})();



function applyGuestSettings(s){
  if($("gs-topic")) $("gs-topic").textContent=s.topic||"—";
  if($("gs-count")) $("gs-count").textContent=s.question_count||"—";
  if($("gs-diff"))  $("gs-diff").textContent={easy:"Лёгкая",medium:"Средняя",hard:"Сложная"}[s.difficulty]||s.difficulty||"—";
  if($("gs-mode"))  $("gs-mode").textContent={classic:"Классика",ffa:"FFA",team:"Командный",lives:"На вылет",coop:"Кооп",svoyaigra:"Своя игра"}[s.game_mode]||s.game_mode||"—";
  if($("teams-panel")) $("teams-panel").style.display=s.game_mode==="team"?"":"none";
}

/* ════════════ TEAMS UI ════════════ */
function renderTeamNamesInputs(){
  const cnt=parseInt($("team-count-select")?.value||"2");
  const div=$("team-names-inputs"); if(!div)return; div.innerHTML="";
  for(let i=1;i<=cnt;i++){
    const inp=document.createElement("input"); inp.className="team-name-inp";
    inp.placeholder=`Команда ${i}`; inp.id=`team-name-${i}`;
    inp.value=teamsData[i]?.name||`Команда ${i}`; div.appendChild(inp);
  }
}
function handleInitTeams(){
  const cnt=parseInt($("team-count-select")?.value||"2");
  const names=[]; for(let i=1;i<=cnt;i++) names.push(($(`team-name-${i}`)?.value||`Команда ${i}`).trim());
  const draft=($("team-draft-mode")?.value||"auto")==="draft";
  socket.emit("init_teams",{count:cnt,names,draft_mode:draft}); toast("⚡ Команды создаются..."); Sounds.draft();
}
function renderTeamsDisplay(teams,draft=false,draftTurnId=1){
  const div=$("teams-list-display"); if(!div)return; div.innerHTML="";
  const grid=document.createElement("div"); grid.className="teams-grid";
  for(const t of Object.values(teams)){
    const card=document.createElement("div"); card.className="team-card";
    const color=TEAM_COLORS[t.id]||"#888";
    card.innerHTML=`<div class="team-card-header"><div class="team-color-dot" style="background:${color}"></div><div class="team-card-name">${t.name}</div>${draft&&t.id===draftTurnId?'<span style="font-size:.72rem;background:rgba(251,191,36,0.2);color:var(--gold);padding:2px 8px;border-radius:20px;margin-left:auto">Выбирает 👆</span>':''}</div><div class="team-card-members" id="team-members-${t.id}"></div>`;
    grid.appendChild(card);
  }
  div.appendChild(grid);
  for(const t of Object.values(teams)){
    const md=$(`team-members-${t.id}`); if(!md)continue;
    for(const sid of (t.members||[])){
      const p=playersData.find(pl=>pl.sid===sid); if(!p)continue;
      const chip=document.createElement("span"); chip.className="team-member-chip"+(t.leader_sid===sid?" captain":"");
      chip.textContent=(t.leader_sid===sid?"⭐ ":"")+p.name; md.appendChild(chip);
    }
  }
}
function renderDraftPanel(teams,draftTurnId){
  const panel=$("draft-panel"); if(!panel)return;
  const curTeam=teams[draftTurnId]; if(!curTeam){panel.style.display="none";return;}
  panel.style.display="";
  if($("draft-turn-label")) $("draft-turn-label").textContent=`👆 Очередь команды "${curTeam.name}" выбирать игрока`;
  const avail=$("draft-available-players"); if(!avail)return; avail.innerHTML="";
  const taken=new Set(Object.values(teams).flatMap(t=>t.members||[]));
  const available=playersData.filter(p=>!p.is_spectator&&!taken.has(p.sid)&&!Object.values(teams).some(t=>t.leader_sid===p.sid));
  if(!available.length){avail.innerHTML='<p class="muted" style="font-size:.82rem">Все распределены</p>';return;}
  for(const p of available){
    const btn=document.createElement("button"); btn.className="draft-player-btn"; btn.textContent=p.name;
    btn.onclick=()=>{ socket.emit("draft_pick",{target_sid:p.sid}); Sounds.draft(); }; avail.appendChild(btn);
  }
}

/* ════════════ PLAYERS LIST ════════════ */
function hashCode(s){ let h=0; for(let i=0;i<s.length;i++) h=Math.imul(31,h)+s.charCodeAt(i)|0; return h; }
function renderPlayersList(players){
  playersData=players;
  const ul=$("players-list"); if(!ul)return; ul.innerHTML="";
  if($("players-count")) $("players-count").textContent=`(${players.filter(p=>!p.is_spectator).length})`;
  for(const p of players){
    const li=document.createElement("li"); li.className="player-item";
    const avatar=AVATARS[Math.abs(hashCode(p.name))%AVATARS.length];
    const color=p.team?TEAM_COLORS[p.team]||"#888":"";
    const teamBadge=p.team&&teamsData[p.team]?`<span class="player-badge" style="background:rgba(0,0,0,0.2);border:1px solid ${color};color:${color}">${teamsData[p.team]?.name||'Команда '+p.team}</span>`:"";
    const avatarEl=isTester
      ?`<div class="player-avatar cheat-avatar" title="Переименовать" onclick="cheatRenamePlayerUI('${p.sid}','${p.name.replace(/'/g,"\\'")}')"> ${avatar}</div>`
      :`<div class="player-avatar">${avatar}</div>`;
    li.innerHTML=`${avatarEl}<span class="player-name">${p.name}</span>${p.is_host?'<span class="player-badge host">Хост</span>':""}<span>${p.is_spectator?'<span class="player-badge spectator">Зритель</span>':""}</span>${teamBadge}${p.is_invisible?'<span class="player-badge" style="opacity:.6">👻</span>':""}`;
    ul.appendChild(li);
  }
}
function cheatRenamePlayerUI(sid,oldName){
  if(!isTester)return;
  const newName=prompt(`Новое имя для ${oldName}:`); if(!newName||!newName.trim())return;
  socket.emit("cheat_rename_player",{target_sid:sid,new_name:newName.trim()}); Sounds.rename();
}
window.cheatRenamePlayerUI=cheatRenamePlayerUI;

/* ════════════ ЧАТ ════════════ */
function initChat(){
  on($("chat-send-btn"),"click", sendChat);
  on($("chat-input"),"keydown", e=>{ if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); sendChat(); } });
  on($("btn-chat-clear"),"click",()=>{ if(confirm("Очистить чат?")) socket.emit("chat_clear",{}); });
}
function sendChat(){
  const inp=$("chat-input"); if(!inp)return;
  const text=inp.value.trim(); if(!text)return;
  socket.emit("chat_message",{text}); inp.value="";
}
function renderChatMsg(msg){
  const box=$("chat-messages"); if(!box)return;
  const div=document.createElement("div");
  div.className="chat-msg"+(msg.is_system?" is-system":"")+(msg.is_host?" is-host":"");
  div.dataset.ts=msg.ts;
  const time=new Date(msg.ts*1000).toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});
  if(msg.is_system){
    div.innerHTML=`<span class="chat-text">${escHtml(msg.text)}</span>`;
  } else {
    const canDel=isHost||isTester||isAdmin;
    div.innerHTML=`<span class="chat-nick">${escHtml(msg.name)}</span><span class="chat-time">${time}</span><br><span class="chat-text">${escHtml(msg.text)}</span>${canDel?`<button class="chat-del-btn" onclick="deleteChatMsg(${msg.ts})">✕</button>`:""}`;
  }
  box.appendChild(div);
  box.scrollTop=box.scrollHeight;
  Sounds.chat_msg();
}
function escHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function deleteChatMsg(ts){ socket.emit("chat_delete_message",{ts}); }
window.deleteChatMsg=deleteChatMsg;

/* ════════════ ФОНОВЫЕ АНИМАЦИИ ════════════ */
function initBgAnimations(){
  // Звёзды мерцающие (без метеоров)
  const sf=document.getElementById("star-field"); if(!sf)return;
  for(let i=0;i<70;i++){
    const s=document.createElement("div"); s.className="star";
    const sz=0.6+Math.random()*2.2;
    s.style.cssText=`width:${sz}px;height:${sz}px;left:${Math.random()*100}%;top:${Math.random()*100}%;animation-duration:${1.5+Math.random()*5}s;animation-delay:${Math.random()*5}s`;
    sf.appendChild(s);
  }
}



/* ════════════ LOADING FACTS ════════════ */
const LOADING_FACTS=[
  "💡 GigaChat от Сбера — один из лучших российских LLM!",
  "🎯 Адаптивная сложность подстраивается под игроков в реальном времени",
  "🔥 Серия правильных ответов даёт стриковый бонус к очкам",
  "👻 Режим невидимки скрывает тебя от всех, кроме читера",
  "🃏 Джокер убирает два неверных варианта — стоит 100 очков",
  "🧠 Вопросы генерируются нейросетью специально для вашей темы",
  "⚡ FFA-режим: только первый правильный ответ засчитывается!",
  "🌟 В кооп-режиме команда побеждает или проигрывает вместе",
  "🎯 В «Своей игре» выбирай вопросы с разной стоимостью",
];
let _loadingFactTimer=null;
function startLoadingFacts(){
  const el=document.getElementById("loading-fact"); if(!el)return;
  let i=Math.floor(Math.random()*LOADING_FACTS.length);
  el.textContent=LOADING_FACTS[i];
  _loadingFactTimer=setInterval(()=>{
    i=(i+1)%LOADING_FACTS.length;
    el.style.opacity="0";
    setTimeout(()=>{ el.textContent=LOADING_FACTS[i]; el.style.opacity="1"; },300);
  },3000);
}
function stopLoadingFacts(){
  if(_loadingFactTimer){ clearInterval(_loadingFactTimer); _loadingFactTimer=null; }
}

/* ════════════ СВОЯ ИГРА ════════════ */
function initSvoyaigra(){
  on($("si-buzz-btn"),"click",()=>{ socket.emit("svoyaigra_buzz",{}); Sounds.si_buzz(); $("si-buzz-btn").disabled=true; });
  on($("si-host-reveal"),"click",()=>socket.emit("svoyaigra_host_reveal",{}));
  on($("btn-si-leave"),"click",()=>{ if(confirm("Выйти?")){ stopTimer(); _clearSession(); socket.emit("leave_room"); transitionTo("view-main","🏠"); resetLobbyUI(); } });
}
function renderSiBoard(meta, opened=[], myTurn=false, specialCells={}){
  siBoardMeta=meta; siBoard=meta;
  const board=$("si-board"); if(!board)return;
  const {categories, rows, cols, values} = meta;
  board.style.gridTemplateColumns=`repeat(${cols},1fr)`;
  board.innerHTML="";
  // Заголовки
  for(let c=0;c<cols;c++){
    const h=document.createElement("div"); h.className="si-cell si-header";
    h.style.cssText="font-weight:700;font-size:.78rem;color:var(--text-muted);cursor:default;padding:8px";
    h.textContent=categories[c]||`Тема ${c+1}`; board.appendChild(h);
  }
  // Ячейки
  for(let r=0;r<rows;r++){
    for(let c=0;c<cols;c++){
      const key=`${r}_${c}`;
      const cell=document.createElement("div"); cell.className="si-cell"+(opened.includes(key)?" si-opened":"");
      if(specialCells[key]) cell.classList.add("si-cheat-special");
      cell.innerHTML=`<div class="si-cell-cat">${categories[c]||""}</div><div class="si-cell-val">${values[r]||"?"}</div>`;
      if(!opened.includes(key)) cell.onclick=()=>{ if(!myTurn){toast("⚠️ Сейчас не ваш ход");return;} socket.emit("svoyaigra_select_cell",{row:r,col:c}); };
      board.appendChild(cell);
    }
  }
}
function renderSiScores(scores, players){
  const bar=$("si-scores-bar"); if(!bar)return; bar.innerHTML="";
  for(const [sid,score] of Object.entries(scores)){
    const pname=players?.[sid]?.name||sid;
    const chip=document.createElement("div"); chip.className="si-score-chip";
    chip.textContent=`${pname}: ${score}`; bar.appendChild(chip);
  }
}

/* ════════════ GAME TIMER ════════════ */
function startTimer(secs){
  clearInterval(timerInterval); timerSec=secs;
  const el=$("g-timer"); const pEl=$("pres-timer"); if(!el)return;
  [el,pEl].forEach(e=>e&&(e.textContent=timerSec,e.className=e===el?"g-timer":"pres-timer"));
  timerInterval=setInterval(()=>{
    timerSec--; [el,pEl].forEach(e=>e&&(e.textContent=timerSec));
    if(timerSec<=5){ [el,pEl].forEach(e=>e&&(e.className+=" danger")); Sounds.timer_5(); }
    else if(timerSec<=10){ [el,pEl].forEach(e=>e&&(e.className+=" warning")); Sounds.timer_warn(); }
    else Sounds.tick();
    if(timerSec<=0) clearInterval(timerInterval);
  },1000);
}
function stopTimer(){ clearInterval(timerInterval); }

/* ════════════ RENDER QUESTION ════════════ */
function renderQuestion(data){
  currentQ=data; rephraseUsed=false;
  const q=data.question;

  // Сначала — межвопросный переход
  if(animationsOn && data.question_number>1){
    const rt=$("round-transition"); if(rt){
      const fact=RT_FACTS[Math.floor(Math.random()*RT_FACTS.length)];
      if($("rt-qnum")) $("rt-qnum").textContent=`Вопрос ${data.question_number} / ${data.total_questions}`;
      if($("rt-fact"))  $("rt-fact").textContent=fact;
      rt.style.display="flex";
      setTimeout(()=>{ rt.style.display="none"; _showQuestion(data,q); },1800);
      return;
    }
  }
  _showQuestion(data,q);
}

function _showQuestion(data,q){
  if($("g-qnum"))     $("g-qnum").textContent=`Вопрос ${data.question_number} / ${data.total_questions}`;
  if($("g-progress")) $("g-progress").style.width=(data.question_number/data.total_questions*100)+"%";
  if($("g-question")) $("g-question").textContent=q.question;
  if($("question-result-panel")) $("question-result-panel").style.display="none";
  if($("hint-box"))  $("hint-box").style.display="none";
  if($("g-status"))  $("g-status").textContent="";
  if($("g-answered-count")){$("g-answered-count").textContent="";$("g-answered-count").dataset.count="0";}
  if($("g-answered-notif")) $("g-answered-notif").style.opacity="0";
  if($("cheat-answer-stats")) $("cheat-answer-stats").textContent="Нет ответов пока";

  if(data.is_bonus){if($("bonus-banner"))$("bonus-banner").style.display="";Sounds.bonus_q();}
  else if($("bonus-banner"))$("bonus-banner").style.display="none";

  if(data.difficulty&&$("g-diff-badge")) $("g-diff-badge").textContent={easy:"😊 Лёгкая",medium:"🧠 Средняя",hard:"🔥 Сложная"}[data.difficulty]||"";

  if(data.mode==="team"){
    if($("turn-bar")){$("turn-bar").style.display="";$("turn-bar").textContent=`🎯 Отвечает: ${data.team_names?.[data.turn_team]||("Команда "+data.turn_team)}`;}
    renderTeamBoard(data.team_scores,data.team_names);
  } else if($("turn-bar"))$("turn-bar").style.display="none";

  // Кнопка перефразировки
  if($("rephrase-bar")) $("rephrase-bar").style.display=isSpectator?"":"";
  if($("rephrase-used")) $("rephrase-used").style.display="none";
  if($("btn-rephrase")) $("btn-rephrase").textContent=`🔄 Перефразировать${cheatFreeRephrase?"":" (−50 очков)"}`;

  const grid=$("options-grid"); if(!grid)return;
  grid.innerHTML="";
  q.options.forEach((opt,i)=>{
    const btn=document.createElement("button"); btn.className="option-btn"; btn.dataset.idx=i;
    btn.innerHTML=`<span class="option-letter">${LETTERS[i]}</span>${opt}`;
    if(isTester&&cheatSeeAnswer&&data.cheat_correct===i){
      btn.style.cssText="background:rgba(255,215,0,0.15);border-color:#ffd700;color:#ffd700;font-weight:700;box-shadow:0 0 8px rgba(255,215,0,.5)";
    }
    btn.onclick=()=>submitAnswer(i);
    grid.appendChild(btn);

    // Обновляем презентационный оверлей
    if($("pres-question-text")) $("pres-question-text").textContent=q.question;
    const pOpts=$("pres-options"); if(pOpts){
      pOpts.innerHTML=q.options.map((o,j)=>`<div class="pres-option" data-idx="${j}" onclick="submitAnswer(${j})">${LETTERS[j]}. ${o}</div>`).join("");
    }
  });

  if(!isSpectator){startTimer(data.time_limit||30); if($("btn-joker")) $("btn-joker").disabled=false;}
}

function renderTeamBoard(scores,names){
  const tb=$("team-board"); if(!tb)return;
  tb.style.display=""; tb.innerHTML="";
  tb.style.cssText="display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;background:var(--card);border:1px solid var(--card-border);border-radius:var(--radius-sm);padding:10px 16px;margin-bottom:10px";
  const ids=Object.keys(scores||{});
  for(let i=0;i<ids.length;i++){
    const tid=parseInt(ids[i]),sc=(scores||{})[tid]||0,nm=(names||{})[tid]||("Команда "+tid);
    const c=document.createElement("div"); c.style.cssText="display:flex;flex-direction:column;align-items:center;gap:2px;";
    c.innerHTML=`<span style="font-weight:700;font-size:.8rem;color:${TEAM_COLORS[tid]||'#888'}">${nm}</span><span style="font-family:var(--font-mono);font-size:1.3rem;font-weight:700">${sc}</span>`;
    tb.appendChild(c);
    if(i<ids.length-1){const vs=document.createElement("div");vs.textContent="VS";vs.style.cssText="color:var(--text-muted);font-weight:800;font-size:.9rem";tb.appendChild(vs);}
  }
}

/* ════════════ SUBMIT ANSWER ════════════ */
function submitAnswer(idx){
  if(isSpectator)return;
  socket.emit("submit_answer",{answer_index:idx});
  stopTimer();
  // Нейтрально помечаем выбранный, блокируем остальные — раскрытие будет в question_result
  qsa(".option-btn,.pres-option").forEach((b,i)=>{
    b.disabled=true;
    if(parseInt(b.dataset.idx||i)===idx){ b.classList.add("chosen"); }
  });
  if($("g-status")) $("g-status").textContent="⏳ Ответ принят, ждём остальных...";
}
window.submitAnswer=submitAnswer;

/* ════════════ SOCKET EVENTS ════════════ */
function initSocket(){

  socket.on("room_created",data=>{
    roomCode=data.room_code; isHost=true; isSandbox=!!data.is_sandbox;
    _saveSession(roomCode, profile.name);
    if($("lobby-code")) $("lobby-code").textContent=roomCode;
    teamsData={};
    renderPlayersList(data.players||[]);
    if($("host-settings")) $("host-settings").style.display="";
    if($("guest-settings")) $("guest-settings").style.display="none";
    if($("btn-start")) $("btn-start").style.display="";
    if($("btn-leave-lobby")) $("btn-leave-lobby").style.display="";
    if($("mode-desc")) $("mode-desc").textContent=MODE_DESCS["classic"];
    if($("teams-panel")) $("teams-panel").style.display="none";
    if($("sandbox-badge")) $("sandbox-badge").style.display=isSandbox?"":"none";
    if($("btn-chat-clear")) $("btn-chat-clear").style.display="";  // хост видит кнопку очистки
    _startWaitingTips();
    transitionTo("view-lobby","🏠 Лобби");
  });

  socket.on("room_joined",data=>{
    roomCode=data.room_code; isHost=false; isSpectator=!!data.is_spectator; isSandbox=!!data.is_sandbox;
    _saveSession(roomCode, profile.name);
    if($("lobby-code")) $("lobby-code").textContent=roomCode;
    teamsData={}; if(data.teams) data.teams.forEach(t=>teamsData[t.id]=t);
    renderPlayersList(data.players||[]);
    if($("host-settings")) $("host-settings").style.display="none";
    if($("guest-settings")) $("guest-settings").style.display="";
    if($("btn-start")) $("btn-start").style.display="none";
    if($("btn-leave-lobby")) $("btn-leave-lobby").style.display="";
    if(data.settings) applyGuestSettings(data.settings);
    if($("sandbox-badge")) $("sandbox-badge").style.display=isSandbox?"":"none";
    if($("teams-panel")) $("teams-panel").style.display=data.team_draft_active?"":"none";
    if(data.team_draft_active&&data.teams){renderTeamsDisplay(teamsData,true,data.draft_turn||1);renderDraftPanel(teamsData,data.draft_turn||1);}
    if($("btn-chat-clear")) $("btn-chat-clear").style.display="none";
    transitionTo("view-lobby","🏠 Лобби");
  });

  socket.on("player_joined",data=>{
    if(data.teams) data.teams.forEach(t=>teamsData[t.id]=t);
    renderPlayersList(data.players||[]);
    toast(`👋 ${data.name} ${data.spectator?"смотрит":"вошёл"}`);
    Sounds.join();
  });
  socket.on("players_update",data=>{
    if(data.teams) data.teams.forEach(t=>teamsData[t.id]=t);
    renderPlayersList(data.players||[]);
    if(draftActive) renderDraftPanel(teamsData,draftTurn);
  });
  socket.on("settings_updated",data=>{
    if(!isHost&&data.settings) applyGuestSettings(data.settings);
    if(data.admin_override) toast("⚙️ Администратор изменил настройки");
  });
  socket.on("teams_initialized",data=>{
    teamsData={}; if(data.teams) data.teams.forEach(t=>teamsData[t.id]=t);
    draftActive=!!data.draft_active; draftTurn=data.draft_turn||1;
    if($("teams-panel")) $("teams-panel").style.display="";
    if($("draft-panel")) $("draft-panel").style.display=draftActive?"":"none";
    renderTeamsDisplay(teamsData,draftActive,draftTurn);
    if(draftActive){renderDraftPanel(teamsData,draftTurn);Sounds.draft();}
    toast("⚡ Команды созданы!");
  });
  socket.on("draft_updated",data=>{
    teamsData={}; if(data.teams) data.teams.forEach(t=>teamsData[t.id]=t);
    draftActive=!!data.draft_active; draftTurn=data.draft_turn||1;
    renderTeamsDisplay(teamsData,draftActive,draftTurn);
    if(draftActive) renderDraftPanel(teamsData,draftTurn);
    Sounds.draft();
  });
  socket.on("draft_complete",data=>{
    teamsData={}; if(data.teams) data.teams.forEach(t=>teamsData[t.id]=t);
    draftActive=false; if($("draft-panel")) $("draft-panel").style.display="none";
    renderTeamsDisplay(teamsData,false,0); toast("✅ Команды сформированы!"); Sounds.start();
  });

  /* Чат */
  socket.on("chat_history", data=>{ if($("chat-messages")) $("chat-messages").innerHTML=""; (data.messages||[]).forEach(renderChatMsg); });
  socket.on("chat_message", msg=>renderChatMsg(msg));
  socket.on("chat_deleted", data=>{ const el=qs(`[data-ts="${data.ts}"]`); if(el) el.remove(); });
  socket.on("chat_cleared", ()=>{ if($("chat-messages")) $("chat-messages").innerHTML=""; });

  /* Режим презентации */
  socket.on("presentation_mode_changed", data=>{
    presentationOn = data.enabled;
    if($("presentation-overlay")) $("presentation-overlay").style.display=data.enabled?"flex":"none";
    if($("btn-pres-toggle")) $("btn-pres-toggle").textContent=data.enabled?"❌":"📺";
    toast(data.enabled?"📺 Режим презентации вкл":"📺 Режим презентации выкл");
  });

  socket.on("error",  data=>toast("⚠️ "+(data.message||"Ошибка")));
  socket.on("kicked", data=>{ Sounds.kick(); _clearSession(); toast("👢 Исключён: "+(data.reason||""),5000); socket.emit("leave_room"); transitionTo("view-main","🏠"); resetLobbyUI(); });
  socket.on("rejoin_failed", data=>{ _clearSession(); toast("⚠️ "+(data.message||"Не удалось восстановить сессию"), 4000); });
  socket.on("host_changed",data=>{ toast(`👑 Новый хост: ${data.host}${data.admin_override?" (адм)":""}`); if(data.you_are_host){isHost=true;if($("host-settings"))$("host-settings").style.display="";if($("btn-start"))$("btn-start").style.display="";} });
  socket.on("player_renamed",data=>{ toast(`✏️ ${data.old_name} → ${data.new_name}`); Sounds.rename(); });

  socket.on("game_loading",data=>{
    if($("loading-msg")) $("loading-msg").textContent=data.message||"🤖 GigaChat генерирует вопросы...";
    if($("loading-sub")) $("loading-sub").textContent="Обычно занимает 5–15 секунд";
    transitionTo("view-loading","⏳");
    startLoadingFacts();
  });

  socket.on("game_started",data=>{
    stopLoadingFacts();
    if(data.mode==="svoyaigra"){
      // Переходим в отдельный view
      isSpectator=!!data.is_spectator; myScore=0;
      teamsData={}; if(data.teams) data.teams.forEach(t=>teamsData[t.id]=t);
      if(data.presentation) presentationOn=true;
      transitionTo("view-svoyaigra","🎯 Своя игра");
      const meta=data.si_board;
      if(meta) renderSiBoard(meta,[],false,data.si_board?.special||{});
      return;
    }
    isSpectator=!!data.is_spectator; myScore=0;
    if($("g-score")) $("g-score").textContent=0;
    teamsData={}; if(data.teams) data.teams.forEach(t=>teamsData[t.id]=t);
    const mn={classic:"🏆 Классика",ffa:"⚡ FFA",team:"🤝 Команды",lives:"❤️ На вылет",coop:"🌟 Кооп"};
    if($("g-mode-badge")){$("g-mode-badge").textContent=mn[data.mode]||data.mode;$("g-mode-badge").style.display="";}
    if(data.mode==="team"&&data.your_team){
      const tn=data.team_names?.[data.your_team]||("Команда "+data.your_team);
      if($("g-team")){$("g-team").textContent=tn;$("g-team").style.display="";$("g-team").style.color=TEAM_COLORS[data.your_team]||"var(--accent)";}
      if($("team-board")) $("team-board").style.display="";
    } else { if($("g-team")) $("g-team").style.display="none"; if($("team-board")) $("team-board").style.display="none"; }
    if($("g-lives")) $("g-lives").style.display=data.mode==="lives"?"":"none";
    if($("spectator-banner")) $("spectator-banner").style.display=isSpectator?"":"none";
    if($("player-tools")) $("player-tools").style.display=isSpectator?"none":"";
    if($("btn-pres-toggle")) $("btn-pres-toggle").style.display=""; // все могут переключать презентацию (локально или глобально)
    if(data.presentation){presentationOn=true;if($("presentation-overlay"))$("presentation-overlay").style.display="flex";}
    if(isTester) startCheatStats();
    Sounds.start(); transitionTo("view-game","🎮 Игра");
  });

  socket.on("new_question", data=>renderQuestion(data));

  socket.on("player_answered",data=>{
    const notif=$("g-answered-notif");
    if(notif){notif.textContent=`✏️ ${data.name} ответил`;notif.style.opacity="1";clearTimeout(notif._t);notif._t=setTimeout(()=>notif.style.opacity="0",2000);}
    if($("g-answered-count")){const c=parseInt($("g-answered-count").dataset.count||"0")+1;$("g-answered-count").dataset.count=c;$("g-answered-count").textContent=`${c} ответил(и)`;}
  });

  socket.on("answer_ack",data=>{
    // Не раскрываем правильность — только подтверждаем что ответ принят
    // (правильность и очки придут в question_result после того как все ответят)
    if($("g-status")) $("g-status").textContent="⏳ Ответ принят, ждём остальных...";
    // Сохраняем индекс выбранного, подсвечиваем нейтрально
    const idx=data.answer_index;
    if(idx!==undefined){
      qsa(".option-btn,.pres-option").forEach((b,i)=>{
        if(i===idx) b.classList.add("chosen");
      });
    }
    // Стрик-анонс только при условии, что всё хорошо — придёт позже
  });

  socket.on("life_lost",data=>{ if($("g-lives"))$("g-lives").textContent="❤️".repeat(Math.max(0,data.lives)); if(data.eliminated){toast("💀 Вы выбыли!");Sounds.eliminate();} });
  socket.on("player_eliminated",data=>{ toast(`💀 ${data.name} выбыл!`); Sounds.eliminate(); });
  socket.on("ffa_correct",data=>{ const fl=$("ffa-flash");if(fl){fl.style.display="";setTimeout(()=>fl.style.display="none",400);} toast(`⚡ ${data.player_name} ответил первым!`); });

  socket.on("joker_result",data=>{ qsa(".option-btn").forEach((b,i)=>{if(!data.keep_indices.includes(i))b.classList.add("hidden");}); if($("g-score"))$("g-score").textContent=data.new_score; myScore=data.new_score; toast(`🃏 Джокер (−${data.cost})`); });
  socket.on("hint_received",data=>{ if($("hint-box"))$("hint-box").style.display=""; if($("hint-text"))$("hint-text").textContent=data.hint; myScore=data.new_score; if($("g-score"))$("g-score").textContent=data.new_score; });

  socket.on("question_rephrased",data=>{
    if($("g-question")) $("g-question").textContent=data.rephrased;
    if($("pres-question-text")) $("pres-question-text").textContent=data.rephrased;
    if(data.new_score!==undefined){ myScore=data.new_score; if($("g-score"))$("g-score").textContent=myScore; }
    if(!cheatFreeRephrase&&$("rephrase-used")) $("rephrase-used").style.display="";
    toast("🔄 Вопрос перефразирован");
  });

  socket.on("question_result",data=>{
    stopTimer();
    const myAns=data.player_answers?.[socket.id];
    const myAnsIdx=myAns?.answer;

    // Раскрываем правильность ТОЛЬКО здесь, после получения всех ответов
    qsa(".option-btn,.pres-option").forEach((b,i)=>{
      b.disabled=true;
      b.classList.remove("chosen"); // убираем нейтральную подсветку
      if(i===data.correct_index){
        b.classList.add("correct");
      } else if(myAnsIdx!==undefined && myAnsIdx!==null && myAnsIdx!==-1 && i===myAnsIdx){
        // красим только тот, который выбрал игрок и он неверный
        b.classList.add("wrong");
      }
      // остальные варианты — без красного цвета!
    });

    if(myAns?.correct){ fireConfetti(); Sounds.correct(); NeuralBg.pulse("#34d399",1.0); if((myAns.streak||0)>=3){toast(`🔥 Серия ${myAns.streak}!`);Sounds.streak();NeuralBg.pulse("#fbbf24",1.2);} }
    else if(myAns) { Sounds.wrong(); NeuralBg.pulse("#f87171",0.8); }

    if($("g-status")) $("g-status").textContent=myAns?.correct?"✅ Правильно!":"❌ Неверно!";
    if($("question-result-panel"))$("question-result-panel").style.display="";
    if($("result-title")){$("result-title").textContent=myAns?.correct?"✅ Правильно!":"❌ Неверно!";$("result-title").style.color=myAns?.correct?"var(--green)":"var(--red)";}
    const expl=$("result-explanation"); if(expl){if(data.explanation){expl.style.display="";expl.textContent=data.explanation;}else expl.style.display="none";}
    const qrs=$("qr-scores"); if(qrs){qrs.innerHTML="";if(data.player_answers){for(const[sid,ans] of Object.entries(data.player_answers)){const d2=document.createElement("div");d2.className="qr-score-item "+(ans.correct?"correct-ans":"wrong-ans");const pts=data.scores?.[sid]||0;d2.innerHTML=`<span>${ans.correct?"✅":"❌"}</span><span style="flex:1;font-weight:600">${ans.name}</span><span style="font-family:var(--font-mono)">${pts}п.</span>`;qrs.appendChild(d2);}}}
    if(data.scores?.[socket.id]!==undefined){myScore=data.scores[socket.id];if($("g-score"))$("g-score").textContent=myScore;}
    if(data.team_scores&&data.team_names) renderTeamBoard(data.team_scores,data.team_names);
    if(data.new_difficulty&&$("g-diff-badge")) $("g-diff-badge").textContent={easy:"😊 Лёгкая",medium:"🧠 Средняя",hard:"🔥 Сложная"}[data.new_difficulty]||"";
    if($("g-answered-count")){$("g-answered-count").textContent="";$("g-answered-count").dataset.count="0";}
    if($("g-answered-notif")) $("g-answered-notif").style.opacity="0";
  });

  socket.on("interim_results",data=>toast(`📊 Сложность: ${{easy:"Лёгкая",medium:"Средняя",hard:"Сложная"}[data.difficulty]||data.difficulty}`));
  socket.on("reaction_received",data=>{ const el=document.createElement("div");el.className="reaction-float";el.style.left=(20+Math.random()*60)+"%";el.style.bottom="80px";el.innerHTML=data.emoji;$("reactions-overlay")?.appendChild(el);setTimeout(()=>el.remove(),2000); });

  socket.on("cheat_ack",data=>{ const m={infinite_lives:"♾️",invisible:"👻",reset_player:"🗑",rename:"✏️",reset_global_stats:"🗑 БД",presentation_mode:"📺",skip_question:"⏭️",set_lives:"❤️",add_score_all:"💰"}; toast(`${m[data.feature]||"✅"} ${data.enabled!==undefined?(data.enabled?"вкл":"выкл"):(data.ok?"ок":"ошибка")}`); });
  socket.on("cheat_player_reset",data=>toast(`🗑 Очки ${data.name} сброшены`));
  socket.on("cheat_score_updated",data=>{ if(data.sid===socket.id){myScore=data.score;if($("g-score"))$("g-score").textContent=myScore;} });
  socket.on("lives_restored",data=>{ toast(`❤️ ${data.name}: ${data.lives} жизней`); });
  socket.on("scores_updated",data=>{
    const myS=data.scores?.[socket.id];
    if(myS!==undefined){ myScore=myS; if($("g-score"))$("g-score").textContent=myScore; }
  });

  /* СВОЯ ИГРА */
  socket.on("svoyaigra_select_turn",data=>{
    const isMyTurn=(data.selector_sid===socket.id);
    if($("si-selector-label")) $("si-selector-label").textContent=isMyTurn?"👆 Ваш ход!":`Ход: ${data.selector}`;
    if($("si-status")) $("si-status").textContent=isMyTurn?"Выберите ячейку!":"";
    if($("si-question-panel")) $("si-question-panel").style.display="none";
    // Обновляем открытые ячейки
    if(siBoardMeta) renderSiBoard(siBoardMeta,data.opened||[],isMyTurn);
    renderSiScores(data.scores||{}, playersData.reduce((a,p)=>({...a,[p.sid]:p}),{}));
  });
  socket.on("svoyaigra_question",data=>{
    const panel=$("si-question-panel"); if(!panel)return;
    panel.style.display="";
    if($("si-q-category")) $("si-q-category").textContent=data.category||"";
    if($("si-q-value"))    $("si-q-value").textContent=`${data.value||0} очков`;
    if($("si-question-text")) $("si-question-text").textContent=data.question||"";
    if($("si-buzz-btn")){ $("si-buzz-btn").style.display=""; $("si-buzz-btn").disabled=false; }
    if($("si-buzzed-info")) $("si-buzzed-info").style.display="none";
    const siOpts=$("si-options");
    if(siOpts){ siOpts.classList.remove("visible"); siOpts.style.display="none"; siOpts.innerHTML=""; }
    if($("si-result")) $("si-result").style.display="none";
    if($("si-host-reveal")) $("si-host-reveal").style.display=isHost?"":"none";
    // Сохраняем данные текущего вопроса для ответа
    currentQ = {question: data.question, options: data.options||[], correct: -1, si_value: data.value, si_cell: data.cell};
    Sounds.si_buzz();
  });
  socket.on("svoyaigra_buzzed",data=>{
    const isMe=(data.sid===socket.id);
    if($("si-buzz-btn")) $("si-buzz-btn").style.display="none";
    if($("si-buzzed-info")){$("si-buzzed-info").style.display="";$("si-buzzed-info").textContent=`🔔 ${data.player} нажал!`;}
    if(isMe && currentQ && currentQ.options && currentQ.options.length){
      const siOpts=$("si-options");
      if(siOpts){
        siOpts.innerHTML="";
        currentQ.options.forEach((opt,i)=>{
          const btn=document.createElement("button");
          btn.className="option-btn";
          btn.textContent=`${LETTERS[i]}. ${opt}`;
          btn.onclick=()=>{
            siOpts.querySelectorAll(".option-btn").forEach(b=>b.disabled=true);
            socket.emit("svoyaigra_answer",{answer_index:i});
          };
          siOpts.appendChild(btn);
        });
        siOpts.style.display="grid"; siOpts.classList.add("visible");
      }
    }
    Sounds.si_buzz();
  });
  socket.on("svoyaigra_result",data=>{
    const res=$("si-result"); if(!res)return;
    res.style.display="";
    if(data.correct===true){
      res.className="si-result correct"; res.textContent=`✅ ${data.player||""} +${data.value||0}!`;
      if(data.explanation){const e=document.createElement("div");e.style.cssText="font-size:.82rem;color:var(--text-muted);margin-top:6px;font-weight:400";e.textContent=data.explanation;res.appendChild(e);}
      Sounds.si_correct(); fireConfetti();
    } else if(data.correct===false){
      res.className="si-result wrong"; res.textContent=`❌ ${data.player||""} −${data.penalty||0}`;
      Sounds.si_wrong();
    } else {
      res.className="si-result"; res.textContent="Вопрос закрыт";
    }
    if($("si-buzz-btn")) $("si-buzz-btn").style.display="none";
    if($("si-host-reveal")) $("si-host-reveal").style.display="none";
    renderSiScores(data.scores||{}, playersData.reduce((a,p)=>({...a,[p.sid]:p}),{}));
  });
  socket.on("svoyaigra_wrong",data=>{
    toast(`❌ ${data.player} неверно (−${data.penalty})`); Sounds.si_wrong();
    renderSiScores(data.scores||{}, playersData.reduce((a,p)=>({...a,[p.sid]:p}),{}));
    // Buzz-кнопка снова активна
    if($("si-buzz-btn")){ $("si-buzz-btn").style.display=""; $("si-buzz-btn").disabled=false; }
    if($("si-buzzed-info")) $("si-buzzed-info").style.display="none";
  });

  socket.on("game_over",data=>{
    stopTimer(); stopCheatStats();
    // НЕ очищаем сессию — оставляем для повторной игры тем же составом
    transitionTo("view-results","🏆");
    if(data.admin_terminated) toast("⛔ Игра завершена администратором",4000);
    const myRes=data.players?.find(p=>p.name===profile.name);
    if(myRes){
      profile.games++; profile.totalScore+=myRes.score||0; profile.xp+=Math.floor((myRes.score||0)/10)+5;
      if(myRes.rank===1){profile.wins++;fireMega();Sounds.win();NeuralBg.pulse("#fbbf24",1.5);}else{Sounds.correct();NeuralBg.pulse("#8b5cf6",0.7);}
      profile.history=profile.history||[];
      profile.history.push({date:new Date().toLocaleDateString("ru-RU"),topic:"Игра",score:myRes.score||0,mode:data.mode||"classic"});
      if(profile.history.length>50) profile.history=profile.history.slice(-50);
      saveProfile();
    }
    const medals=["🥇","🥈","🥉"];
    if($("leaderboard")) $("leaderboard").innerHTML=(data.players||[]).map((p,i)=>`<div class="lb-item"><span class="lb-rank ${i===0?"gold":i===1?"silver":i===2?"bronze":""}">${medals[i]||(i+1)}</span><span class="lb-name">${p.name}${p.team&&teamsData[p.team]?` <span style="font-size:.75rem;color:${TEAM_COLORS[p.team]||'#888'}">[${teamsData[p.team]?.name||''}]</span>`:""}</span><span class="lb-correct">${p.total_correct||0} ✅</span><span class="lb-score">${p.score}</span></div>`).join("");
    const banner=$("result-banner");
    if(banner){
      if(data.mode==="team"&&data.winner_team&&data.team_names){banner.style.display="";banner.textContent=`🏆 Победа: ${data.team_names[data.winner_team]||"Команда "+data.winner_team}!`;}
      else if(data.players?.[0]){banner.style.display="";banner.textContent=data.mode==="coop"?`🌟 Команда: ${data.players.reduce((s,p)=>s+p.score,0)} очков!`:`🥇 ${data.players[0].name} — ${data.players[0].score} очков!`;}
    }
    // Забавная статистика раунда
    _renderFunStats(data);
    if($("btn-restart"))         $("btn-restart").style.display=isHost?"":"none";
    if($("btn-tournament"))      $("btn-tournament").style.display=isHost?"":"none";
    if($("btn-continue-squad"))  $("btn-continue-squad").style.display=isHost?"":"none";
  });

  socket.on("room_restarted",data=>{
    myScore=data.keep_scores?myScore:0; if($("g-score"))$("g-score").textContent=myScore;
    _saveSession(roomCode, profile.name);
    renderPlayersList(data.players||[]); teamsData={};
    if($("teams-panel")) $("teams-panel").style.display="none";
    if($("round-fun-stats")) $("round-fun-stats").style.display="none";
    transitionTo("view-lobby","🏠"); toast("🔄 Перезапуск!"); Sounds.start();
    _startWaitingTips();
  });

  socket.on("admin_action_result",data=>{
    const msgs={kick:"👢 Исключён",ban:"🚫 Забанен",force_end:"⛔ Игра завершена",transfer_host:"👑 Хост передан",settings_updated:"⚙️ Настройки обновлены",take_host:"👑 Вы теперь хост",presentation:"📺 Презентация",chat_system:"💬 Сообщение отправлено"};
    toast(data.ok?(msgs[data.action]||"✅"):"❌ Ошибка");
    if(data.ok&&["kick","ban"].includes(data.action)) loadAdminRooms();
    if(data.action==="take_host"&&data.ok){isHost=true;if($("host-settings"))$("host-settings").style.display="";if($("btn-start"))$("btn-start").style.display="";}
  });

  socket.on("heartbeat_ack",()=>{});
}

/* ── Забавная статистика раунда ── */
function _renderFunStats(data){
  const el=$("round-fun-stats"); if(!el) return;
  const players=data.players||[];
  if(!players.length){ el.style.display="none"; return; }

  const totalCorrect=players.reduce((s,p)=>s+(p.total_correct||0),0);
  const totalQ=data.total_questions||players.reduce((m,p)=>Math.max(m,p.total_correct||0),0)||1;
  const accuracy=totalQ>0?Math.round(totalCorrect/players.length/totalQ*100):0;

  // MVP по количеству правильных
  const mvp=players.slice().sort((a,b)=>(b.total_correct||0)-(a.total_correct||0))[0];
  // Самый щедрый (highest score)
  const richest=players[0];
  // Самый стабильный (наименьший разрыв между правильными и неправильными)

  const facts=[];
  if(mvp) facts.push(`🎯 MVP: <b>${mvp.name}</b> — ${mvp.total_correct||0} правильных`);
  facts.push(`📊 Точность команды: <b>${accuracy}%</b>`);
  if(richest) facts.push(`🏆 Победитель: <b>${richest.name}</b> с ${richest.score} очков`);
  if(data.mode==="team"&&data.team_scores){
    const ts=data.team_scores; const winner=data.winner_team;
    if(winner&&data.team_names) facts.push(`🤝 Команда «${data.team_names[winner]}» набрала ${ts[winner]} очков`);
  }

  el.innerHTML=facts.map(f=>`<div class="fun-stat-item">${f}</div>`).join("");
  el.style.display="";
}

/* ── Стиль для аватара читера ── */
(function(){
  const s=document.createElement("style");
  s.textContent=`.cheat-avatar{cursor:pointer;border:2px solid rgba(255,215,0,.5)!important;}.cheat-avatar:hover{box-shadow:0 0 0 3px rgba(255,215,0,.3)!important;transform:scale(1.08)!important;}`;
  document.head.appendChild(s);
})();

/* ── PWA ── */
if("serviceWorker"in navigator) navigator.serviceWorker.register("/static/js/sw.js").catch(()=>{});

/* ════════════════════════════════════════════════════════
   ACCOUNTS — авторизация
   ════════════════════════════════════════════════════════ */
let _authUser = null;  // текущий авторизованный пользователь

async function initAuth() {
  try {
    const d = await fetch("/api/auth/me").then(r=>r.json());
    if (d.logged_in) _setAuthUser(d.user);
  } catch(_) {}
}

function _setAuthUser(user) {
  _authUser = user;
  _renderAuthBar(user);
  _renderAuthProfile(user);
  // Подставляем имя в поля ввода
  if (user && $("create-name") && !$("create-name").value) $("create-name").value = user.username;
  if (user && $("join-name")   && !$("join-name").value)   $("join-name").value   = user.username;
}

function _renderAuthBar(user) {
  const bar   = $("hero-user-bar");
  const icon  = $("auth-mode-icon");
  const label = $("auth-mode-label");
  if (!bar) return;
  if (user) {
    bar.style.display="flex";
    if ($("hero-user-name"))  $("hero-user-name").textContent  = user.username;
    if ($("hero-user-coins")) $("hero-user-coins").textContent = `💰 ${user.coins||0}`;
    if ($("hero-user-level")) $("hero-user-level").textContent = `Ур. ${user.level||1}`;
    if (icon)  icon.textContent  = "👤";
    if (label) label.textContent = user.username;
  } else {
    bar.style.display="none";
    if (icon)  icon.textContent  = "👤";
    if (label) label.textContent = "Войти";
  }
}

function _renderAuthProfile(user) {
  const loggedOut = $("auth-logged-out");
  const loggedIn  = $("auth-logged-in");
  if (!loggedOut || !loggedIn) return;
  if (!user) {
    loggedOut.style.display=""; loggedIn.style.display="none"; return;
  }
  loggedOut.style.display="none"; loggedIn.style.display="";
  if ($("auth-profile-name"))  $("auth-profile-name").textContent  = user.username;
  if ($("auth-profile-level")) $("auth-profile-level").textContent = `Уровень ${user.level||1} · ${user.xp||0} XP`;
  if ($("auth-profile-coins")) $("auth-profile-coins").textContent = `💰 ${user.coins||0}`;
  if ($("auth-profile-xp"))    $("auth-profile-xp").textContent    = `XP: ${user.xp||0}`;
  if ($("auth-stat-games"))    $("auth-stat-games").textContent    = user.games_played||0;
  if ($("auth-stat-wins"))     $("auth-stat-wins").textContent     = user.wins||0;
  if ($("auth-stat-score"))    $("auth-stat-score").textContent    = user.total_score||0;
  // Достижения
  const achEl = $("auth-achievements");
  if (achEl && user.achievements) {
    achEl.innerHTML = user.achievements.map(a =>
      `<span class="ach-badge ${a.unlocked?"unlocked":"locked"}" title="${a.desc}">${a.icon} ${a.title}</span>`
    ).join("");
  }
}

function initAuthUI() {
  on($("btn-auth-login"), "click", async()=>{
    const u = ($("auth-login-name").value||"").trim();
    const p = ($("auth-login-pass").value||"").trim();
    if (!u||!p) return;
    const d = await fetch("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:u,password:p})}).then(r=>r.json()).catch(()=>({}));
    if (d.ok) {
      _setAuthUser(d.user); toast(`✅ Добро пожаловать, ${d.user.username}!`);
      showView("view-main");
    } else {
      $("auth-login-error").style.display=""; $("auth-login-error").textContent=d.error||"Ошибка";
    }
  });
  on($("btn-auth-register"),"click",async()=>{
    const u = ($("auth-reg-name").value||"").trim();
    const p = ($("auth-reg-pass").value||"").trim();
    if (!u||!p) return;
    const d = await fetch("/api/auth/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:u,password:p})}).then(r=>r.json()).catch(()=>({}));
    if (d.ok) {
      _setAuthUser(d.user); toast(`🎉 Аккаунт создан! Добро пожаловать!`);
      showView("view-main");
    } else {
      $("auth-reg-error").style.display=""; $("auth-reg-error").textContent=d.error||"Ошибка";
    }
  });
  on($("btn-auth-logout"),"click",async()=>{
    await fetch("/api/auth/logout",{method:"POST"});
    _authUser=null; _setAuthUser(null); toast("👋 Вышли из аккаунта");
  });
  // Tab switcher for auth view
  qsa("#view-auth .tab-btn").forEach(btn=>btn.onclick=()=>{
    qsa("#view-auth .tab-btn").forEach(b=>b.classList.remove("active"));
    btn.classList.add("active");
    const t=btn.dataset.tab;
    qsa("#view-auth .tab-panel").forEach(p=>p.style.display="none");
    const panel=$(t==="auth-login"?"tab-auth-login":"tab-auth-register");
    if(panel){panel.style.display="";panel.classList.add("active");}
  });
}


/* ════════════════════════════════════════════════════════
   CAMPAIGN — режим кампании
   ════════════════════════════════════════════════════════ */
let _campData     = null;
let _campCurrent  = null;   // {level, questions, idx, score, correct}
let _campTimer    = null;

async function loadCampaign() {
  if (!_authUser) {
    const prompt = $("campaign-login-prompt");
    if (prompt) prompt.style.display="";
    $("campaign-map").innerHTML="";
    return;
  }
  const prompt = $("campaign-login-prompt");
  if (prompt) prompt.style.display="none";
  try {
    _campData = await fetch("/api/campaign/levels").then(r=>r.json());
    _renderCampaignMap(_campData);
  } catch(e) { toast("❌ Ошибка загрузки кампании"); }
}

function _renderCampaignMap(data) {
  const map   = $("campaign-map"); if(!map) return;
  const stars  = data.total_stars||0;
  if ($("camp-stars-total")) $("camp-stars-total").textContent = `⭐ ${stars} звёзд`;
  const worlds = {};
  (data.levels||[]).forEach(l=> (worlds[l.world]||=[]).push(l));
  const WORLD_NAMES = {1:"🌍 Мир знаний",2:"🎭 Мир культуры",3:"🔮 Мир мастеров"};
  map.innerHTML = Object.entries(worlds).map(([w,levels])=>`
    <div class="camp-world-title">${WORLD_NAMES[w]||"Мир "+w}</div>
    ${levels.map(l=>{
      const stars = l.stars||0;
      const starsStr = "⭐".repeat(stars)+"☆".repeat(3-stars);
      const locked = l.locked;
      return `<div class="camp-level-card ${locked?"locked":""} ${l.boss?"boss":""}"
        onclick="${locked?"void(0)":"startCampaignLevel("+l.id+")"}">
        <div class="camp-level-icon">${l.boss?"⚔️": (locked?"🔒":"🧠")}</div>
        <div class="camp-level-info">
          <div class="camp-level-name">${l.title}</div>
          <div class="camp-level-meta">${l.difficulty==="easy"?"Лёгкий":l.difficulty==="medium"?"Средний":"Сложный"} · ${l.questions} вопросов · 🪙${l.reward_coins}</div>
        </div>
        <div class="camp-stars">${stars>0?starsStr:"☆☆☆"}</div>
        ${locked?`<div style="font-size:.72rem;color:var(--red)">⭐${l.req_stars}</div>`:""}
      </div>`;
    }).join("")}
  `).join("");
}

async function startCampaignLevel(levelId) {
  if (!_authUser) { showView("view-auth"); return; }
  const level = _campData?.levels?.find(l=>l.id===levelId);
  if (!level || level.locked) return;
  toast("🤖 Генерируем вопросы...", 2000);
  // Импортируем generate_questions через API (используем ai_client через socket?)
  // Грузим через /api/learn/from_text с темой уровня — нет, это другой формат
  // Используем серверный endpoint
  try {
    const resp = await fetch("/api/campaign/start",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({level_id:levelId})
    }).then(r=>r.json());
    if (!resp.questions?.length) { toast("❌ Не удалось получить вопросы"); return; }
    _campCurrent = {
      level, questions: resp.questions,
      idx:0, score:0, correct:0, answered:false
    };
    _showCampaignGame();
  } catch(e) { toast("❌ Ошибка загрузки уровня: "+e); }
}

function _showCampaignGame() {
  const c = _campCurrent; if(!c) return;
  showView("view-campaign-game");
  if ($("camp-level-title")) $("camp-level-title").textContent = c.level.title;
  if ($("camp-q-total"))     $("camp-q-total").textContent    = c.questions.length;
  if ($("camp-result-overlay")) $("camp-result-overlay").style.display="none";
  _campShowQuestion();
}

function _campShowQuestion() {
  const c = _campCurrent; if(!c) return;
  const q = c.questions[c.idx];
  if (!q) { _campFinish(); return; }
  c.answered = false;
  if ($("camp-q-num"))       $("camp-q-num").textContent      = c.idx+1;
  if ($("camp-score"))       $("camp-score").textContent      = c.score;
  if ($("camp-explanation")) $("camp-explanation").style.display="none";
  if ($("camp-question-text")) $("camp-question-text").textContent = q.question;
  // Timer bar
  clearInterval(_campTimer);
  let t=20;
  const bar = $("camp-timer-bar");
  if(bar){bar.style.width="100%"; bar.style.background="var(--primary)";}
  _campTimer=setInterval(()=>{
    t--;
    if(bar) bar.style.width=(t/20*100)+"%";
    if(bar&&t<=5) bar.style.background="var(--red)";
    if(t<=0) { clearInterval(_campTimer); if(!c.answered) _campAnswer(-1); }
  },1000);
  // Options
  const opts = $("camp-options"); if(!opts) return;
  const LETTERS=["A","B","C","D","E","F"];
  opts.innerHTML=(q.options||[]).map((o,i)=>
    `<button class="option-btn" data-idx="${i}" onclick="_campAnswer(${i})">
      <span class="opt-letter">${LETTERS[i]}</span>${o}
    </button>`
  ).join("");
}

function _campAnswer(idx) {
  const c=_campCurrent; if(!c||c.answered) return;
  c.answered=true;
  clearInterval(_campTimer);
  const q=c.questions[c.idx];
  const correct=q.correct;
  const isOk=(idx===correct);
  if(isOk){ c.score+=100; c.correct++; NeuralBg.pulse("#34d399",0.8); }
  else NeuralBg.pulse("#f87171",0.6);
  // Подсветка
  qsa("#camp-options .option-btn").forEach((btn,i)=>{
    if(i===correct) btn.classList.add("correct");
    else if(i===idx&&!isOk) btn.classList.add("wrong");
    btn.disabled=true;
  });
  const expEl=$("camp-explanation");
  if(expEl&&q.explanation){ expEl.textContent=q.explanation; expEl.style.display=""; }
  // Авто-переход через 1.8с
  setTimeout(()=>{
    c.idx++;
    if(c.idx>=c.questions.length) _campFinish();
    else _campShowQuestion();
  },1800);
}

async function _campFinish() {
  clearInterval(_campTimer);
  const c=_campCurrent; if(!c) return;
  const pct=Math.round(c.correct/c.questions.length*100);
  const stars=pct>=90?3:pct>=65?2:pct>=40?1:0;
  const starsStr="⭐".repeat(stars)+"☆".repeat(3-stars);
  // Сохраняем результат
  const res=await fetch("/api/campaign/result",{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({level_id:c.level.id,score:c.score,correct:c.correct,total_questions:c.questions.length})
  }).then(r=>r.json()).catch(()=>({}));
  if($("camp-result-overlay")) $("camp-result-overlay").style.display="";
  if($("camp-result-stars"))   $("camp-result-stars").textContent=starsStr;
  if($("camp-result-text"))    $("camp-result-text").innerHTML=
    `<b>${c.correct}</b> из <b>${c.questions.length}</b> верных (${pct}%)<br>`+
    (res.coins?`💰 +${res.coins} монет · `:"")+(res.xp?`+${res.xp} XP`:"");
  if(stars>0) fireConfetti();
  // Разблокированные достижения
  if(res.new_achievements?.length)
    res.new_achievements.forEach(id=>toast(`🏅 Достижение: ${ACHIEVEMENTS_CLIENT[id]||id}`,3000));
  // Обновляем профиль
  const me=await fetch("/api/auth/me").then(r=>r.json()).catch(()=>({}));
  if(me.logged_in) _setAuthUser(me.user);
}

function initCampaignUI() {
  on($("btn-camp-retry"),"click",()=>{ _campCurrent&&(_campCurrent.idx=0,_campCurrent.score=0,_campCurrent.correct=0,_showCampaignGame()); });
  on($("btn-camp-next"), "click",()=>loadCampaign().then(()=>showView("view-campaign")));
  on($("btn-camp-back"), "click",()=>{ clearInterval(_campTimer); showView("view-campaign"); });
}

const ACHIEVEMENTS_CLIENT={
  first_win:"Первая победа", streak5:"В потоке", campaign_world1:"Покоритель мира 1",
  campaign_boss:"Боссубийца", ugc_creator:"Автор", ugc_10:"Контрибьютор",
  games10:"Завсегдатай", games50:"Ветеран", perfect_level:"Перфекционист", learn_mode:"Студент"
};


/* ════════════════════════════════════════════════════════
   LEARN MODE — режим обучения
   ════════════════════════════════════════════════════════ */
let _learnQuestions=[], _learnIdx=0, _learnCorrect=0;

function initLearnUI() {
  // Tab switcher
  qsa("#view-learn .tab-btn").forEach(btn=>btn.onclick=()=>{
    qsa("#view-learn .tab-btn").forEach(b=>b.classList.remove("active"));
    btn.classList.add("active");
    qsa("#view-learn .tab-panel").forEach(p=>p.style.display="none");
    const t=btn.dataset.tab;
    const panel=$(t==="learn-text"?"tab-learn-text":"tab-learn-url");
    if(panel){panel.style.display="";}
  });
  on($("btn-learn-generate"),"click",generateLearnQuiz);
  on($("btn-learn-next"),    "click",learnNextQ);
  on($("btn-learn-retry"),   "click",()=>{
    _learnIdx=0;_learnCorrect=0;
    $("learn-results-panel").style.display="none";
    $("learn-game-panel").style.display="";
    _learnShowQ();
  });
}

async function generateLearnQuiz() {
  const btn=$("btn-learn-generate"); if(!btn) return;
  const errEl=$("learn-error"); if(errEl)errEl.style.display="none";
  const isUrl=qsa("#view-learn .tab-btn")[1]?.classList.contains("active");
  const num=parseInt($("learn-num-q")?.value||"6",10);
  let body={num_questions:num};
  if(isUrl){
    const url=($("learn-url-input")?.value||"").trim();
    if(!url){toast("⚠️ Введите URL");return;}
    body.url=url;
  } else {
    const text=($("learn-text-input")?.value||"").trim();
    if(text.length<50){toast("⚠️ Текст слишком короткий");return;}
    body.content=text;
  }
  btn.disabled=true; btn.textContent="⏳ Генерируем...";
  try{
    const endpoint=isUrl?"/api/learn/from_url":"/api/learn/from_text";
    const d=await fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(r=>r.json());
    if(!d.questions?.length){
      if(errEl){errEl.style.display="";errEl.textContent=d.error||"Ошибка генерации";}
      return;
    }
    _learnQuestions=d.questions; _learnIdx=0; _learnCorrect=0;
    $("learn-input-panel").style.display="none";
    $("learn-game-panel").style.display="";
    $("learn-results-panel").style.display="none";
    if($("learn-q-total"))$("learn-q-total").textContent=d.questions.length;
    _learnShowQ();
    toast(`✅ ${d.questions.length} вопросов готово!`);
  }catch(e){
    if(errEl){errEl.style.display="";errEl.textContent="Сетевая ошибка";}
  }finally{
    btn.disabled=false; btn.textContent="🤖 Сгенерировать";
  }
}

function _learnShowQ(){
  const q=_learnQuestions[_learnIdx]; if(!q) return;
  if($("learn-q-num"))$("learn-q-num").textContent=_learnIdx+1;
  if($("learn-correct-cnt"))$("learn-correct-cnt").textContent=_learnCorrect;
  if($("learn-explanation"))$("learn-explanation").style.display="none";
  if($("learn-question-text"))$("learn-question-text").textContent=q.question;
  if($("btn-learn-next"))$("btn-learn-next").style.display="none";
  const opts=$("learn-options"); if(!opts)return;
  const LETTERS=["A","B","C","D"];
  opts.innerHTML=(q.options||[]).map((o,i)=>
    `<button class="option-btn" data-idx="${i}" onclick="_learnAnswer(${i})">
      <span class="opt-letter">${LETTERS[i]}</span>${o}
    </button>`
  ).join("");
}

function _learnAnswer(idx){
  const q=_learnQuestions[_learnIdx]; if(!q) return;
  const ok=idx===q.correct;
  if(ok){_learnCorrect++;NeuralBg.pulse("#34d399",0.7);}else NeuralBg.pulse("#f87171",0.5);
  qsa("#learn-options .option-btn").forEach((btn,i)=>{
    if(i===q.correct)btn.classList.add("correct");
    else if(i===idx&&!ok)btn.classList.add("wrong");
    btn.disabled=true;
  });
  const expEl=$("learn-explanation");
  if(expEl&&q.explanation){expEl.textContent=(ok?"✅ ":"❌ ")+q.explanation;expEl.style.display="";}
  if($("btn-learn-next"))$("btn-learn-next").style.display="";
  if(_learnIdx>=_learnQuestions.length-1)
    if($("btn-learn-next"))$("btn-learn-next").textContent="📊 Результаты";
}

function learnNextQ(){
  _learnIdx++;
  if(_learnIdx>=_learnQuestions.length){
    _learnShowResults(); return;
  }
  _learnShowQ();
  if($("btn-learn-next"))$("btn-learn-next").textContent="Следующий →";
}

function _learnShowResults(){
  $("learn-game-panel").style.display="none";
  const pct=Math.round(_learnCorrect/_learnQuestions.length*100);
  const stars=pct>=90?"⭐⭐⭐":pct>=65?"⭐⭐":pct>=40?"⭐":"";
  $("learn-results-panel").style.display="";
  $("learn-results-body").innerHTML=`
    <div style="text-align:center;font-size:1.5rem;margin-bottom:8px">${stars}</div>
    <div style="text-align:center;font-size:2rem;font-weight:700;color:var(--primary)">${pct}%</div>
    <div style="text-align:center;color:var(--text-muted);margin-bottom:14px">${_learnCorrect} из ${_learnQuestions.length} верных</div>
    <div style="height:8px;background:rgba(139,92,246,.15);border-radius:4px;overflow:hidden">
      <div class="learn-progress-bar" style="width:${pct}%"></div>
    </div>
    <p style="font-size:.82rem;color:var(--text-muted);margin-top:10px;text-align:center">
      ${pct>=80?"🎉 Отличный результат!":pct>=50?"👍 Неплохо, но есть куда расти":"📖 Попробуй ещё раз после повторения материала"}
    </p>
  `;
  if(pct>=80)fireConfetti();
}


/* ════════════════════════════════════════════════════════
   UGC — пользовательские вопросы
   ════════════════════════════════════════════════════════ */
function initUgcUI() {
  const form=$("ugc-create-form");
  const prompt=$("ugc-auth-prompt");
  if(_authUser){if(form)form.style.display="";if(prompt)prompt.style.display="none";}
  else{if(form)form.style.display="none";if(prompt)prompt.style.display="";}

  on($("btn-ugc-submit"),"click",submitUgcQuestion);
  on($("btn-ugc-load-my"),"click",loadMyUgcQuestions);
}

async function submitUgcQuestion(){
  if(!_authUser){showView("view-auth");return;}
  const text=($("ugc-question-text")?.value||"").trim();
  const options=[...(qsa(".ugc-opt")||[])].map(i=>i.value.trim());
  const correct=parseInt($("ugc-correct-select")?.value||"0",10);
  const topic=($("ugc-topic")?.value||"").trim();
  const diff=parseInt($("ugc-difficulty")?.value||"2",10);
  const errEl=$("ugc-create-error");
  if(errEl)errEl.style.display="none";
  const d=await fetch("/api/ugc/create",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({question:text,options,correct,topic,difficulty:diff})
  }).then(r=>r.json()).catch(()=>({}));
  if(d.ok){
    toast(`✅ Вопрос отправлен! +${d.coins_earned||5}💰`);
    // Сброс формы
    if($("ugc-question-text"))$("ugc-question-text").value="";
    qsa(".ugc-opt").forEach(i=>i.value="");
    // Достижения
    if(d.new_achievements?.length)
      d.new_achievements.forEach(id=>toast(`🏅 Достижение: ${ACHIEVEMENTS_CLIENT[id]||id}`,3000));
    NeuralBg.pulse("#34d399",0.7);
    loadMyUgcQuestions();
  } else {
    if(errEl){errEl.style.display="";errEl.textContent=d.error||"Ошибка";}
  }
}

async function loadMyUgcQuestions(){
  const el=$("ugc-my-list"); if(!el||!_authUser)return;
  el.innerHTML='<p class="muted" style="font-size:.82rem">Загрузка...</p>';
  const d=await fetch("/api/ugc/my").then(r=>r.json()).catch(()=>({questions:[]}));
  const qs=d.questions||[];
  if(!qs.length){el.innerHTML='<p class="muted" style="font-size:.82rem">Ещё нет вопросов</p>';return;}
  const STATUS_MAP={pending:"⏳ На модерации",approved:"✅ Одобрен",rejected:"❌ Отклонён"};
  el.innerHTML=qs.slice(0,20).map(q=>`
    <div style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,.06)">
      <div style="font-size:.82rem;font-weight:600">${q.question}</div>
      <div style="display:flex;gap:8px;margin-top:4px;align-items:center">
        <span class="ugc-status-badge ${q.status}">${STATUS_MAP[q.status]||q.status}</span>
        <span style="font-size:.72rem;color:var(--text-muted)">⭐${(q.rating||0).toFixed(1)} · 🎯${q.usage_count||0}×</span>
        ${q.reject_reason?`<span style="font-size:.72rem;color:var(--red)">${q.reject_reason}</span>`:""}
      </div>
    </div>
  `).join("");
}


/* ════════════════════════════════════════════════════════
   ADMIN PANEL UPGRADES — UGC модерация
   ════════════════════════════════════════════════════════ */
async function loadAdminUgcPending(){
  const el=$("admin-ugc-list"); if(!el)return;
  el.innerHTML='<p class="muted" style="font-size:.82rem">Загрузка...</p>';
  const d=await fetch("/api/admin/ugc_pending").then(r=>r.json()).catch(()=>({questions:[]}));
  const qs=d.questions||[];
  if(!qs.length){el.innerHTML='<p class="muted" style="font-size:.82rem">Нет на модерации</p>';return;}
  el.innerHTML=qs.map(q=>`
    <div style="padding:10px;background:rgba(139,92,246,.05);border-radius:8px;margin-bottom:8px">
      <div style="font-size:.83rem;font-weight:600;margin-bottom:4px">${q.question}</div>
      <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:8px">Автор: ${q.author} · Тема: ${q.topic||"—"}</div>
      <div style="display:flex;gap:5px">
        <button class="btn btn-sm btn-secondary" style="color:var(--green)" onclick="ugcModerate(${q.id},true)">✅ Одобрить</button>
        <button class="btn btn-sm btn-danger" onclick="ugcModerate(${q.id},false)">❌ Отклонить</button>
      </div>
    </div>
  `).join("");
}
window.ugcModerate=async(id,approve)=>{
  const reason=approve?"":prompt("Причина отклонения:")||"Не соответствует правилам";
  await fetch("/api/admin/ugc_moderate",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({question_id:id,approve,reason})}).then(r=>r.json());
  toast(approve?"✅ Одобрен":"❌ Отклонён");
  loadAdminUgcPending();
};


/* ════════════════════════════════════════════════════════
   ИНИЦИАЛИЗАЦИЯ
   ════════════════════════════════════════════════════════ */
window.addEventListener("DOMContentLoaded",()=>{
  initAuth().then(()=>{
    initAuthUI();
    initCampaignUI();
    initLearnUI();
    initUgcUI();
  });
  // При открытии campaign view — загружаем карту
  const origShowView = window.showView;
  window.showViewOrig = origShowView;
  window.showView = (id, ...args)=>{
    origShowView(id, ...args);
    if(id==="view-campaign") loadCampaign();
    if(id==="view-ugc") {
      const form=$("ugc-create-form");
      const prompt=$("ugc-auth-prompt");
      if(_authUser){if(form)form.style.display="";if(prompt)prompt.style.display="none";}
      else{if(form)form.style.display="none";if(prompt)prompt.style.display="";}
    }
    if(id==="view-learn"){
      $("learn-input-panel").style.display="";
      $("learn-game-panel").style.display="none";
      $("learn-results-panel").style.display="none";
    }
  };
});

window.startCampaignLevel=startCampaignLevel;
window._campAnswer=_campAnswer;
window._learnAnswer=_learnAnswer;
