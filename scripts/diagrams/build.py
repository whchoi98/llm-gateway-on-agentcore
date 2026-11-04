"""Builds docs/architecture.html (Korean) and docs/architecture.en.html (English) in the
aws-diagram-design AWS skin: architecture, request flow, fallback sequence, deploy order.
Run scripts/diagrams/export.sh, which also exports the SVG/PNG files and verifies them."""
import os
import pathlib
import re
import shutil

def _installed_skill() -> pathlib.Path:
    """Highest installed my-plugins version (numeric order: 1.10.0 > 1.9.0)."""
    root = pathlib.Path.home() / ".claude/plugins/cache/my-plugins/my-plugins"
    found = [p for p in root.glob("*/skills/aws-diagram-design") if p.is_dir()]
    if not found:
        raise SystemExit(f"aws-diagram-design not found under {root}; set AWS_DIAGRAM_SKILL")
    return max(found, key=lambda p: tuple(int(n) if n.isdigit() else -1 for n in p.parts[-3].split(".")))


SKILL = pathlib.Path(os.environ["AWS_DIAGRAM_SKILL"]) if os.environ.get("AWS_DIAGRAM_SKILL") else _installed_skill()
ICONS = SKILL / "assets/aws-icons"
OUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "docs"

INK, MUTED, SOFT, ACCENT, LINK = "#232F3E", "#545B64", "#7D8998", "#EC7211", "#0972D3"
SANS_EN = "'Amazon Ember', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO_EN = "'Amazon Ember Mono', ui-monospace, monospace"
# Amazon Ember has no Hangul: the Korean variant names CJK faces right after Ember.
SANS_KO = "'Amazon Ember', 'Noto Sans CJK KR', 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Helvetica Neue', Arial, sans-serif"
MONO_KO = "'Amazon Ember Mono', 'D2Coding', 'Noto Sans Mono CJK KR', ui-monospace, monospace"
SANS, MONO = SANS_EN, MONO_EN
LANG = "en"


def set_lang(lang):
    global SANS, MONO, LANG
    LANG = lang
    SANS, MONO = (SANS_KO, MONO_KO) if lang == "ko" else (SANS_EN, MONO_EN)


def T(en, ko):
    return ko if LANG == "ko" else en


LABEL_PX = 10  # arrow labels: 8px was unreadable once the PNG is scaled down in the README
NAME_PX, SUB_PX = 13, 11  # node title and sublabel (were 12 / 9)
OVERFLOW = []


def sub_w(s, px=SUB_PX):
    """Rendered width of mono sublabel text: Amazon Ember Mono measures ~0.63em per Latin
    glyph in Chromium; Hangul falls back to a CJK face at ~1em."""
    return sum(px if ord(c) >= 0x1100 else px * 0.64 for c in s)


def text_w(s, ascii_px=7, wide_px=11):
    """Approximate width of LABEL_PX mono text (0.6em + tracking); Hangul is about 1.6x a Latin glyph."""
    return sum(wide_px if ord(c) >= 0x1100 else ascii_px for c in s)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def icon(rel: str, x: int, y: int, size: int = 24) -> str:
    """Inline an official AWS icon unmodified (ids/clip refs stripped, geometry untouched)."""
    raw = (ICONS / rel).read_text()
    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', raw)
    scale = size / int(vb.group(1))
    raw = re.sub(r"<\?xml[^>]*\?>", "", raw)
    raw = re.sub(r"<title>.*?</title>", "", raw, flags=re.S)
    raw = re.sub(r"<defs>.*?</defs>", "", raw, flags=re.S)
    inner = re.sub(r"^\s*<svg[^>]*>", "", raw.strip(), flags=re.S)
    inner = re.sub(r"</svg>\s*$", "", inner)
    inner = re.sub(r'\s(id|clip-path)="[^"]*"', "", inner)
    inner = re.sub(r">\s+<", "><", inner).strip()
    return f'<g transform="translate({x},{y}) scale({scale:g})" aria-hidden="true">{inner}</g>'


I_USERS = "resource/General-Icons/Res_Users_48_Light.svg"
I_COGNITO = "service/Security-Identity/Arch_Amazon-Cognito_48.svg"
I_AGENTCORE = "service/Artificial-Intelligence/Arch_Amazon-Bedrock-AgentCore_48.svg"
I_BEDROCK = "service/Artificial-Intelligence/Arch_Amazon-Bedrock_48.svg"
I_LAMBDA = "service/Compute/Arch_AWS-Lambda_48.svg"
I_CLOUDWATCH = "service/Management-Tools/Arch_Amazon-CloudWatch_48.svg"
I_SECRETS = "service/Security-Identity/Arch_AWS-Secrets-Manager_48.svg"
I_CFN = "service/Management-Tools/Arch_AWS-CloudFormation_48.svg"
G_REGION = "group/Region_32.svg"
G_ACCOUNT = "group/AWS-Account_32.svg"

KINDS = {
    "backend": ("#ffffff", INK, "1"),
    "gateway": ("#ffffff", INK, "1.4"),
    "external": ("rgba(35,47,62,0.03)", "rgba(35,47,62,0.30)", "1"),
    "input": ("rgba(84,91,100,0.10)", SOFT, "1"),
    "focal": ("rgba(255,153,0,0.10)", ACCENT, "1.2"),
}


