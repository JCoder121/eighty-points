// ============================================================
// Shengji (升级) — browser frontend
// ============================================================
// Single-page app: Landing → Lobby → Game
// All state lives on the server; the client re-renders on
// every game_state / room_update message.
// ============================================================

"use strict";

// ── Constants ──────────────────────────────────────────────────────────────

const RANK_ORDER = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"];

const SUIT_SYMBOL = {
  spades:   "♠",
  hearts:   "♥",
  diamonds: "♦",
  clubs:    "♣",
  joker:    "★",
};

const SUIT_COLOR_CLASS = {
  spades:   "suit-spades",
  hearts:   "suit-hearts",
  diamonds: "suit-diamonds",
  clubs:    "suit-clubs",
  joker:    "suit-joker",
};

function rankDisplay(rank) {
  if (rank === "small_joker") return "SJ";
  if (rank === "big_joker")   return "BJ";
  return rank;
}

// ── Application state ─────────────────────────────────────────────────────

const S = {
  roomId:       null,
  playerId:     null,
  playerName:   null,
  isGameMaster: false,

  ws:           null,

  roomUpdate:   null,   // last room_update payload
  gameState:    null,   // last game_state payload

  // In-hand selection: Set of string keys ("hand:N" or "bot:N")
  selectedKeys: new Set(),

  // Waiting for play_valid/play_invalid from server?
  awaitingValidation: false,

  // Bidding state — reset when a new bid is placed or a new deal starts.
  hasPassed:     false,  // true once this player has pressed Pass this round
  lastBidsCount: 0,      // tracks gs.bids.length to detect new bids
};

// Timer for auto-dismiss round-over overlay
let _roundOverlayTimer = null;

// ── Screen management ─────────────────────────────────────────────────────

function showScreen(id) {
  for (const el of document.querySelectorAll(
    "#screen-landing, #screen-lobby, #screen-game"
  )) {
    el.style.display = "none";
  }
  const target = document.getElementById(id);
  target.style.display = "flex";
  target.style.flexDirection = "column";
}

// ── Error display ─────────────────────────────────────────────────────────

function setLandingError(msg) {
  document.getElementById("landing-error").textContent = msg;
}

function setGameError(msg) {
  const el = document.getElementById("game-error");
  el.textContent = msg;
  if (msg) {
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.textContent = ""; }, 6000);
  }
}

// ── REST helpers ──────────────────────────────────────────────────────────

