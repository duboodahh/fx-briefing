"""FX 브리핑 봇 프로필 이미지(SVG) 생성. 실행: python assets/make_avatar.py → assets/fx_briefing_avatar.svg"""
import math
import random
from pathlib import Path

S = 1024
CX, CY, R = 512, 600, 250            # 지구 중심·반지름
RING_RX, RING_RY, TILT = 420, 104, -11  # 링(타원) 반지름과 기울기(도)
# θ=45°·i (0=오른쪽 끝, 90°=앞 중앙). 앞 중앙(i=2)에 ₩가 오도록 배치
SYMBOLS = ["¥", "$", "₩", "€", "£", "$", "¥", "€"]

def rot(x, y, deg=TILT, cx=CX, cy=CY):
    a = math.radians(deg)
    dx, dy = x - cx, y - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)

def coin(i, theta):
    x0, y0 = CX + RING_RX * math.cos(theta), CY + RING_RY * math.sin(theta)
    x, y = rot(x0, y0)
    z = math.sin(theta)                       # 앞(+) / 뒤(-)
    sc = 0.78 + 0.32 * (z + 1) / 2
    r = 40 * sc
    op = 0.55 + 0.45 * (z + 1) / 2
    sym = SYMBOLS[i % len(SYMBOLS)]
    return z, f'''<g opacity="{op:.2f}">
  <circle cx="{x:.1f}" cy="{y+4*sc:.1f}" r="{r:.1f}" fill="#000" opacity=".25"/>
  <circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="url(#gold)" stroke="#667085" stroke-width="{2.2*sc:.1f}"/>
  <circle cx="{x:.1f}" cy="{y:.1f}" r="{r*0.78:.1f}" fill="none" stroke="#ffffff" stroke-opacity=".7" stroke-width="{1.6*sc:.1f}"/>
  <text x="{x:.1f}" y="{y+r*0.36:.1f}" text-anchor="middle" font-size="{r*1.05:.1f}" font-weight="800"
        font-family="'Arial Rounded MT Bold','Helvetica Neue','Apple SD Gothic Neo',Arial,sans-serif" fill="#394256">{sym}</text>
  <ellipse cx="{x - r*0.32:.1f}" cy="{y - r*0.5:.1f}" rx="{r*0.28:.1f}" ry="{r*0.14:.1f}" fill="#fff" opacity=".55" transform="rotate(-25 {x - r*0.32:.1f} {y - r*0.5:.1f})"/>
</g>'''

n = len(SYMBOLS)
coins = [coin(i, 2 * math.pi * i / n) for i in range(n)]
back = "\n".join(c for z, c in sorted(coins) if z < 0)
front = "\n".join(c for z, c in sorted(coins) if z >= 0)

random.seed(7)
stars = "\n".join(
    f'<circle cx="{random.uniform(0,S):.0f}" cy="{random.uniform(0,S):.0f}" r="{random.choice([1.2,1.6,2.2,2.8]):.1f}" fill="#fff" opacity="{random.uniform(.35,.95):.2f}"/>'
    for _ in range(90))
sparkles = "".join(
    f'<path d="M{x} {y-16} L{x+4} {y-4} L{x+16} {y} L{x+4} {y+4} L{x} {y+16} L{x-4} {y+4} L{x-16} {y} L{x-4} {y-4} Z" fill="#fff6c8" opacity=".9"/>'
    for x, y in [(170, 190), (860, 250), (120, 800), (900, 840), (780, 130)])

# 링의 타원 경로(뒤쪽 호 = 위쪽 반, 앞쪽 호 = 아래쪽 반)
def arc(sweep_back):
    x1, y1 = rot(CX - RING_RX, CY); x2, y2 = rot(CX + RING_RX, CY)
    flag = 1 if sweep_back else 0
    return f'M{x1:.1f} {y1:.1f} A{RING_RX} {RING_RY} {TILT} 0 {flag} {x2:.1f} {y2:.1f}'

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">
<defs>
  <radialGradient id="bg" cx="50%" cy="46%" r="75%"><stop offset="0" stop-color="#26397a"/><stop offset=".55" stop-color="#121c48"/><stop offset="1" stop-color="#050818"/></radialGradient>
  <radialGradient id="earth" cx="36%" cy="30%" r="80%"><stop offset="0" stop-color="#8fd8ff"/><stop offset=".35" stop-color="#2f86d6"/><stop offset=".75" stop-color="#14498f"/><stop offset="1" stop-color="#0a2554"/></radialGradient>
  <radialGradient id="shade" cx="32%" cy="26%" r="85%"><stop offset=".5" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#020a22" stop-opacity=".62"/></radialGradient>
  <radialGradient id="atmo" cx="50%" cy="50%" r="50%"><stop offset=".86" stop-color="#7fd0ff" stop-opacity="0"/><stop offset=".97" stop-color="#9fe0ff" stop-opacity=".55"/><stop offset="1" stop-color="#9fe0ff" stop-opacity="0"/></radialGradient>
  <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset=".45" stop-color="#cdd4e0"/><stop offset="1" stop-color="#8b95a8"/></linearGradient>
  <linearGradient id="ringg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#e9edf5"/><stop offset=".5" stop-color="#aab3c2"/><stop offset="1" stop-color="#eef1f7"/></linearGradient>
  <linearGradient id="orange" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffa57a"/><stop offset=".55" stop-color="#e8835a"/><stop offset="1" stop-color="#c9633e"/></linearGradient>
  <clipPath id="ec"><circle cx="{CX}" cy="{CY}" r="{R}"/></clipPath>
  <filter id="glow" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="7"/></filter>
  <filter id="soft"><feGaussianBlur stdDeviation="2.2"/></filter>