def node(x, y, w, h, name, subs=(), ic=None, kind="backend", rx=6, chips=(), step=None):
    fill, stroke, sw = KINDS[kind]
    tx = x + 48 if ic else x + 16
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="#ffffff"/>',
           f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>']
    if ic:
        out.append(icon(ic, x + 12, y + 16))  # on the title row (as in the Lambda node), never box-centered
    out.append(f'<text x="{tx}" y="{y + 28}" fill="{INK}" font-size="{NAME_PX}" font-weight="600" font-family="{SANS}">{esc(name)}</text>')
    for i, s in enumerate(subs):
        out.append(f'<text x="{tx}" y="{y + 46 + 16 * i}" fill="{MUTED}" font-size="{SUB_PX}" font-family="{MONO}">{esc(s)}</text>')
        room = x + w - 12 - tx  # keep a 12px inner margin on the right
        if sub_w(s) > room:
            OVERFLOW.append(f"{name!r}: {s!r} needs {sub_w(s):.0f}px, has {room}px")
    for cx, cy, cw, label, red in chips:
        cs = "rgba(221,52,76,0.60)" if red else "rgba(35,47,62,0.25)"
        cf = "rgba(221,52,76,0.05)" if red else "#ffffff"
        dash = ' stroke-dasharray="4,4"' if red else ""
        tc = "#B0263B" if red else MUTED
        out.append(f'<rect x="{cx}" y="{cy}" width="{cw}" height="20" rx="2" fill="{cf}" stroke="{cs}" stroke-width="0.8"{dash}/>')
        out.append(f'<text x="{cx + cw // 2}" y="{cy + 14}" fill="{tc}" font-size="9" font-family="{MONO}" text-anchor="middle" letter-spacing="0.04em">{esc(label)}</text>')
    if step is not None:
        out.append(f'<circle cx="{x}" cy="{y}" r="10" fill="{INK}"/>')
        out.append(f'<text x="{x}" y="{y + 4}" fill="#ffffff" font-size="10" font-weight="700" font-family="{MONO}" text-anchor="middle">{step}</text>')
    return "\n".join(out)


def zone(x, y, w, h, badge, label, color, dashed):
    dash = ' stroke-dasharray="4,4"' if dashed else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{color}" stroke-width="1"{dash}/>\n'
            f'{icon(badge, x, y, 24)}\n'
            f'<text x="{x + 32}" y="{y + 16}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}">{esc(label)}</text>')


def path(d, color=MUTED, marker="arrow", dashed=False, width="1.2"):
    dash = ' stroke-dasharray="5,4"' if dashed else ""
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash} marker-end="url(#{marker})"/>'


def label(cx, cy, text, w=None, anchor="middle", color="#545B64"):
    """Mask plate + text. (cx, cy) = text baseline; plate spans cy-11..cy+3, so a label
    placed 12px above its connector keeps a 9px gap."""
    w = w or (text_w(text) + 8)
    w += (-w) % 4
    x0 = cx - w // 2 if anchor == "middle" else cx - 4
    return (f'<rect x="{x0}" y="{cy - 11}" width="{w}" height="14" rx="2" fill="#ffffff"/>\n'
            f'<text x="{cx}" y="{cy}" fill="{color}" font-size="{LABEL_PX}" font-family="{MONO}" text-anchor="{anchor}" letter-spacing="0.04em">{esc(text)}</text>')


def markers(prefix):
    return "\n".join(
        f'<marker id="{prefix}-{name}" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{c}"/></marker>'
        for name, c in (("arrow", MUTED), ("accent", ACCENT), ("link", LINK), ("ink", INK)))


def legend(y, width, items, prefix):
    out = [f'<line x1="24" y1="{y - 8}" x2="{width - 24}" y2="{y - 8}" stroke="rgba(35,47,62,0.10)" stroke-width="0.8"/>',
           f'<text x="24" y="{y + 12}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.14em">{T("LEGEND", "범례")}</text>']
    x = 104
    for kind, text, color, dashed in items:
        if kind == "line":
            dash = ' stroke-dasharray="5,4"' if dashed else ""
            out.append(f'<line x1="{x}" y1="{y + 8}" x2="{x + 32}" y2="{y + 8}" stroke="{color}" stroke-width="1.2"{dash}/>')
        elif kind == "frame":
            out.append(f'<rect x="{x}" y="{y}" width="32" height="16" rx="2" fill="rgba(35,47,62,0.02)" stroke="rgba(35,47,62,0.22)" stroke-width="1"/>')
        else:
            out.append(f'<rect x="{x}" y="{y}" width="32" height="16" rx="2" fill="rgba(221,52,76,0.05)" stroke="rgba(221,52,76,0.60)" stroke-width="0.8" stroke-dasharray="4,4"/>')
        out.append(f'<text x="{x + 40}" y="{y + 12}" fill="{MUTED}" font-size="10" font-family="{MONO}">{esc(text)}</text>')
        x += 48 + text_w(text) + 32
    return "\n".join(out)


