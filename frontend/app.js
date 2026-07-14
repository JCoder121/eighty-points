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
  if (rank === "BJ") return "大";
  if (rank === "SJ") return "小";
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

  // Cards captured when Play was pressed (used across the check_play →
  // confirm → validate_play → play_cards round trips).
  pendingPlayCards: null,

  // Bidding state — reset when a new bid is placed or a new deal starts.
  hasPassed:     false,  // true once this player has pressed Pass this round
  lastBidsCount: 0,      // tracks gs.bids.length to detect new bids

  // Rank display sticky-note (client-only toggle).
  showRankDisplay: false,

  // Friend reveal tracking (Find Friends mode).
  // Reset each round; used to detect newly revealed friends.
  knownFriends:   new Set(),
  lastRoundNumber: null,
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
    case "ready_update": handleReadyUpdate(msg); break;
    case "game_over":    handleGameOver(msg);    break;
    case "game_aborted": handleGameAborted(msg); break;
    case "play_valid":   handlePlayValid();      break;
    case "play_invalid": handlePlayInvalid(msg); break;
    case "check_play_result": handleCheckPlayResult(msg); break;
    case "throw_failed": handleThrowFailed(msg); break;
    case "last_trick_hold": handleLastTrickHold(msg); break;
    case "redeal":       handleRedeal(msg);      break;
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

  // Dismiss round-over overlay whenever a new round starts dealing.
  // This triggers whether the overlay was auto-timed or awaiting ready clicks.
  if (msg.phase === "dealing") {
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

function handleLastTrickHold(msg) {
  // Show a countdown in the trick status area so players know round is ending.
  const statusEl = document.getElementById("trick-status");
  if (!statusEl) return;
  const delaySecs = Math.ceil(msg.delay || 3);
  let remaining = delaySecs;
  statusEl.textContent = `Round ending in ${remaining}s…`;
  const timer = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(timer);
      statusEl.textContent = "";
    } else {
      statusEl.textContent = `Round ending in ${remaining}s…`;
    }
  }, 1000);
}

function handleRedeal(msg) {
  const banner = document.createElement("div");
  banner.className = "redeal-banner";
  banner.textContent = msg.reason || "All players passed — re-dealing.";
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 3000);
}

function handleRoundOver(msg) {
  const pts      = msg.attacking_points || 0;
  const isDefWin = msg.winner === "defending";
  const steps    = msg.steps;
  const players  = msg.players || [];
  const bottomDeck = msg.bottom_deck || null;

  // Build HTML content for the overlay body
  const div = document.createElement("div");

  // Points line
  const overThreshold = pts >= ATK_THRESHOLD;
  const ptsLine = document.createElement("div");
  ptsLine.className = "pts-line";
  ptsLine.textContent = `Attacking scored ${pts} pts${overThreshold ? " ✓ (≥ 80)" : " ✗ (< 80)"}`;
  div.appendChild(ptsLine);

  // Outcome line
  const outLine = document.createElement("div");
  outLine.className = "outcome-line";
  if (isDefWin) {
    outLine.textContent = steps > 0
      ? `Defenders win — advance ${steps} rank${steps !== 1 ? "s" : ""}.`
      : "Defenders win — already at max rank.";
  } else if (steps === 0) {
    outLine.textContent = "Attackers take over as Defenders — same rank.";
  } else {
    outLine.textContent = `Attackers win — advance ${steps} rank${steps !== 1 ? "s" : ""}.`;
  }
  div.appendChild(outLine);

  // Team breakdown
  if (players.length) {
    const teamsRow = document.createElement("div");
    teamsRow.className = "teams-row";

    for (const teamKey of ["defending", "attacking"]) {
      const block = document.createElement("div");
      block.className = `team-block ${teamKey}`;

      const label = document.createElement("div");
      label.className = "team-label";
      label.textContent = teamKey === "defending" ? "Defenders" : "Attackers";
      block.appendChild(label);

      const teamPlayers = players.filter(p => p.is_defending === (teamKey === "defending"));
      for (const p of teamPlayers) {
        const line = document.createElement("div");
        line.className = "player-rank-line";
        const rankStr = p.old_rank && p.old_rank !== p.rank
          ? `${rankDisplay(p.old_rank)} → ${rankDisplay(p.rank)}`
          : rankDisplay(p.rank);
        line.textContent = `${p.name} — ${rankStr}`;
        block.appendChild(line);
      }
      teamsRow.appendChild(block);
    }
    div.appendChild(teamsRow);
  }

  // Bottom deck reveal (always shown so all players can review)
  if (bottomDeck && bottomDeck.length) {
    const botSection = document.createElement("div");
    botSection.className = "bottom-section";

    const botLabel = document.createElement("div");
    botLabel.className = "bottom-label";
    botLabel.textContent = "Bottom cards:";
    botSection.appendChild(botLabel);

    const botCards = document.createElement("div");
    botCards.className = "bottom-cards";
    for (const card of bottomDeck) {
      botCards.appendChild(makeCardEl(card, false));
    }
    botSection.appendChild(botCards);
    div.appendChild(botSection);
  }

  // Ready-for-next-round section
  const readySection = document.createElement("div");
  readySection.style.cssText = "margin-top:12px;display:flex;flex-direction:column;align-items:center;gap:6px;";

  const readyBtn = document.createElement("button");
  readyBtn.id = "overlay-ready-btn";
  readyBtn.textContent = "Ready for Next Round";
  readyBtn.style.cssText = "font-size:14px;padding:10px 20px;";
  readyBtn.addEventListener("click", () => {
    sendWS({ action: "ready_for_next_round" });
    readyBtn.textContent = "Ready ✓";
    readyBtn.disabled = true;
    readyBtn.classList.add("btn-passed");
  });
  readySection.appendChild(readyBtn);

  const readyCount = document.createElement("div");
  readyCount.id = "overlay-ready-count";
  readyCount.style.cssText = "font-size:12px;color:#666;";
  readyCount.textContent = "0/4 ready";
  readySection.appendChild(readyCount);

  div.appendChild(readySection);

  showRoundOverlay("Round Over", div);
}