</defs>

<rect width="{S}" height="{S}" fill="url(#bg)"/>
{stars}
{sparkles}

<!-- 링 뒤쪽 -->
<path d="{arc(True)}" fill="none" stroke="#cfe6ff" stroke-width="20" opacity=".5" filter="url(#glow)"/>
<path d="{arc(True)}" fill="none" stroke="url(#ringg)" stroke-width="12" opacity=".75"/>
{back}

<!-- 지구 -->
<circle cx="{CX}" cy="{CY}" r="{R+26}" fill="#7fd0ff" opacity=".22" filter="url(#glow)"/>
<circle cx="{CX}" cy="{CY}" r="{R}" fill="url(#earth)"/>
<g clip-path="url(#ec)">
  <g fill="#43b36b" opacity=".95">
    <path d="M300 520 C340 470 420 470 450 510 C480 545 440 590 470 630 C490 670 440 720 400 700 C360 680 340 640 320 610 C300 585 280 560 300 520 Z"/>
    <path d="M560 470 C610 440 700 450 740 500 C770 540 730 570 700 560 C670 600 700 640 660 660 C620 680 590 630 600 590 C570 570 520 500 560 470 Z"/>
    <path d="M610 700 C650 690 700 710 690 750 C680 790 630 800 610 770 C595 745 590 715 610 700 Z"/>
    <path d="M380 770 C420 750 470 770 460 805 C450 835 400 840 380 815 C365 800 365 782 380 770 Z"/>
  </g>
  <g fill="#7fd68e" opacity=".55">
    <path d="M320 535 C350 500 410 500 430 525 C400 540 360 545 320 535 Z"/>
    <path d="M590 480 C630 462 690 470 715 500 C680 505 630 505 590 480 Z"/>
  </g>
  <g fill="#fff" opacity=".7" filter="url(#soft)">
    <ellipse cx="430" cy="430" rx="95" ry="22"/><ellipse cx="640" cy="640" rx="85" ry="18"/>
    <ellipse cx="360" cy="690" rx="70" ry="16"/><ellipse cx="700" cy="420" rx="70" ry="15"/>
  </g>
  <circle cx="{CX}" cy="{CY}" r="{R}" fill="url(#shade)"/>
  <ellipse cx="420" cy="440" rx="120" ry="70" fill="#fff" opacity=".13" transform="rotate(-30 420 440)" filter="url(#soft)"/>
</g>
<circle cx="{CX}" cy="{CY}" r="{R}" fill="url(#atmo)"/>

<!-- 마스코트: 지구 꼭대기에 '앉아 있는' 코딩 크리처 -->
<g transform="translate(512 382) rotate(-4) scale(1.34) translate(-512 -340)">
  <ellipse cx="512" cy="342" rx="108" ry="17" fill="#000" opacity=".32" filter="url(#soft)"/>
  <rect x="385" y="258" width="34" height="40" rx="9" fill="url(#orange)"/>
  <rect x="605" y="258" width="34" height="40" rx="9" fill="url(#orange)"/>
  <rect x="414" y="205" width="196" height="128" rx="22" fill="url(#orange)"/>
  <rect x="424" y="212" width="176" height="14" rx="7" fill="#fff" opacity=".28"/>
  <rect x="414" y="306" width="196" height="27" rx="13" fill="#9c4326" opacity=".2"/>
  <!-- 앞으로 내민 발 -->
  <rect x="420" y="311" width="58" height="32" rx="14" fill="#d26b46"/>
  <rect x="546" y="311" width="58" height="32" rx="14" fill="#d26b46"/>
  <rect x="428" y="316" width="42" height="7" rx="3.5" fill="#fff" opacity=".25"/>
  <rect x="554" y="316" width="42" height="7" rx="3.5" fill="#fff" opacity=".25"/>
  <rect x="456" y="243" width="26" height="46" rx="8" fill="#241210"/>
  <rect x="542" y="243" width="26" height="46" rx="8" fill="#241210"/>
  <circle cx="465" cy="255" r="5.5" fill="#fff"/><circle cx="551" cy="255" r="5.5" fill="#fff"/>
  <ellipse cx="438" cy="298" rx="14" ry="8" fill="#ff8f8f" opacity=".7"/><ellipse cx="586" cy="298" rx="14" ry="8" fill="#ff8f8f" opacity=".7"/>
</g>

<!-- 링 앞쪽 -->
<path d="{arc(False)}" fill="none" stroke="#cfe6ff" stroke-width="24" opacity=".55" filter="url(#glow)"/>
<path d="{arc(False)}" fill="none" stroke="url(#ringg)" stroke-width="15"/>
<path d="{arc(False)}" fill="none" stroke="#ffffff" stroke-width="3.5" opacity=".85" transform="translate(0 -2)"/>
{front}
</svg>'''

out = Path(__file__).parent / "fx_briefing_avatar.svg"
out.write_text(svg, encoding="utf-8")
print("saved", out)