# ---------------------------------------------------------------- diagram 1
def architecture():
    P = f"arch-{LANG}"
    W, H = 1280, 768
    zones = [
        zone(200, 56, 744, 640, G_REGION, T("AWS Account, ap-northeast-2 (Seoul)", "AWS 계정, ap-northeast-2 (서울)"), "#00A4A6", True),
        zone(976, 360, 280, 136, G_ACCOUNT, T("AWS Account, Claude Platform on AWS", "AWS 계정, Claude Platform on AWS"), "#E7157B", False),
        zone(976, 560, 280, 136, G_REGION, T("us-east-1 (N. Virginia)", "us-east-1 (버지니아 북부)"), "#00A4A6", True),
    ]
    arrows = [
        path("M 104,276 V 140 Q 104,132 112,132 H 232", LINK, f"{P}-link"),
        label(116, 212, T("TOKEN", "토큰"), anchor="start"),
        path("M 184,324 H 232", LINK, f"{P}-link"),
        label(208, 312, "JWT"),
        path("M 352,248 V 160", MUTED, f"{P}-arrow", dashed=True, width="1"),
        label(364, 208, "JWKS", anchor="start"),
        path("M 352,392 V 448", MUTED, f"{P}-arrow"),
        label(364, 424, T("REQUEST", "요청 전처리"), anchor="start"),
        path("M 232,376 H 224 Q 216,376 216,384 V 604 Q 216,612 224,612 H 232", MUTED, f"{P}-arrow", dashed=True, width="1"),
        path("M 472,288 H 664", INK, f"{P}-ink", width="1.4"),
        label(616, 276, T("PRIMARY", "기본 경로")),
        path("M 472,320 H 560 Q 568,320 568,328 V 432 Q 568,440 576,440 H 664", ACCENT, f"{P}-accent"),
        label(620, 428, "CLAUDE / 1P"),
        path("M 904,440 H 992", ACCENT, f"{P}-accent"),
        label(948, 428, "+WORKSPACE"),
        path("M 472,352 H 544 Q 552,352 552,360 V 632 Q 552,640 560,640 H 992", ACCENT, f"{P}-accent"),
        label(780, 628, "GPT / MANTLE"),
    ]
    nodes = [
        node(24, 276, 160, 96, T("Clients", "클라이언트"), ["Anthropic SDK", "OpenAI SDK", "Bedrock SDK"], I_USERS, kind="input"),
        node(232, 104, 240, 56, "Amazon Cognito", ["M2M client_credentials"], I_COGNITO),
        node(232, 248, 240, 144, "AgentCore Gateway", ["llm-gateway /inference"], I_AGENTCORE, kind="gateway",
             chips=[(244, 316, 104, T("JWT AUTH", "JWT 인증"), False), (356, 316, 104, T("RATE LIMITS", "요청 한도"), False),
                    (244, 348, 104, T("RULES+FALLBACK", "라우팅, FALLBACK"), False), (356, 348, 104, T("CEDAR POLICY", "Cedar 정책"), False)]),
        node(232, 448, 240, 80, "Interceptor Lambda",
             [T("Guardrail, claude-auto", "가드레일, claude-auto"), T("dialect, premium, EMF", "dialect, premium 검사, EMF")], I_LAMBDA),
        node(232, 584, 240, 56, "CloudWatch / X-Ray", [T("routing logs, alarms", "라우팅 로그, 알람")], I_CLOUDWATCH),
        node(664, 248, 240, 80, "Amazon Bedrock", ["Global CRIS, global.*", "Claude 5.5, GPT 6.x"], I_BEDROCK),
        node(664, 400, 240, 80, T("CPonAWS proxy", "CPonAWS 프록시"),
             ["Lambda Function URL (IAM)", T("workspace (SSM), key (SM)", "workspace(SSM), 키(SM)")], I_LAMBDA),
        node(992, 400, 240, 80, "Claude Platform on AWS", ["aws-external-anthropic", "claude-*-5-5 (1P)"], kind="external"),
        node(992, 600, 240, 80, "Bedrock Mantle", ["bedrock-mantle /openai/v1", T("openai.gpt-6* (in-Region)", "openai.gpt-6* (리전 내)")], I_BEDROCK),
    ]
    leg = legend(728, W, [
        ("line", T("PRIMARY / GLOBAL CRIS", "기본 경로 / GLOBAL CRIS"), INK, False),
        ("line", T("FALLBACK", "FALLBACK 경로"), ACCENT, False),
        ("line", T("HTTPS API CALL", "HTTPS API 호출"), LINK, False),
        ("line", T("AUTH CHECK / TELEMETRY", "인증 확인 / 텔레메트리"), MUTED, True),
    ], P)
    title = T("AgentCore LLM Gateway architecture", "AgentCore LLM Gateway 아키텍처")
    desc = T("Clients get a Cognito token and call one AgentCore Gateway in Seoul, which sends Claude and GPT traffic to Bedrock Global CRIS first and falls back to Claude Platform on AWS for Claude or to Bedrock Mantle in us-east-1 for GPT.",
             "클라이언트는 Cognito 토큰으로 서울의 AgentCore Gateway 하나를 호출하고, Gateway는 Claude와 GPT 요청을 Bedrock Global CRIS로 먼저 보낸 뒤 실패하면 Claude는 Claude Platform on AWS로, GPT는 us-east-1 Bedrock Mantle로 넘깁니다.")
    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{P}-title {P}-desc">
