import sys
PAPER="#f5f5f5"; INK="#2d3142"; MUTED="#4f5d75"; SOFT="#5a6580"; ACC="#bf4520"; LINK="#2e5aa8"
SANS="'Geist', 'Be Vietnam Pro', system-ui, sans-serif"; MONO="'Geist Mono', ui-monospace, monospace"; SERIF="'Instrument Serif', 'Noto Serif', serif"
o=[]
def zone(x,y,w,h,label,sub=False,lx=None):
    dash=' stroke-dasharray="4,3"' if sub else ''
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="rgba(45,49,66,{0.03 if sub else 0.02})" stroke="rgba(45,49,66,{0.18 if sub else 0.10})" stroke-width="0.8"{dash}/>')
    lw=int(len(label)*5.4+12); lx = x+12 if lx is None else lx
    o.append(f'<rect x="{lx}" y="{y+4}" width="{lw}" height="13" rx="2" fill="{PAPER}"/>')
    o.append(f'<text x="{lx+lw/2}" y="{y+13.5}" fill="{SOFT}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.1em">{label}</text>')
T={'focal':("rgba(191,69,32,0.08)",ACC),'backend':("#ffffff",INK),'store':("rgba(45,49,66,0.05)",MUTED),'input':("rgba(79,93,117,0.10)",SOFT)}
def node(x,y,w,h,kind,name,sub=None,tag=None):
    f,s=T[kind]; cx=x+w/2; cy=y+h/2
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>')
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{f}" stroke="{s}" stroke-width="1"/>')
    if tag:
        tw=len(tag)*5+10
        o.append(f'<rect x="{x+8}" y="{y+6}" width="{tw}" height="12" rx="2" fill="none" stroke="{s}" stroke-opacity="0.4" stroke-width="0.8"/>')
        o.append(f'<text x="{x+8+tw/2}" y="{y+15}" fill="{s}" fill-opacity="0.85" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.08em">{tag}</text>')
    if sub:
        ny, sy = (cy-1, cy+12) if h<=40 else (cy+2, cy+16)
        o.append(f'<text x="{cx}" y="{ny}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{name}</text>')
        o.append(f'<text x="{cx}" y="{sy}" fill="{MUTED}" font-size="9" font-family="{MONO}" text-anchor="middle">{sub}</text>')
    else:
        o.append(f'<text x="{cx}" y="{cy+4}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{name}</text>')
