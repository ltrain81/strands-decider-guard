"""Generate docs/images/architecture.drawio (draw.io AWS4 shapes). Edit the layout here or in draw.io, then render:
   python3 architecture.py architecture.drawio && drawio -x -f png -s 2 -b 10 -o architecture.png architecture.drawio
"""
import sys
from xml.sax.saxutils import escape

cells, n = [], [1]
def nid():
    n[0] += 1
    return f"c{n[0]}"

BASE_ICON = ("sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;strokeColor=#ffffff;dashed=0;"
             "verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=12;fontStyle=0;aspect=fixed;")
LABEL_TOP = "verticalLabelPosition=top;verticalAlign=bottom;"
LABEL_RIGHT = "labelPosition=right;verticalLabelPosition=middle;align=left;verticalAlign=middle;spacingLeft=6;"
def service(label, res, color, x, y, size=56, label_at=""):
    i = nid()
    st = BASE_ICON + f"fillColor={color};shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};"
    st = st.replace("verticalLabelPosition=bottom;verticalAlign=top;align=center;", "verticalLabelPosition=bottom;verticalAlign=top;align=center;" + label_at)
    cells.append((i, label, st, x, y, size, size, "1"))
    return i
def shape(label, shp, color, x, y, w=48, h=48, parent="1", top=False):
    i = nid()
    pos = "verticalLabelPosition=top;verticalAlign=bottom;" if top else "verticalLabelPosition=bottom;verticalAlign=top;"
    st = (f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;strokeColor=none;dashed=0;{pos}"
          f"align=center;html=1;fontSize=12;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.{shp};fillColor={color};")
    cells.append((i, label, st, x, y, w, h, parent))
    return i
def group(label, gr, stroke, font, x, y, w, h, fill="none", dashed=0, extra=""):
    i = nid()
    st = ("points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=1;container=0;pointerEvents=0;"
          f"collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr};strokeColor={stroke};fillColor={fill};"
          f"verticalAlign=top;align=left;spacingLeft=30;fontColor={font};dashed={dashed};{extra}")
    cells.append((i, label, st, x, y, w, h, "1"))
    return i
def box(label, x, y, w, h, fill="#FFFFFF", stroke="#232F3E", extra=""):
    i = nid()
    st = f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};fontColor=#232F3E;fontSize=12;arcSize=8;{extra}"
    cells.append((i, label, st, x, y, w, h, "1"))
    return i
edges = []
def edge(src, dst, label="", color="#232F3E", dashed=0, pts=None, exit=None, entry=None, width=2):
    st = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;strokeWidth={width};strokeColor={color};"
          f"fontSize=11;fontColor={color};labelBackgroundColor=#FFFFFF;dashed={dashed};")
    if exit: st += f"exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;"
    if entry: st += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    edges.append((nid(), label, st, src, dst, pts or []))

DEV, ADM, NET = "#232F3E", "#8C4FFF", "#7D8998"
box("<b style='font-size:18px'>strands-decider-guard</b><br>PII and secrets are checked before they reach the model",
    20, 0, 560, 46, fill="none", stroke="none", extra="align=left;verticalAlign=middle;")
inet = shape("", "internet_alt2", NET, 604, 0, 40, 30)
box("<b>Internet</b> · PyPI, GitHub, Hugging Face, SSM", 650, 0, 320, 30, fill="none", stroke="none",
    extra="align=left;verticalAlign=middle;fontColor=#5A6C86;")

# ---- developer side
group("Developer machine", "group_corporate_data_center", "#7D8998", "#5A6C86", 20, 90, 330, 400)
cc = shape("Claude Code", "client", "#232F3D", 60, 165, top=True)
cx = shape("Codex CLI", "client", "#232F3D", 160, 165, top=True)
kr = shape("Kiro CLI<br><i>(opt-in, tool calls)</i>", "client", "#7D8998", 260, 165, top=True)
hook = box("<b>PII guard hook</b><br>client/decider_guard.py<br><font color='#5A6C86'>prompts · Read/Write/Edit · Bash<br>+ files a command reads · Bash output</font>",
           45, 255, 280, 86, fill="#F4F6F8", stroke="#7D8998")