<title id="{P}-title">{esc(title)}</title>
<desc id="{P}-desc">{esc(desc)}</desc>
<defs>{markers(P)}</defs>
<rect width="100%" height="100%" fill="#ffffff"/>
{chr(10).join(zones)}
{chr(10).join(arrows)}
{chr(10).join(nodes)}
{leg}
</svg>'''


# ---------------------------------------------------------------- diagram 2
def flow():
    P = f"flow-{LANG}"
    W, H = 1280, 680
    TOP = 72  # crop the empty band above row 1 (step badges start at y=102)
    D = (808, 320)  # decision diamond center
    arrows = [
        path("M 24,160 H 136", LINK, f"{P}-link"),
        label(68, 148, T("REQUEST", "요청")),
        path("M 376,160 H 416", INK, f"{P}-ink"),
        path("M 656,160 H 696", INK, f"{P}-ink"),
        path("M 936,160 H 976", INK, f"{P}-ink"),
        path("M 1096,208 V 280", INK, f"{P}-ink"),
        label(1108, 248, T("ALLOWED", "허용"), anchor="start"),
        path(f"M 976,320 H {D[0] + 72}", INK, f"{P}-ink"),
        label(928, 308, T("RESULT", "결과")),
        path(f"M {D[0] - 72},320 H 264 Q 256,320 256,328 V 440", MUTED, f"{P}-arrow"),
        label(496, 308, T("NO / RETURN", "아니오 / 반환")),
        path(f"M {D[0]},{D[1] + 48} V 400", ACCENT, f"{P}-accent", width="1.2"),
        label(820, 388, T("YES", "예"), anchor="start"),
        path("M 800,404 H 704 Q 696,404 696,412 V 440", ACCENT, f"{P}-accent"),
        label(748, 392, "CLAUDE"),
        path("M 816,404 H 960 Q 968,404 968,412 V 440", ACCENT, f"{P}-accent"),
        label(888, 392, "GPT"),
        path("M 576,480 H 376", MUTED, f"{P}-arrow"),
        path("M 968,520 V 544 Q 968,552 960,552 H 264 Q 256,552 256,544 V 520", MUTED, f"{P}-arrow"),
    ]
    dx, dy = D
    diamond = (f'<polygon points="{dx - 72},{dy} {dx},{dy - 48} {dx + 72},{dy} {dx},{dy + 48}" fill="#ffffff"/>\n'
               f'<polygon points="{dx - 72},{dy} {dx},{dy - 48} {dx + 72},{dy} {dx},{dy + 48}" fill="rgba(255,153,0,0.10)" stroke="{ACCENT}" stroke-width="1.2"/>\n'
               f'<text x="{dx}" y="{dy - 4}" fill="{INK}" font-size="{NAME_PX}" font-weight="600" font-family="{SANS}" text-anchor="middle">Fallback</text>\n'
               f'<text x="{dx}" y="{dy + 12}" fill="{INK}" font-size="{NAME_PX}" font-weight="600" font-family="{SANS}" text-anchor="middle">{T("eligible?", "대상인가?")}</text>\n'
               f'<circle cx="{dx - 72}" cy="{dy - 40}" r="10" fill="{INK}"/>'
               f'<text x="{dx - 72}" y="{dy - 36}" fill="#ffffff" font-size="10" font-weight="700" font-family="{MONO}" text-anchor="middle">6</text>\n'
               f'<circle cx="{dx}" cy="404" r="4" fill="{ACCENT}"/>')
    nodes = [
        node(136, 112, 240, 96, T("Inbound auth, rate limits", "인바운드 인증, 요청 한도"),
             ["Cognito JWT, scope invoke", T("per-team, per-model", "팀별, 모델별")], I_COGNITO,
             chips=[(288, 180, 80, "401 / 429", True)], step=1),
        node(416, 112, 240, 96, T("Rule match", "라우팅 Rule 매칭"),
             [T("model as sent → route", "보낸 model 그대로 매칭"), T("primary + fallback chosen", "primary, fallback 결정")], I_AGENTCORE, step=2),
        node(696, 112, 240, 96, "Interceptor Lambda",
             [T("guardrail, claude-auto", "가드레일, claude-auto"), "dialect, premium (Invoke)"], I_LAMBDA,
             chips=[(848, 180, 80, "400 / 403", True)], step=3),
        node(976, 112, 240, 96, T("Cedar policy", "Cedar 정책"),
             ["invoke scope, premium", T("max output tokens", "최대 출력 토큰")], I_AGENTCORE,
             chips=[(1128, 180, 80, "403", True)], step=4),
        node(976, 280, 240, 80, "Amazon Bedrock", [T("Global CRIS, Seoul", "Global CRIS, 서울"), "global.anthropic|openai.*"], I_BEDROCK, step=5),
        node(576, 440, 240, 80, "Claude Platform on AWS", [T("via proxy λ, +workspace", "proxy λ 경유, +workspace"), "claude-*-5-5 (1P)"], kind="external"),
        node(848, 440, 240, 80, "Bedrock Mantle", ["us-east-1 /openai/v1", "openai.gpt-6*"], I_BEDROCK),
        node(136, 440, 240, 80, T("Response", "응답"), [T("SSE stream or JSON", "SSE 스트림 또는 JSON"), T("id or model shows who served", "id, model로 응답 주체 확인")], kind="input", rx=20),
    ]
    note_text = T("FALLBACK ON: 429, 5XX, 408, 403, FIRST_BYTE_TIMEOUT, CONNECTION_ERROR, UNROUTABLE.   NOT ON 400, AND NOT ONCE A STREAM HAS STARTED.",
                  "FALLBACK 조건: 429, 5XX, 408, 403, FIRST_BYTE_TIMEOUT, CONNECTION_ERROR, UNROUTABLE.   400은 제외하며, 스트림이 시작된 뒤에는 FALLBACK하지 않습니다.")
    note = f'<text x="24" y="600" fill="{MUTED}" font-size="10" font-family="{MONO}">{esc(note_text)}</text>'
    leg = legend(640, W, [
        ("line", T("PIPELINE", "처리 단계"), INK, False),
        ("line", T("FALLBACK PATH", "FALLBACK 경로"), ACCENT, False),
        ("line", T("RESPONSE", "응답"), MUTED, False),
        ("chip", T("REJECTED WITH STATUS", "거부 (상태 코드)"), None, False),
    ], P)
    title = T("LLM Gateway request flow", "LLM Gateway 요청 흐름")
    desc = T("A request passes authentication and rate limits, rule matching, the interceptor and Cedar policy, then goes to Bedrock Global CRIS; eligible failures fall back to Claude Platform on AWS for Claude or Bedrock Mantle for GPT before the response returns.",
             "요청은 인증과 요청 한도, rule 매칭, interceptor, Cedar 정책을 거쳐 Bedrock Global CRIS로 가고, fallback 대상 오류이면 Claude는 Claude Platform on AWS로, GPT는 Bedrock Mantle로 넘어간 뒤 응답이 반환됩니다.")
    return f'''<svg viewBox="0 {TOP} {W} {H - TOP}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{P}-title {P}-desc">