async function apiPost(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

// ── Landing page actions ──────────────────────────────────────────────────

async function createRoom() {
  const name = document.getElementById("create-name").value.trim();
  if (!name) { setLandingError("Enter your name first."); return; }
  setLandingError("");
  try {
    const data = await apiPost("/rooms", { name });
    S.roomId     = data.room_id;
    S.playerId   = data.player_id;
    S.playerName = name;
    connectWS();
  } catch (e) {
    setLandingError(e.message);
  }
}

async function joinRoom() {
  const code = document.getElementById("join-code").value.trim().toUpperCase();
  const name = document.getElementById("join-name").value.trim();
  if (!code) { setLandingError("Enter the room code."); return; }
  if (!name) { setLandingError("Enter your name."); return; }
  setLandingError("");
  try {
    const data = await apiPost(`/rooms/${code}/join`, { name });
    S.roomId     = code;
    S.playerId   = data.player_id;
    S.playerName = name;
    connectWS();
  } catch (e) {
    setLandingError(e.message);
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url   = `${proto}//${location.host}/ws/${S.roomId}/${S.playerId}`;
  S.ws = new WebSocket(url);

  S.ws.addEventListener("open", () => {
    showScreen("screen-lobby");
  });

  S.ws.addEventListener("message", (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch { return; }
    dispatchMessage(msg);
  });

  S.ws.addEventListener("close", (evt) => {
    // Only show disconnect message if we haven't already handled game_aborted
    if (document.getElementById("overlay").classList.contains("hidden")) {
      showFinalOverlay("Disconnected", "Connection to the server was lost.");
    }
  });

  S.ws.addEventListener("error", () => {
    setLandingError("WebSocket connection failed. Is the server running?");
    showScreen("screen-landing");
  });
}

function sendWS(obj) {
  if (S.ws && S.ws.readyState === WebSocket.OPEN) {
    S.ws.send(JSON.stringify(obj));
  }
}

// ── Message dispatcher ────────────────────────────────────────────────────

function dispatchMessage(msg) {
  switch (msg.type) {
    case "room_update":  handleRoomUpdate(msg);  break;
    case "game_state":   handleGameState(msg);   break;
    case "card_dealt":                           break; // game_state follows
    case "round_over":   handleRoundOver(msg);   break;
    case "game_over":    handleGameOver(msg);    break;
    case "game_aborted": handleGameAborted(msg); break;
    case "play_valid":   handlePlayValid();      break;
    case "play_invalid": handlePlayInvalid(msg); break;
    case "error":        handleError(msg);       break;
    default: console.warn("Unknown message type:", msg.type);
  }
}

// ── Message handlers ──────────────────────────────────────────────────────

function handleRoomUpdate(msg) {
  S.roomUpdate = msg;
  S.isGameMaster = (S.playerId === msg.game_master_id);

  document.getElementById("lobby-room-code").textContent = `ROOM CODE: ${msg.room_id}`;
  document.getElementById("game-room-code").textContent  = `ROOM CODE: ${msg.room_id}`;

  renderLobby();
}

function handleGameState(msg) {
  // Reset selection on every state update — server state is the truth
  S.selectedKeys.clear();

  // Bidding pass-state tracking:
  // - A new deal resets the pass flag (new bidding round begins).
  // - A new bid by ANY player resets the pass flag because the server clears
  //   passed_in_bidding on every bid, so all players must pass again.
  const newBidsCount = (msg.bids || []).length;
  if (msg.phase === "dealing" || newBidsCount > S.lastBidsCount) {
    S.hasPassed = false;
  }
  S.lastBidsCount = newBidsCount;

  S.gameState = msg;

  // Auto-dismiss round-over overlay when a new round starts dealing
  if (msg.phase === "dealing" && _roundOverlayTimer !== null) {
    clearTimeout(_roundOverlayTimer);
    _roundOverlayTimer = null;
    hideOverlay();
  }

  // Transition screens
  const gamePhases = [
    "dealing", "bidding_after_deal", "bottom_exchange",
    "friend_declaration", "playing", "scoring", "round_over", "game_over",
  ];
  if (gamePhases.includes(msg.phase)) {
    showScreen("screen-game");
  } else {
    showScreen("screen-lobby");
    renderLobby();
  }

  updateTrumpInfo(msg);

  if (document.getElementById("screen-game").style.display !== "none") {
    renderGame(msg);
  }
}

function handleRoundOver(msg) {
  const isDefWin = msg.winner === "defending";
  const winner   = isDefWin ? "Defenders" : "Attackers";
  const pts      = msg.attacking_points;
  const steps    = msg.steps;
  let outcome;
  if (steps === 0) {
    outcome = "Attackers take over as Defenders — no rank change.";
  } else {
    outcome = `${winner} advance ${steps} rank${steps !== 1 ? "s" : ""}.`;
  }
  const body = `Attacking team scored ${pts} pts. ${outcome}`;
  showRoundOverlay("Round Over", body);
}

function handleGameOver(msg) {
  clearTimeout(_roundOverlayTimer);
  _roundOverlayTimer = null;
  const winner = msg.winner === "defending" ? "Defenders" : "Attackers";
  showFinalOverlay("Game Over!", `${winner} win the game!`);
}

function handleGameAborted(msg) {
  clearTimeout(_roundOverlayTimer);
  _roundOverlayTimer = null;
  showFinalOverlay("Game Aborted", msg.reason || "A player disconnected.");
}

function handlePlayValid() {
  S.awaitingValidation = false;
  // Commit the validated play
  const cards = getSelectedCards();
  sendWS({ action: "play_cards", cards });
  S.selectedKeys.clear();
  const el = document.getElementById("play-validation-msg");
  if (el) { el.textContent = ""; }
  setGameError("");
}

function handlePlayInvalid(msg) {
  S.awaitingValidation = false;
  const reason = msg.reason || "Invalid play.";
  const el = document.getElementById("play-validation-msg");
  if (el) el.textContent = reason;
  setGameError(reason);
}

function handleError(msg) {
  setGameError(msg.message || "Server error.");
}

// ── Overlays ──────────────────────────────────────────────────────────────

// Round-over: auto-dismisses after 4s or when next DEALING state arrives.
function showRoundOverlay(title, body) {
  document.getElementById("overlay-title").textContent = title;
  document.getElementById("overlay-body").textContent  = body;
  document.getElementById("overlay-btn").classList.add("hidden");
  document.getElementById("overlay").classList.remove("hidden");
  clearTimeout(_roundOverlayTimer);
  _roundOverlayTimer = setTimeout(() => {
    _roundOverlayTimer = null;
    hideOverlay();
  }, 4000);
}

// Final overlay (game over / disconnected): requires user to click OK.
function showFinalOverlay(title, body) {
  document.getElementById("overlay-title").textContent = title;
  document.getElementById("overlay-body").textContent  = body;
  document.getElementById("overlay-btn").classList.remove("hidden");
  document.getElementById("overlay").classList.remove("hidden");
}

function hideOverlay() {
  document.getElementById("overlay").classList.add("hidden");
}

// ── Trump info bar ────────────────────────────────────────────────────────

function updateTrumpInfo(gs) {
  let text;
  if (gs.trump_context && gs.trump_context.trump_rank) {
    const rank = rankDisplay(gs.trump_context.trump_rank);
    if (gs.trump_context.trump_suit) {
      const sym = SUIT_SYMBOL[gs.trump_context.trump_suit] || gs.trump_context.trump_suit;
      text = `Playing: ${rank} ${sym}`;
    } else {
      text = `Playing: ${rank} No Trump`;
    }
  } else {
    // During WAITING, show the defending players' current rank
    const defending = (gs.players || []).filter(p => p.is_defending);
    const ref = defending.length ? defending[0] : (gs.players || [])[0];
    const rank = ref ? rankDisplay(ref.rank) : "2";
    text = `Currently at Rank ${rank}`;
  }
  document.getElementById("lobby-trump-info").textContent = text;
  document.getElementById("game-trump-info").textContent  = text;
}

// ── Lobby rendering ───────────────────────────────────────────────────────

function renderLobby() {
  if (!S.roomUpdate) return;

  const ru     = S.roomUpdate;
  const gs     = S.gameState;
  const mode   = gs ? gs.mode : null;
  const phase  = gs ? gs.phase : "waiting";
  const n      = ru.players.length;

  // Player list (4 slots)
  const list = document.getElementById("player-list");
  list.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    if (i < n) {
      const p   = ru.players[i];
      const div = document.createElement("div");
      div.className = "player-entry";
      const nameSpan = document.createElement("span");
      nameSpan.textContent = p.name;
      div.appendChild(nameSpan);
      if (p.id === ru.game_master_id) {
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = "Host";
        div.appendChild(badge);
      }
      list.appendChild(div);
    } else {
      const div = document.createElement("div");
      div.className = "player-slot";
      div.textContent = `Seat ${i + 1} — waiting...`;
      list.appendChild(div);
    }
  }

  // Status text
  const statusEl = document.getElementById("lobby-status");
  if (phase !== "waiting") {
    statusEl.textContent = "Game in progress...";
  } else if (n < 4) {
    statusEl.textContent = `Waiting for players... (${n}/4 joined)`;
  } else if (!mode) {
    statusEl.textContent = S.isGameMaster
      ? "4 players ready — select a game mode to begin."
      : "4 players ready — waiting for host to select a game mode.";
  } else {
    statusEl.textContent = `Mode: ${modeName(mode)} — starting...`;
  }

  // Mode selector (game master only)
  const modeDiv = document.getElementById("mode-selector");
  if (S.isGameMaster && phase === "waiting") {
    modeDiv.classList.remove("hidden");
    document.getElementById("btn-upgrade").classList.toggle("active", mode === "upgrade");
    document.getElementById("btn-find-friends").classList.toggle("active", mode === "find_friends");
  } else {
    modeDiv.classList.add("hidden");
  }

  // Superuser section (game master only)
  const suDiv = document.getElementById("superuser-section");
  S.isGameMaster ? suDiv.classList.remove("hidden") : suDiv.classList.add("hidden");
}

function modeName(mode) {
  if (mode === "upgrade")      return "Upgrade (升级)";
  if (mode === "find_friends") return "Find Friends (找朋友)";
  return mode || "—";
}

// ── Game screen ───────────────────────────────────────────────────────────

function renderGame(gs) {
  renderRoundInfo(gs);
  renderTrickArea(gs);
  renderPoints(gs);
  renderHand(gs);
  renderActionArea(gs);
}

function renderRoundInfo(gs) {
  let text = `Round ${gs.round_number}`;
  if (gs.phase === "playing" || gs.phase === "scoring") {
    text += ` · Trick ${gs.trick_number}`;
  }
  text += ` · ${gs.phase}`;
  document.getElementById("round-info").textContent = text;
}

// ── Trick area ────────────────────────────────────────────────────────────

function renderTrickArea(gs) {
  const myIdx = gs.players.findIndex(p => p.id === S.playerId);
  if (myIdx === -1) return;

  // Counter-clockwise seating: left = +1, opposite = +2, right = +3
  const positions = {
    top:    { idx: (myIdx + 2) % 4, nameId: "name-top",    cardsId: "cards-top"    },
    left:   { idx: (myIdx + 1) % 4, nameId: "name-left",   cardsId: "cards-left"   },
    right:  { idx: (myIdx + 3) % 4, nameId: "name-right",  cardsId: "cards-right"  },
    bottom: { idx: myIdx,           nameId: "name-bottom",  cardsId: "cards-bottom" },
  };

  // Map player_id → cards played in current trick
  const trickMap = {};
  for (const play of (gs.current_trick || [])) {
    trickMap[play.player_id] = play.cards;
  }

  for (const pos of Object.values(positions)) {
    const p       = gs.players[pos.idx];
    const nameEl  = document.getElementById(pos.nameId);
    const cardsEl = document.getElementById(pos.cardsId);

    // Name with turn/leader highlight
    nameEl.textContent = p ? p.name : "—";
    nameEl.className   = "player-name-label";
    if (p) {
      if (p.id === gs.current_turn_id)   nameEl.classList.add("is-turn");
      else if (p.id === gs.current_leader_id) nameEl.classList.add("is-leader");
    }

    // Cards played this trick
    cardsEl.innerHTML = "";
    const played = p ? (trickMap[p.id] || []) : [];
    for (const card of played) {
      cardsEl.appendChild(makeCardEl(card, false));
    }
  }

  // Center status
  const statusEl = document.getElementById("trick-status");
  if (gs.phase === "playing") {
    const cp = gs.players.find(p => p.id === gs.current_turn_id);
    statusEl.textContent = cp
      ? (cp.id === S.playerId ? "Your turn!" : `${cp.name}'s turn`)
      : "";
  } else {
    statusEl.textContent = "";
  }
}

// ── Points display ────────────────────────────────────────────────────────

function renderPoints(gs) {
  const atk = gs.attacking_points || 0;
  document.getElementById("pts-attacking").textContent = atk;
  // Attacking team needs ≥ 200 pts (1 deck × 100 pts × 2 decks) to take over.
  // Show how far they are from the key threshold.
  const toScore = Math.max(0, 200 - atk);
  document.getElementById("pts-defending").textContent =
    atk >= 200 ? "200+ (scoring!)" : `${toScore} to 200`;
}

// ── Hand rendering ────────────────────────────────────────────────────────

// During BOTTOM_EXCHANGE, the round leader sees their hand + the 8 bottom cards
// (33 total), and selects 8 of those 33 to put back.
// Cards from hand use key "hand:N"; bottom deck cards use key "bot:N".

function renderHand(gs) {
  const handArea   = document.getElementById("hand-area");
  const handHeader = document.getElementById("hand-header");
  handArea.innerHTML = "";

  const me = gs.players.find(p => p.id === S.playerId);
  if (!me || !me.hand) {
    handHeader.textContent = "";
    return;
  }

  const phase      = gs.phase;
  const isExchange = phase === "bottom_exchange" && Array.isArray(gs.bottom_deck);

  // Combine cards for display (33 during exchange, 25 otherwise)
  const handCards   = me.hand.map((card, i) => ({ card, key: `hand:${i}` }));
  const bottomCards = isExchange
    ? (gs.bottom_deck || []).map((card, i) => ({ card, key: `bot:${i}` }))
    : [];
  const allDisplay = [...handCards, ...bottomCards];

  const canSelect = (
    phase === "playing" ||
    phase === "bottom_exchange" ||
    phase === "friend_declaration"
  );

  const total = allDisplay.length;
  handHeader.textContent = isExchange
    ? `Your hand + bottom deck (${total} cards) — select 8 to put back`
    : `Your hand (${total} cards)`;

  // Sort combined set; bottom deck cards rendered after hand cards
  const sorted = sortCardSet(allDisplay, gs.trump_context);

  for (const { card, key } of sorted) {
    const el = makeCardEl(card, canSelect);

    // Mark bottom deck cards with a subtle indicator (no opacity change
    // because selected state would look dim; use the ⊕ badge instead)
    if (key.startsWith("bot:")) {
      el.title = "Bottom deck card — can be put back";
      const badge = document.createElement("span");
      badge.style.cssText = "font-size:8px;color:#888;position:absolute;top:1px;right:2px;";
      el.style.position = "relative";
      badge.textContent = "⊕";
      el.appendChild(badge);
    }

    if (canSelect) {
      if (S.selectedKeys.has(key)) el.classList.add("selected");
      el.addEventListener("click", () => onCardClick(key, el, gs));
    }
    handArea.appendChild(el);
  }
}

function onCardClick(key, el, gs) {
  const phase = gs.phase;
  if (phase === "playing") {
    if (S.selectedKeys.has(key)) {
      S.selectedKeys.delete(key);
      el.classList.remove("selected");
    } else {
      S.selectedKeys.add(key);
      el.classList.add("selected");
    }
    // Update play button disabled state
    const playBtn = document.getElementById("play-btn");
    if (playBtn) {
      playBtn.disabled = S.selectedKeys.size === 0 || S.awaitingValidation
        || gs.current_turn_id !== S.playerId;
    }
  } else if (phase === "bottom_exchange") {
    if (S.selectedKeys.has(key)) {
      S.selectedKeys.delete(key);
      el.classList.remove("selected");
    } else if (S.selectedKeys.size < 8) {
      S.selectedKeys.add(key);
      el.classList.add("selected");
    }
    // Update confirm button + counter
    const confirmBtn = document.getElementById("bottom-confirm-btn");
    const countEl    = document.getElementById("bottom-sel-count");
    if (confirmBtn) confirmBtn.disabled = S.selectedKeys.size !== 8;
    if (countEl)    countEl.textContent = `${S.selectedKeys.size}/8 selected`;
  }
}

// ── Card element ──────────────────────────────────────────────────────────

function makeCardEl(card, selectable) {
  const el = document.createElement("span");
  el.className = `card ${SUIT_COLOR_CLASS[card.suit] || ""}`;
  if (selectable) el.classList.add("selectable");

  const rEl = document.createElement("span");
  rEl.className = "card-rank";
  rEl.textContent = rankDisplay(card.rank);

  const sEl = document.createElement("span");
  sEl.className = "card-suit";
  sEl.textContent = SUIT_SYMBOL[card.suit] || card.suit;

  el.appendChild(rEl);
  el.appendChild(sEl);
  return el;
}

// ── Hand sorting ──────────────────────────────────────────────────────────

// Sort an array of { card, key } objects for display.
function sortCardSet(items, trumpContext) {
  return [...items].sort((a, b) => {
    const ka = cardSortKey(a.card, trumpContext);
    const kb = cardSortKey(b.card, trumpContext);
    for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
      const d = (ka[i] || 0) - (kb[i] || 0);
      if (d !== 0) return d;
    }
    return 0;
  });
}

