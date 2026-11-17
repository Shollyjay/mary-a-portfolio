"""Remove 'Lagos, Nigeria | ' from the resume's contact line and pull the
remaining text back to the left margin.

The PDF uses Identity-H subset fonts, so the text is not byte-searchable in the
content stream: each glyph is a separate Tj preceded by a Td. The glyphs are
decoded through each font's ToUnicode CMap, the run spelling the location is
dropped along with its positioning ops, and an absolute Tm re-anchors whatever
follows to the line's original left margin.
"""
import re, sys
from pikepdf import Pdf, parse_content_stream, unparse_content_stream, Operator, Array, Name, String

SRC, DST = sys.argv[1], sys.argv[2]
TARGET = 'Lagos, Nigeria | '
LEFT_MARGIN = 12.0

def tounicode(font):
    data = bytes(font.ToUnicode.read_bytes()).decode('latin-1'); m = {}
    for blk in re.findall(r'beginbfchar(.*?)endbfchar', data, re.S):
        for s, d in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            m[int(s, 16)] = ''.join(chr(int(d[i:i+4], 16)) for i in range(0, len(d), 4))
    for blk in re.findall(r'beginbfrange(.*?)endbfrange', data, re.S):
        for lo, hi, d in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            lo, hi, base = int(lo, 16), int(hi, 16), int(d, 16)
            for i in range(lo, hi + 1): m[i] = chr(base + i - lo)
    return m

IDENT = (1, 0, 0, 1, 0, 0)
def mul(a, b):
    a0,a1,a2,a3,a4,a5 = a; b0,b1,b2,b3,b4,b5 = b
    return (a0*b0+a1*b2, a0*b1+a1*b3, a2*b0+a3*b2, a2*b1+a3*b3,
            a4*b0+a5*b2+b4, a4*b1+a5*b3+b5)

pdf = Pdf.open(SRC)
changed = 0

for page in pdf.pages:
    if '/Font' not in page.Resources: continue
    fonts = {str(k): tounicode(page.Resources.Font[k]) for k in page.Resources.Font.keys()}
    ops = list(parse_content_stream(page))

    tm = tlm = IDENT; cur = None; glyphs = []
    for i, (operands, op) in enumerate(ops):
        o = str(op)
        if o == 'BT': tm = tlm = IDENT
        elif o == 'Tf': cur = str(operands[0])
        elif o == 'Tm': tm = tlm = tuple(float(x) for x in operands)
        elif o in ('Td', 'TD'):
            tm = tlm = mul((1, 0, 0, 1, float(operands[0]), float(operands[1])), tlm)
        elif o == 'Tj':
            b = bytes(operands[0]); mp = fonts.get(cur, {})
            txt = ''.join(mp.get(int.from_bytes(b[j:j+2], 'big'), '') for j in range(0, len(b), 2))
            glyphs.append((i, round(tm[5], 2), txt, tm))

    # group glyphs by baseline, find the line containing the target
    lines = {}
    for i, y, t, m in glyphs: lines.setdefault(y, []).append((i, t, m))
    for y, items in lines.items():
        text = ''.join(t for _, t, _m in items)
        if not text.startswith(TARGET): continue
        n = len(TARGET)
        first_tj = items[0][0]
        next_tj  = items[n][0]
        keep_m   = items[n][2]          # text matrix of the first surviving glyph
        drop_lo  = first_tj - 1          # the Td that positions the first glyph
        drop_hi  = next_tj - 1           # through the Td positioning the next survivor
        new_ops  = ops[:drop_lo]
        # reuse the original matrix's scale/rotation (a,b,c,d) — replacing it
        # with an identity would mirror the line — and move only the x origin.
        a, b, c, d, _e, f = keep_m
        new_ops.append(([a, b, c, d, LEFT_MARGIN, f], Operator('Tm')))
        new_ops += ops[drop_hi + 1:]
        page.Contents = pdf.make_stream(unparse_content_stream(new_ops))
        changed += 1
        break

pdf.save(DST)
print('lines rewritten:', changed)
