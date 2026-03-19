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

// Display string for a rank value (e.g. "small_joker" → "SJ")
function rankDisplay(rank) {
  if (rank === "small_joker") return "SJ";
  if (rank === "big_joker")   return "BJ";
  return rank;
}

// ── Application state ─────────────────────────────────────────────────────

const S = {
  roomId:       null,   // string
  playerId:     null,   // string
  playerName:   null,   // string
  isGameMaster: false,

  ws:           null,   // WebSocket

  // Last received messages
  roomUpdate:   null,   // last room_update payload
  gameState:    null,   // last game_state payload

  // In-hand selection: Set of card-index strings (index into hand array)
  selectedIndices: new Set(),

  // Waiting for play_valid/play_invalid from server?
  awaitingValidation: false,

  // Superuser confirm step visible?
  superuserConfirmVisible: false,
};

// ── Screen management ─────────────────────────────────────────────────────

function showScreen(id) {
  for (const el of document.querySelectorAll(
    "#screen-landing, #screen-lobby, #screen-game"
  )) {
    el.style.display = "none";
  }
  document.getElementById(id).style.display = "flex";
  document.getElementById(id).style.flexDirection = "column";
}

// ── Error display ─────────────────────────────────────────────────────────

function setLandingError(msg) {
  document.getElementById("landing-error").textContent = msg;
}

