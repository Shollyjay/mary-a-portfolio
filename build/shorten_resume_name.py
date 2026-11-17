"""Shorten 'MARY ADEPOJU' to 'MARY A.' everywhere it appears in the resume.

The PDF uses Identity-H subset fonts, so the text is not byte-searchable: each
Tj carries one or more 2-byte glyph codes decoded through the font's ToUnicode
CMap. A run may straddle several Tj ops and a single Tj may hold part of the
run, so ops at the boundary are rewritten rather than dropped. The heading
subsets carry no full stop, so one is borrowed from another font on the page
and drawn at the same size.
"""
import re, sys
from pikepdf import (Pdf, parse_content_stream, unparse_content_stream,
                     Operator, String, Name)

SRC, DST = sys.argv[1], sys.argv[2]
FULL, KEEP = 'MARY ADEPOJU', 'MARY A'

def cmap(font):
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

def codes(operand):           # 2-byte glyph codes in a Tj string
    b = bytes(operand)
    return [int.from_bytes(b[j:j+2], 'big') for j in range(0, len(b), 2)]

def tj(cs):                   # glyph codes -> Tj operand
    return String(b''.join(c.to_bytes(2, 'big') for c in cs).decode('latin-1'))

pdf = Pdf.open(SRC)
total = 0

for page in pdf.pages:
    if '/Font' not in page.Resources: continue
    maps = {str(k): cmap(page.Resources.Font[k]) for k in page.Resources.Font.keys()}
    rev  = {f: {v: k for k, v in m.items()} for f, m in maps.items()}

    again = True
    while again:
        again = False
        ops = list(parse_content_stream(page))

        tm = tlm = IDENT; cur = None; size = 0.0; runs = []
        for i, (operands, op) in enumerate(ops):
            o = str(op)
            if o == 'BT': tm = tlm = IDENT
            elif o == 'Tf': cur, size = str(operands[0]), float(operands[1])
            elif o == 'Tm': tm = tlm = tuple(float(x) for x in operands)
            elif o in ('Td', 'TD'):
                tm = tlm = mul((1, 0, 0, 1, float(operands[0]), float(operands[1])), tlm)
            elif o == 'Tj':
                mp = maps.get(cur, {})
                cs = codes(operands[0])
                txt = ''.join(mp.get(c, '') for c in cs)
                runs.append((i, round(tm[5], 2), txt, cur, size, cs))

        lines = {}
        for r in runs: lines.setdefault(r[1], []).append(r)

        for y, items in lines.items():
            # map every character position back to (op index, glyph slot)
            text, owner = '', []
            for i, _y, t, f, sz, cs in items:
                for slot, ch in enumerate(t):
                    owner.append((i, slot, f, sz))
                text += t
            at = text.find(FULL)
            if at < 0: continue

            a_i, a_slot, font, sz = owner[at + len(KEEP) - 1]   # final 'A' of KEEP
            u_i, u_slot, _f, _s  = owner[at + len(FULL) - 1]    # final 'U'

            code, donor = rev.get(font, {}).get('.'), font
            if code is None:
                for cand, r in rev.items():
                    if '.' in r: code, donor = r['.'], cand; break
            if code is None: continue

            by_i = {r[0]: r for r in items}
            new = []
            for i, (operands, op) in enumerate(ops):
                if i == a_i:
                    cs = by_i[i][5]
                    new.append(([tj(cs[:a_slot + 1])], Operator('Tj')))   # keep through 'A'
                    if donor != font: new.append(([Name(donor), sz], Operator('Tf')))
                    new.append(([tj([code])], Operator('Tj')))            # the full stop
                    if donor != font: new.append(([Name(font), sz], Operator('Tf')))
                elif a_i < i < u_i:
                    if i in by_i: continue          # a Tj wholly inside the run
                    continue                        # and its positioning op
                elif i == u_i:
                    cs = by_i[i][5]
                    tail = cs[u_slot + 1:]
                    if tail: new.append(([tj(tail)], Operator('Tj')))
                else:
                    new.append((operands, op))

            page.Contents = pdf.make_stream(unparse_content_stream(new))
            total += 1; again = True
            break

pdf.save(DST)
print('occurrences shortened:', total)
