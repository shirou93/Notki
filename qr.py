# Pure Python QR Code Generator (no dependencies)
# Generates SVG string for QR codes up to version 10 (sufficient for URLs and TOTP URIs).

class QRError(Exception):
    pass

# GF(2^8) Galois Field with primitive polynomial 0x11D (285)
EXP = [0] * 512
LOG = [0] * 256
x = 1
for i in range(255):
    EXP[i] = x
    LOG[x] = i
    x <<= 1
    if x & 256:
        x ^= 285
for i in range(255, 512):
    EXP[i] = EXP[i - 255]

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
# Format: (version, size, [(block_count, total_codewords_per_block, data_codewords_per_block), ...])
QR_SPECS_M = [
    (1, 21, [(1, 26, 16)]),
    (2, 25, [(1, 44, 28)]),
    (3, 29, [(1, 70, 44)]),
    (4, 33, [(2, 50, 32)]),
    (5, 37, [(2, 67, 43)]),
    (6, 41, [(4, 43, 27)]),
    (7, 45, [(4, 49, 31)]),
    (8, 49, [(2, 60, 38), (2, 61, 39)]),
    (9, 53, [(3, 58, 36), (2, 59, 37)]),
    (10, 57, [(4, 69, 43), (1, 70, 44)]),
]

