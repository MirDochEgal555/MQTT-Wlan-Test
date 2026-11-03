// E-Ink Tischkarten Labor - Frontend Application

let currentFilter = 'all';
let allLogs = [];
let ws = null;
let currentCountdown = 15.0;
let countdownTimer = null;
let systemState = null;

// Presets data
const PRESETS = {
    soup: {
        badge: "HEUTE EMPFOHLEN",
        title: "Kürbissuppe",
        subtitle: "mit gerösteten Kürbiskernen & Steirischem Kernöl",
        price: "6,90 €"
    },
    schnitzel: {
        badge: "KLASSIKER DES HAUSES",
        title: "Wiener Schnitzel vom Kalb",
        subtitle: "mit lauwarmem Erdäpfel-Vogerlsalat & Preiselbeeren",
        price: "18,50 €"
    },
    lemonade: {
        badge: "HAUSGEMACHT",
        title: "Minz-Ingwer Limonade 0,5l",
        subtitle: "frische Minze, Bio-Ingwer, Limettensaft, Soda",
        price: "4,20 €"
    },
    reserved: {
        badge: "TISCHRESERVIERUNG",
        title: "RESERVIERT",
        subtitle: "Herzlich willkommen ab 19:30 Uhr · Fam. Berger",
        price: "TISCH 12"
    }
};

function init() {
    setupWebSocket();
    fetchStatus();
    startCountdownTicker();
}

function startCountdownTicker() {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
        if (currentCountdown > 0.1) {
            currentCountdown = Math.max(0, currentCountdown - 0.2);
            const el = document.getElementById('d2Countdown');
            if (el) el.textContent = `${currentCountdown.toFixed(1)}s`;
        }
    }, 200);
}

function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        document.getElementById('wsDot').className = 'dot dot-green';
        document.getElementById('wsText').textContent = 'Live verbunden';
    };

    ws.onclose = () => {
        document.getElementById('wsDot').className = 'dot dot-red';
        document.getElementById('wsText').textContent = 'Verbindung getrennt (Retry...)';
        setTimeout(setupWebSocket, 2000);
    };

    ws.onerror = () => {
        document.getElementById('wsDot').className = 'dot dot-red';
    };

    ws.onmessage = (event) => {
        try {
            const data = jsonParseSafe(event.data);
            if (!data) return;

            if (data.type === 'init') {
                allLogs = data.logs || [];
                renderLogs();
                if (data.status) updateStatusUI(data.status);
            } else if (data.type === 'log') {
                allLogs.push(data.data);
                if (allLogs.length > 500) allLogs.shift();
                appendLogEntry(data.data);
                highlightFlowFromLog(data.data);
            } else if (data.type === 'status') {
                updateStatusUI(data.data);
            }
        } catch (e) {
            console.error("WS error:", e);
        }
    };
}

function jsonParseSafe(str) {
    try {
        return JSON.parse(str);
    } catch {
        return null;
    }
}

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        updateStatusUI(data);
    } catch (e) {
        console.error("fetchStatus failed:", e);
    }
}