box("with AWS, one mode per machine: ① IAM or ①′ sign-in<br><font color='#5A6C86'>(local mode, not shown: no AWS)</font><br><b>allow</b> → continue &nbsp; <b>ask</b> → user confirms<br><b>block</b> → masked reasons + who decided", 45, 380, 280, 84,
    fill="#FFFFFF", stroke="#D5DBDB", extra="fontSize=11;")
for a_ in (cc, cx, kr):
    edge(a_, hook, "", color=DEV, width=1.5)
box("", 20, 520, 330, 120, fill="#FFFFFF", stroke="#7D8998", extra="dashed=1;")
ll = shape("<b>LiteLLM proxy</b> (optional)<br>calls the guard with its IAM role,<br>logged with the LiteLLM key's user", "traditional_server", "#7D8998", 161, 535, 36, 48)
admin = shape("Policy admin<br>(browser)", "user", "#232F3D", 161, 870)

# ---- AWS
group("AWS Cloud", "group_aws_cloud_alt", "#232F3E", "#232F3E", 400, 60, 1340, 940)
group("Region", "group_region", "#00A4A6", "#147EBA", 420, 95, 1305, 890, dashed=1)
group("VPC", "group_vpc2", "#8C4FFF", "#8C4FFF", 445, 130, 790, 470)
group("Public subnet", "group_security_group", "#7AA116", "#248814", 465, 170, 200, 230, fill="#F2F6E8", extra="grStroke=0;")
group("Isolated subnet", "group_security_group", "#00A4A6", "#147EBA", 685, 170, 250, 230, fill="#E6F6F7", extra="grStroke=0;")
group("Private subnet", "group_security_group", "#00A4A6", "#147EBA", 955, 170, 260, 230, fill="#E6F6F7", extra="grStroke=0;")
nat = shape("NAT Gateway", "nat_gateway", "#8C4FFF", 600, 200, 48, 48)
guard = service("<b>Guard Lambda</b><br>regex + policy", "lambda", "#ED7100", 786, 266, size=64, label_at=LABEL_TOP)
ec2 = service("<b>EC2 g6.xlarge</b> (NVIDIA L4)<br>strands-decider 2B :8000<br><font color='#5A6C86'>no public IP</font>", "ec2", "#ED7100", 1057, 270)
gwe = shape("S3 gateway<br>endpoint", "endpoints", "#8C4FFF", 794, 474)

logs = service("<b>CloudWatch</b><br>decision log, metrics, alarms", "cloudwatch_2", "#E7157B", 1290, 175)
sns = service("<b>SNS</b><br>alert emails", "sns", "#E7157B", 1500, 175)
bedrock = service("<b>Amazon Bedrock</b><br>models", "bedrock", "#01A88D", 1620, 175)
s3 = box("<b>Amazon S3</b>", 1270, 340, 215, 230, fill="#F2F6E8", stroke="#7AA116",
         extra="verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;")
policy = service("<b>Policy bucket</b><br>versioned", "s3", "#7AA116", 1290, 380, label_at=LABEL_RIGHT)
evid = service("<b>Evidence bucket</b><br>opt-in, 30-day expiry", "s3", "#7AA116", 1290, 480, label_at=LABEL_RIGHT)

group("Policy console", "group_security_group", "#7D8998", "#5A6C86", 445, 760, 1260, 200, extra="grStroke=0;")
cf = service("<b>CloudFront</b><br>console (S3 site)", "cloudfront", "#8C4FFF", 500, 830)
cog = service("<b>Cognito</b><br>admin sign-in", "cognito", "#DD344C", 720, 830)
api = service("<b>API Gateway</b> (HTTP API, JWT authorizers)<br>/guard/check: hooks, developer pool<br>/api/*: console, admin pool", "api_gateway", "#E7157B", 600, 630, label_at=LABEL_RIGHT)
adm = service("<b>Admin Lambda</b><br>policy · tests · stats · alerts", "lambda", "#ED7100", 1160, 830)
eb = service("<b>EventBridge</b><br>health check (5 min)<br>host schedule (optional)", "eventbridge", "#E7157B", 1420, 830)

