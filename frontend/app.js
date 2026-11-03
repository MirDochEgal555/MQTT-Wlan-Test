// E-Ink Tischkarten Labor - Frontend Application
// Supports both Live FastAPI Backend mode and static GitHub Pages Client Simulator mode!

let isLiveBackend = false;
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

// Client-Side Simulation State (for GitHub Pages static hosting)
const clientSim = {
    version: 1,
    cardData: {
        badge: "HEUTE EMPFOHLEN",
        title: "Kürbissuppe",
        subtitle: "mit gerösteten Kürbiskernen & Steirischem Kernöl",
        price: "6,90 €",
        tableName: "TISCH 12"
    },
    currentImageDataUrl: "",
    gatewayOnline: true,
    wifiOnline: true,
    wifiStatus: "sleeping", // sleeping | waking | connecting_wifi | checking_manifest | downloading | refreshing
    wifiSleepInterval: 15.0,
    nextWakeTime: Date.now() + 15000,
    display001: {
        version: 1,
        imageUrl: "",
        batteryMv: 3150,
        rssi: -65
    },
    display002: {
        version: 1,
        imageUrl: "",
        batteryMv: 3280,
        rssi: -62
    }
};

async function init() {
    startCountdownTicker();
    await detectEnvironment();
}

async function detectEnvironment() {
    updateModeBadge(false, "Prüfe Backend...");
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 1200);
        // Use relative URL so it works regardless of domain or subpath
        const res = await fetch('api/status', { signal: controller.signal });
        clearTimeout(timeoutId);
        if (res.ok) {
            const data = await res.json();
            isLiveBackend = true;
            updateModeBadge(true, "Live Backend (FastAPI)");
            setupWebSocket();
            updateStatusUI(data);
            return;
        }
    } catch (e) {
        // Backend not reachable, fall back to Client-Side Simulator
    }

    // Static hosting / GitHub Pages mode
    isLiveBackend = false;
    updateModeBadge(false, "GitHub Pages (Client Simulator)");
    initClientSideSimulator();
}

function updateModeBadge(live, text) {
    const badge = document.getElementById('modeBadge');
    const dot = document.getElementById('modeDot');
    const modeText = document.getElementById('modeText');
    const mqttBadge = document.getElementById('mqttStatusBadge');
    const wsBadge = document.getElementById('wsStatusBadge');

    if (modeText) modeText.textContent = text;
    if (dot) {
        dot.className = live ? 'dot dot-green' : 'dot dot-cyan';
    }
    if (!live) {
        const mqttText = document.getElementById('mqttPortText');
        if (mqttText) mqttText.textContent = "Simuliert";
        const wsText = document.getElementById('wsText');
        if (wsText) wsText.textContent = "Client Engine";
    }
}

function startCountdownTicker() {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
        if (!isLiveBackend) {
            // In client mode, compute countdown to nextWakeTime
            const remaining = Math.max(0, (clientSim.nextWakeTime - Date.now()) / 1000);
            currentCountdown = remaining;
            const el = document.getElementById('d2Countdown');
            if (el) el.textContent = `${currentCountdown.toFixed(1)}s`;

            if (remaining <= 0 && clientSim.wifiStatus === 'sleeping') {
                runClientWifiCycle();
            }
        } else {
            if (currentCountdown > 0.1) {
                currentCountdown = Math.max(0, currentCountdown - 0.2);
                const el = document.getElementById('d2Countdown');
                if (el) el.textContent = `${currentCountdown.toFixed(1)}s`;
            }
        }
    }, 200);
}