<title id="{P}-title">{esc(title)}</title>
<desc id="{P}-desc">{esc(desc)}</desc>
<defs>{markers(P)}</defs>
<rect y="{TOP}" width="100%" height="100%" fill="#ffffff"/>
{chr(10).join(arrows)}
{chr(10).join(nodes)}
{diamond}
{note}
{leg}
</svg>'''


# ---------------------------------------------------------------- diagram 3
def lifeline(cx, y1, y2):
    return f'<line x1="{cx}" y1="{y1}" x2="{cx}" y2="{y2}" stroke="rgba(35,47,62,0.20)" stroke-width="1" stroke-dasharray="3,3"/>'


def activation(cx, y1, y2):
    return f'<rect x="{cx - 4}" y="{y1}" width="8" height="{y2 - y1}" fill="rgba(35,47,62,0.06)" stroke="{MUTED}" stroke-width="0.8"/>'


def sequence():
    """Fallback over time: one Claude request, the ALT fragment shows the breaker closed vs open."""
    P = f"seq-{LANG}"
    W, H = 1280, 712
    C, G, B, F = 160, 480, 800, 1120  # lifeline centers
    FX, FY, FW, FH, DIV = 344, 232, 816, 240, 400  # ALT frame and its region divider
    lines = [lifeline(x, 104, 584) for x in (C, G, B, F)]
    frame = [
        f'<rect x="{FX}" y="{FY}" width="{FW}" height="{FH}" rx="4" fill="rgba(35,47,62,0.02)" stroke="rgba(35,47,62,0.22)" stroke-width="1"/>',
        f'<rect x="{FX}" y="{FY}" width="40" height="16" rx="2" fill="#ffffff" stroke="rgba(35,47,62,0.22)" stroke-width="1"/>',
        f'<text x="{FX + 20}" y="{FY + 12}" fill="{MUTED}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.12em">ALT</text>',
        f'<text x="{FX + 12}" y="264" fill="{MUTED}" font-size="10" font-family="{MONO}">{esc(T("[breaker closed]", "[회로 차단기 닫힘]"))}</text>',
        f'<line x1="{FX + 8}" y1="{DIV}" x2="{FX + FW - 8}" y2="{DIV}" stroke="rgba(35,47,62,0.20)" stroke-width="1" stroke-dasharray="4,3"/>',
        f'<text x="{FX + 12}" y="424" fill="{MUTED}" font-size="10" font-family="{MONO}">{esc(T("[breaker open]", "[회로 차단기 열림]"))}</text>',
    ]
    bars = [activation(C, 144, 560), activation(G, 148, 556), activation(B, 284, 332), activation(F, 364, 516)]
    msgs = [
        path(f"M {C + 4},152 H {G - 4}", LINK, f"{P}-link"),
        label(320, 140, "POST /inference  claude-sonnet-5-5", color=LINK),
        path(f"M {G + 4},184 H 512 Q 520,184 520,192 V 200 Q 520,208 512,208 H {G + 4}", MUTED, f"{P}-arrow"),
        label(528, 200, T("match rule: primary, then fallback", "rule 매칭: primary 다음 fallback"), anchor="start"),
        path(f"M {G + 4},288 H {B - 4}", LINK, f"{P}-link"),
        label(640, 276, "global.anthropic.claude-sonnet-5-5", color=LINK),
        path(f"M {B - 4},328 H {G + 4}", MUTED, f"{P}-arrow", dashed=True),
        label(640, 316, T("429, 5XX, 408, 403 or first-byte timeout", "429, 5XX, 408, 403 또는 첫 바이트 timeout")),  # must fit between the bars (484..796)
        path(f"M {G + 4},368 H {F - 4}", ACCENT, f"{P}-accent", width="1.4"),
        label(960, 356, T("fall back: claude-sonnet-5-5 on cponaws", "fallback: cponaws의 claude-sonnet-5-5"), color="#B35400"),
        path(f"M {G + 4},448 H {F - 4}", ACCENT, f"{P}-accent", width="1.4"),
        label(960, 436, T("primary skipped, straight to fallback", "primary를 건너뛰고 바로 fallback"), color="#B35400"),
        path(f"M {F - 4},512 H {G + 4}", MUTED, f"{P}-arrow", dashed=True),
        label(960, 500, T("200, response starts", "200, 응답 시작")),
        path(f"M {G - 4},552 H {C + 4}", MUTED, f"{P}-arrow", dashed=True),
        label(320, 540, T("200: one request, one response", "200: 요청 하나에 응답 하나")),
    ]
    actors = [
        node(40, 32, 240, 72, T("Client", "클라이언트"), [T("Anthropic or OpenAI SDK", "Anthropic, OpenAI SDK"), T("Bearer: Cognito JWT", "Bearer: Cognito JWT")], I_USERS, kind="input"),
        node(360, 32, 240, 72, "AgentCore Gateway", [T("rule: primary + fallback", "rule: primary + fallback"), T("breaker per destination", "destination별 회로 차단기")], I_AGENTCORE, kind="gateway"),
        node(680, 32, 240, 72, "Amazon Bedrock", [T("primary, Global CRIS", "primary, Global CRIS"), "global.anthropic.*"], I_BEDROCK),
        node(1000, 32, 240, 72, T("Fallback destination", "Fallback 대상"), [T("Claude: CPonAWS (1P)", "Claude: CPonAWS (1P)"), T("GPT: Mantle us-east-1", "GPT: Mantle us-east-1")], kind="external"),
    ]
    notes = [
        T("NOT ON 400: the error returns to the caller unchanged.   NOT AFTER THE FIRST BYTE: once a stream has started, the caller gets a partial response and an error, and retries.",
          "400은 fallback하지 않음: 오류를 그대로 호출자에게 돌려줍니다.   첫 바이트 이후에는 fallback하지 않음: 스트림이 시작되면 호출자는 부분 응답과 오류를 받고 재시도합니다."),
        T("BILLING: each attempt is one gateway invocation, so an open breaker also saves the failed attempt.   GPT takes the same path, with Bedrock Mantle as the fallback.",
          "과금: 시도 한 번이 gateway 호출 한 번이므로, 회로 차단기가 열리면 실패할 시도 비용도 줄어듭니다.   GPT도 같은 순서로 동작하며 fallback 대상은 Bedrock Mantle입니다."),
    ]
    note = "\n".join(f'<text x="24" y="{612 + 18 * i}" fill="{MUTED}" font-size="10" font-family="{MONO}">{esc(t)}</text>' for i, t in enumerate(notes))
    leg = legend(680, W, [
        ("line", T("CALL", "호출"), LINK, False),
        ("line", T("RETURN", "응답"), MUTED, True),
        ("line", T("FALLBACK CALL", "FALLBACK 호출"), ACCENT, False),
        ("frame", T("ALT: ONE OF TWO CASES", "ALT: 두 경우 중 하나"), None, False),
    ], P)
    title = T("Fallback over time", "시간 순서로 본 fallback")
    desc = T("A Claude request reaches the gateway, which tries Bedrock Global CRIS first. With the circuit breaker closed, a 429, 5XX, 408, 403 or a first-byte timeout sends the same request to the fallback destination; with the breaker open, the gateway skips the primary. The caller gets one response.",
             "Claude 요청이 Gateway에 오면 Bedrock Global CRIS를 먼저 시도합니다. 회로 차단기가 닫혀 있으면 429, 5XX, 408, 403 또는 첫 바이트 timeout 때 같은 요청을 fallback 대상으로 보내고, 열려 있으면 primary를 건너뜁니다. 호출자는 응답 하나를 받습니다.")
    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{P}-title {P}-desc">
<title id="{P}-title">{esc(title)}</title>
<desc id="{P}-desc">{esc(desc)}</desc>
<defs>{markers(P)}</defs>
<rect width="100%" height="100%" fill="#ffffff"/>
{chr(10).join(lines)}
{chr(10).join(frame)}
{chr(10).join(bars)}
{chr(10).join(msgs)}
{chr(10).join(actors)}
{note}
{leg}
</svg>'''