function handleReadyUpdate(msg) {
  const el = document.getElementById("overlay-ready-count");
  if (el) el.textContent = `${msg.ready_count}/${msg.total} ready`;
}

function handleGameOver(msg) {
  clearTimeout(_roundOverlayTimer);
  _roundOverlayTimer = null;
  const isDefWin = msg.winner === "defending";
  const div = document.createElement("div");
  const line = document.createElement("div");
  line.className = "outcome-line";
  line.textContent = isDefWin
    ? "Defenders successfully defended from Ace — they win the game!"
    : "Attackers win the game!";
  div.appendChild(line);
  showFinalOverlay("Game Over!", div);
}

function handleGameAborted(msg) {
  clearTimeout(_roundOverlayTimer);
  _roundOverlayTimer = null;
  showFinalOverlay("Game Aborted", msg.reason || "A player disconnected.");
}

function handlePlayValid() {
  S.awaitingValidation = false;
  // Commit the validated play (pendingPlayCards survives re-renders that
  // clear the visual selection).
  const cards = S.pendingPlayCards || getSelectedCards();
  S.pendingPlayCards = null;
  sendWS({ action: "play_cards", cards });
  S.selectedKeys.clear();
  const el = document.getElementById("play-validation-msg");
  if (el) { el.textContent = ""; }
  setGameError("");
}

function handlePlayInvalid(msg) {
  S.awaitingValidation = false;
  S.pendingPlayCards = null;
  removeThrowConfirm();
  const reason = msg.reason || "Invalid play.";
  const el = document.getElementById("play-validation-msg");
  if (el) el.textContent = reason;
  setGameError(reason);
}

// ── Throw (甩牌) confirm flow ─────────────────────────────────────────────

function handleCheckPlayResult(msg) {
  const cards = S.pendingPlayCards;
  if (!cards || !cards.length) {
    S.awaitingValidation = false;
    return;
  }
  if (msg.is_throw) {
    showThrowConfirm(cards);
  } else {
    // Not a throw — continue with the normal validation flow.
    sendWS({ action: "validate_play", cards });
  }
}

function cardText(card) {
  return `${rankDisplay(card.rank)}${SUIT_SYMBOL[card.suit] || card.suit}`;
}

function removeThrowConfirm() {
  const bar = document.getElementById("throw-confirm-bar");
  if (bar) bar.remove();
}