function cardSortKey(card, ctx) {
  // Suit display order (non-trump): ♦ ♣ ♥ ♠  (alternating red/black)
  // Groups (lower = shown further left):
  //   0 = ♦ diamonds  (non-trump, non-rank)
  //   1 = ♣ clubs     (non-trump, non-rank)
  //   2 = ♥ hearts    (non-trump, non-rank)
  //   3 = ♠ spades    (non-trump, non-rank)
  //   4 = trump-suit non-rank cards
  //   5 = ALL trump-rank cards (any suit) — off-suit by ♦♣♥♠ order, on-suit last
  //   6 = jokers (SJ < BJ)
  const SUITS = ["diamonds", "clubs", "hearts", "spades"];
  const ri = RANK_ORDER.indexOf(card.rank);

  if (card.rank === "small_joker") return [6, 0];
  if (card.rank === "big_joker")   return [6, 1];

  if (!ctx || !ctx.trump_rank) {
    const si = SUITS.indexOf(card.suit);
    return [si >= 0 ? si : SUITS.length - 1, ri];
  }

  const { trump_rank, trump_suit } = ctx;
  const isTrumpRank = card.rank === trump_rank;
  const isTrumpSuit = trump_suit && card.suit === trump_suit;

  // All trump-rank cards in one block (group 5).
  // On-suit trump rank is the strongest of the group — sort it last (subIdx = 4).
  if (isTrumpRank) {
    const subIdx = isTrumpSuit ? SUITS.length : SUITS.indexOf(card.suit);
    return [5, subIdx >= 0 ? subIdx : SUITS.length - 1];
  }
  if (isTrumpSuit) return [4, ri];

  const si = SUITS.indexOf(card.suit);
  return [si >= 0 ? si : SUITS.length - 1, ri];
}