ALIGNMENT_PATTERNS = {
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

# Format info string generator (15 bits: 5 data bits + 10 BCH bits ^ mask 0x5412)
# EC Level M = 00
def get_format_info(mask_pattern):
    data = (0b00 << 3) | mask_pattern  # EC Level M is 00
    g = 0x537  # BCH generator 10100110111
    rem = data << 10
    for i in range(4, -1, -1):
        if (rem >> (i + 10)) & 1:
            rem ^= g << i
    fmt = (data << 10) | rem
    return fmt ^ 0x5412

def get_version_info(version):
    g = 0x1F25
    rem = version << 12
    for i in range(5, -1, -1):
        if (rem >> (i + 12)) & 1:
            rem ^= g << i
    return (version << 12) | rem

def get_mask_bit(pattern, r, c):
    if pattern == 0: return (r + c) % 2 == 0
    if pattern == 1: return r % 2 == 0
    if pattern == 2: return c % 3 == 0
    if pattern == 3: return (r + c) % 3 == 0
    if pattern == 4: return (r // 2 + c // 3) % 2 == 0
    if pattern == 5: return ((r * c) % 2) + ((r * c) % 3) == 0
    if pattern == 6: return (((r * c) % 2) + ((r * c) % 3)) % 2 == 0
    if pattern == 7: return (((r + c) % 2) + ((r * c) % 3)) % 2 == 0
    return False

def evaluate_penalty(matrix, size):
    penalty = 0
    # Rule 1: 5 or more same color modules in row/col
    for r in range(size):
        count = 1
        for c in range(1, size):
            if matrix[r][c] == matrix[r][c - 1]:
                count += 1
            else:
                if count >= 5:
                    penalty += 3 + (count - 5)
                count = 1
        if count >= 5:
            penalty += 3 + (count - 5)

    for c in range(size):
        count = 1
        for r in range(1, size):
            if matrix[r][c] == matrix[r - 1][c]:
                count += 1
            else:
                if count >= 5:
                    penalty += 3 + (count - 5)
                count = 1
        if count >= 5:
            penalty += 3 + (count - 5)

    # Rule 2: 2x2 blocks of same color
    for r in range(size - 1):
        for c in range(size - 1):
            val = matrix[r][c]
            if matrix[r + 1][c] == val and matrix[r][c + 1] == val and matrix[r + 1][c + 1] == val:
                penalty += 3

    # Rule 3: 1:1:3:1:1 finder-like pattern
    for r in range(size):
        for c in range(size - 6):
            if matrix[r][c:c + 7] == [1, 0, 1, 1, 1, 0, 1]:
                if c >= 4 and matrix[r][c - 4:c] == [0, 0, 0, 0]:
                    penalty += 40
                if c + 11 <= size and matrix[r][c + 7:c + 11] == [0, 0, 0, 0]:
                    penalty += 40

    for c in range(size):
        col_vals = [matrix[r][c] for r in range(size)]
        for r in range(size - 6):
            if col_vals[r:r + 7] == [1, 0, 1, 1, 1, 0, 1]:
                if r >= 4 and col_vals[r - 4:r] == [0, 0, 0, 0]:
                    penalty += 40
                if r + 11 <= size and col_vals[r + 7:r + 11] == [0, 0, 0, 0]:
                    penalty += 40

    # Rule 4: Proportion of dark modules
    dark_count = sum(sum(row) for row in matrix)
    percent = (dark_count * 100) // (size * size)
    penalty += (abs(percent - 50) // 5) * 10

    return penalty

def generate_qr_matrix(text):
    data_bytes = text.encode('utf-8')
    data_len = len(data_bytes)

    # Find suitable QR version
    spec = None
    for s in QR_SPECS_M:
        version, size, blocks_spec = s
        total_data_bytes = sum(count * dcnt for count, tcnt, dcnt in blocks_spec)
        len_bits = 16 if version >= 10 else 8
        needed_bytes = (4 + len_bits + data_len * 8 + 7) // 8
        if needed_bytes <= total_data_bytes:
            spec = s
            break

    if not spec:
        raise QRError("Data too long for QR generator")

    version, size, blocks_spec = spec
    total_data_bytes = sum(count * dcnt for count, tcnt, dcnt in blocks_spec)

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
    data_blocks = []
    ec_blocks = []
    offset = 0
    for count, tcnt, dcnt in blocks_spec:
        ec_per_block = tcnt - dcnt
        for _ in range(count):
            block = raw_data[offset : offset + dcnt]
            offset += dcnt
            data_blocks.append(block)
            ec_blocks.append(rs_encode(block, ec_per_block))

    # Interleave codewords
    final_codewords = []
    max_data_len = max(len(b) for b in data_blocks)
    for i in range(max_data_len):
        for b in data_blocks:
            if i < len(b):
                final_codewords.append(b[i])
    max_ec_len = max(len(b) for b in ec_blocks)
    for i in range(max_ec_len):
        for b in ec_blocks:
            if i < len(b):
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

    # Timing patterns
    for i in range(8, size - 8):
        if not reserved[6][i]:
            set_module(6, i, 1 if i % 2 == 0 else 0)
        if not reserved[i][6]:
            set_module(i, 6, 1 if i % 2 == 0 else 0)

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

    # Reserve version info areas (Version 7+)
    if version >= 7:
        v_bits = get_version_info(version)
        for i in range(18):
            mod = (v_bits >> i) & 1
            set_module(i // 3, i % 3 + size - 11, mod)
            set_module(i % 3 + size - 11, i // 3, mod)

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

    # Evaluate 8 mask patterns and pick the one with lowest penalty score
    best_matrix = None
    best_penalty = float('inf')

    for p in range(8):
        mat = [row[:] for row in grid]
        for r in range(size):
            for c in range(size):
                if not reserved[r][c]:
                    if get_mask_bit(p, r, c):
                        mat[r][c] ^= 1

        fmt_bits = get_format_info(p)

        # Vertical format info (top: rows 0..5, 7..8 -> bits 14..7; bottom: rows size-7..size-1 -> bits 6..0)
        for idx in range(15):
            mod = (fmt_bits >> (14 - idx)) & 1
            if idx < 6:
                mat[idx][8] = mod
            elif idx < 8:
                mat[idx + 1][8] = mod
            else:
                mat[size - 15 + idx][8] = mod

        # Horizontal format info (left: cols 0..5, 7..8 -> bits 14..7; right: cols size-7..size-1 -> bits 6..0)
        for idx in range(15):
            mod = (fmt_bits >> (14 - idx)) & 1
            if idx < 6:
                mat[8][idx] = mod
            elif idx == 6:
                mat[8][7] = mod
            elif idx == 7:
                mat[8][8] = mod
            else:
                mat[8][size - 15 + idx] = mod

        score = evaluate_penalty(mat, size)
        if score < best_penalty:
            best_penalty = score
            best_matrix = mat

    return best_matrix


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
