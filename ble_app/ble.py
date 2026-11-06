"""
Ядро демодуляции BLE (BLE 4.x advertising, 1 Msym/s GFSK).

Чистые DSP-функции без привязки к SDR/Web — можно тестировать офлайн
на сохранённых IQ-сэмплах (см. scripts/validate_dataset.py).
"""

import numpy as np

# Access Address рекламных каналов 0x8E89BED6, биты в порядке передачи (LSB first)
AA_BITS = "01101011011111011001000101110001"
AA_PATTERN = np.array([1.0 if b == "1" else -1.0 for b in AA_BITS])

SAMPLE_RATE = 4e6          # 4 сэмпла на символ (1 Msym/s GFSK)
SPS = 4                    # сэмплов на символ
MAX_PAYLOAD = 37           # максимум для legacy advertising PDU
CRC_POLY = 0x00065B        # x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1
CRC_INIT = 0x555555

PDU_TYPES = {
    0: "ADV_IND",
    1: "ADV_DIRECT_IND",
    2: "ADV_NONCONN_IND",
    3: "SCAN_REQ",
    4: "SCAN_RSP",
    5: "CONNECT_IND",
    6: "ADV_SCAN_IND",
    7: "ADV_EXT_IND",
}


# ---------------------------------------------------------------------------
# Де-скремблирование (data whitening): LFSR x^7 + x^4 + 1, выход = MSR (бит 6)
# Сиды подобраны эмпирически и валидированы CRC24 на живом эфире.
# ---------------------------------------------------------------------------
WHITEN_SEED = {37: 0x53, 38: 0x33, 39: 0x73}

_STREAM_CACHE = {}


def _whitening_stream(channel, nbits):
    """Биты потока whitening для канала (предрасчёт с кэшем)."""
    stream = _STREAM_CACHE.get(channel)
    if stream is None or len(stream) < nbits:
        lfsr = WHITEN_SEED[channel]
        stream = np.empty(max(nbits, 512), dtype=np.uint8)
        for i in range(len(stream)):
            msb = (lfsr & 0x40) >> 6
            stream[i] = msb
            lfsr = (((lfsr << 1) & 0x7F) ^ 0x11) if msb else ((lfsr << 1) & 0x7F)
        _STREAM_CACHE[channel] = stream
    return stream[:nbits]


def _pack_bits_lsb(bits_arr):
    """Массив бит 0/1 (первый бит = LSB) -> bytes через numpy."""
    n = len(bits_arr) // 8
    b = bits_arr[: n * 8].reshape(n, 8)[:, ::-1]
    return np.packbits(b, axis=1).flatten()


def dewhiten_bits(bits, channel=37):
    arr = np.frombuffer(bits.encode(), dtype=np.uint8) & 1
    clean = arr ^ _whitening_stream(channel, len(arr))
    return "".join("1" if b else "0" for b in clean)


def bits_to_bytes(bits):
    """Биты в порядке передачи (первый бит = LSB) -> bytes."""
    nbytes = len(bits) // 8
    buf = bytearray(nbytes)
    for i in range(nbytes):
        byte = 0
        for j in range(8):
            if bits[i * 8 + j] == "1":
                byte |= 1 << j
        buf[i] = byte
    return bytes(buf)


# ---------------------------------------------------------------------------
# CRC24 BLE (полином x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1)
# Рефлективная (LSB-first) реализация, эквивалентная scapy BTLE.compute_crc
# и gr-ble. Проверена на живом эфире.
# ---------------------------------------------------------------------------
def _swap24(num):
    return int(format(num & 0xFFFFFF, "024b")[::-1], 2)


_CRC_POLY_R = _swap24(CRC_POLY)
_CRC_INIT_R = _swap24(CRC_INIT)


def crc24(pdu_bytes, init=CRC_INIT):
    crc = _swap24(init)
    poly = _swap24(CRC_POLY)
    for byte in pdu_bytes:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ poly) & 0xFFFFFF if crc & 1 else (crc >> 1) & 0xFFFFFF
    return crc


# ---------------------------------------------------------------------------
# Разбор PDU
# ---------------------------------------------------------------------------
def mac_str(addr_bytes):
    """6 байт AdvA (в порядке передачи) -> читаемый MAC."""
    return ":".join(f"{b:02X}" for b in reversed(addr_bytes))


def parse_pdu(pdu_bytes):
    """pdu_bytes = header(2) + payload(length). Возвращает dict или None."""
    if len(pdu_bytes) < 8:
        return None
    pdu_type = pdu_bytes[0] & 0x0F
    length = pdu_bytes[1] & 0x3F
    if pdu_type not in PDU_TYPES or length > MAX_PAYLOAD:
        return None
    payload = pdu_bytes[2:2 + length]
    if len(payload) < length:
        return None

    result = {
        "pdu_type": PDU_TYPES[pdu_type],
        "length": length,
    }

    if pdu_type == 7:                       # ADV_EXT_IND: AdvA в расширенном заголовке
        result["mac"] = "N/A (ext)"
        result["payload"] = payload.hex().upper()
    elif pdu_type in (0, 2, 4, 6):          # advertising с AdvA
        if length < 6:
            return None
        result["mac"] = mac_str(payload[0:6])
        result["payload"] = payload[6:].hex().upper()
    elif pdu_type == 3:                     # SCAN_REQ: ScanA + AdvA
        if length < 12:
            return None
        result["mac"] = mac_str(payload[0:6])
        result["payload"] = payload[6:].hex().upper()
    elif pdu_type == 5:                     # CONNECT_IND: InitA + AdvA + LLData
        if length < 12:
            return None
        result["mac"] = mac_str(payload[0:6])
        result["payload"] = payload[6:].hex().upper()
    else:                                   # ADV_DIRECT_IND
        if length < 12:
            return None
        result["mac"] = mac_str(payload[0:6])
        result["payload"] = payload[6:].hex().upper()
    return result