function updateStatusUI(data) {
    systemState = data;

    // Display 001 (MQTT)
    const d1 = data.display_001;
    const gw = data.gateway;
    const d1VersionEl = document.getElementById('d1Version');
    if (d1VersionEl) d1VersionEl.textContent = `v${d1.version}`;

    const d1StatusText = document.getElementById('d1StatusText');
    const card001 = document.getElementById('cardDisplay001');
    const btnGw = document.getElementById('btnGatewayText');

    if (gw.online) {
        d1StatusText.textContent = "Gateway verbunden";
        card001.classList.remove('offline-overlay-active');
        btnGw.textContent = "Gateway: Online";
    } else {
        d1StatusText.textContent = "Gateway OFFLINE";
        card001.classList.add('offline-overlay-active');
        btnGw.textContent = "Gateway: Offline";
    }

    const d1Img = document.getElementById('d1Image');
    const newD1Src = `${d1.image_url}?t=${Date.now()}`;
    if (d1Img && d1Img.dataset.lastVersion !== String(d1.version)) {
        d1Img.dataset.lastVersion = String(d1.version);
        triggerEinkRefresh('d1ScreenWrapper');
        d1Img.src = newD1Src;
    }

    // Display 002 (WLAN)
    const d2 = data.display_002;
    const d2VersionEl = document.getElementById('d2Version');
    if (d2VersionEl) d2VersionEl.textContent = `v${d2.version}`;

    const d2StatusText = document.getElementById('d2StatusText');
    const card002 = document.getElementById('cardDisplay002');
    const btnWf = document.getElementById('btnWifiText');

    if (d2.online) {
        card002.classList.remove('offline-overlay-active');
        btnWf.textContent = "WLAN: Online";
    } else {
        card002.classList.add('offline-overlay-active');
        btnWf.textContent = "WLAN: Ausfall";
    }

    // Status message for Display 002
    if (!d2.online) {
        d2StatusText.textContent = "WLAN nicht erreichbar";
    } else if (d2.status === 'sleeping') {
        d2StatusText.textContent = `Schläft (Deep Sleep)`;
    } else if (d2.status === 'waking' || d2.status === 'connecting_wifi') {
        d2StatusText.textContent = "Wacht auf · Verbindet WLAN...";
    } else if (d2.status === 'checking_manifest') {
        d2StatusText.textContent = "Fragt Manifest ab...";
    } else if (d2.status === 'downloading') {
        d2StatusText.textContent = "Lädt neues PNG-Bild herunter...";
    } else if (d2.status === 'refreshing') {
        d2StatusText.textContent = "E-Ink Bildrefresh läuft...";
    }

    if (d2.next_wake_in !== undefined) {
        currentCountdown = d2.next_wake_in;
    }

    const d2Img = document.getElementById('d2Image');
    if (d2Img && d2.image_url && d2Img.dataset.lastVersion !== String(d2.version)) {
        d2Img.dataset.lastVersion = String(d2.version);
        triggerEinkRefresh('d2ScreenWrapper');
        d2Img.src = `${d2.image_url}?t=${Date.now()}`;
    }
}

function triggerEinkRefresh(wrapperId) {
    const el = document.getElementById(wrapperId);
    if (!el) return;
    el.classList.remove('eink-refreshing');
    void el.offsetWidth; // Trigger reflow
    el.classList.add('eink-refreshing');
    setTimeout(() => {
        el.classList.remove('eink-refreshing');
    }, 1600);
}

// Log Handling
function appendLogEntry(entry) {
    if (currentFilter !== 'all' && entry.source !== currentFilter) {
        return;
    }
    const consoleEl = document.getElementById('logConsole');
    if (!consoleEl) return;

    const line = createLogElement(entry);
    consoleEl.appendChild(line);
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

function createLogElement(entry) {
    const div = document.createElement('div');
    div.className = `log-line ${entry.level === 'error' ? 'log-level-error' : ''}`;

    const cleanSourceClass = `source-${entry.source.replace(/\s+/g, '\\ ')}`;

    div.innerHTML = `
        <span class="log-time font-mono">${entry.time}</span>
        <span class="log-source font-mono ${cleanSourceClass}">${escapeHtml(entry.source)}:</span>
        <span class="log-msg">${escapeHtml(entry.message)}</span>
    `;
    return div;
}

function renderLogs() {
    const consoleEl = document.getElementById('logConsole');
    if (!consoleEl) return;
    consoleEl.innerHTML = '';

    const filtered = currentFilter === 'all' 
        ? allLogs 
        : allLogs.filter(l => l.source === currentFilter);

    filtered.forEach(entry => {
        consoleEl.appendChild(createLogElement(entry));
    });
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

function setLogFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === filter);
    });
    renderLogs();
}