def arrow(d,kind="muted",dash=False):
    c={'muted':MUTED,'accent':ACC,'link':LINK}[kind]; m={'muted':'arrow','accent':'arrow-accent','link':'arrow-link'}[kind]
    ds=' stroke-dasharray="4,3"' if dash else ''
    sw=1 if dash else (1.4 if kind=='accent' else 1.2)
    o.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{sw}"{ds} marker-end="url(#{m})"/>')
def label(x,y,text,anchor="start"):
    w=int(len(text)*5.4+10)
    rx = x if anchor=="start" else x-w/2
    o.append(f'<rect x="{rx}" y="{y}" width="{w}" height="12" rx="2" fill="{PAPER}"/>')
    o.append(f'<text x="{rx+w/2}" y="{y+8.5}" fill="{SOFT}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{text}</text>')

# zones
zone(16,24,1168,96,"LỚP GIAO DIỆN NGƯỜI DÙNG")
zone(16,144,1168,96,"LỚP GIAO TIẾP API")
zone(16,264,1168,200,"LỚP ĐIỀU PHỐI AI · LANGGRAPH")
zone(16,488,840,240,"LỚP TRUY XUẤT · AGENTIC RAG",lx=144)
zone(872,488,312,240,"LỚP NGHIỆP VỤ · MICROSERVICES",lx=1000)
zone(40,512,376,176,"HYBRID RETRIEVAL",sub=True,lx=160)

# arrows (drawn before nodes)
arrow("M 200,80 H 280")
arrow("M 380,104 V 176"); label(388,134,"TIN NHẮN")
arrow("M 480,200 H 600"); label(540,180,"CHUYỂN TIẾP","middle")
arrow("M 700,224 V 296")
arrow("M 800,320 H 880",dash=True)
arrow("M 650,344 V 364 Q 650,372 642,372 H 232 Q 224,372 224,380 V 400")
arrow("M 700,344 V 400")
arrow("M 750,344 V 364 Q 750,372 758,372 H 1012 Q 1020,372 1020,380 V 400")
label(296,352,"TƯ VẤN SẢN PHẨM")
label(858,352,"GIỎ HÀNG · ĐƠN")
label(708,378,"CHÍNH SÁCH")
arrow("M 188,448 V 464 Q 188,472 180,472 H 142 Q 134,472 134,480 V 544")
arrow("M 260,448 V 464 Q 260,472 268,472 H 306 Q 314,472 314,480 V 544")
arrow("M 134,584 V 596 Q 134,604 142,604 H 192 Q 200,604 200,612 V 624")
arrow("M 314,584 V 596 Q 314,604 306,604 H 256 Q 248,604 248,612 V 624")
arrow("M 294,644 H 440")
arrow("M 520,624 V 432 Q 520,424 512,424 H 324",dash=True); label(528,540,"TOP-K")
arrow("M 700,448 V 544"); label(708,512,"TRA CỨU")
arrow("M 960,448 V 528","accent"); label(968,470,"GỌI CÔNG CỤ")

# nodes
node(40,56,160,48,'input',"Người mua",tag="USER")
node(280,56,200,48,'backend',"React Frontend","Chatbot Interface",tag="UI")
node(280,176,200,48,'backend',"API Gateway","Backend API",tag="API")
node(600,176,200,48,'backend',"AI Chatbot Service","FastAPI",tag="SVC")
node(600,296,200,48,'focal',"Router / Supervisor","phân loại ý định",tag="LLM")
node(880,296,200,48,'store',"Conversation State","checkpoint",tag="DB")
node(124,400,200,48,'backend',"ProductAgent","tool: search",tag="AGENT")
node(600,400,200,48,'backend',"Nhánh chính sách","policy QA",tag="AGENT")
node(920,400,200,48,'backend',"OrderAgent","tool: cart · order",tag="AGENT")
node(64,544,140,40,'backend',"BM25","Qdrant · sparse")
node(244,544,140,40,'backend',"Dense Vector","Qdrant · dense")
node(154,624,140,40,'backend',"RRF","rank fusion")
node(440,624,160,40,'backend',"Cross-Encoder","reranking")
node(600,544,200,48,'store',"Policy Knowledge","tài liệu chính sách",tag="KB")
# services card
x,y,w,h=920,528,200,176
o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>')
o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#ffffff" stroke="{INK}" stroke-width="1"/>')
o.append(f'<rect x="{x+8}" y="{y+6}" width="30" height="12" rx="2" fill="none" stroke="{INK}" stroke-opacity="0.4" stroke-width="0.8"/>')
o.append(f'<text x="{x+23}" y="{y+15}" fill="{INK}" fill-opacity="0.85" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.08em">API</text>')
o.append(f'<text x="{x+w/2+12}" y="{y+19}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">Dịch vụ nghiệp vụ</text>')
rows=["Catalog Service","Inventory Service","Cart Service","Order Service","Payment / Wallet Services"]
for i,n in enumerate(rows):
    ry=y+32+i*28
    o.append(f'<line x1="{x+12}" y1="{ry}" x2="{x+w-12}" y2="{ry}" stroke="rgba(45,49,66,0.12)" stroke-width="0.8"/>')
    o.append(f'<text x="{x+16}" y="{ry+18}" fill="{INK}" font-size="11" font-weight="500" font-family="{SANS}">{n}</text>')
# callout
o.append(f'<text x="1184" y="756" fill="{MUTED}" font-size="14" font-style="italic" font-family="{SERIF}" text-anchor="end">LLM không ghi trực tiếp vào CSDL giao dịch — mọi thay đổi đơn hàng, thanh toán đều đi qua dịch vụ nghiệp vụ.</text>')
# legend
LY=788
o.append(f'<line x1="16" y1="{LY-12}" x2="1184" y2="{LY-12}" stroke="rgba(45,49,66,0.10)" stroke-width="0.8"/>')
o.append(f'<text x="16" y="{LY+8}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.14em">CHÚ GIẢI</text>')
items=[('focal',"Điều phối trung tâm"),('backend',"Thành phần xử lý"),('store',"Dữ liệu / trạng thái"),('input',"Người dùng")]
lx=110
for k,t in items:
    f,s=T[k]
    o.append(f'<rect x="{lx}" y="{LY}" width="16" height="10" rx="2" fill="{f}" stroke="{s}" stroke-width="1"/>')
    o.append(f'<text x="{lx+22}" y="{LY+8.5}" fill="{INK}" font-size="10" font-family="{SANS}">{t}</text>'); lx+=170
o.append(f'<line x1="{lx}" y1="{LY+5}" x2="{lx+24}" y2="{LY+5}" stroke="{ACC}" stroke-width="1.4"/>')
o.append(f'<text x="{lx+30}" y="{LY+8.5}" fill="{INK}" font-size="10" font-family="{SANS}">Gọi API nghiệp vụ</text>'); lx+=160
o.append(f'<line x1="{lx}" y1="{LY+5}" x2="{lx+24}" y2="{LY+5}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3"/>')
o.append(f'<text x="{lx+30}" y="{LY+8.5}" fill="{INK}" font-size="10" font-family="{SANS}">Trả kết quả / lưu trạng thái</text>')

body="\n        ".join(o)
TPL=open(sys.argv[2],encoding="utf-8").read()
html=TPL.replace("{{BODY}}",body)
open(sys.argv[1],"w",encoding="utf-8").write(html)