// ── Selected cards → serialized card objects ──────────────────────────────

function getSelectedCards() {
  const gs = S.gameState;
  if (!gs) return [];
  const me = gs.players.find(p => p.id === S.playerId);
  if (!me || !me.hand) return [];

  const cards = [];
  for (const key of S.selectedKeys) {
    const [type, idxStr] = key.split(":");
    const idx  = parseInt(idxStr, 10);
    if (type === "hand") {
      if (me.hand[idx]) cards.push(me.hand[idx]);
    } else if (type === "bot") {
      if (gs.bottom_deck && gs.bottom_deck[idx]) cards.push(gs.bottom_deck[idx]);
    }
  }
  return cards;
}

// ── Action area rendering ─────────────────────────────────────────────────

function renderActionArea(gs) {
  const area = document.getElementById("action-area");
  area.innerHTML = "";

  const phase = gs.phase;
  if (phase === "dealing" || phase === "bidding_after_deal") {
    renderBidArea(area, gs);
  } else if (phase === "bottom_exchange") {
    renderBottomExchange(area, gs);
  } else if (phase === "friend_declaration") {
    renderFriendDeclaration(area, gs);
  } else if (phase === "playing") {
    renderPlayArea(area, gs);
  } else {
    const p = document.createElement("p");
    p.style.color = "#666";
    p.textContent = {
      scoring:    "Scoring in progress...",
      round_over: "Round over — next round starting...",
      game_over:  "Game over.",
      waiting:    "In lobby...",
    }[phase] || phase;
    area.appendChild(p);
  }
}