async function clearLogs() {
    await fetch('/api/logs', { method: 'DELETE' });
    allLogs = [];
    renderLogs();
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// Flow Highlighting
function highlightFlowFromLog(entry) {
    const msg = entry.message || '';
    const src = entry.source || '';

    // Flow A: MQTT
    if (src === 'Backend' && msg.includes('Bildversion')) {
        flashStep('stepUI', 'stepBackend');
    }
    if (src === 'MQTT' && msg.includes('gateway/001/command')) {
        flashStep('stepBackend', 'stepBroker');
    }
    if (src === 'Gateway' && msg.includes('Auftrag empfangen')) {
        flashStep('stepBroker', 'stepGateway');
    }
    if (src === 'Gateway' && msg.includes('Simulation: Display display_001')) {
        flashStep('stepGateway', 'stepDisplay1');
    }

    // Flow B: WLAN
    if (src === 'WLAN-Display 002' && msg.includes('Aufwachen')) {
        flashStep('stepD2Wake', 'stepD2Wifi');
    }
    if (src === 'WLAN-Display 002' && msg.includes('GET') && msg.includes('manifest')) {
        flashStep('stepD2Wifi', 'stepD2Manifest');
    }
    if (src === 'WLAN-Display 002' && msg.includes('GET') && msg.includes('images')) {
        flashStep('stepD2Manifest', 'stepD2Image');
    }
    if (src === 'WLAN-Display 002' && msg.includes('Deep Sleep')) {
        flashStep('stepD2Image', 'stepD2Sleep');
    }
}

function flashStep(...stepIds) {
    stepIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.classList.add('active-step');
            setTimeout(() => el.classList.remove('active-step'), 1200);
        }
    });
}

// User Actions
function applyPreset(name) {
    const preset = PRESETS[name];
    if (!preset) return;
    document.getElementById('inputBadge').value = preset.badge;
    document.getElementById('inputTitle').value = preset.title;
    document.getElementById('inputSubtitle').value = preset.subtitle;
    document.getElementById('inputPrice').value = preset.price;
}

async function handleFormSubmit(event) {
    event.preventDefault();
    await sendCardUpdate(true, true);
}

async function saveOnlyImage() {
    await sendCardUpdate(false, false);
}

async function sendCardUpdate(triggerMqtt, triggerWifiWake) {
    const badge = document.getElementById('inputBadge').value;
    const title = document.getElementById('inputTitle').value;
    const subtitle = document.getElementById('inputSubtitle').value;
    const price = document.getElementById('inputPrice').value;
    const dither = document.getElementById('checkDither').checked;

    try {
        const res = await fetch('/api/card/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                badge,
                title,
                subtitle,
                price,
                trigger_mqtt: triggerMqtt,
                trigger_wifi_wake: triggerWifiWake,
                dither_eink: dither
            })
        });
        const data = await res.json();
        fetchStatus();
    } catch (e) {
        console.error("sendCardUpdate failed:", e);
    }
}

async function triggerMqttUpdate() {
    try {
        await fetch('/api/mqtt/trigger-command', { method: 'POST' });
    } catch (e) {
        console.error("triggerMqttUpdate failed:", e);
    }
}

async function triggerWifiWake() {
    try {
        await fetch('/api/wifi/wake-up', { method: 'POST' });
        currentCountdown = 0.5;
    } catch (e) {
        console.error("triggerWifiWake failed:", e);
    }
}

async function toggleGatewayOnline() {
    if (!systemState) return;
    const nextState = !systemState.gateway.online;
    await fetch('/api/sim/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gateway_online: nextState })
    });
    fetchStatus();
}

async function toggleWifiOnline() {
    if (!systemState) return;
    const nextState = !systemState.display_002.online;
    await fetch('/api/sim/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wifi_online: nextState })
    });
    fetchStatus();
}

// Start on load
window.addEventListener('DOMContentLoaded', init);