function showThrowConfirm(cards) {
  removeThrowConfirm();
  const area = document.getElementById("action-area");
  if (!area) return;

  const bar = document.createElement("div");
  bar.id = "throw-confirm-bar";

  const text = document.createElement("div");
  text.className = "throw-confirm-text";
  text.textContent =
    `This play is a 甩牌 (throw) — if any part can be beaten, you'll be ` +
    `forced to play the beatable part and concede 10 pts per thrown card ` +
    `(${cards.length * 10} pts). Play it?`;
  bar.appendChild(text);

  const row = document.createElement("div");
  row.className = "action-row";

  const confirmBtn = document.createElement("button");
  confirmBtn.textContent = "Play Throw";
  confirmBtn.addEventListener("click", () => {
    removeThrowConfirm();
    sendWS({ action: "validate_play", cards });
  });

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => {
    removeThrowConfirm();
    S.pendingPlayCards = null;
    S.awaitingValidation = false;
    const playBtn = document.getElementById("play-btn");
    if (playBtn) playBtn.disabled = S.selectedKeys.size === 0;
  });

  row.appendChild(confirmBtn);
  row.appendChild(cancelBtn);
  bar.appendChild(row);
  area.appendChild(bar);
}

// Broadcast to all players when a leader's throw failed and was forced down
// to its smallest beatable component.  Mirrors the re-deal banner pattern.
function handleThrowFailed(msg) {
  const forced = (msg.forced_cards || []).map(cardText).join(" ");
  const banner = document.createElement("div");
  banner.className = "redeal-banner throw-failed-banner";
  banner.textContent =
    `${msg.player_name || "Player"}'s throw failed — forced to play ` +
    `${forced}, conceding ${msg.penalty} pts to the other team.`;
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 4000);
}

function handleError(msg) {
  setGameError(msg.message || "Server error.");
}

// ── Overlays ──────────────────────────────────────────────────────────────

// Set the overlay body — accepts a string or a DOM Node.
function _setOverlayBody(body) {
  const el = document.getElementById("overlay-body");
  el.innerHTML = "";
  if (typeof body === "string") {
    el.textContent = body;
  } else {
    el.appendChild(body);
  }
}

// Round-over: stays open until all players press "Ready for Next Round".
// Dismissed by the next DEALING game_state (in handleGameState).
function showRoundOverlay(title, body) {
  document.getElementById("overlay-title").textContent = title;
  _setOverlayBody(body);
  document.getElementById("overlay-btn").classList.add("hidden");
  document.getElementById("overlay").classList.remove("hidden");
}