function setGameError(msg) {
  const el = document.getElementById("game-error");
  el.textContent = msg;
  if (msg) {
    clearTimeout(el._timeout);
    el._timeout = setTimeout(() => { el.textContent = ""; }, 5000);
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

  S.ws.addEventListener("close", () => {
    // If we didn't already handle a game_aborted, show a generic message
    showOverlay("Disconnected", "Connection to the server was lost.", true);
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
    case "room_update":   handleRoomUpdate(msg);   break;
    case "game_state":    handleGameState(msg);    break;
    case "card_dealt":    handleCardDealt(msg);    break;
    case "round_over":    handleRoundOver(msg);    break;
    case "game_over":     handleGameOver(msg);     break;
    case "game_aborted":  handleGameAborted(msg);  break;
    case "play_valid":    handlePlayValid();        break;
    case "play_invalid":  handlePlayInvalid(msg);  break;
    case "error":         handleError(msg);        break;
    default: console.warn("Unknown message type:", msg.type);
  }
}

// ── Message handlers ──────────────────────────────────────────────────────

function handleRoomUpdate(msg) {
  S.roomUpdate = msg;

  // Determine if we are game master
  S.isGameMaster = (S.playerId === msg.game_master_id);

  // Update room code displays
  document.getElementById("lobby-room-code").textContent = `ROOM CODE: ${msg.room_id}`;
  document.getElementById("game-room-code").textContent  = `ROOM CODE: ${msg.room_id}`;

  renderLobby();
}

function handleGameState(msg) {
  S.gameState = msg;

  // Transition to game screen once dealing has started
  const gamePhases = ["DEALING","BIDDING_AFTER_DEAL","BOTTOM_EXCHANGE",
                      "FRIEND_DECLARATION","PLAYING","SCORING","ROUND_OVER","GAME_OVER"];
  if (gamePhases.includes(msg.phase)) {
    showScreen("screen-game");
  } else if (msg.phase === "WAITING") {
    showScreen("screen-lobby");
    renderLobby();
  }

  // Update trump info in top bars
  updateTrumpInfo(msg);

  // If in game, render game screen
  if (document.getElementById("screen-game").style.display !== "none") {
    renderGame(msg);
  }
}

function handleCardDealt(msg) {
  // Server also sends a game_state after card_dealt, so we don't need to
  // manually append the card — the next game_state will include the updated hand.
  // This handler is a no-op; the hand re-renders on game_state.
}

function handleRoundOver(msg) {
  const winner = msg.winner === "defending" ? "Defenders" : "Attackers";
  const pts    = msg.attacking_points;
  const steps  = msg.steps;
  let body;
  if (steps > 0) {
    body = `Attacking team scored ${pts} pts.\n${winner} advance ${steps} rank(s).`;
  } else if (steps < 0) {
    body = `Attacking team scored ${pts} pts.\n${winner} advance ${Math.abs(steps)} rank(s).`;
  } else {
    body = `Attacking team scored ${pts} pts.\nAttackers take over as defenders (no rank change).`;
  }
  // Don't show overlay for round_over — the next game_state will re-render
  // with ROUND_OVER phase, which we show inline.
  setGameError(`Round over! ${winner} win. ${body.replace("\n", " ")}`);
}

function handleGameOver(msg) {
  const winner = msg.winner === "defending" ? "Defenders" : "Attackers";
  showOverlay("Game Over!", `${winner} win the game!`, true);
}

function handleGameAborted(msg) {
  showOverlay("Game Aborted", msg.reason || "A player disconnected.", true);
}

function handlePlayValid() {
  S.awaitingValidation = false;
  // Commit the play with the currently selected cards
  const cards = selectedCards();
  sendWS({ action: "play_cards", cards });
  S.selectedIndices.clear();
  setGameError("");
  const el = document.getElementById("play-validation-msg");
  if (el) { el.textContent = ""; el.className = ""; }
}

function handlePlayInvalid(msg) {
  S.awaitingValidation = false;
  const el = document.getElementById("play-validation-msg");
  if (el) {
    el.textContent = msg.reason || "Invalid play.";
    el.className = "";
  }
  setGameError(msg.reason || "Invalid play.");
}

function handleError(msg) {
  setGameError(msg.message || "Server error.");
}

// ── Overlay ───────────────────────────────────────────────────────────────

function showOverlay(title, body, showBtn) {
  document.getElementById("overlay-title").textContent = title;
  document.getElementById("overlay-body").textContent  = body;
  const btn = document.getElementById("overlay-btn");
  if (showBtn) {
    btn.classList.remove("hidden");
  } else {
    btn.classList.add("hidden");
  }
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
    // Find leader's rank or just use "2"
    const players = gs.players || [];
    // Defending players' rank determines what's being played
    const defending = players.filter(p => p.is_defending);
    const dispRank = defending.length ? defending[0].rank : (players[0] ? players[0].rank : "2");
    text = `Currently at Rank ${rankDisplay(dispRank)}`;
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
  const phase  = gs ? gs.phase : "WAITING";
  const nPlayers = ru.players.length;

  // Player list
  const list = document.getElementById("player-list");
  list.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    if (i < nPlayers) {
      const p   = ru.players[i];
      const div = document.createElement("div");
      div.className = "player-entry";
      div.textContent = p.name;
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
  if (phase !== "WAITING") {
    statusEl.textContent = "Game in progress...";
  } else if (nPlayers < 4) {
    statusEl.textContent = `Waiting for players... (${nPlayers}/4)`;
  } else if (!mode) {
    statusEl.textContent = S.isGameMaster
      ? "4 players ready — select a game mode to begin."
      : "4 players ready — waiting for host to select a game mode.";
  } else {
    statusEl.textContent = `Mode: ${modeName(mode)}. Starting...`;
  }

  // Mode selector (game master only, WAITING phase)
  const modeDiv = document.getElementById("mode-selector");
  if (S.isGameMaster && phase === "WAITING") {
    modeDiv.classList.remove("hidden");
    document.getElementById("btn-upgrade").classList.toggle("active", mode === "upgrade");
    document.getElementById("btn-find-friends").classList.toggle("active", mode === "find_friends");
  } else {
    modeDiv.classList.add("hidden");
  }

  // Superuser section (game master only)
  const suDiv = document.getElementById("superuser-section");
  if (S.isGameMaster) {
    suDiv.classList.remove("hidden");
  } else {
    suDiv.classList.add("hidden");
  }
}

function modeName(mode) {
  if (mode === "upgrade")      return "Upgrade (升级)";
  if (mode === "find_friends") return "Find Friends (找朋友)";
  return mode || "—";
}

// ── Game screen rendering ─────────────────────────────────────────────────

function renderGame(gs) {
  renderRoundInfo(gs);
  renderTrickArea(gs);
  renderPoints(gs);
  renderHand(gs);
  renderActionArea(gs);
}

function renderRoundInfo(gs) {
  let text = `Round ${gs.round_number}`;
  if (gs.phase === "PLAYING" || gs.phase === "SCORING") {
    text += ` · Trick ${gs.trick_number}`;
  }
  text += ` · ${gs.phase}`;
  document.getElementById("round-info").textContent = text;
}

// ── Trick area ────────────────────────────────────────────────────────────

function renderTrickArea(gs) {
  const myIdx = playerIndex(gs, S.playerId);
  if (myIdx === -1) return;

  // Positions relative to self (counter-clockwise seating)
  const idxTop   = (myIdx + 2) % 4;  // opposite
  const idxLeft  = (myIdx + 1) % 4;  // counter-clockwise (my left)
  const idxRight = (myIdx + 3) % 4;  // clockwise (my right)
  const idxBot   = myIdx;

  const positions = {
    top:    { idx: idxTop,   nameEl: "name-top",    cardsEl: "cards-top"    },
    left:   { idx: idxLeft,  nameEl: "name-left",   cardsEl: "cards-left"   },
    right:  { idx: idxRight, nameEl: "name-right",  cardsEl: "cards-right"  },
    bottom: { idx: idxBot,   nameEl: "name-bottom", cardsEl: "cards-bottom" },
  };

  // Build a map from player_id → cards played in current trick
  const trickMap = {};
  for (const play of (gs.current_trick || [])) {
    trickMap[play.player_id] = play.cards;
  }

  for (const [, pos] of Object.entries(positions)) {
    const p     = gs.players[pos.idx];
    const nameEl  = document.getElementById(pos.nameEl);
    const cardsEl = document.getElementById(pos.cardsEl);

    // Label
    let label = p ? p.name : "—";
    nameEl.textContent = label;
    nameEl.className   = "player-name-label";
    if (p && p.id === gs.current_turn_id) {
      nameEl.classList.add("is-turn");
    } else if (p && p.id === gs.current_leader_id) {
      nameEl.classList.add("is-leader");
    }

    // Cards in trick
    cardsEl.innerHTML = "";
    const played = p ? (trickMap[p.id] || []) : [];
    for (const card of played) {
      cardsEl.appendChild(makeCardEl(card, false));
    }
  }

  // Center status
  const statusEl = document.getElementById("trick-status");
  if (gs.phase === "PLAYING") {
    const currentPlayer = gs.players.find(p => p.id === gs.current_turn_id);
    statusEl.textContent = currentPlayer ? `${currentPlayer.name}'s turn` : "";
  } else {
    statusEl.textContent = "";
  }
}

// ── Points display ────────────────────────────────────────────────────────

function renderPoints(gs) {
  const atk = gs.attacking_points || 0;
  const needed = 200; // 2 decks × 100 pts
  document.getElementById("pts-attacking").textContent = atk;
  // Show what defending team needs to win (score < 200n means defenders win if < 200)
  document.getElementById("pts-defending").textContent = `${needed - atk} remaining`;
}

// ── Hand rendering ────────────────────────────────────────────────────────

function renderHand(gs) {
  const me = gs.players.find(p => p.id === S.playerId);
  const handArea   = document.getElementById("hand-area");
  const handHeader = document.getElementById("hand-header");
  handArea.innerHTML = "";

  if (!me || !me.hand) {
    handHeader.textContent = "";
    return;
  }

  const phase = gs.phase;
  const isMyTurn = gs.current_turn_id === S.playerId;
  const canSelect = (
    phase === "PLAYING" ||
    phase === "BOTTOM_EXCHANGE" ||
    phase === "FRIEND_DECLARATION"
  );

  handHeader.textContent = `Your hand (${me.hand.length} cards)`;

  // Sort hand
  const sorted = sortHand(me.hand, gs.trump_context);

  for (let i = 0; i < sorted.length; i++) {
    const { card, origIndex } = sorted[i];
    const key = String(origIndex);
    const el  = makeCardEl(card, canSelect);
    if (canSelect) {
      if (S.selectedIndices.has(key)) {
        el.classList.add("selected");
      }
      el.addEventListener("click", () => toggleCard(key, el, gs));
    }
    el.dataset.idx = key;
    handArea.appendChild(el);
  }
}

function toggleCard(key, el, gs) {
  const phase = gs.phase;
  if (phase === "PLAYING") {
    if (S.selectedIndices.has(key)) {
      S.selectedIndices.delete(key);
      el.classList.remove("selected");
    } else {
      S.selectedIndices.add(key);
      el.classList.add("selected");
    }
  } else if (phase === "BOTTOM_EXCHANGE") {
    // Allow up to 8 selected
    if (S.selectedIndices.has(key)) {
      S.selectedIndices.delete(key);
      el.classList.remove("selected");
    } else if (S.selectedIndices.size < 8) {
      S.selectedIndices.add(key);
      el.classList.add("selected");
    }
    updateBottomExchangeBtn(gs);
  } else if (phase === "FRIEND_DECLARATION") {
    // No card selection for friend declaration — handled via dropdowns
  }
}

// ── Card element creation ─────────────────────────────────────────────────

function makeCardEl(card, selectable) {
  const el = document.createElement("span");
  el.className = `card ${SUIT_COLOR_CLASS[card.suit] || ""}`;
  if (selectable) el.classList.add("selectable");

  const rankEl = document.createElement("span");
  rankEl.className = "card-rank";
  rankEl.textContent = rankDisplay(card.rank);

  const suitEl = document.createElement("span");
  suitEl.className = "card-suit";
  suitEl.textContent = SUIT_SYMBOL[card.suit] || card.suit;

  el.appendChild(rankEl);
  el.appendChild(suitEl);
  return el;
}

// ── Hand sorting ──────────────────────────────────────────────────────────

function sortHand(hand, trumpContext) {
  const indexed = hand.map((card, i) => ({ card, origIndex: i }));
  indexed.sort((a, b) => {
    const ka = cardSortKey(a.card, trumpContext);
    const kb = cardSortKey(b.card, trumpContext);
    // Compare multi-key tuples
    for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
      const diff = (ka[i] || 0) - (kb[i] || 0);
      if (diff !== 0) return diff;
    }
    return 0;
  });
  return indexed;
}

function cardSortKey(card, ctx) {
  // Returns [primaryGroup, secondaryOrder] where lower = left in hand.
  // Groups: 0-3 = non-trump suits (spades, hearts, diamonds, clubs)
  //         7   = trump suit non-rank
  //         8   = off-suit trump rank cards
  //         9   = on-suit trump rank card
  //         10  = jokers

  const SUITS_ORDER = ["spades", "hearts", "diamonds", "clubs"];
  const rankIdx = RANK_ORDER.indexOf(card.rank);

  if (card.rank === "small_joker") return [10, 0];
  if (card.rank === "big_joker")   return [10, 1];

  if (!ctx || !ctx.trump_rank) {
    // No trump context — sort by suit, then by rank descending
    const si = SUITS_ORDER.indexOf(card.suit);
    return [si >= 0 ? si : 4, rankIdx];
  }

  const { trump_rank, trump_suit } = ctx;
  const isTrumpRank = card.rank === trump_rank;
  const isTrumpSuit = trump_suit && card.suit === trump_suit;

  if (isTrumpRank && isTrumpSuit) return [9, 0];
  if (isTrumpRank)                return [8, SUITS_ORDER.indexOf(card.suit)];
  if (isTrumpSuit)                return [7, rankIdx];

  const si = SUITS_ORDER.indexOf(card.suit);
  return [si >= 0 ? si : 4, rankIdx];
}

// ── Selected cards helper ─────────────────────────────────────────────────

function selectedCards() {
  const gs = S.gameState;
  if (!gs) return [];
  const me = gs.players.find(p => p.id === S.playerId);
  if (!me || !me.hand) return [];
  const cards = [];
  for (const idx of S.selectedIndices) {
    const card = me.hand[parseInt(idx, 10)];
    if (card) cards.push(card);
  }
  return cards;
}

// ── Action area rendering ─────────────────────────────────────────────────

function renderActionArea(gs) {
  const area = document.getElementById("action-area");
  area.innerHTML = "";
  document.getElementById("play-validation-msg") &&
    (document.getElementById("play-validation-msg").textContent = "");

  const phase = gs.phase;

  if (phase === "DEALING" || phase === "BIDDING_AFTER_DEAL") {
    renderBidArea(area, gs);
  } else if (phase === "BOTTOM_EXCHANGE") {
    renderBottomExchange(area, gs);
  } else if (phase === "FRIEND_DECLARATION") {
    renderFriendDeclaration(area, gs);
  } else if (phase === "PLAYING") {
    renderPlayArea(area, gs);
  } else if (phase === "SCORING" || phase === "ROUND_OVER") {
    const p = document.createElement("p");
    p.textContent = phase === "SCORING" ? "Scoring in progress..." : "Round over — next round starting...";
    p.style.color = "#888";
    area.appendChild(p);
  } else if (phase === "WAITING") {
    const p = document.createElement("p");
    p.textContent = "Waiting in lobby...";
    p.style.color = "#888";
    area.appendChild(p);
  }
}

// ── Bid area ──────────────────────────────────────────────────────────────

function renderBidArea(area, gs) {
  // Current bid display
  const bidInfoDiv = document.createElement("div");
  bidInfoDiv.id = "current-bid-display";
  const lastBid = gs.bids && gs.bids.length ? gs.bids[gs.bids.length - 1] : null;
  if (lastBid) {
    const bidderName = playerName(gs, lastBid.player_id);
    const cards      = lastBid.cards || [];
    const isPair     = cards.length >= 2;
    const tc         = lastBid.resulting_trump;
    let bidDesc;
    if (tc && !tc.trump_suit) {
      bidDesc = isPair ? "No Trump (pair)" : "No Trump";
    } else if (tc) {
      const sym = SUIT_SYMBOL[tc.trump_suit] || tc.trump_suit;
      bidDesc = isPair ? `${rankDisplay(tc.trump_rank)} ${sym} (pair)` : `${rankDisplay(tc.trump_rank)} ${sym}`;
    } else {
      bidDesc = cards.map(c => `${rankDisplay(c.rank)}${SUIT_SYMBOL[c.suit]}`).join("");
    }
    bidInfoDiv.innerHTML = `Current bid: <strong>${bidderName} — ${bidDesc}</strong>`;
  } else {
    bidInfoDiv.innerHTML = "No bid yet.";
  }
  area.appendChild(bidInfoDiv);

  // Available bids (per-player, from server)
  const available = gs.available_bids || [];

  const bidRow = document.createElement("div");
  bidRow.className = "action-row";

  const SUIT_SYMS = [
    { suit: "spades",   sym: "♠" },
    { suit: "hearts",   sym: "♥" },
    { suit: "diamonds", sym: "♦" },
    { suit: "clubs",    sym: "♣" },
  ];

  for (const { suit, sym } of SUIT_SYMS) {
    const btn = document.createElement("button");
    btn.className = `bid-btn-suit suit-${suit}`;
    btn.textContent = sym;
    const hasSingle = available.some(b => b.type === "single" && b.suit === suit);
    const hasPair   = available.some(b => b.type === "pair"   && b.suit === suit);
    btn.disabled = !(hasSingle || hasPair);
    if (!btn.disabled) {
      btn.title = hasPair ? `Bid ${sym} (pair)` : `Bid ${sym} (single)`;
      btn.addEventListener("click", () => sendWS({ action: "bid", suit }));
    }
    bidRow.appendChild(btn);
  }

  // Joker buttons
  for (const joker of ["small", "big"]) {
    const btn = document.createElement("button");
    btn.textContent = joker === "small" ? "No Trump (SJ)" : "No Trump (BJ)";
    btn.disabled = !available.some(b => b.type === "joker_pair" && b.joker === joker);
    if (!btn.disabled) {
      btn.addEventListener("click", () => sendWS({ action: "bid", joker }));
    }
    bidRow.appendChild(btn);
  }

  area.appendChild(bidRow);

  // Pass / close bidding buttons
  const ctrlRow = document.createElement("div");
  ctrlRow.className = "action-row";

  if (gs.phase === "BIDDING_AFTER_DEAL") {
    const passBtn = document.createElement("button");
    passBtn.textContent = "Pass";
    passBtn.addEventListener("click", () => sendWS({ action: "pass_bid" }));
    ctrlRow.appendChild(passBtn);
  }

  if (S.isGameMaster) {
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Close Bidding";
    closeBtn.addEventListener("click", () => sendWS({ action: "close_bidding" }));
    ctrlRow.appendChild(closeBtn);
  }

  if (ctrlRow.children.length) area.appendChild(ctrlRow);

  // Progress bar for dealt cards
  const total = 100; // 100 cards in draw pile
  const dealt = gs.cards_dealt_count || 0;
  const prog  = document.createElement("div");
  prog.style.cssText = "font-size:12px;color:#666;text-align:center;";
  prog.textContent = gs.phase === "DEALING"
    ? `Dealing cards... ${dealt}/${total}`
    : `All ${total} cards dealt. Bidding phase.`;
  area.appendChild(prog);
}

// ── Bottom exchange ───────────────────────────────────────────────────────

function renderBottomExchange(area, gs) {
  const isLeader = gs.current_turn_id === S.playerId ||
                   (gs.players.find(p => p.id === S.playerId) && gs.players.find(p=>p.id===S.playerId).id);
  // Only the round_leader can exchange; detect via bottom_deck visibility
  const isMyExchange = Array.isArray(gs.bottom_deck);

  if (!isMyExchange) {
    const p = document.createElement("p");
    p.textContent = "Waiting for the bid winner to exchange the bottom deck...";
    p.style.color = "#888";
    area.appendChild(p);
    return;
  }

  // Show bottom deck cards in the area
  const bottomDiv = document.createElement("div");
  bottomDiv.style.cssText = "font-size:13px;color:#aaa;margin-bottom:6px;text-align:center;";
  bottomDiv.textContent = "Bottom cards added to your hand. Select 8 to put back:";
  area.appendChild(bottomDiv);

  // Selection count
  const selCount = document.createElement("div");
  selCount.id    = "bottom-sel-count";
  selCount.style.cssText = "font-size:13px;color:#ffcc44;text-align:center;";
  selCount.textContent   = `${S.selectedIndices.size}/8 selected`;
  area.appendChild(selCount);

  // Confirm button
  const confirmBtn = document.createElement("button");
  confirmBtn.id        = "bottom-confirm-btn";
  confirmBtn.textContent = "Confirm Exchange";
  confirmBtn.disabled    = S.selectedIndices.size !== 8;
  confirmBtn.addEventListener("click", () => {
    const cards = selectedCards();
    if (cards.length !== 8) { setGameError("Select exactly 8 cards."); return; }
    sendWS({ action: "exchange_bottom", cards_to_put_back: cards });
    S.selectedIndices.clear();
  });

  const row = document.createElement("div");
  row.className = "action-row";
  row.appendChild(confirmBtn);
  area.appendChild(row);
}

function updateBottomExchangeBtn(gs) {
  const btn = document.getElementById("bottom-confirm-btn");
  if (btn) btn.disabled = S.selectedIndices.size !== 8;
  const cnt = document.getElementById("bottom-sel-count");
  if (cnt) cnt.textContent = `${S.selectedIndices.size}/8 selected`;
}

// ── Friend declaration ────────────────────────────────────────────────────

function renderFriendDeclaration(area, gs) {
  const me = gs.players.find(p => p.id === S.playerId);
  const isLeader = me && me.id === (gs.players.find(p => p.is_defending && gs.players.indexOf(p) === 0)?.id
    || gs.current_leader_id);

  // Find who is the round leader (bid winner = is_defending leader)
  // We detect if it's our turn by whether current_turn_id is us or by checking
  // if we have a full hand (33 cards → bottom exchange done, we're the leader)
  const myHand    = me ? (me.hand || []) : [];
  const iAmLeader = me && (gs.current_turn_id === "" || myHand.length >= 25);

  // Simpler: only show the form if our player is the one who should declare.
  // Server will reject the action if we're not the leader anyway.

  const panel = document.createElement("div");
  panel.id = "friend-decl-panel";

  const info = document.createElement("div");
  info.style.cssText = "font-size:13px;color:#aaa;text-align:center;";

  // Check if we are the round leader by comparing server state
  // The server sends FRIEND_DECLARATION phase to everyone after exchange_bottom
  // Only the round_leader_id player can declare.
  // We detect via: the server sends current_turn_id = "" during FRIEND_DECLARATION,
  // and the player with the full hand after bottom exchange is the leader.
  // Best approach: just show UI to everyone and let server reject non-leaders.

  info.textContent = "Declare your friend card (Find Friends mode):";
  panel.appendChild(info);

  const ctx = gs.trump_context;
  const trumpRank = ctx ? ctx.trump_rank : null;

  // Rank dropdown (2–A, excluding trump rank)
  const rankLabel = document.createElement("label");
  rankLabel.textContent = "Rank: ";

  const rankSel = document.createElement("select");
  rankSel.id = "fd-rank";
  for (const r of RANK_ORDER) {
    if (r === trumpRank) continue; // exclude trump rank
    const opt = document.createElement("option");
    opt.value = r;
    opt.textContent = rankDisplay(r);
    rankSel.appendChild(opt);
  }

  // Suit dropdown
  const suitLabel = document.createElement("label");
  suitLabel.textContent = "Suit: ";

  const suitSel = document.createElement("select");
  suitSel.id = "fd-suit";
  for (const [suit, sym] of Object.entries(SUIT_SYMBOL)) {
    if (suit === "joker") continue;
    const opt = document.createElement("option");
    opt.value = suit;
    opt.textContent = `${sym} ${suit}`;
    suitSel.appendChild(opt);
  }

  // Ordinal dropdown
  const ordLabel = document.createElement("label");
  ordLabel.textContent = "Ordinal: ";

  const ordSel = document.createElement("select");
  ordSel.id = "fd-ordinal";
  for (const ord of [1, 2]) {
    const opt = document.createElement("option");
    opt.value = ord;
    opt.textContent = ord === 1 ? "1st person to play this card" : "2nd person to play this card";
    ordSel.appendChild(opt);
  }

  const row1 = document.createElement("div");
  row1.className = "friend-decl-row";
  row1.appendChild(rankLabel);
  row1.appendChild(rankSel);
  row1.appendChild(suitLabel);
  row1.appendChild(suitSel);
  row1.appendChild(ordLabel);
  row1.appendChild(ordSel);

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

  panel.appendChild(row1);
  panel.appendChild(declBtn);
  area.appendChild(panel);
}

// ── Play area ─────────────────────────────────────────────────────────────

function renderPlayArea(area, gs) {
  const isMyTurn = gs.current_turn_id === S.playerId;

  // Validation message area
  const msgDiv = document.createElement("div");
  msgDiv.id = "play-validation-msg";
  area.appendChild(msgDiv);

  const row = document.createElement("div");
  row.className = "action-row";

  // Play button
  const playBtn = document.createElement("button");
  playBtn.textContent = "Play";
  playBtn.disabled    = !isMyTurn || S.selectedIndices.size === 0 || S.awaitingValidation;
  playBtn.addEventListener("click", () => {
    if (S.selectedIndices.size === 0) { setGameError("Select cards to play."); return; }
    const cards = selectedCards();
    S.awaitingValidation = true;
    sendWS({ action: "validate_play", cards });
    // Re-render to show disabled state
    playBtn.disabled = true;
  });

  // Clear selection button
  const clearBtn = document.createElement("button");
  clearBtn.textContent = "Clear Selection";
  clearBtn.addEventListener("click", () => {
    S.selectedIndices.clear();
    renderHand(gs);
  });

  row.appendChild(playBtn);
  row.appendChild(clearBtn);
  area.appendChild(row);

  if (!isMyTurn) {
    const waiting = document.createElement("div");
    waiting.style.cssText = "font-size:12px;color:#666;text-align:center;";
    const currentPlayer = gs.players.find(p => p.id === gs.current_turn_id);
    waiting.textContent = currentPlayer ? `Waiting for ${currentPlayer.name}...` : "";
    area.appendChild(waiting);
  }
}

// ── Lobby helpers ─────────────────────────────────────────────────────────

function playerIndex(gs, pid) {
  return gs.players.findIndex(p => p.id === pid);
}

function playerName(gs, pid) {
  const p = gs.players.find(p => p.id === pid);
  return p ? p.name : pid;
}

// ── Superuser enable ──────────────────────────────────────────────────────

async function enableSuperuser() {
  try {
    await apiPost(`/superuser/enable/${S.roomId}`, {});
    document.getElementById("btn-superuser-enable").textContent = "Superuser Mode: ON";
    document.getElementById("btn-superuser-enable").disabled = true;
    document.getElementById("superuser-confirm").classList.add("hidden");
  } catch (e) {
    setGameError(`Superuser enable failed: ${e.message}`);
  }
}

// ── Event listeners (init) ────────────────────────────────────────────────

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

  // Room code copy-on-click
  for (const id of ["lobby-room-code", "game-room-code"]) {
    document.getElementById(id).addEventListener("click", () => {
      const code = S.roomId;
      if (code) navigator.clipboard.writeText(code).catch(() => {});
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
  document.getElementById("btn-superuser-yes").addEventListener("click", () => {
    enableSuperuser();
  });
  document.getElementById("btn-superuser-cancel").addEventListener("click", () => {
    document.getElementById("superuser-confirm").classList.add("hidden");
  });

  // Overlay OK button → return to landing
  document.getElementById("overlay-btn").addEventListener("click", () => {
    hideOverlay();
    if (S.ws) { try { S.ws.close(); } catch (_) {} S.ws = null; }
    S.roomId = S.playerId = S.playerName = null;
    S.isGameMaster = false;
    S.roomUpdate = S.gameState = null;
    S.selectedIndices.clear();
    S.awaitingValidation = false;
    showScreen("screen-landing");
  });

  // Start on landing screen
  showScreen("screen-landing");
});