// ── Bid area ──────────────────────────────────────────────────────────────

function renderBidArea(area, gs) {
  // Current bid banner
  const bidBanner = document.createElement("div");
  bidBanner.id = "current-bid-display";
  const lastBid = gs.bids && gs.bids.length ? gs.bids[gs.bids.length - 1] : null;
  if (lastBid) {
    const name  = (gs.players.find(p => p.id === lastBid.player_id) || {}).name || lastBid.player_id;
    const tc    = lastBid.resulting_trump;
    const pair  = (lastBid.cards || []).length >= 2;
    let desc;
    if (!tc.trump_suit) {
      desc = pair ? "No Trump (pair)" : "No Trump";
    } else {
      const sym = SUIT_SYMBOL[tc.trump_suit] || tc.trump_suit;
      desc = `${rankDisplay(tc.trump_rank)} ${sym}${pair ? " (pair)" : ""}`;
    }
    bidBanner.innerHTML = `Current bid: <strong>${name} — ${desc}</strong>`;
  } else {
    bidBanner.textContent = "No bid yet.";
  }
  area.appendChild(bidBanner);

  // Bid buttons
  const available = gs.available_bids || [];
  const bidRow    = document.createElement("div");
  bidRow.className = "action-row";

  // Same order as the hand display: ♦ ♣ ♥ ♠
  const SUITS = [
    { suit: "diamonds", sym: "♦" },
    { suit: "clubs",    sym: "♣" },
    { suit: "hearts",   sym: "♥" },
    { suit: "spades",   sym: "♠" },
  ];
  for (const { suit, sym } of SUITS) {
    const btn = document.createElement("button");
    btn.className = `bid-btn-suit suit-${suit}`;
    btn.textContent = sym;
    const canBid = available.some(b =>
      (b.type === "single" || b.type === "pair") && b.suit === suit
    );
    btn.disabled = !canBid;
    if (canBid) {
      const isPair = available.some(b => b.type === "pair" && b.suit === suit);
      btn.title = isPair ? `Bid ${sym} (pair — nails it down)` : `Bid ${sym}`;
      btn.addEventListener("click", () => sendWS({ action: "bid", suit }));
    }
    bidRow.appendChild(btn);
  }

  for (const joker of ["small", "big"]) {
    const btn = document.createElement("button");
    btn.textContent = joker === "small" ? "No Trump (SJ)" : "No Trump (BJ)";
    btn.disabled    = !available.some(b => b.type === "joker_pair" && b.joker === joker);
    if (!btn.disabled) {
      btn.addEventListener("click", () => sendWS({ action: "bid", joker }));
    }
    bidRow.appendChild(btn);
  }
  area.appendChild(bidRow);

  // Pass / close bidding
  const ctrlRow = document.createElement("div");
  ctrlRow.className = "action-row";
  if (gs.phase === "bidding_after_deal") {
    const passBtn = document.createElement("button");
    // Once a player has placed a bid they cannot take it back by passing.
    const iHaveBid = (gs.bids || []).some(b => b.player_id === S.playerId);
    passBtn.textContent = S.hasPassed ? "Passed ✓" : "Pass";
    passBtn.disabled = iHaveBid || S.hasPassed;
    if (S.hasPassed) passBtn.classList.add("btn-passed");
    if (!passBtn.disabled) {
      passBtn.addEventListener("click", () => {
        S.hasPassed = true;
        sendWS({ action: "pass_bid" });
        // Update button immediately; full re-render arrives with next game_state
        passBtn.textContent = "Passed ✓";
        passBtn.disabled = true;
        passBtn.classList.add("btn-passed");
      });
    }
    ctrlRow.appendChild(passBtn);
  }
  if (S.isGameMaster) {
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Close Bidding";
    closeBtn.addEventListener("click", () => sendWS({ action: "close_bidding" }));
    ctrlRow.appendChild(closeBtn);
  }
  if (ctrlRow.children.length) area.appendChild(ctrlRow);

  // Deal progress
  const prog = document.createElement("div");
  prog.style.cssText = "font-size:12px;color:#555;text-align:center;";
  const dealt = gs.cards_dealt_count || 0;
  prog.textContent = gs.phase === "dealing"
    ? `Dealing... ${dealt}/100 cards`
    : "All 100 cards dealt — bidding phase.";
  area.appendChild(prog);
}