# ---- flows
edge(hook, guard, "① IAM mode: lambda:Invoke", color=DEV, exit=(1, 0.5), entry=(0, 0.5))
edge(ll, guard, "", color=DEV, dashed=1, exit=(1, 0.5), entry=(0, 0.75), pts=[(420, 559), (420, 314)])
edge(guard, ec2, "② one model call (private IP)", color=DEV, exit=(1, 0.5), entry=(0, 0.5))
edge(guard, gwe, "③ policy, evidence", color=DEV, exit=(0.5, 1), entry=(0.5, 0))
edge(gwe, s3, "", color=DEV, exit=(1, 0.5), entry=(0, 0.687))
edge(guard, logs, "④ decision log (no text)", color=DEV, exit=(0.75, 1), entry=(0, 0.5), pts=[(834, 440), (1250, 440), (1250, 203)])
edge(cc, bedrock, "⑤ only what passed goes to the model", color="#01A88D", exit=(0, 0.5), entry=(0.5, 0), pts=[(34, 189), (34, 52), (1648, 52)])
edge(ec2, nat, "first boot: packages, model · SSM", color=NET, dashed=1, exit=(0.5, 0), entry=(1, 0.5), pts=[(1085, 150), (680, 150), (680, 224)])
edge(nat, inet, "", color=NET, dashed=1, exit=(0.5, 0), entry=(0.5, 1))
edge(logs, sns, "alarms", color=ADM, dashed=1, exit=(1, 0.5), entry=(0, 0.5))
edge(admin, cf, "Ⓐ open console", color=ADM, exit=(1, 0.5), entry=(0, 0.5))
edge(cf, cog, "sign in", color=ADM, dashed=1)
edge(cog, api, "ID token", color=ADM, dashed=1, exit=(0.5, 0), entry=(0.714, 1), pts=[(748, 720), (640, 720)])
edge(api, adm, "", color=ADM, exit=(0.3, 1), entry=(0.25, 0), pts=[(617, 700), (1174, 700)])
edge(adm, s3, "Ⓑ save policy version · view original (audited)", color=ADM, exit=(0.75, 0), entry=(0.5, 1), pts=[(1202, 640), (1377, 640)])
edge(eb, adm, "", color=ADM, dashed=1, exit=(0, 0.5), entry=(1, 0.5))
edge(hook, api, "①′ sign-in mode", color=DEV, exit=(1, 0.8), entry=(0, 0.5), pts=[(375, 325), (375, 658)])
edge(api, guard, "user from token", color=DEV, exit=(0.5, 0), entry=(0, 0.92), pts=[(628, 325)])

out = ['<mxfile host="drawio"><diagram name="architecture" id="arch"><mxGraphModel dx="1600" dy="900" grid="1" gridSize="10" guides="1" '
       'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1760" pageHeight="1110" background="#FFFFFF" math="0" shadow="0">'
       '<root><mxCell id="0"/><mxCell id="1" parent="0"/>']
for i, label, st, x, y, w, h, parent in cells:
    out.append(f'<mxCell id="{i}" value="{escape(label, {chr(34): "&quot;"})}" style="{st}" vertex="1" parent="{parent}">'
               f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
for i, label, st, s, d, pts in edges:
    pts_xml = "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in pts)
    out.append(f'<mxCell id="{i}" value="{escape(label)}" style="{st}" edge="1" parent="1" source="{s}" target="{d}">'
               f'<mxGeometry relative="1" as="geometry">{"<Array as=\"points\">" + pts_xml + "</Array>" if pts else ""}</mxGeometry></mxCell>')
out.append("</root></mxGraphModel></diagram></mxfile>")
open(sys.argv[1], "w").write("\n".join(out))