# ---------------------------------------------------------------- diagram 4
def deploy():
    """Deploy order: the CPonAWS key must exist and work before the core stack creates its targets."""
    P = f"dep-{LANG}"
    W, H = 1280, 448
    D = (96, 176)  # decision diamond center
    dx, dy = D
    arrows = [
        path(f"M {dx + 72},{dy} H 200", INK, f"{P}-ink"),
        label(184, 164, T("YES", "예")),
        path("M 448,176 H 464", INK, f"{P}-ink"),
        path("M 712,176 H 728", INK, f"{P}-ink"),
        path("M 976,176 H 992", INK, f"{P}-ink"),
        path("M 588,128 V 104 Q 588,96 580,96 H 332 Q 324,96 324,104 V 128", MUTED, f"{P}-arrow", dashed=True),
        label(456, 84, T("BAD KEY: TARGET FAILS, STACK ROLLS BACK", "키 오류: TARGET 생성 실패, 스택 ROLLBACK")),
        path(f"M {dx},{dy + 48} V 288", MUTED, f"{P}-arrow"),
        label(108, 260, T("NO", "아니오"), anchor="start"),
        path("M 352,328 H 1108 Q 1116,328 1116,320 V 224", MUTED, f"{P}-arrow"),
        label(736, 316, T("BOTH STACKS, NO CPONAWS TARGET", "두 스택 배포, CPONAWS TARGET 제외")),
    ]
    diamond = (f'<polygon points="{dx - 72},{dy} {dx},{dy - 48} {dx + 72},{dy} {dx},{dy + 48}" fill="#ffffff"/>\n'
               f'<polygon points="{dx - 72},{dy} {dx},{dy - 48} {dx + 72},{dy} {dx},{dy + 48}" fill="rgba(255,153,0,0.10)" stroke="{ACCENT}" stroke-width="1.2"/>\n'
               f'<text x="{dx}" y="{dy - 4}" fill="{INK}" font-size="{NAME_PX}" font-weight="600" font-family="{SANS}" text-anchor="middle">{T("CPonAWS key", "CPonAWS 키가")}</text>\n'
               f'<text x="{dx}" y="{dy + 12}" fill="{INK}" font-size="{NAME_PX}" font-weight="600" font-family="{SANS}" text-anchor="middle">{T("ready?", "있나요?")}</text>')
    nodes = [
        node(200, 128, 248, 96, T("Store key, workspace ID", "1P 키, workspace 저장"),
             ["scripts/set-cponaws-key.sh", T("checks GET /v1/models", "GET /v1/models로 먼저 검증"), "→ Secrets Manager, SSM"], I_SECRETS, step=1),
        node(464, 128, 248, 96, T("Deploy the core stack", "Core 스택 배포"),
             ["LlmGatewayStack", T("each target lists models", "target 생성 시 모델 조회"), T("on create: key must work", "→ 키가 미리 유효해야 함")], I_CFN, step=2),
        node(728, 128, 248, 96, T("Deploy the policy stack", "정책 스택 배포"),
             ["LlmGatewayPolicyStack", T("Cedar permit, forbid rules", "Cedar permit, forbid 정책"), T("reads core stack exports", "Core 스택 export 참조")], I_CFN, step=3),
        node(992, 128, 248, 96, T("Smoke test", "스모크 테스트"),
             ["uv run scripts/smoke_test.py", T("routing, failover drills", "라우팅, failover drill"), T("routing evidence from logs", "로그로 라우팅 근거 확인")], kind="input", step=4),
        node(24, 288, 328, 80, T("Deploy without 1P", "1P 없이 배포"),
             ["cdk deploy --all -c enable1p=false", T("Claude has no fallback until step 1", "1단계 전까지 Claude fallback 없음")], I_CFN),
    ]
    note_text = T("WHY THE KEY LIVES OUTSIDE THE STACKS: a stack-owned secret would be deleted on rollback, and the rollback is exactly what a bad key causes.",
                  "키를 스택 밖에 두는 이유: 스택이 소유한 secret은 rollback 때 삭제되는데, 키가 잘못되면 바로 그 rollback이 일어납니다.")
    note = f'<text x="24" y="400" fill="{MUTED}" font-size="10" font-family="{MONO}">{esc(note_text)}</text>'
    leg = legend(424, W, [
        ("line", T("DEPLOY ORDER", "배포 순서"), INK, False),
        ("line", T("WITHOUT 1P", "1P 없이"), MUTED, False),
        ("line", T("ON FAILURE", "실패 시"), MUTED, True),
    ], P)
    title = T("Deploy order", "배포 순서")
    desc = T("Store and verify the CPonAWS key and workspace ID first, then deploy the core stack, whose targets check the key when they are created, then the Cedar policy stack, then run the smoke test. Without a key, deploy both stacks with enable1p=false.",
             "CPonAWS 키와 workspace ID를 먼저 검증해 저장하고, target 생성 때 키를 확인하는 Core 스택, Cedar 정책 스택 순서로 배포한 뒤 스모크 테스트를 실행합니다. 키가 없으면 enable1p=false로 두 스택을 배포합니다.")
    return f'''<svg viewBox="0 48 {W} {H - 48}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{P}-title {P}-desc">
<title id="{P}-title">{esc(title)}</title>
<desc id="{P}-desc">{esc(desc)}</desc>
<defs>{markers(P)}</defs>
<rect y="48" width="100%" height="100%" fill="#ffffff"/>
{chr(10).join(arrows)}
{chr(10).join(nodes)}
{diamond}
{note}
{leg}
</svg>'''


