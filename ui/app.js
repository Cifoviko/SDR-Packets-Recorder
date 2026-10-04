// State management
const devicesState = {}; 
let currentViewMac = null;

// WebSocket setup
const protocol = window.location.protocol === "https:" ? "wss" : "ws";
const ws = new WebSocket(`${protocol}://${window.location.host}/ws`);
const statusDiv = document.getElementById("connection-status");

ws.onopen = () => { statusDiv.textContent = "🟢 Live"; };
ws.onclose = () => { statusDiv.textContent = "🔴 Offline"; };

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.status === "ok") {
        handleNewPacket(data);
    }
};

function handleNewPacket(pkt) {
    const mac = pkt.mac;
    
    // Initialize state for new MAC
    if (!devicesState[mac]) {
        devicesState[mac] = {
            mac: mac,
            count: 0,
            lastSeen: pkt.timestamp,
            messages: []
        };
    }
    
    // Update state
    devicesState[mac].count += 1;
    devicesState[mac].lastSeen = pkt.timestamp;
    
    // Keep only last 50 messages per device to save memory
    devicesState[mac].messages.unshift(pkt);
    if (devicesState[mac].messages.length > 50) {
        devicesState[mac].messages.pop();
    }
    
    // Re-render UI based on current view
    renderDashboard();
    
    if (currentViewMac === mac) {
        renderDeviceDetails(mac);
    }
}

// --- RENDERING LOGIC ---

function renderDashboard() {
    const grid = document.getElementById("devices-grid");
    grid.innerHTML = "";
    
    // Sort devices by most recently seen
    const sortedMacs = Object.keys(devicesState).sort((a, b) => 
        devicesState[b].lastSeen - devicesState[a].lastSeen
    );
    
    sortedMacs.forEach(mac => {
        const device = devicesState[mac];
        const timeAgo = Math.round((Date.now()/1000) - device.lastSeen);
        
        const card = document.createElement("div");
        card.className = "card";
        card.onclick = () => showDeviceDetails(mac);
        card.innerHTML = `
            <h3>${mac}</h3>
            <p><span class="badge">${device.count}</span> Messages</p>
            <p>Last seen: ${timeAgo}s ago</p>
        `;
        grid.appendChild(card);
    });
}

function renderDeviceDetails(mac) {
    const container = document.getElementById("messages-list");
    container.innerHTML = "";
    
    devicesState[mac].messages.forEach((msg, index) => {
        const date = new Date(msg.timestamp * 1000).toLocaleTimeString();
        const msgId = `${mac.replace(/:/g, '')}-${index}`;
        
        const msgHtml = `
            <div class="msg-box">
                <div class="msg-header">
                    <strong>Time: ${date}</strong>
                    <span>Channel: <b>${msg.channel}</b> (${msg.frequency} MHz)</span>
                </div>
                <div class="msg-body">
                    <div class="msg-data">
                        <h4>Packet Data</h4>
                        <p><strong>Payload (Hex):</strong> <br><code>${msg.payload_hex}</code></p>
                        <!-- Future: Render specific Scapy parsed fields here -->
                    </div>
                    <div class="msg-signal">
                        <h4>Signal (I/Q)</h4>
                        <canvas id="canvas-${msgId}"></canvas>
                        <button class="btn-download" onclick='downloadIQ(${JSON.stringify(msg.iq_data)}, "${mac}", ${msg.timestamp})'>
                            📥 Download I/Q Sample (.json)
                        </button>
                    </div>
                </div>
            </div>
        `;
        container.insertAdjacentHTML("beforeend", msgHtml);
        
        // Draw the waveform immediately after inserting into DOM
        drawWaveform(`canvas-${msgId}`, msg.iq_data);
    });
}

// --- NAVIGATION ---

function showDeviceDetails(mac) {
    currentViewMac = mac;
    document.getElementById("view-dashboard").classList.add("hidden");
    document.getElementById("view-details").classList.remove("hidden");
    document.getElementById("detail-mac-title").textContent = `Device: ${mac}`;
    renderDeviceDetails(mac);
}

function showDashboard() {
    currentViewMac = null;
    document.getElementById("view-details").classList.add("hidden");
    document.getElementById("view-dashboard").classList.remove("hidden");
    renderDashboard();
}

// --- SIGNAL VISUALIZATION (CANVAS) ---

function drawWaveform(canvasId, iqData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    
    const width = canvas.width;
    const height = canvas.height;
    const midY = height / 2;
    
    // Clear background
    ctx.clearRect(0, 0, width, height);
    
    // Helper to draw a line
    function drawLine(dataArray, color) {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        
        const step = Math.max(1, Math.floor(dataArray.length / width));
        for (let i = 0; i < width; i++) {
            const dataIdx = i * step;
            if (dataIdx >= dataArray.length) break;
            
            // Normalize value (assuming values are roughly -1 to 1)
            const val = dataArray[dataIdx];
            const y = midY - (val * (height/2.5)); 
            
            if (i === 0) ctx.moveTo(i, y);
            else ctx.lineTo(i, y);
        }
        ctx.stroke();
    }
    
    // Draw I (Real) in Cyan, Q (Imaginary) in Magenta
    drawLine(iqData.I, "#00ffff");
    drawLine(iqData.Q, "#ff00ff");
}

// --- DOWNLOAD FILE ---

function downloadIQ(iqData, mac, timestamp) {
    // Create a Blob from the JSON data
    const blob = new Blob([JSON.stringify(iqData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement("a");
    a.href = url;
    a.download = `iq_sample_${mac.replace(/:/g, '')}_${timestamp}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
