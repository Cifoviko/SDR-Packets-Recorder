"""
BLE Passive Identifier — приложение.

Архитектура:
  USRP B210 (4 MSPS, RX2) -> детект всплесков по энергии -> корреляция
  Access Address -> GFSK демодуляция -> dewhitening -> CRC24 ->
  сохранение сырых IQ в dataset/*.npy + метаданных -> FastAPI Web UI.

Запуск:
  venv_ble/bin/python app.py
"""

import os
import queue
import threading
import time

import numpy as np
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

import ble

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
os.makedirs(DATASET_DIR, exist_ok=True)

# Рекламные каналы BLE: (номер канала, частота)
CHANNELS = [(37, 2.402e9), (38, 2.426e9), (39, 2.480e9)]
HOP_INTERVAL = 2.0        # секунд на канал (ретюн кратковременно роняет поток — hop'аем редко)
GAIN = 50
SAMP_RATE = 2e6           # 2 MSPS = 16 МБ/с (устойчиво даже на слабом USB)
SPS = 2                   # сэмплов на символ
CHUNK = 16384             # сэмплов на итерацию обработки
GUARD = 3000              # хвост буфера, не обрабатываемый (защита от обрезанных всплесков)

messages_db = []
stats = {
    "running": False,
    "channel": 37,
    "bursts": 0,          # всего всплесков энергии
    "aa_found": 0,        # всплесков с найденным Access Address
    "decoded": 0,         # пакетов с валидным CRC
    "dropped": 0,         # пропущенных буферов (переполнение)
    "errors": [],
}
lock = threading.Lock()


def save_packet(iq, parsed, channel, freq):
    """Кладёт пакет в очередь на запись (пишет writer-поток)."""
    ts = time.time()
    mac = parsed.get("mac", "unknown")
    fname_mac = "".join(c if c.isalnum() else "_" for c in mac)
    fname = f"{int(ts * 1000)}_{fname_mac}_{parsed['pdu_type']}.npy"
    msg = {
        "timestamp": ts,
        "channel": channel,
        "frequency": freq,
        "pdu_type": parsed["pdu_type"],
        "mac": parsed["mac"],
        "length": parsed["length"],
        "payload": parsed["payload"],
        "iq_file": f"/dataset/{fname}",
        "iq_samples": int(len(iq)),
    }
    with lock:
        messages_db.append(msg)
        if len(messages_db) > 500:
            del messages_db[:-500]
    SAVE_QUEUE.put((os.path.join(DATASET_DIR, fname), np.ascontiguousarray(iq, dtype=np.complex128)))


def writer_loop():
    """Отдельный поток записи .npy, чтобы диск не тормозил обработку."""
    while True:
        path, iq = SAVE_QUEUE.get()
        try:
            np.save(path, iq)
        except Exception as ex:               # noqa: BLE001
            stats["errors"].append(f"save: {type(ex).__name__}: {ex}")


SAVE_QUEUE = queue.Queue(maxsize=100)
_writer_started = threading.Event()


def _ensure_writer():
    if not _writer_started.is_set():
        _writer_started.set()
        threading.Thread(target=writer_loop, daemon=True).start()


def process_buffer(buf, channel, freq):
    for s, e in ble.detect_bursts(buf, min_len=100, max_len=2000,
                                  smooth=16, merge_gap=50, margin=32):
        if e + 100 > len(buf):
            continue                        # всплеск обрезан — подождём хвост
        ss = max(0, s - 32)
        ee = min(len(buf), e + 32)
        stats["bursts"] += 1
        parsed = ble.decode_capture(buf[ss:ee], channel=channel, sps=SPS)
        if parsed:
            stats["decoded"] += 1
            save_packet(buf[ss:ee], parsed, channel, freq)
        yield ee