FONT_FILES = ["AmazonEmber_W_Rg.woff2", "AmazonEmber_W_RgIt.woff2", "AmazonEmber_W_SBd.woff2",
              "AmazonEmber_W_Bd.woff2", "AmazonEmberMono_W_Rg.woff2", "AmazonEmberMono_W_Bd.woff2"]

COPY = {
    "en": dict(
        lang="en", other="architecture.html", other_label="한국어",
        title="AgentCore LLM Gateway — Architecture",
        eyebrow="Architecture / Amazon Bedrock AgentCore Gateway",
        h1="AgentCore LLM Gateway — architecture and request flow",
        subtitle="One gateway in Seoul sends Claude 5.5 and GPT 6.x requests to Bedrock Global CRIS first. On failure, Claude falls back to Claude Platform on AWS (1P) and GPT to Bedrock Mantle in us-east-1. Source: <code>lib/</code> (CDK), <code>lambda/</code>.",
        h2a="1. Architecture",
        capa="Zones: Seoul account and Region (gateway, 3P primary, 1P proxy); CPonAWS account (Claude fallback); us-east-1 (GPT fallback). Clients hold only a Cognito JWT; every backend credential stays on the gateway side.",
        h2b="2. Request flow",
        capb="Order: rate limits → rules (documented); rules → interceptor (verified on this deployment); interceptor → Cedar policy (AWS documentation). Red chips are the HTTP status returned when a step rejects the request.",
        h2c="3. Fallback over time",
        capc="Timeouts per model come from lib/config.ts (Sonnet 120 s shown). The breaker is per destination and enabled on every production route; the failover drills disable it so they never trip production routes.",
        h2d="4. Deploy order",
        capd="npx cdk deploy --all runs steps 2 and 3 in order; review npx cdk diff --all first. To add the Claude fallback later, run step 1 and deploy again.",
        cards=[("Claude 5.5", "accent", "Bedrock → Claude Platform on AWS",
                ["API: Anthropic Messages, Bedrock InvokeModel (premium scope)", "Primary <code>global.anthropic.claude-*-5-5</code>",
                 "Fallback <code>cponaws</code> (the proxy λ adds the workspace header)", "Tell: an <code>id</code> starting with <code>msg_bdrk_</code> is 3P"]),
               ("GPT 6.x", "accent", "Bedrock → Mantle us-east-1",
                ["API: Chat Completions, Responses", "Primary <code>global.openai.gpt-6*</code>",
                 "Fallback <code>mantle</code> (data leaves for the US during a fallback)", "Tell: <code>model</code> = <code>openai.*</code> means fallback"]),
               ("Operations", "ink", "What to check",
                ["Drill: <code>*-failover-drill</code>", "Alarm <code>FallbackActive</code>", "Logs <code>body.routing.reason</code>", "Checks <code>scripts/smoke_test.py</code>"])],
    ),
    "ko": dict(
        lang="ko", other="architecture.en.html", other_label="English",
        title="AgentCore LLM Gateway — 아키텍처",
        eyebrow="Architecture / Amazon Bedrock AgentCore Gateway",
        h1="AgentCore LLM Gateway — 아키텍처와 요청 흐름",
        subtitle="서울 리전의 단일 Gateway가 Claude 5.5와 GPT 6.x 요청을 모두 Bedrock Global CRIS로 먼저 보냅니다. 실패하면 Claude는 Claude Platform on AWS(1P)로, GPT는 Bedrock Mantle us-east-1로 넘어갑니다. 소스: <code>lib/</code> (CDK), <code>lambda/</code>.",
        h2a="① 아키텍처",
        capa="구역: 서울 계정과 리전 (Gateway, 3P primary, 1P proxy), CPonAWS 계정 (Claude fallback), us-east-1 (GPT fallback). 클라이언트는 Cognito JWT만 갖고, 백엔드 자격증명은 모두 Gateway 쪽에 있습니다.",
        h2b="② 요청 흐름",
        capb="처리 순서: rate limit → rule (문서 기준), rule → interceptor (배포 환경에서 검증), interceptor → Cedar policy (AWS 문서 기준). 빨간 칩은 그 단계에서 거부될 때의 HTTP 상태 코드입니다.",
        h2c="③ 시간 순서로 본 Fallback",
        capc="모델별 timeout은 lib/config.ts에 있습니다(그림은 Sonnet 120초). 회로 차단기는 destination마다 따로 동작하며 모든 운영 route에서 켜져 있고, failover drill은 운영 route를 건드리지 않도록 이를 끕니다.",
        h2d="④ 배포 순서",
        capd="npx cdk deploy --all이 2, 3단계를 순서대로 실행합니다. 배포 전에 npx cdk diff --all로 변경 사항을 확인하세요. Claude fallback을 나중에 추가하려면 1단계를 실행한 뒤 다시 배포합니다.",
        cards=[("Claude 5.5", "accent", "Bedrock → Claude Platform on AWS",
                ["API: Anthropic Messages, Bedrock InvokeModel(premium scope)", "Primary <code>global.anthropic.claude-*-5-5</code>",
                 "Fallback <code>cponaws</code> (proxy λ가 workspace 헤더 추가)", "판별: <code>id</code>가 <code>msg_bdrk_</code>이면 3P"]),
               ("GPT 6.x", "accent", "Bedrock → Mantle us-east-1",
                ["API: Chat Completions, Responses", "Primary <code>global.openai.gpt-6*</code>",
                 "Fallback <code>mantle</code> (fallback 중에는 데이터가 미국으로 감)", "판별: <code>model</code>이 <code>openai.*</code>이면 fallback"]),
               ("Operations", "ink", "점검 포인트",
                ["Drill: <code>*-failover-drill</code>", "알람 <code>FallbackActive</code>", "로그 <code>body.routing.reason</code>", "검증 <code>scripts/smoke_test.py</code>"])],
    ),
}