# ---------------------------------------------------------------------------
# GFSK демодуляция
# ---------------------------------------------------------------------------
def _instant_freq(iq):
    """Мгновенная частота (рад/сэмпл) через разность фаз."""
    d = iq[1:] * np.conj(iq[:-1])
    return np.angle(d)


def _bits_per_symbol(ph, offset, sps=SPS):
    """Усреднение блоков по sps сэмплов -> 1 мягкое значение на символ."""
    a = ph[offset:]
    a = a[: (len(a) // sps) * sps]
    return a.reshape(-1, sps).mean(axis=1)


def find_access_address(soft_bits, sps=SPS):
    """
    Поиск AA корреляцией по битовой сетке (все фазы децимации).
    Возвращает (symbol_index, polarity, sb) или None.
    polarity = +1: частота + -> бит '1', -1: инверсия.
    """
    best = None
    for off in range(sps):
        sb = _bits_per_symbol(soft_bits, off, sps)
        if len(sb) < len(AA_PATTERN):
            continue
        hb = np.where(sb >= 0, 1.0, -1.0)
        corr = np.correlate(hb, AA_PATTERN, mode="valid")
        if len(corr) == 0:
            continue
        idx = int(np.argmax(np.abs(corr)))
        score = float(np.abs(corr[idx]))    # 0..32, число совпавших бит
        if best is None or score > best[0]:
            best = (score, off, idx, 1.0 if corr[idx] >= 0 else -1.0)
    if best is None:
        return None
    score, off, idx, polarity = best
    if score < 28.0:                        # допускаем до 4 битовых ошибок в AA
        return None
    sb = _bits_per_symbol(soft_bits, off, sps)
    return idx, polarity, sb


def decode_capture(iq, channel=37, sps=SPS):
    """
    Декодирование одной записи (всплеска) IQ-сэмплов.
    Возвращает dict с полями pdu_type/mac/length/payload/crc_ok
    или None, если валидный BLE-пакет не найден.
    """
    iq = np.asarray(iq)
    if iq.ndim == 1 and len(iq) < 88 * sps:
        return None

    ph = _instant_freq(iq)
    ph = ph - np.median(ph)                 # убираем CFO/DC (медиана устойчива к несбалансированным битам)

    found = find_access_address(ph, sps)
    if not found:
        return None
    aa_idx, polarity, sb = found

    # Мягкие значения после AA -> биты PDU
    pdu_soft = sb[aa_idx + len(AA_PATTERN):] * polarity
    hard = (pdu_soft > 0).astype(np.uint8)

    if len(hard) < 16:                      # заголовок минимум
        return None

    # De-whitening целиком (поток непрерывный на всём PDU+CRC) и сборка байтов
    clean = hard ^ _whitening_stream(channel, len(hard))
    bts = _pack_bits_lsb(clean)

    length = bts[1] & 0x3F
    if length > MAX_PAYLOAD:
        return None

    total_bytes = 2 + length + 3          # header + payload + CRC
    if len(bts) < total_bytes:
        return None

    pdu_bytes = bytes(bts[: 2 + length])
    crc_rx = bts[2 + length: total_bytes]
    crc_rx_val = int(crc_rx[0]) | (int(crc_rx[1]) << 8) | (int(crc_rx[2]) << 16)
    crc_ok = crc24(pdu_bytes) == crc_rx_val
    if not crc_ok:
        return None

    parsed = parse_pdu(pdu_bytes)
    if parsed is None:
        return None
    parsed["crc_ok"] = True
    parsed["channel"] = channel
    return parsed


# ---------------------------------------------------------------------------
# Детект всплесков по энергии (для живого потока)
# ---------------------------------------------------------------------------
def detect_bursts(iq, thresh_db=8.0, smooth=32, min_len=160, max_len=4000,
                  merge_gap=100, margin=64):
    """
    Поиск участков с энергией выше порога в непрерывном потоке.
    Возвращает список (start, end) — только всплески, полностью
    завершившиеся внутри переданного буфера.
    """
    p = np.abs(iq) ** 2
    kernel = np.ones(smooth) / smooth
    ps = np.convolve(p, kernel, mode="same")
    noise = np.median(ps) + 1e-12
    thr = noise * 10 ** (thresh_db / 10)

    above = ps > thr
    d = np.diff(above.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if above[0]:
        starts.insert(0, 0)
    if above[-1]:
        ends.append(len(above))             # обрезан буфером — неполный

    bursts = []
    for s, e in zip(starts, ends):
        if bursts and s - bursts[-1][1] < merge_gap:
            bursts[-1] = (bursts[-1][0], e)
            continue
        bursts.append((s, e))

    out = []
    for s, e in bursts:
        if e - s < min_len:
            continue
        if e - s > max_len:
            continue
        s = max(0, s - margin)
        e = min(len(iq), e + margin)
        out.append((s, e))
    return out