// ── Bottom exchange ───────────────────────────────────────────────────────

function renderBottomExchange(area, gs) {
  // Only the round leader sees the bottom deck (gs.bottom_deck is an array for them).
  if (!Array.isArray(gs.bottom_deck)) {
    const p = document.createElement("p");
    p.style.color = "#888";
    p.textContent = "Waiting for the bid winner to exchange the bottom deck...";
    area.appendChild(p);
    return;
  }

  // Hand area shows 33 cards (hand + bottom_deck); select 8 to put back.
  const selCount = document.createElement("div");
  selCount.id = "bottom-sel-count";
  selCount.style.cssText = "font-size:13px;color:#ffcc44;text-align:center;";
  selCount.textContent = `${S.selectedKeys.size}/8 selected`;
  area.appendChild(selCount);

  const confirmBtn = document.createElement("button");
  confirmBtn.id = "bottom-confirm-btn";
  confirmBtn.textContent = "Confirm Exchange";
  confirmBtn.disabled    = S.selectedKeys.size !== 8;
  confirmBtn.addEventListener("click", () => {
    const cards = getSelectedCards();
    if (cards.length !== 8) { setGameError("Select exactly 8 cards to put back."); return; }
    sendWS({ action: "exchange_bottom", cards_to_put_back: cards });
    S.selectedKeys.clear();
  });

  const row = document.createElement("div");
  row.className = "action-row";
  row.appendChild(confirmBtn);
  area.appendChild(row);
}

