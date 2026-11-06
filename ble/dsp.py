"""BLE DSP core: pure demodulation/decoding functions with no I/O dependencies.

Can be tested offline on recorded IQ samples (see scripts/validate_dataset.py).
"""

import numpy as np

# Advertising channel Access Address 0x8E89BED6, bits in transmission order (LSB first)
AA_BITS = "01101011011111011001000101110001"
AA_PATTERN = np.array([1.0 if b == "1" else -1.0 for b in AA_BITS])
PREAMBLE_BITS = "10101010"   # last preamble bit equals the LSB of the Access Address

SAMPLE_RATE = 4e6            # reference rate for 4 samples per symbol (1 Msym/s GFSK)
SPS = 4                      # samples per symbol at SAMPLE_RATE
MAX_PAYLOAD = 37             # maximum legacy advertising PDU payload
CRC_POLY = 0x00065B          # x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1
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
# Data whitening: LFSR x^7 + x^4 + 1, output taken from the MSB (bit 6).
# Seeds were found empirically and validated with CRC24 over live air traffic.
# ---------------------------------------------------------------------------
WHITEN_SEED = {37: 0x53, 38: 0x33, 39: 0x73}

_STREAM_CACHE = {}


def _whitening_stream(channel, nbits):
    """Whitening stream bits for a channel (precomputed and cached)."""
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
    """Array of 0/1 bits (first bit = LSB) -> byte array via numpy."""
    n = len(bits_arr) // 8
    b = bits_arr[: n * 8].reshape(n, 8)[:, ::-1]
    return np.packbits(b, axis=1).flatten()


def dewhiten_bits(bits, channel=37):
    """Dewhiten a bit string ('0'/'1' chars in transmission order)."""
    arr = np.frombuffer(bits.encode(), dtype=np.uint8) & 1
    clean = arr ^ _whitening_stream(channel, len(arr))
    return "".join("1" if b else "0" for b in clean)


def whiten_bytes(data, channel=37):
    """Apply BLE data whitening to a byte sequence (XOR is symmetric with dewhitening)."""
    data = np.frombuffer(bytes(data), dtype=np.uint8).copy()
    sb = _whitening_stream(channel, len(data) * 8).reshape(-1, 8)
    out = np.zeros_like(data)
    for i in range(8):
        out |= (((data >> i) & 1) ^ sb[:, i]) << i
    return out.tobytes()


def bits_to_bytes(bits):
    """Bits in transmission order (first bit = LSB) -> bytes."""
    nbytes = len(bits) // 8
    buf = bytearray(nbytes)
    for i in range(nbytes):
        byte = 0
        for j in range(8):
            if bits[i * 8 + j] == "1":
                byte |= 1 << j
        buf[i] = byte
    return bytes(buf)


def bytes_to_bits(data):
    """Bytes -> bit string in transmission order (LSB of each byte first)."""
    return "".join("1" if (b >> i) & 1 else "0" for b in data for i in range(8))


# ---------------------------------------------------------------------------
# CRC24 (polynomial x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1).
# Reflected (LSB-first) implementation, equivalent to scapy BTLE.compute_crc
# and gr-ble. Verified against live air traffic.
# ---------------------------------------------------------------------------
def _swap24(num):
    return int(format(num & 0xFFFFFF, "024b")[::-1], 2)


def crc24(pdu_bytes, init=CRC_INIT):
    """Compute the BLE CRC24 of a PDU (header + payload), returned as an integer."""
    crc = _swap24(init)
    poly = _swap24(CRC_POLY)
    for byte in pdu_bytes:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ poly) & 0xFFFFFF if crc & 1 else (crc >> 1) & 0xFFFFFF
    return crc


# ---------------------------------------------------------------------------
# PDU parsing
# ---------------------------------------------------------------------------
def mac_str(addr_bytes):
    """6 AdvA bytes (transmission order) -> human-readable MAC string."""
    return ":".join(f"{b:02X}" for b in reversed(addr_bytes))


def parse_pdu(pdu_bytes):
    """Parse a PDU (header(2) + payload). Returns a dict or None."""
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

    if pdu_type == 7:                       # ADV_EXT_IND: AdvA lives in the extended header
        result["mac"] = "N/A (ext)"
        result["payload"] = payload.hex().upper()
        return result

    # All other handled types carry a 6-byte advertiser address first
    if pdu_type == 3 and length < 12:       # SCAN_REQ: ScanA + AdvA
        return None
    if pdu_type in (1, 5) and length < 12:  # ADV_DIRECT_IND / CONNECT_IND
        return None
    if pdu_type in (0, 2, 4, 6) and length < 6:
        return None
    result["mac"] = mac_str(payload[0:6])
    result["payload"] = payload[6:].hex().upper()
    return result