// -----------------------------------------------------------------------------
// Live Backend Mode Handlers (WebSocket & REST)
// -----------------------------------------------------------------------------
function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        document.getElementById('wsDot').className = 'dot dot-green';
        document.getElementById('wsText').textContent = 'Live verbunden';
    };

    ws.onclose = () => {
        if (isLiveBackend) {
            document.getElementById('wsDot').className = 'dot dot-red';
            document.getElementById('wsText').textContent = 'Getrennt (Retry...)';
            setTimeout(setupWebSocket, 2000);
        }
    };

    ws.onerror = () => {
        if (isLiveBackend) {
            document.getElementById('wsDot').className = 'dot dot-red';
        }
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

// -----------------------------------------------------------------------------
// Client-Side Canvas Image Generator (In-Browser Rendering for GitHub Pages)
// -----------------------------------------------------------------------------
function renderEinkCardToDataUrl({
    title = "Kürbissuppe",
    subtitle = "mit gerösteten Kürbiskernen & Steirischem Kernöl",
    price = "6,90 €",
    badge = "HEUTE EMPFOHLEN",
    tableName = "TISCH 12",
    version = 1,
    dither = false
} = {}) {
    const canvas = document.getElementById('einkCanvas') || document.createElement('canvas');
    canvas.width = 800;
    canvas.height = 480;
    const ctx = canvas.getContext('2d');

    // Background (off-white paper)
    ctx.fillStyle = '#fcfcfa';
    ctx.fillRect(0, 0, 800, 480);

    const fgBlack = '#141416';
    const fgGray = '#646469';
    const margin = 16;

    // Outer & inner frame
    ctx.strokeStyle = fgBlack;
    ctx.lineWidth = 3;
    ctx.strokeRect(margin, margin, 800 - 2 * margin, 480 - 2 * margin);

    const innerMargin = margin + 6;
    ctx.strokeStyle = fgGray;
    ctx.lineWidth = 1;
    ctx.strokeRect(innerMargin, innerMargin, 800 - 2 * innerMargin, 480 - 2 * innerMargin);

    // Decorative corner brackets
    const cs = 14;
    ctx.strokeStyle = fgBlack;
    ctx.lineWidth = 2;
    // Top-left
    ctx.beginPath(); ctx.moveTo(margin + 2, margin + 2); ctx.lineTo(margin + 2 + cs, margin + 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(margin + 2, margin + 2); ctx.lineTo(margin + 2, margin + 2 + cs); ctx.stroke();
    // Top-right
    ctx.beginPath(); ctx.moveTo(800 - margin - 2, margin + 2); ctx.lineTo(800 - margin - 2 - cs, margin + 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(800 - margin - 2, margin + 2); ctx.lineTo(800 - margin - 2, margin + 2 + cs); ctx.stroke();
    // Bottom-left
    ctx.beginPath(); ctx.moveTo(margin + 2, 480 - margin - 2); ctx.lineTo(margin + 2 + cs, 480 - margin - 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(margin + 2, 480 - margin - 2); ctx.lineTo(margin + 2, 480 - margin - 2 - cs); ctx.stroke();
    // Bottom-right
    ctx.beginPath(); ctx.moveTo(800 - margin - 2, 480 - margin - 2); ctx.lineTo(800 - margin - 2 - cs, 480 - margin - 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(800 - margin - 2, 480 - margin - 2); ctx.lineTo(800 - margin - 2, 480 - margin - 2 - cs); ctx.stroke();

    // Top Header Badge
    const pillW = 260;
    const pillH = 34;
    const pillX = (800 - pillW) / 2;
    const pillY = margin + 18;

    ctx.fillStyle = fgBlack;
    roundRect(ctx, pillX, pillY, pillW, pillH, 6);
    ctx.fill();

    ctx.fillStyle = '#fcfcfa';
    ctx.font = 'bold 15px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(badge.toUpperCase(), 400, pillY + pillH / 2);

    // Table identifier & time
    ctx.fillStyle = fgBlack;
    ctx.font = 'bold 14px "Plus Jakarta Sans", sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(tableName, innerMargin + 16, margin + 35);

    const now = new Date();
    const timeStr = `Stand ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')} Uhr`;
    ctx.fillStyle = fgGray;
    ctx.font = '14px "Plus Jakarta Sans", sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(timeStr, 800 - innerMargin - 16, margin + 35);

    // Divider line
    const divY = pillY + pillH + 16;
    ctx.strokeStyle = fgGray;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(innerMargin + 20, divY);
    ctx.lineTo(800 - innerMargin - 20, divY);
    ctx.stroke();

    // Dish Title (Serif)
    ctx.fillStyle = fgBlack;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold 42px "Playfair Display", Georgia, serif';
    const titleY = divY + 60;
    ctx.fillText(title, 400, titleY);

    // Subtitle / Description
    ctx.fillStyle = fgGray;
    ctx.font = 'italic 19px "Playfair Display", Georgia, serif';
    const subY = titleY + 36;
    // Word wrap subtitle if needed
    if (ctx.measureText(subtitle).width > 680 && subtitle.includes(' ')) {
        const words = subtitle.split(' ');
        const mid = Math.ceil(words.length / 2);
        const line1 = words.slice(0, mid).join(' ');
        const line2 = words.slice(mid).join(' ');
        ctx.fillText(line1, 400, subY);
        ctx.fillText(line2, 400, subY + 26);
    } else {
        ctx.fillText(subtitle, 400, subY);
    }

    // Price
    ctx.fillStyle = fgBlack;
    ctx.font = 'bold 50px "Plus Jakarta Sans", sans-serif';
    ctx.fillText(price, 400, subY + 84);

    // Footer metadata & E-Ink status bar
    const footerDivY = 480 - margin - 46;
    ctx.strokeStyle = fgGray;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(innerMargin + 20, footerDivY);
    ctx.lineTo(800 - innerMargin - 20, footerDivY);
    ctx.stroke();

    ctx.fillStyle = fgGray;
    ctx.font = '12px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`E-Ink Tischkarte · Version ${version} · Akku: 98% · YUPSALE Kommunikationslabor`, innerMargin + 16, footerDivY + 26);

    ctx.textAlign = 'right';
    ctx.fillText('EPD 800x480 · 1-BIT', 800 - innerMargin - 16, footerDivY + 26);

    // Optional Floyd-Steinberg Dithering
    if (dither) {
        applyFloydSteinberg(ctx, 800, 480);
    }

    return canvas.toDataURL('image/png');
}

function roundRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
}

function applyFloydSteinberg(ctx, width, height) {
    const imgData = ctx.getImageData(0, 0, width, height);
    const d = imgData.data;

    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const idx = (y * width + x) * 4;
            const oldL = 0.299 * d[idx] + 0.587 * d[idx + 1] + 0.114 * d[idx + 2];
            const newL = oldL < 128 ? 0 : 255;
            const err = oldL - newL;

            d[idx] = newL;
            d[idx + 1] = newL;
            d[idx + 2] = newL;

            // Distribute error
            if (x + 1 < width) {
                distributeErr(d, (y * width + (x + 1)) * 4, err * 7 / 16);
            }
            if (x - 1 >= 0 && y + 1 < height) {
                distributeErr(d, ((y + 1) * width + (x - 1)) * 4, err * 3 / 16);
            }
            if (y + 1 < height) {
                distributeErr(d, ((y + 1) * width + x) * 4, err * 5 / 16);
            }
            if (x + 1 < width && y + 1 < height) {
                distributeErr(d, ((y + 1) * width + (x + 1)) * 4, err * 1 / 16);
            }
        }
    }
    ctx.putImageData(imgData, 0, 0);
}

function distributeErr(d, idx, val) {
    d[idx] = Math.min(255, Math.max(0, d[idx] + val));
    d[idx + 1] = Math.min(255, Math.max(0, d[idx + 1] + val));
    d[idx + 2] = Math.min(255, Math.max(0, d[idx + 2] + val));
}

// -----------------------------------------------------------------------------
// Client-Side Simulation Engine (for GitHub Pages)
// -----------------------------------------------------------------------------
function initClientSideSimulator() {
    // Generate initial image
    const initialDataUrl = renderEinkCardToDataUrl({
        title: clientSim.cardData.title,
        subtitle: clientSim.cardData.subtitle,
        price: clientSim.cardData.price,
        badge: clientSim.cardData.badge,
        version: clientSim.version,
        dither: false
    });

    clientSim.currentImageDataUrl = initialDataUrl;
    clientSim.display001.imageUrl = initialDataUrl;
    clientSim.display002.imageUrl = initialDataUrl;

    // Set preview images
    const d1Img = document.getElementById('d1Image');
    const d2Img = document.getElementById('d2Image');
    if (d1Img) d1Img.src = initialDataUrl;
    if (d2Img) d2Img.src = initialDataUrl;

    // Reset log and add initial entries
    allLogs = [];
    clientLog("Backend", `System gestartet · Initiale Bildversion ${clientSim.version} generiert`);
    clientLog("Simulator", "Gateway 001 und WLAN-Display 002 erfolgreich initialisiert (GitHub Pages Modus)");

    renderClientStatusUI();
    clientSim.nextWakeTime = Date.now() + (clientSim.wifiSleepInterval * 1000);
}

function clientLog(source, message, level = 'info') {
    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
    const entry = {
        id: `${Date.now()}_${allLogs.length}`,
        time: timeStr,
        source: source,
        level: level,
        message: message
    };
    allLogs.push(entry);
    if (allLogs.length > 500) allLogs.shift();
    appendLogEntry(entry);
    highlightFlowFromLog(entry);
}

function renderClientStatusUI() {
    // Display 001
    const d1Ver = document.getElementById('d1Version');
    if (d1Ver) d1Ver.textContent = `v${clientSim.display001.version}`;

    const d1StatusText = document.getElementById('d1StatusText');
    const card001 = document.getElementById('cardDisplay001');
    const btnGw = document.getElementById('btnGatewayText');

    if (clientSim.gatewayOnline) {
        d1StatusText.textContent = "Gateway verbunden";
        card001.classList.remove('offline-overlay-active');
        btnGw.textContent = "Gateway: Online";
    } else {
        d1StatusText.textContent = "Gateway OFFLINE";
        card001.classList.add('offline-overlay-active');
        btnGw.textContent = "Gateway: Offline";
    }

    // Display 002
    const d2Ver = document.getElementById('d2Version');
    if (d2Ver) d2Ver.textContent = `v${clientSim.display002.version}`;

    const d2StatusText = document.getElementById('d2StatusText');
    const card002 = document.getElementById('cardDisplay002');
    const btnWf = document.getElementById('btnWifiText');

    if (clientSim.wifiOnline) {
        card002.classList.remove('offline-overlay-active');
        btnWf.textContent = "WLAN: Online";
    } else {
        card002.classList.add('offline-overlay-active');
        btnWf.textContent = "WLAN: Ausfall";
    }

    if (!clientSim.wifiOnline) {
        d2StatusText.textContent = "WLAN nicht erreichbar";
    } else if (clientSim.wifiStatus === 'sleeping') {
        d2StatusText.textContent = "Schläft (Deep Sleep)";
    } else if (clientSim.wifiStatus === 'waking' || clientSim.wifiStatus === 'connecting_wifi') {
        d2StatusText.textContent = "Wacht auf · Verbindet WLAN...";
    } else if (clientSim.wifiStatus === 'checking_manifest') {
        d2StatusText.textContent = "Fragt Manifest ab...";
    } else if (clientSim.wifiStatus === 'downloading') {
        d2StatusText.textContent = "Lädt neues PNG-Bild herunter...";
    } else if (clientSim.wifiStatus === 'refreshing') {
        d2StatusText.textContent = "E-Ink Bildrefresh läuft...";
    }
}

async function runClientWifiCycle() {
    clientSim.wifiStatus = "waking";
    renderClientStatusUI();
    clientLog("WLAN-Display 002", "WLAN-Display display_002: Aufwachen aus Deep Sleep");

    // Wi-Fi connection simulation
    clientSim.wifiStatus = "connecting_wifi";
    renderClientStatusUI();
    await delay(1000);

    if (!clientSim.wifiOnline) {
        clientSim.wifiStatus = "sleeping";
        clientSim.nextWakeTime = Date.now() + (clientSim.wifiSleepInterval * 1000);
        renderClientStatusUI();
        clientLog("WLAN-Display 002", "WLAN-Fehler: Display display_002 konnte keine WLAN-Verbindung herstellen (SSID nicht erreichbar)", "error");
        clientLog("WLAN-Display 002", `WLAN-Display display_002: Gehe in Deep Sleep für ${clientSim.wifiSleepInterval}s`);
        return;
    }

    const rssi = -60 - Math.floor(Math.random() * 8);
    clientLog("WLAN-Display 002", `WLAN-Display display_002: Verbunden mit WLAN (RSSI ${rssi} dBm)`);

    // Fetch manifest
    clientSim.wifiStatus = "checking_manifest";
    renderClientStatusUI();
    clientLog("WLAN-Display 002", "WLAN-Display display_002: GET /api/displays/display_002/manifest");
    await delay(500);

    if (clientSim.version > clientSim.display002.version) {
        clientLog("WLAN-Display 002", `WLAN-Display display_002: Manifest empfangen -> Version ${clientSim.version} (Lokal: ${clientSim.display002.version})`);

        clientSim.wifiStatus = "downloading";
        renderClientStatusUI();
        clientLog("WLAN-Display 002", `WLAN-Display display_002: GET /images/menu-v${clientSim.version}.png`);
        await delay(600);

        clientLog("WLAN-Display 002", `WLAN-Display display_002: Bild empfangen (24150 Bytes)`);

        clientSim.wifiStatus = "refreshing";
        renderClientStatusUI();
        clientLog("WLAN-Display 002", "WLAN-Display display_002: Dekodiere Bild und starte E-Ink Refresh-Wellenform...");
        triggerEinkRefresh('d2ScreenWrapper');
        await delay(1200);

        clientSim.display002.version = clientSim.version;
        clientSim.display002.imageUrl = clientSim.currentImageDataUrl;
        const d2Img = document.getElementById('d2Image');
        if (d2Img) d2Img.src = clientSim.currentImageDataUrl;

        clientLog("WLAN-Display 002", `Simulation: Display display_002 aktualisiert (Version ${clientSim.version})`);
    } else {
        clientLog("WLAN-Display 002", `WLAN-Display display_002: Version unverändert (v${clientSim.display002.version}). Kein Bilddownload nötig (Energie gespart!).`);
    }

    // Go to sleep
    clientSim.wifiStatus = "sleeping";
    clientSim.nextWakeTime = Date.now() + (clientSim.wifiSleepInterval * 1000);
    renderClientStatusUI();
    clientLog("WLAN-Display 002", `WLAN-Display display_002: Gehe in Deep Sleep für ${clientSim.wifiSleepInterval}s`);
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// -----------------------------------------------------------------------------
// UI Updates (Backend Mode)
// -----------------------------------------------------------------------------
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

// -----------------------------------------------------------------------------
// Log Handling
// -----------------------------------------------------------------------------
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
    if (isLiveBackend) {
        await fetch('api/logs', { method: 'DELETE' });
    }
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

// -----------------------------------------------------------------------------
// Flow Highlighting
// -----------------------------------------------------------------------------
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
    if ((src === 'Gateway' || src === 'Simulator') && msg.includes('display_001')) {
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

// -----------------------------------------------------------------------------
// User Actions (Dual Mode)
// -----------------------------------------------------------------------------
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

    if (!isLiveBackend) {
        // Client-Side Simulation update
        clientSim.version += 1;
        clientSim.cardData = { badge, title, subtitle, price, tableName: "TISCH 12" };

        const dataUrl = renderEinkCardToDataUrl({
            title,
            subtitle,
            price,
            badge,
            version: clientSim.version,
            dither
        });
        clientSim.currentImageDataUrl = dataUrl;

        clientLog("Backend", `Bildversion ${clientSim.version} erstellt (${title} · ${price})`);

        if (triggerMqtt) {
            triggerClientMqttUpdate();
        }

        if (triggerWifiWake) {
            triggerClientWifiWake();
        }

        renderClientStatusUI();
        return;
    }

    // Backend Mode
    try {
        const res = await fetch('api/card/update', {
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
    } catch (e) {
        console.error("sendCardUpdate failed:", e);
    }
}

async function triggerMqttUpdate() {
    if (!isLiveBackend) {
        triggerClientMqttUpdate();
        return;
    }
    try {
        await fetch('api/mqtt/trigger-command', { method: 'POST' });
    } catch (e) {
        console.error("triggerMqttUpdate failed:", e);
    }
}

function triggerClientMqttUpdate() {
    clientLog("MQTT", `Auftrag an gateway/001/command veröffentlicht (v${clientSim.version})`);

    if (!clientSim.gatewayOnline) {
        clientLog("Gateway", "DROPPED: Command received but Gateway is OFFLINE", "error");
        return;
    }

    clientLog("Gateway", `Auftrag empfangen für display_001 (Version ${clientSim.version})`);
    clientLog("Gateway", "Funksignal (Sub-1GHz) an display_001 gestartet...");

    setTimeout(() => {
        if (!clientSim.gatewayOnline) {
            clientLog("Gateway", "Transmission interrupted: Gateway went OFFLINE", "error");
            return;
        }
        clientSim.display001.version = clientSim.version;
        clientSim.display001.imageUrl = clientSim.currentImageDataUrl;

        const d1Img = document.getElementById('d1Image');
        if (d1Img) d1Img.src = clientSim.currentImageDataUrl;
        triggerEinkRefresh('d1ScreenWrapper');

        clientLog("Gateway", `Simulation: Display display_001 erfolgreich per Funk aktualisiert (v${clientSim.version})`);
        clientLog("Gateway-Status", `Status-Update von 001: update_success`);
        renderClientStatusUI();
    }, 1200);
}

async function triggerWifiWake() {
    if (!isLiveBackend) {
        triggerClientWifiWake();
        return;
    }
    try {
        await fetch('api/wifi/wake-up', { method: 'POST' });
        currentCountdown = 0.5;
    } catch (e) {
        console.error("triggerWifiWake failed:", e);
    }
}

function triggerClientWifiWake() {
    clientLog("WLAN-Display 002", "Manuelles Aufwecken für WLAN-Display display_002 ausgelöst!");
    clientSim.nextWakeTime = Date.now();
    currentCountdown = 0.1;
    runClientWifiCycle();
}

async function toggleGatewayOnline() {
    if (!isLiveBackend) {
        clientSim.gatewayOnline = !clientSim.gatewayOnline;
        const statusTxt = clientSim.gatewayOnline ? "ONLINE" : "OFFLINE";
        clientLog("Simulation", `Gateway 001 Status geändert auf: ${statusTxt}`);
        renderClientStatusUI();
        return;
    }
    if (!systemState) return;
    const nextState = !systemState.gateway.online;
    await fetch('api/sim/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gateway_online: nextState })
    });
}

async function toggleWifiOnline() {
    if (!isLiveBackend) {
        clientSim.wifiOnline = !clientSim.wifiOnline;
        const statusTxt = clientSim.wifiOnline ? "online" : "offline (WLAN-Ausfall)";
        clientLog("Simulation", `WLAN-Status geändert: ${statusTxt}`);
        renderClientStatusUI();
        return;
    }
    if (!systemState) return;
    const nextState = !systemState.display_002.online;
    await fetch('api/sim/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wifi_online: nextState })
    });
}

// Start on load
window.addEventListener('DOMContentLoaded', init);
