# Pure Python QR Code Generator (no dependencies)
# Generates SVG string for QR codes up to version 10 (sufficient for URLs and TOTP URIs).

class QRError(Exception):
    pass

# GF(2^8) Galois Field with primitive polynomial 0x11D (285)
EXP = [0] * 512
LOG = [0] * 256
x = 1
for i in range(256):
    EXP[i] = x
    LOG[x] = i
    x <<= 1
    if x & 256:
        x ^= 285
for i in range(256, 512):
    EXP[i] = EXP[i - 256]

def gf_mul(x, y):
    if x == 0 or y == 0:
        return 0
    return EXP[LOG[x] + LOG[y]]

def rs_poly_mul(p1, p2):
    r = [0] * (len(p1) + len(p2) - 1)
    for i, c1 in enumerate(p1):
        for j, c2 in enumerate(p2):
            r[i + j] ^= gf_mul(c1, c2)
    return r

def rs_generator_poly(nsym):
    g = [1]
    for i in range(nsym):
        g = rs_poly_mul(g, [1, EXP[i]])
    return g

def rs_encode(data, nsym):
    gen = rs_generator_poly(nsym)
    res = list(data) + [0] * nsym
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(len(gen)):
                res[i + j] ^= gf_mul(gen[j], coef)
    return res[len(data):]

# QR Version Capacity and EC Specs (Version 1..10, EC level M)
# Format: (version, size, ec_codewords_per_block, num_blocks, total_data_bytes)
QR_SPECS_M = [
    (1, 21, 10, 1, 16),
    (2, 25, 16, 1, 28),
    (3, 29, 26, 1, 44),
    (4, 33, 18, 2, 64),
    (5, 37, 24, 2, 86),
    (6, 41, 16, 4, 108),
    (7, 45, 18, 4, 124),
    (8, 49, 22, 4, 154),
    (9, 53, 20, 5, 182),
    (10, 57, 24, 5, 216),
]

ALIGNMENT_PATTERNS = {
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 38],
    8: [6, 42],
    9: [6, 46],
    10: [6, 50],
}

# Format info string generator (15 bits: 5 data bits + 10 BCH bits ^ mask 0x5465)
# EC Level M = 00
def get_format_info(mask_pattern):
    data = (0 << 3) | mask_pattern  # EC Level M is 00
    g = 0x537  # BCH generator 10100110111
    rem = data << 10
    for i in range(4, -1, -1):
        if (rem >> (i + 10)) & 1:
            rem ^= g << i
    fmt = (data << 10) | rem
    return fmt ^ 0x5465