// ── Friend declaration ────────────────────────────────────────────────────

function renderFriendDeclaration(area, gs) {
  // current_leader_id is set to round_leader_id at start of dealing and doesn't
  // change until PLAYING begins. Use it to determine if we're the leader.
  const isLeader = gs.current_leader_id === S.playerId;

  if (!isLeader) {
    const p = document.createElement("p");
    p.style.color = "#888";
    p.textContent = "Waiting for the round leader to declare their friend...";
    area.appendChild(p);
    return;
  }

  const ctx       = gs.trump_context;
  const trumpRank = ctx ? ctx.trump_rank : null;

  const info = document.createElement("div");
  info.style.cssText = "font-size:13px;color:#aaa;text-align:center;margin-bottom:4px;";
  info.textContent = "Declare your friend (Find Friends mode):";
  area.appendChild(info);

  // Rank dropdown — exclude trump rank and jokers
  const rankSel = document.createElement("select");
  rankSel.id = "fd-rank";
  for (const r of RANK_ORDER) {
    if (r === trumpRank) continue;
    const opt = document.createElement("option");
    opt.value = r;
    opt.textContent = rankDisplay(r);
    rankSel.appendChild(opt);
  }

  // Suit dropdown — no joker
  const suitSel = document.createElement("select");
  suitSel.id = "fd-suit";
  for (const [suit, sym] of Object.entries(SUIT_SYMBOL)) {
    if (suit === "joker") continue;
    const opt = document.createElement("option");
    opt.value = suit;
    opt.textContent = `${sym} ${suit.charAt(0).toUpperCase() + suit.slice(1)}`;
    suitSel.appendChild(opt);
  }

  // Ordinal dropdown
  const ordSel = document.createElement("select");
  ordSel.id = "fd-ordinal";
  for (const [val, label] of [[1, "1st person"], [2, "2nd person"]]) {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = `${label} to play this card`;
    ordSel.appendChild(opt);
  }

  function lbl(text) {
    const l = document.createElement("label");
    l.textContent = text;
    return l;
  }

  const row = document.createElement("div");
  row.className = "friend-decl-row";
  row.appendChild(lbl("Rank:"));
  row.appendChild(rankSel);
  row.appendChild(lbl("Suit:"));
  row.appendChild(suitSel);
  row.appendChild(lbl("Ordinal:"));
  row.appendChild(ordSel);

  const row2 = document.createElement("div");
  row2.className = "friend-decl-row";
  const declBtn = document.createElement("button");
  declBtn.textContent = "Declare Friend";
  declBtn.addEventListener("click", () => {
    const rank    = document.getElementById("fd-rank").value;
    const suit    = document.getElementById("fd-suit").value;
    const ordinal = parseInt(document.getElementById("fd-ordinal").value, 10);
    sendWS({
      action: "declare_friends",
      declarations: [{ card: { suit, rank }, ordinal }],
    });
  });
  row2.appendChild(declBtn);

  area.appendChild(row);
  area.appendChild(row2);
}