// Final overlay (game over / disconnected): requires user to click OK.
function showFinalOverlay(title, body) {
  document.getElementById("overlay-title").textContent = title;
  _setOverlayBody(body);
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
  const leader = (gs.players || []).find(p => p.id === gs.round_leader_id);
  const inRound0Bidding = gs.round_number === 0 &&
    ["waiting", "dealing", "bidding_after_deal"].includes(gs.phase);
  if (leader && !inRound0Bidding) {
    text += ` · Leader: ${leader.name}`;
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

  // Mode selector (game master only, and only once all 4 players have joined)
  const modeDiv = document.getElementById("mode-selector");
  if (S.isGameMaster && phase === "waiting" && n === 4) {
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
  checkFriendReveals(gs);
  renderFriendStatus(gs);
  renderPoints(gs);
  renderHand(gs);
  renderActionArea(gs);
  renderRankDisplay(gs);
}

// ── Friend declaration status bar ─────────────────────────────────────────

function renderFriendStatus(gs) {
  const el = document.getElementById("friend-status");
  const decls = gs.friend_declarations;
  if (gs.mode !== "find_friends" || !decls || decls.length === 0) {
    el.classList.add("hidden");
    return;
  }

  const decl = decls[0];
  const card = decl.card;
  const sym  = SUIT_SYMBOL[card.suit] || card.suit;

  if (decl.resolved_player_id) {
    const friend = gs.players.find(p => p.id === decl.resolved_player_id);
    const name   = friend ? friend.name : decl.resolved_player_id;
    el.textContent = `${name} is the friend!`;
    el.classList.remove("hidden");
  } else {
    const leader = gs.players.find(p => p.id === gs.round_leader_id);
    const name   = leader ? leader.name : gs.round_leader_id;
    el.textContent = `${name} is looking for ${card.rank}${sym}`;
    el.classList.remove("hidden");
  }
}

// ── Friend reveal popups ──────────────────────────────────────────────────

function checkFriendReveals(gs) {
  if (gs.mode !== "find_friends") return;

  // Reset known friends at the start of each new round.
  if (gs.round_number !== S.lastRoundNumber) {
    S.knownFriends.clear();
    S.lastRoundNumber = gs.round_number;
  }

  const revealed = gs.revealed_friends || [];
  for (const pid of revealed) {
    if (S.knownFriends.has(pid)) continue;
    S.knownFriends.add(pid);

    const player = gs.players.find(p => p.id === pid);
    if (!player) continue;

    // Find which position (top/left/right/bottom) this player occupies.
    const myIdx = gs.players.findIndex(p => p.id === S.playerId);
    const playerIdx = gs.players.findIndex(p => p.id === pid);
    const posMap = { top: (myIdx + 2) % 4, left: (myIdx + 1) % 4, right: (myIdx + 3) % 4, bottom: myIdx };
    const posName = Object.keys(posMap).find(k => posMap[k] === playerIdx);
    if (!posName) continue;

    const posDiv = document.getElementById(`pos-${posName}`);
    if (!posDiv) continue;

    const popup = document.createElement("div");
    popup.className = "friend-reveal-popup";
    popup.textContent = `${player.name} is the friend!`;
    posDiv.appendChild(popup);
    setTimeout(() => popup.remove(), 4000);
  }
}

// ── Rank sticky-note ──────────────────────────────────────────────────────

function renderRankDisplay(gs) {
  const panel = document.getElementById("rank-display");
  if (!S.showRankDisplay) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");

  const content = document.getElementById("rank-display-content");
  content.innerHTML = "";

  const teamsKnown = gs.players && gs.players.some(p => p.team !== undefined && p.team !== null);

  for (const p of (gs.players || [])) {
    const row = document.createElement("div");
    row.className = "rank-entry" + (p.id === S.playerId ? " is-self" : "");

    const nameSpan = document.createElement("span");
    nameSpan.textContent = p.name;
    row.appendChild(nameSpan);

    const right = document.createElement("span");
    right.style.display = "flex";
    right.style.gap = "6px";
    right.style.alignItems = "center";

    const rankSpan = document.createElement("span");
    rankSpan.className = "rank-val";
    rankSpan.textContent = rankDisplay(p.rank || "2");
    right.appendChild(rankSpan);

    if (teamsKnown && p.team) {
      const tag = document.createElement("span");
      tag.className = "team-tag " + (p.is_defending ? "def" : "atk");
      tag.textContent = p.is_defending ? "Def" : "Atk";
      right.appendChild(tag);
    }

    row.appendChild(right);
    content.appendChild(row);
  }
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
      if (p.id === S.playerId)           nameEl.classList.add("is-self");
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

// With 2 decks (200 total pts), the threshold for attackers to take over is 80 pts.
const ATK_THRESHOLD = 80;

function renderPoints(gs) {
  const atk = gs.attacking_points || 0;
  document.getElementById("pts-attacking").textContent = atk;
  const statusEl = document.getElementById("pts-threshold-status");
  if (atk >= ATK_THRESHOLD) {
    const over = atk - ATK_THRESHOLD;
    statusEl.textContent = `+${over} over 80 ✓`;
    statusEl.style.color = "#66ff88";
  } else {
    const need = ATK_THRESHOLD - atk;
    statusEl.textContent = `need ${need} more (of 80)`;
    statusEl.style.color = "#aaa";
  }
}

// ── Hand rendering helpers ────────────────────────────────────────────────

function isJoker(card) {
  return card.rank === "SJ" || card.rank === "BJ";
}

// Return true if card is a trump card given the resolved trump context.
// Jokers are ALWAYS trump regardless of context.
// Also covers trump-rank cards (any suit) and trump-suit cards (if a suit is set).
function isTrumpCard(card, trumpContext) {
  if (isJoker(card)) return true;
  if (!trumpContext) return false;
  if (trumpContext.trump_rank && card.rank === trumpContext.trump_rank) return true;
  if (trumpContext.trump_suit && card.suit === trumpContext.trump_suit) return true;
  return false;
}

// Return the trump rank string (e.g. "7") from the game state.
// Works before any bid is placed by reading the round leader's current rank.
function getTrumpRank(gs) {
  if (gs.trump_context && gs.trump_context.trump_rank) {
    return gs.trump_context.trump_rank;
  }
  // Before a bid: current_leader_id == round_leader_id (set in start_dealing).
  const leader = gs.players.find(p => p.id === gs.current_leader_id);
  return leader ? leader.rank : null;
}

// Sort for the bidding-phase main group: ♦ ♣ ♥ ♠ left-to-right, rank ascending.
function sortBiddingMain(items) {
  const SUITS = ["diamonds", "clubs", "hearts", "spades"];
  return [...items].sort((a, b) => {
    const sd = SUITS.indexOf(a.card.suit) - SUITS.indexOf(b.card.suit);
    if (sd !== 0) return sd;
    return RANK_ORDER.indexOf(a.card.rank) - RANK_ORDER.indexOf(b.card.rank);
  });
}

// Sort for the bidding-phase highlighted group:
// trump-rank cards by ♦ ♣ ♥ ♠ order, then small joker, then big joker.
function sortBiddingHighlight(items) {
  const SUITS = ["diamonds", "clubs", "hearts", "spades"];
  return [...items].sort((a, b) => {
    const aJ = isJoker(a.card), bJ = isJoker(b.card);
    if (aJ && bJ) return (a.card.rank === "BJ" ? 1 : 0) - (b.card.rank === "BJ" ? 1 : 0);
    if (aJ) return 1;
    if (bJ) return -1;
    return SUITS.indexOf(a.card.suit) - SUITS.indexOf(b.card.suit);
  });
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
  const isBidding  = phase === "dealing" || phase === "bidding_after_deal";
  const isExchange = phase === "bottom_exchange" && Array.isArray(gs.bottom_deck);

  const handCards = me.hand.map((card, i) => ({ card, key: `hand:${i}` }));

  // ── DEALING / BIDDING phase: split hand into main + highlighted sections ──
  if (isBidding) {
    const trumpRank = getTrumpRank(gs);

    // A joker is only biddable as "no trump" when the player holds a PAIR of
    // that joker type (SJ+SJ or BJ+BJ).  Single jokers cannot win a bid, so
    // they stay in the main group without the "bid these!" highlight.
    const sjCount = handCards.filter(({ card }) => card.rank === "SJ").length;
    const bjCount = handCards.filter(({ card }) => card.rank === "BJ").length;
    const jokerHighlighted = ({ card }) =>
      (card.rank === "SJ" && sjCount >= 2) || (card.rank === "BJ" && bjCount >= 2);

    // Main group: non-trump-rank cards + un-paired jokers.
    // Highlighted group: trump-rank cards (any suit) + paired jokers.
    const mainItems = handCards.filter(({ card }) => {
      if (isJoker(card)) return !jokerHighlighted({ card });
      return trumpRank === null || card.rank !== trumpRank;
    });
    const highlightItems = handCards.filter(({ card }) =>
      jokerHighlighted({ card }) || (trumpRank !== null && card.rank === trumpRank)
    );

    handHeader.textContent = `Your hand (${handCards.length} cards)`;

    // Render main group: ♦ ♣ ♥ ♠ sorted by rank
    for (const { card } of sortBiddingMain(mainItems)) {
      handArea.appendChild(makeCardEl(card, false));
    }

    // Render highlighted trump-rank group (only if non-empty)
    if (highlightItems.length > 0) {
      const rankLabel = trumpRank ? rankDisplay(trumpRank) : "?";
      const sep = document.createElement("div");
      sep.className = "hand-trump-sep";
      sep.textContent = `— rank ${rankLabel} cards (trump rank — bid these!) —`;
      handArea.appendChild(sep);

      for (const { card } of sortBiddingHighlight(highlightItems)) {
        const el = makeCardEl(card, false);
        el.classList.add("trump-highlight");
        handArea.appendChild(el);
      }
    }
    return;
  }

  // ── All other phases: single sorted group ──
  const canSelect = (
    phase === "playing" ||
    phase === "bottom_exchange" ||
    phase === "friend_declaration"
  );

  // During BOTTOM_EXCHANGE the leader sees hand + bottom deck (33 cards).
  const bottomCards = isExchange
    ? (gs.bottom_deck || []).map((card, i) => ({ card, key: `bot:${i}` }))
    : [];
  const allDisplay = [...handCards, ...bottomCards];

  const total = allDisplay.length;
  handHeader.textContent = isExchange
    ? `Your hand + bottom deck (${total} cards) — select 8 to put back`
    : `Your hand (${total} cards)`;

  const sorted = sortCardSet(allDisplay, gs.trump_context);

  for (const { card, key } of sorted) {
    const el = makeCardEl(card, canSelect);

    // Highlight trump cards (trump-rank, trump-suit, jokers) for accessibility.
    if (isTrumpCard(card, gs.trump_context)) {
      el.classList.add("trump-highlight");
    }

    // Mark bottom deck cards with a subtle indicator (⊕ badge in corner)
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

  if (card.rank === "SJ") return [6, 0];
  if (card.rank === "BJ") return [6, 1];

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
    btn.disabled = !canBid || S.hasPassed;
    if (canBid && !S.hasPassed) {
      const isPair = available.some(b => b.type === "pair" && b.suit === suit);
      btn.title = isPair ? `Bid ${sym} (pair — nails it down)` : `Bid ${sym}`;
      btn.addEventListener("click", () => sendWS({ action: "bid", suit }));
    }
    bidRow.appendChild(btn);
  }

  for (const joker of ["small", "big"]) {
    const btn = document.createElement("button");
    btn.textContent = joker === "small" ? "No Trump (小)" : "No Trump (大)";
    btn.disabled    = !available.some(b => b.type === "joker_pair" && b.joker === joker) || S.hasPassed;
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
    // Only the current highest bidder cannot pass (can't take back your own
    // winning bid).  An outbid player MUST be able to pass.
    const bids = gs.bids || [];
    const isCurrentBidder = bids.length > 0 && bids[bids.length - 1].player_id === S.playerId;
    passBtn.textContent = S.hasPassed ? "Passed ✓" : "Pass";
    passBtn.disabled = isCurrentBidder || S.hasPassed;
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
  const trumpSuit = ctx ? ctx.trump_suit : null;

  const info = document.createElement("div");
  info.style.cssText = "font-size:13px;color:#aaa;text-align:center;margin-bottom:4px;";
  info.textContent = "Declare your friend (Find Friends mode):";
  area.appendChild(info);

  // Ordinal dropdown — 1st (default) or 2nd
  const ordSel = document.createElement("select");
  ordSel.id = "fd-ordinal";
  for (const [val, label] of [[1, "1st"], [2, "2nd"]]) {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    ordSel.appendChild(opt);
  }

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

  // Suit dropdown — empty default, no joker, no trump suit
  const suitSel = document.createElement("select");
  suitSel.id = "fd-suit";
  const blankOpt = document.createElement("option");
  blankOpt.value = "";
  blankOpt.textContent = "— suit —";
  suitSel.appendChild(blankOpt);
  for (const [suit, sym] of Object.entries(SUIT_SYMBOL)) {
    if (suit === "joker") continue;
    if (suit === trumpSuit) continue;
    const opt = document.createElement("option");
    opt.value = suit;
    opt.textContent = `${sym} ${suit.charAt(0).toUpperCase() + suit.slice(1)}`;
    suitSel.appendChild(opt);
  }

  function lbl(text) {
    const l = document.createElement("label");
    l.style.margin = "0 4px";
    l.textContent = text;
    return l;
  }

  const row = document.createElement("div");
  row.className = "friend-decl-row";
  row.appendChild(ordSel);
  row.appendChild(rankSel);
  row.appendChild(lbl("of"));
  row.appendChild(suitSel);

  const confirmBtn = document.createElement("button");
  confirmBtn.textContent = "Confirm";
  confirmBtn.addEventListener("click", () => {
    const rank    = document.getElementById("fd-rank").value;
    const suit    = document.getElementById("fd-suit").value;
    const ordinal = parseInt(document.getElementById("fd-ordinal").value, 10);
    if (!suit) {
      setGameError("Please select a suit.");
      return;
    }
    sendWS({
      action: "declare_friends",
      declarations: [{ card: { suit, rank }, ordinal }],
    });
  });
  row.appendChild(confirmBtn);

  area.appendChild(row);
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
    S.pendingPlayCards = cards;
    playBtn.disabled = true;
    // A multi-card LEAD may be a throw (甩牌) — ask the server to classify
    // it first so we can show a confirm step before committing.
    const isLeading = !(gs.current_trick || []).length;
    if (isLeading && cards.length > 1) {
      sendWS({ action: "check_play", cards });
    } else {
      sendWS({ action: "validate_play", cards });
    }
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

  // Rank display toggle
  document.getElementById("btn-rank-display").addEventListener("click", () => {
    S.showRankDisplay = !S.showRankDisplay;
    const btn = document.getElementById("btn-rank-display");
    btn.classList.toggle("active", S.showRankDisplay);
    if (S.gameState) renderRankDisplay(S.gameState);
  });

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
      awaitingValidation: false, showRankDisplay: false,
    });
    S.selectedKeys.clear();
    document.getElementById("btn-rank-display").classList.remove("active");
    document.getElementById("rank-display").classList.add("hidden");
    showScreen("screen-landing");
  });

  showScreen("screen-landing");
});