FONT_FACES = """@font-face { font-family: 'Amazon Ember'; font-weight: 400; font-style: normal; src: local('Amazon Ember'), url('fonts/AmazonEmber_W_Rg.woff2') format('woff2'); }
@font-face { font-family: 'Amazon Ember'; font-weight: 400; font-style: italic; src: local('Amazon Ember Italic'), local('Amazon Ember'), url('fonts/AmazonEmber_W_RgIt.woff2') format('woff2'); }
@font-face { font-family: 'Amazon Ember'; font-weight: 600; font-style: normal; src: local('Amazon Ember Medium'), local('Amazon Ember'), url('fonts/AmazonEmber_W_SBd.woff2') format('woff2'); }
@font-face { font-family: 'Amazon Ember'; font-weight: 700; font-style: normal; src: local('Amazon Ember Bold'), local('Amazon Ember'), url('fonts/AmazonEmber_W_Bd.woff2') format('woff2'); }
@font-face { font-family: 'Amazon Ember Mono'; font-weight: 400; font-style: normal; src: local('Amazon Ember Mono'), url('fonts/AmazonEmberMono_W_Rg.woff2') format('woff2'); }
@font-face { font-family: 'Amazon Ember Mono'; font-weight: 700; font-style: normal; src: local('Amazon Ember Mono Bold'), local('Amazon Ember Mono'), url('fonts/AmazonEmberMono_W_Bd.woff2') format('woff2'); }"""


def page(lang):
    set_lang(lang)
    c = COPY[lang]
    cards = "\n".join(
        f'  <div class="card"><p class="eyebrow">{eb}</p><h3><span class="dot {dot}"></span>{h}</h3>\n'
        f'    <ul>{"".join(f"<li>{li}</li>" for li in items)}</ul></div>'
        for eb, dot, h, items in c["cards"])
    return f"""<!DOCTYPE html>
<html lang="{c['lang']}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{c['title']}</title>
<style>
{FONT_FACES}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{ --paper: #ffffff; --ink: #232F3E; --muted: #545B64; --soft: #7D8998; --rule: rgba(35,47,62,0.12); --accent: #EC7211; --link: #0972D3;
  --sans: {SANS}; --mono: {MONO}; }}
body {{ font-family: var(--sans); background: var(--paper); color: var(--ink); padding: 3rem 2rem; }}
.frame {{ max-width: 1280px; margin: 0 auto; }}
.eyebrow {{ font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.18em; text-transform: uppercase; color: var(--muted); margin-bottom: 0.5rem; }}
.lang {{ float: right; font-family: var(--mono); font-size: 0.75rem; color: var(--link); }}
h1 {{ font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.15; margin-bottom: 0.5rem; }}
.subtitle {{ color: var(--muted); margin-bottom: 2.5rem; max-width: 60rem; line-height: 1.5; }}
h2 {{ font-size: 1.125rem; font-weight: 700; margin: 2.5rem 0 1rem; }}
figure {{ overflow-x: auto; }}
svg {{ width: 100%; min-width: 960px; display: block; }}
figcaption {{ font-family: var(--mono); font-size: 0.7rem; color: var(--soft); margin-top: 0.5rem; }}
.cards {{ display: grid; grid-template-columns: 1.1fr 1fr 0.9fr; gap: 1rem; margin-top: 2.5rem; }}
.card {{ border: 1px solid var(--rule); border-radius: 6px; padding: 1.25rem; }}
.card .eyebrow {{ margin-bottom: 0.25rem; }}
.card h3 {{ font-size: 1rem; font-weight: 700; margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.5rem; }}
.dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
.dot.ink {{ background: var(--ink); }} .dot.accent {{ background: var(--accent); }}
.card ul {{ list-style: none; font-size: 0.875rem; line-height: 1.6; }}
.card li {{ padding-left: 0.9rem; position: relative; }}
.card li::before {{ content: '–'; position: absolute; left: 0; color: var(--soft); }}
code {{ font-family: var(--mono); font-size: 0.8em; }}
footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--rule); font-family: var(--mono); font-size: 0.7rem; color: var(--soft); }}
@media (max-width: 900px) {{ .cards {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="frame">
<a class="lang" href="{c['other']}">{c['other_label']}</a>
<p class="eyebrow">{c['eyebrow']}</p>
<h1>{c['h1']}</h1>
<p class="subtitle">{c['subtitle']}</p>

<h2>{c['h2a']}</h2>
<figure>
{architecture()}
<figcaption>{c['capa']}</figcaption>
</figure>

<h2>{c['h2b']}</h2>
<figure>
{flow()}
<figcaption>{c['capb']}</figcaption>
</figure>

<h2>{c['h2c']}</h2>
<figure>
{sequence()}
<figcaption>{c['capc']}</figcaption>
</figure>

<h2>{c['h2d']}</h2>
<figure>
{deploy()}
<figcaption>{c['capd']}</figcaption>
</figure>

<div class="cards">
{cards}
</div>

<footer>Generated with aws-diagram-design. AWS Architecture Icons © Amazon Web Services, Inc. Source of truth: lib/config.ts</footer>
</div>
</body>
</html>
"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fonts = OUT_DIR / "fonts"
    fonts.mkdir(exist_ok=True)
    for f in FONT_FILES:
        shutil.copy(SKILL / "assets/fonts/woff2" / f, fonts / f)
    for lang, name in (("ko", "architecture.html"), ("en", "architecture.en.html")):
        html = page(lang)
        (OUT_DIR / name).write_text(html)
        print("wrote", OUT_DIR / name, len(html), "bytes")
    if OVERFLOW:
        raise SystemExit("SUBLABEL OVERFLOW (shorten the text or widen the box):\n  " + "\n  ".join(dict.fromkeys(OVERFLOW)))


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--print-skill"]:
        print(SKILL)  # used by export.sh to find the skill's checkers
    else:
        main()
