"""Convert usecase-system.mmd (usecase-beta) into a native draw.io file."""
import re
import sys
from xml.sax.saxutils import escape

src, out = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()

labels = dict(re.findall(r'^\s*(?:actor\s+)?(\w+)\("([^"]*)"\)', text, re.M))
boundary = re.search(r'systemBoundary\s+\w+\["([^"]*)"\]', text).group(1)
actors = re.findall(r'^actor\s+(\w+)\(', text, re.M)
assoc = re.findall(r'^(\w+)\s+--\s+(\w+)\s*$', text, re.M)
gen = re.findall(r'^(\w+)\s+--\|>\s+(\w+)\s*$', text, re.M)
dep = re.findall(r'^(\w+)\s+\.\.>:(include|extend)\s+(\w+)\s*$', text, re.M)

# ---- layout -------------------------------------------------------------
W, H, PITCH, TOP = 170, 56, 76, 120
COLS = {"A": 260, "B": 480, "C": 700, "D": 940}
layout = {
    "A": ["Register", "BrowseCategory", "SearchProduct", "ViewProduct", "ViewShop",
          "ViewReview", "ChatAI", "Profile", "ManageCart", "Address", "PlaceOrder",
          "TrackOrder", "CancelOrder", "Dispute", "WriteReview", "TopUp", "Withdraw",
          "WalletHistory", "ChatSeller"],
    "B": {0: "Login", 5: "AIAdvise", 6: "AICart", 7: "AIOrderPolicy",
          9: "ApplyVoucher", 11: "PayOrder"},
    "C": {10: "PayWallet", 11: "PayQR", 12: "PayCOD"},
    "D": ["ManageShop", "ManageProduct", "ManageInventory", "ShopCategory",
          "ProcessOrder", "ShopVoucher", "SalesStats", "ShopPayout", "InvoiceRequest",
          "ReplyChat", "ManageUser", "ModerateProduct", "PlatformCategory",
          "ManageAllOrders", "ResolveDispute", "PlatformVoucher", "ApproveInvoice",
          "Settlement"],
}
pos = {}
for col, items in layout.items():
    pairs = enumerate(items) if isinstance(items, list) else items.items()
    for row, uc in pairs:
        pos[uc] = (COLS[col], TOP + row * PITCH)

usecases = [k for k in labels if k not in actors]
missing = [u for u in usecases if u not in pos]
assert not missing, f"no layout slot for: {missing}"

rows = 19
bx, by = 220, 40
bw = COLS["D"] + W + 40 - bx
bh = TOP + (rows - 1) * PITCH + H + 40 - by
AW, AH = 36, 72


def row_y(r):
    return TOP + r * PITCH + H / 2 - AH / 2


actor_pos = {
    "Guest": (80, row_y(3)),
    "Buyer": (80, row_y(12)),
    "Seller": (bx + bw + 120, row_y(4.5)),
    "Admin": (bx + bw + 120, row_y(13.5)),
    "Scheduler": (bx + bw + 120, row_y(17.5)),
    "SePay": (560, by + bh + 70),
    "Carrier": (860, by + bh + 70),
}

# ---- styles -------------------------------------------------------------
FONT = "fontFamily=Helvetica;fontColor=#222222;"
ACTOR = ("shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;"
         "outlineConnect=0;fontSize=13;" + FONT)
ACTOR_FILL = {
    "Admin": "fillColor=#E8C9C2;strokeColor=#A0574A;",
    "SePay": "fillColor=#EEEEEE;strokeColor=#555555;",
    "Carrier": "fillColor=#EEEEEE;strokeColor=#555555;",
    "Scheduler": "fillColor=#EEEEEE;strokeColor=#555555;",
}
UC = ("ellipse;whiteSpace=wrap;html=1;fillColor=#FCF3CF;strokeColor=#B8A060;"
      "fontSize=12;" + FONT)
BOUNDARY = ("rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#222222;"
            "verticalAlign=top;spacingTop=8;fontSize=16;" + FONT)
ASSOC = "endArrow=none;html=1;strokeColor=#333333;rounded=0;"
GEN = "endArrow=block;endFill=0;endSize=14;html=1;strokeColor=#333333;rounded=0;"
DEP = ("endArrow=open;endFill=0;endSize=10;dashed=1;html=1;strokeColor=#555555;"
       "rounded=0;fontSize=10;labelBackgroundColor=#FFFFFF;" + FONT)

cells = []


def vertex(cid, value, style, x, y, w, h):
    cells.append(
        f'<mxCell id="{cid}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" '
        f'vertex="1" parent="1"><mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w}" '
        f'height="{h}" as="geometry"/></mxCell>')


def edge(cid, s, t, style, value=""):
    cells.append(
        f'<mxCell id="{cid}" value="{escape(value)}" style="{style}" edge="1" parent="1" '
        f'source="{s}" target="{t}"><mxGeometry relative="1" as="geometry"/></mxCell>')


vertex("boundary", boundary, BOUNDARY, bx, by, bw, bh)
for a in actors:
    x, y = actor_pos[a]
    vertex(a, labels[a], ACTOR + ACTOR_FILL.get(a, "fillColor=#FFFFFF;strokeColor=#222222;"),
           x, y, AW, AH)
for u in usecases:
    x, y = pos[u]
    vertex(u, labels[u], UC, x, y, W, H)

n = 0
for s, t in assoc:
    n += 1
    edge(f"e{n}", s, t, ASSOC)
for s, t in gen:
    n += 1
    edge(f"e{n}", s, t, GEN)
for s, kind, t in dep:
    n += 1
    edge(f"e{n}", s, t, DEP, f"«{kind}»")

xml = (
    '<mxfile host="app.diagrams.net">'
    '<diagram id="usecase-system" name="System Use Case">'
    '<mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" '
    'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1600" '
    'pageHeight="2000" math="0" shadow="0"><root><mxCell id="0"/>'
    '<mxCell id="1" parent="0"/>' + "".join(cells) +
    "</root></mxGraphModel></diagram></mxfile>"
)
open(out, "w", encoding="utf-8").write(xml)
print(f"actors={len(actors)} usecases={len(usecases)} assoc={len(assoc)} "
      f"gen={len(gen)} dep={len(dep)}")
