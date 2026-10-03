// Connect to the FastAPI WebSocket endpoint
const protocol = window.location.protocol === "https:" ? "wss" : "ws";
const ws = new WebSocket(`${protocol}://${window.location.host}/ws`);

const statusDiv = document.getElementById("connection-status");
const tableBody = document.getElementById("packet-table-body");

ws.onopen = () => {
    statusDiv.textContent = "🟢 Connected to Backend. Listening for BLE packets...";
    statusDiv.style.backgroundColor = "#e8f5e9";
};

ws.onclose = () => {
    statusDiv.textContent = "🔴 Disconnected from Backend.";
    statusDiv.style.backgroundColor = "#ffebee";
};

ws.onmessage = (event) => {
    // Parse the JSON received from the Python backend
    const data = JSON.parse(event.data);
    
    if (data.status === "ok") {
        addPacketToTable(data);
    }
};

function addPacketToTable(data) {
    const row = document.createElement("tr");
    
    const now = new Date();
    const timeString = `${now.getHours()}:${now.getMinutes()}:${now.getSeconds()}.${now.getMilliseconds()}`;

    row.innerHTML = `
        <td>${timeString}</td>
        <td><strong>${data.mac}</strong></td>
        <td><code>${data.payload_hex}</code></td>
        <td>${data.iq_length}</td>
    `;
    
    // Insert new row at the top
    tableBody.insertBefore(row, tableBody.firstChild);
    
    // Keep only the last 20 rows to avoid memory leaks in the browser
    if (tableBody.children.length > 20) {
        tableBody.removeChild(tableBody.lastChild);
    }
}