def generate_qr_matrix(text):
    data_bytes = text.encode('utf-8')
    data_len = len(data_bytes)

    # Find suitable QR version
    spec = None
    for s in QR_SPECS_M:
        # Byte mode overhead: 4 bits mode + 8 bits len (v1-9) or 16 bits len (v10+)
        len_bits = 16 if s[0] >= 10 else 8
        needed_bytes = (4 + len_bits + data_len * 8 + 7) // 8
        if needed_bytes <= s[4]:
            spec = s
            break

    if not spec:
        raise QRError("Data too long for QR generator")

    version, size, ec_per_block, num_blocks, total_data_bytes = spec

    # Build bit buffer
    bits = []
    def add_bits(val, count):
        for i in range(count - 1, -1, -1):
            bits.append((val >> i) & 1)

    # Byte mode = 0100
    add_bits(0b0100, 4)
    len_bits = 16 if version >= 10 else 8
    add_bits(data_len, len_bits)
    for b in data_bytes:
        add_bits(b, 8)

    # Terminator
    term_len = min(4, total_data_bytes * 8 - len(bits))
    add_bits(0, term_len)

    # Pad to byte boundary
    while len(bits) % 8 != 0:
        bits.append(0)

    # Pad bytes 0xEC, 0x11
    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(bits) < total_data_bytes * 8:
        add_bits(pad_bytes[pad_idx], 8)
        pad_idx = (pad_idx + 1) % 2

    # Convert bits to data codewords
    raw_data = []
    for i in range(0, len(bits), 8):
        val = 0
        for b in bits[i:i+8]:
            val = (val << 1) | b
        raw_data.append(val)

    # Divide data into blocks and compute EC
    block_len = total_data_bytes // num_blocks
    extra = total_data_bytes % num_blocks
    data_blocks = []
    ec_blocks = []
    offset = 0
    for i in range(num_blocks):
        blen = block_len + (1 if i >= num_blocks - extra else 0)
        block = raw_data[offset : offset + blen]
        offset += blen
        data_blocks.append(block)
        ec_blocks.append(rs_encode(block, ec_per_block))

    # Interleave codewords
    final_codewords = []
    max_data_len = max(len(b) for b in data_blocks)
    for i in range(max_data_len):
        for b in data_blocks:
            if i < len(b):
                final_codewords.append(b[i])
    for i in range(ec_per_block):
        for b in ec_blocks:
            final_codewords.append(b[i])

    # Build matrix grid
    # grid: -1 = unassigned, 0 = white, 1 = black
    grid = [[-1] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_module(r, c, val, is_res=True):
        grid[r][c] = val
        if is_res:
            reserved[r][c] = True

    # Finder patterns
    def place_finder(r0, c0):
        for r in range(7):
            for c in range(7):
                is_black = (r in (0, 6) or c in (0, 6)) or (2 <= r <= 4 and 2 <= c <= 4)
                set_module(r0 + r, c0 + c, 1 if is_black else 0)
        # Separator
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= r0 + r < size and 0 <= c0 + c < size:
                    if not reserved[r0 + r][c0 + c]:
                        set_module(r0 + r, c0 + c, 0)

    place_finder(0, 0)
    place_finder(0, size - 7)
    place_finder(size - 7, 0)

    # Timing patterns
    for i in range(8, size - 8):
        if not reserved[6][i]:
            set_module(6, i, 1 if i % 2 == 0 else 0)
        if not reserved[i][6]:
            set_module(i, 6, 1 if i % 2 == 0 else 0)

    # Alignment patterns
    if version in ALIGNMENT_PATTERNS:
        coords = ALIGNMENT_PATTERNS[version]
        for r in coords:
            for c in coords:
                if reserved[r][c]:
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        is_black = (abs(dr) == 2 or abs(dc) == 2) or (dr == 0 and dc == 0)
                        set_module(r + dr, c + dc, 1 if is_black else 0)

    # Reserve format info areas
    for i in range(9):
        if not reserved[8][i]:
            set_module(8, i, 0)
        if not reserved[i][8]:
            set_module(i, 8, 0)
    for i in range(8):
        if not reserved[8][size - 1 - i]:
            set_module(8, size - 1 - i, 0)
        if not reserved[size - 1 - i][8]:
            set_module(size - 1 - i, 8, 0)
    set_module(size - 8, 8, 1)  # Always dark module

    # Place data bits
    bit_index = 0
    total_bits = len(final_codewords) * 8

    # Traverse matrix columns right to left in pairs
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:  # Skip vertical timing column
            col -= 1
        for row_idx in range(size):
            r = (size - 1 - row_idx) if upward else row_idx
            for c in (col, col - 1):
                if not reserved[r][c]:
                    bit_val = 0
                    if bit_index < total_bits:
                        byte_idx = bit_index // 8
                        bit_pos = 7 - (bit_index % 8)
                        bit_val = (final_codewords[byte_idx] >> bit_pos) & 1
                        bit_index += 1
                    grid[r][c] = bit_val
        col -= 2
        upward = not upward

    # Apply mask pattern (pattern 0: (r + c) % 2 == 0)
    mask_pattern = 0
    final_matrix = [row[:] for row in grid]
    for r in range(size):
        for c in range(size):
            if not reserved[r][c]:
                if (r + c) % 2 == 0:
                    final_matrix[r][c] ^= 1

    # Write format information
    fmt_bits = get_format_info(mask_pattern)
    fmt_list = [(fmt_bits >> i) & 1 for i in range(15)]

    # Top-left format info
    coords_tl = [(8,0),(8,1),(8,2),(8,3),(8,4),(8,5),(8,7),(8,8),(7,8),(5,8),(4,8),(3,8),(2,8),(1,8),(0,8)]
    for idx, (r, c) in enumerate(coords_tl):
        final_matrix[r][c] = fmt_list[idx]

    # Split format info (top-right and bottom-left)
    coords_br = [(8, size-1), (8, size-2), (8, size-3), (8, size-4), (8, size-5), (8, size-6), (8, size-7),
                 (size-7, 8), (size-6, 8), (size-5, 8), (size-4, 8), (size-3, 8), (size-2, 8), (size-1, 8)]
    for idx, (r, c) in enumerate(coords_br[:7]):
        final_matrix[r][c] = fmt_list[idx]
    for idx, (r, c) in enumerate(coords_br[7:]):
        final_matrix[r][c] = fmt_list[idx + 7]
    final_matrix[size - 8][8] = fmt_list[14]

    return final_matrix


def generate_qr_svg(text, module_size=4, border=4):
    """Generates an SVG string representing the QR code for `text`."""
    matrix = generate_qr_matrix(text)
    size = len(matrix)
    total_size = (size + border * 2) * module_size

    rects = []
    for r in range(size):
        for c in range(size):
            if matrix[r][c] == 1:
                x = (c + border) * module_size
                y = (r + border) * module_size
                rects.append(f'<rect x="{x}" y="{y}" width="{module_size}" height="{module_size}" fill="#000000"/>')

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_size} {total_size}" '
        f'width="{total_size}" height="{total_size}" style="max-width: 100%; height: auto; background: #ffffff; border-radius: 8px; padding: 4px;">'
        f'{"".join(rects)}'
        f'</svg>'
    )
    return svg