// ── Play area ─────────────────────────────────────────────────────────────

function renderPlayArea(area, gs) {
  const isMyTurn = gs.current_turn_id === S.playerId;

  // Inline validation message
  const msgDiv = document.createElement("div");
  msgDiv.id = "play-validation-msg";
  area.appendChild(msgDiv);

  const row = document.createElement("div");
  row.className = "action-row";

  const playBtn = document.createElement("button");
  playBtn.id        = "play-btn";
  playBtn.textContent = "Play";
  playBtn.disabled  = !isMyTurn || S.selectedKeys.size === 0 || S.awaitingValidation;
  playBtn.addEventListener("click", () => {
    if (S.selectedKeys.size === 0) { setGameError("Select cards to play."); return; }
    const cards = getSelectedCards();
    S.awaitingValidation = true;
    playBtn.disabled = true;
    sendWS({ action: "validate_play", cards });
  });

  const clearBtn = document.createElement("button");
  clearBtn.textContent = "Clear";
  clearBtn.addEventListener("click", () => {
    S.selectedKeys.clear();
    renderHand(gs);
  });

  row.appendChild(playBtn);
  row.appendChild(clearBtn);
  area.appendChild(row);

  if (!isMyTurn) {
    const waiting = document.createElement("div");
    waiting.style.cssText = "font-size:12px;color:#555;text-align:center;";
    const cp = gs.players.find(p => p.id === gs.current_turn_id);
    waiting.textContent = cp ? `Waiting for ${cp.name}...` : "";
    area.appendChild(waiting);
  }
}

// ── Superuser enable ──────────────────────────────────────────────────────

async function enableSuperuser() {
  try {
    await apiPost(`/superuser/enable/${S.roomId}`, {});
    const btn = document.getElementById("btn-superuser-enable");
    btn.textContent = "Superuser Mode: ON";
    btn.disabled    = true;
    document.getElementById("superuser-confirm").classList.add("hidden");
  } catch (e) {
    setGameError(`Superuser enable failed: ${e.message}`);
  }
}

// ── Event listeners ───────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Landing
  document.getElementById("create-btn").addEventListener("click", createRoom);
  document.getElementById("join-btn").addEventListener("click",   joinRoom);
  document.getElementById("create-name").addEventListener("keydown", e => {
    if (e.key === "Enter") createRoom();
  });
  document.getElementById("join-name").addEventListener("keydown", e => {
    if (e.key === "Enter") joinRoom();
  });
  document.getElementById("join-code").addEventListener("keydown", e => {
    if (e.key === "Enter") joinRoom();
  });

  // Room code click → copy to clipboard
  for (const id of ["lobby-room-code", "game-room-code"]) {
    document.getElementById(id).addEventListener("click", () => {
      if (S.roomId) navigator.clipboard.writeText(S.roomId).catch(() => {});
    });
  }

  // Mode selector
  document.getElementById("btn-upgrade").addEventListener("click", () => {
    sendWS({ action: "select_mode", mode: "upgrade" });
  });
  document.getElementById("btn-find-friends").addEventListener("click", () => {
    sendWS({ action: "select_mode", mode: "find_friends" });
  });

  // Superuser
  document.getElementById("btn-superuser-enable").addEventListener("click", () => {
    document.getElementById("superuser-confirm").classList.remove("hidden");
  });
  document.getElementById("btn-superuser-yes").addEventListener("click", enableSuperuser);
  document.getElementById("btn-superuser-cancel").addEventListener("click", () => {
    document.getElementById("superuser-confirm").classList.add("hidden");
  });

  // Overlay OK → reset all state and go back to landing
  document.getElementById("overlay-btn").addEventListener("click", () => {
    hideOverlay();
    clearTimeout(_roundOverlayTimer);
    _roundOverlayTimer = null;
    if (S.ws) { try { S.ws.close(); } catch (_) {} S.ws = null; }
    Object.assign(S, {
      roomId: null, playerId: null, playerName: null,
      isGameMaster: false, roomUpdate: null, gameState: null,
      awaitingValidation: false,
    });
    S.selectedKeys.clear();
    showScreen("screen-landing");
  });

  showScreen("screen-landing");
});