def sdr_worker():
    try:
        import uhd

        _ensure_writer()

        usrp = uhd.usrp.MultiUSRP("type=b200")
        usrp.set_rx_rate(SAMP_RATE, 0)
        usrp.set_rx_gain(GAIN, 0)
        usrp.set_rx_antenna("RX2", 0)

        st_args = uhd.usrp.StreamArgs("fc32", "sc16")
        st_args.channels = [0]
        st_args.args = "num_recv_frames=256,recv_frame_size=16384"   # большой FIFO: защита от всплесков нагрузки CPU
        stream = usrp.get_rx_stream(st_args)

        stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
        stream_cmd.stream_now = True

        tmp = np.zeros(8192, dtype=np.complex64)
        md = uhd.types.RXMetadata()

        hop_idx = 0
        last_hop = time.time()
        usrp.set_rx_freq(uhd.types.TuneRequest(CHANNELS[0][1]), 0)

        # Очередь между потоком приёма и потоком обработки (~0.5 с буфера)
        rx_queue = queue.Queue(maxsize=64)

        def recv_loop():
            """Только вычитывает USB и кладёт сырые куски в очередь."""
            nonlocal hop_idx, last_hop
            stream.issue_stream_cmd(stream_cmd)
            while True:
                if time.time() - last_hop > HOP_INTERVAL:
                    hop_idx = (hop_idx + 1) % len(CHANNELS)
                    ch, freq = CHANNELS[hop_idx]
                    usrp.set_rx_freq(uhd.types.TuneRequest(freq), 0)
                    stats["channel"] = ch
                    last_hop = time.time()
                n = stream.recv(tmp, md, 0.5)
                if n <= 0:
                    continue
                try:
                    rx_queue.put_nowait(tmp[:n].copy())
                except queue.Full:
                    # не успеваем обрабатывать — выбрасываем самый старый кусок
                    try:
                        rx_queue.get_nowait()
                        stats["dropped"] += 1
                        rx_queue.put_nowait(tmp[:n].copy())
                    except queue.Empty:
                        pass

        stats["running"] = True
        print(f"[*] SDR запущен: {SAMP_RATE/1e6:.0f} MSPS, антенна RX2, gain={GAIN}")
        threading.Thread(target=recv_loop, daemon=True).start()

        # Поток обработки: детект -> демодуляция -> CRC -> сохранение
        pending = []
        pending_len = 0
        while True:
            try:
                chunk = rx_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            pending.append(chunk)
            pending_len += len(chunk)
            if pending_len < CHUNK + GUARD:
                continue

            buf = pending[0] if len(pending) == 1 else np.concatenate(pending)
            pending = []
            pending_len = 0

            ch, freq = CHANNELS[hop_idx]
            work = buf[:-GUARD]
            consumed = 0
            for end in process_buffer(work, ch, freq):
                consumed = max(consumed, end)
            if consumed:
                tail = buf[consumed:]
                pending = [tail]
                pending_len = len(tail)

    except Exception as ex:                 # noqa: BLE001
        stats["errors"].append(f"{type(ex).__name__}: {ex}")
        print(f"[!] Ошибка SDR-потока: {ex}")
    finally:
        stats["running"] = False


app = FastAPI(title="BLE Passive Identifier")


@app.on_event("startup")
def startup():
    _ensure_writer()
    threading.Thread(target=sdr_worker, daemon=True).start()


@app.get("/api/messages")
def get_messages():
    with lock:
        return list(reversed(messages_db[-200:]))


@app.get("/api/stats")
def get_stats():
    return {
        "running": stats["running"],
        "channel": stats["channel"],
        "bursts": stats["bursts"],
        "decoded": stats["decoded"],
        "total_messages": len(messages_db),
        "dropped": stats["dropped"],
        "errors": stats["errors"][-5:],
    }


@app.get("/dataset/{fname}")
def get_dataset_file(fname: str):
    # защита от path traversal
    safe = os.path.basename(fname)
    path = os.path.join(DATASET_DIR, safe)
    if not os.path.isfile(path):
        return {"error": "not found"}
    return FileResponse(path, media_type="application/octet-stream", filename=safe)


app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "static"), html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info", access_log=False)