# ---------------------------------------------------------------------------
# GFSK modulation (used by the synthetic signal source)
# ---------------------------------------------------------------------------
_GAUSS_CACHE = {}


def _gaussian_kernel(sps, bt=0.5, span=3):
    key = (sps, bt, span)
    if key not in _GAUSS_CACHE:
        sigma = np.sqrt(np.log(2)) / (2 * np.pi * bt)
        t = np.arange(-span * sps, span * sps + 1) / sps
        g = np.exp(-(t ** 2) / (2 * sigma ** 2))
        _GAUSS_CACHE[key] = g / g.sum()
    return _GAUSS_CACHE[key]


def modulate_gfsk(bits, sps, samp_rate, deviation=250e3):
    """GFSK-modulate a bit string into complex baseband IQ (complex64)."""
    nrz = np.array([1.0 if b == "1" else -1.0 for b in bits])
    shaped = np.convolve(np.repeat(nrz, sps), _gaussian_kernel(sps), mode="same")
    freq = shaped * deviation
    phase = np.cumsum(2 * np.pi * freq / samp_rate)
    return np.exp(1j * phase).astype(np.complex64)


# ---------------------------------------------------------------------------
# GFSK demodulation
# ---------------------------------------------------------------------------
def _instant_freq(iq):
    """Instantaneous frequency (rad/sample) via phase difference."""
    d = iq[1:] * np.conj(iq[:-1])
    return np.angle(d)


def _bits_per_symbol(ph, offset, sps=SPS):
    """Average sps-sample blocks -> 1 soft value per symbol."""
    a = ph[offset:]
    a = a[: (len(a) // sps) * sps]
    return a.reshape(-1, sps).mean(axis=1)


def find_access_address(soft_bits, sps=SPS):
    """
    Locate the Access Address by correlating on the bit grid (all decimation phases).
    Returns (symbol_index, polarity, soft_bits) or None.
    polarity = +1: positive frequency means bit '1', -1: inverted.
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
        score = float(np.abs(corr[idx]))    # 0..32, number of matched bits
        if best is None or score > best[0]:
            best = (score, off, idx, 1.0 if corr[idx] >= 0 else -1.0)
    if best is None:
        return None
    score, off, idx, polarity = best
    if score < 28.0:                        # allow up to 4 bit errors in the AA
        return None
    sb = _bits_per_symbol(soft_bits, off, sps)
    return idx, polarity, sb


def decode_capture(iq, channel=37, sps=SPS):
    """
    Decode a single capture (burst) of IQ samples.
    Returns a dict with pdu_type/mac/length/payload fields, or None if no
    valid BLE packet was found (AA not located or CRC mismatch).
    """
    iq = np.asarray(iq)
    if iq.ndim == 1 and len(iq) < 88 * sps:
        return None

    ph = _instant_freq(iq)
    # Median is robust against unbalanced bit statistics (mean is not)
    ph = ph - np.median(ph)

    found = find_access_address(ph, sps)
    if not found:
        return None
    aa_idx, polarity, sb = found

    # Soft values after the AA -> hard PDU bits
    pdu_soft = sb[aa_idx + len(AA_PATTERN):] * polarity
    hard = (pdu_soft > 0).astype(np.uint8)

    if len(hard) < 16:                      # need at least the header
        return None

    # Dewhiten everything at once (the stream is continuous over PDU+CRC) and pack bytes
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
    if crc24(pdu_bytes) != crc_rx_val:
        return None

    parsed = parse_pdu(pdu_bytes)
    if parsed is None:
        return None
    parsed["crc_ok"] = True
    parsed["channel"] = channel
    return parsed


# ---------------------------------------------------------------------------
# Energy-based burst detection (for live streams)
# ---------------------------------------------------------------------------
def detect_bursts(iq, thresh_db=8.0, smooth=32, min_len=160, max_len=4000,
                  merge_gap=100, margin=64):
    """
    Find regions with energy above threshold in a continuous stream.
    Returns a list of (start, end) sample indices for bursts that finished
    completely inside the given buffer.
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
        ends.append(len(above))             # clipped by the buffer -> incomplete

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
