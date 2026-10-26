"""Regenerate README artwork. Requires Pillow and Arial/DejaVu Sans; no API calls."""
from pathlib import Path
from functools import lru_cache
import math
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets'; OUT.mkdir(exist_ok=True)
W,H=1200,720
BG='#0a1020'; PANEL='#111c30'; INK='#eaf1ff'; MUTED='#94a8c7'; TEAL='#55e3c0'; BLUE='#75aaff'; LINE='#293d5b'
FONT='/System/Library/Fonts/Supplemental/Arial.ttf'
BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
@lru_cache(maxsize=None)
def font(n, b=False):
 candidates = (BOLD if b else FONT,
               '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if b else
               '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
               'DejaVuSans-Bold.ttf' if b else 'DejaVuSans.ttf')
 for candidate in candidates:
  try:
   return ImageFont.truetype(candidate, n)
  except OSError:
   continue
 raise RuntimeError('Install Arial or DejaVu Sans to regenerate the README visuals.')
def text(d,xy,s,n=20,c=INK,b=False): d.text(xy,s,font=font(n,b),fill=c)
def base(height=H):
 im=Image.new('RGB',(W,height),BG); d=ImageDraw.Draw(im)
 for x in range(0,W,40): d.line((x,0,x,height),fill='#101a2b')
 for y in range(0,height,40): d.line((0,y,W,y),fill='#101a2b')
 return im,d
def pill(d,box,s,c=TEAL):
 d.rounded_rectangle(box, radius=14,fill=PANEL,outline=c,width=1)
 bb=d.textbbox((0,0),s,font=font(16,True)); tw=bb[2]-bb[0]
 text(d,((box[0]+box[2]-tw)/2,box[1]+9),s,16,c,True)
def node(d,x,y,label,active=False,width=156):
 d.rounded_rectangle((x-width/2,y-23,x+width/2,y+23),radius=10,fill='#143b3c' if active else PANEL,outline=TEAL if active else LINE,width=2)
 bb=d.textbbox((0,0),label,font=font(16,True)); text(d,(x-(bb[2]-bb[0])/2,y-9),label,16,TEAL if active else INK,True)
# Static hero: one compact brand surface, with readable text and a miniature tree.
im,d=base(420); text(d,(60,30),'STRATAWALK',18,TEAL,True)
text(d,(58,80),'Long context.',54,INK,True); text(d,(58,143),'Navigable memory.',54,INK,True)
text(d,(61,226),'Build once. Search at any scale.',25,MUTED)
text(d,(61,260),'Walk back to the source.',25,MUTED)
text(d,(61,344),'OVERVIEW   /   TOPICS   /   SOURCE',18,TEAL,True)
positions=[(930,75),(820,190),(1040,190),(765,305),(875,305),(985,305),(1095,305)]
for a,b in [(0,1),(0,2),(1,3),(1,4),(2,5),(2,6)]: d.line((*positions[a],*positions[b]),fill=LINE,width=3)
for i,(x,y) in enumerate(positions):
 d.ellipse((x-20,y-20,x+20,y+20),fill=PANEL,outline=TEAL if i in (0,1,4) else BLUE,width=3)
for a,b in [(0,1),(1,4)]: d.line((*positions[a],*positions[b]),fill=TEAL,width=3)
text(d,(60,393),'ORDERED MEMORY  /  SEMANTIC ENTRY  /  EVIDENCE-DIRECTED NAVIGATION',14,MUTED)
im.save(OUT/'hero.png')

# The index is a persistent structure. Tool actions live in a separate panel.
# Node IDs are illustrative, blocks are inside nodes, and edges are node links.
pos={ 'R':(420,242), 'C1':(230,378), 'C2':(610,378),
      'L1':(135,514), 'L2':(325,514), 'L3':(515,514), 'L4':(705,514)}
edges=[('R','C1'),('R','C2'),('C1','L1'),('C1','L2'),('C2','L3'),('C2','L4')]
def box(d,key,on=False):
 x,y=pos[key]; w=170 if key.startswith('L') else 190
 d.rounded_rectangle((x-w/2,y-38,x+w/2,y+38),radius=9,fill='#143b3c' if on else PANEL,outline=TEAL if on else LINE,width=2)
 title={'R':'Root node R','C1':'Chapter node C1','C2':'Chapter node C2'}.get(key,'Leaf node '+key)
 text(d,(x-w/2+12,y-28),title,16,TEAL if on else INK,True)
 if key.startswith('L'):
  text(d,(x-w/2+12,y+2),'Source chunk + emb.',14,MUTED)
 else:
  for j in range(3):
   left=x-w/2+12+j*55
   d.rounded_rectangle((left,y+1,left+48,y+24),radius=4,fill='#20354d',outline=BLUE)
   text(d,(left+7,y+4),'b'+str(j+1),12,INK)
def canvas(title,sub):
 im,d=base(); text(d,(38,27),'STRATAWALK / TREE INDEX + AGENT NAVIGATION',16,TEAL,True)
 text(d,(38,76),title,31,INK,True); text(d,(40,119),sub,18,MUTED)
 text(d,(40,164),'PERSISTENT INDEX',14,BLUE,True)
 return im,d
def panel(d,title,lines):
 d.rounded_rectangle((834,165,1164,568),radius=14,fill=PANEL,outline=LINE)
 text(d,(852,186),title,16,TEAL,True)
 for i,line in enumerate(lines): text(d,(852,231+i*31),line,17,INK if i==0 else MUTED,i==0)
def footer(d,n,total,label):
 text(d,(40,599),label,16,TEAL,True)
 step=1120/total
 for j in range(total): d.rounded_rectangle((40+j*step,635,40+(j+1)*step-12,640),radius=2,fill=TEAL if j<=n else LINE)
 text(d,(40,674),'Schematic only. Node IDs, block counts and paths are illustrative; no live execution is claimed.',15,MUTED)
def drawtree(d,visible,active):
 for a,b in edges:
  if a in visible and b in visible:
   x,y=pos[a]; xx,yy=pos[b]; d.line((x,y+38,xx,yy-38),fill=TEAL if a in active and b in active else LINE,width=3)
 for key in visible: box(d,key,key in active)
# Index construction animation: no agent/tool steps inside the tree.
build=[
 ('01 / CHUNK','Create ordered source leaves.','Parse d chapters; split each into overlapping, embedding-bounded chunks.', ['L1','L2','L3','L4'],['L1','L2','L3','L4'],['SOURCE ORDER','Chapter 1: L1, L2, ...','Chapter 2: L3, L4, ...','','Each leaf stores a chunk','and its embedding.']),
 ('02 / REDUCE','Summarize groups within each chapter.','An LLM reduces n input blocks into a node containing k summary blocks.',list(pos)[1:],['C1','C2'],['BOTTOM-UP REDUCTION','[chunk blocks] -> node','node = [b1, b2, ..., bk]','','Each block gets an embedding.','Long chapters may need','multiple local reduction rounds.']),
 ('03 / REPEAT','Reduce chapter representations upward.','Preserve source order and node links; repeat until a root budget is reached.',list(pos),['R'],['RECURSIVE ABSTRACTION','chapter nodes -> upper nodes','upper nodes -> root R','','Root contains h blocks.','Intermediate levels omitted','in this compact illustration.']),
 ('04 / STORE','Persist structure and multi-scale embeddings.','The finished index supports both semantic entry and structural navigation.',list(pos),list(pos),['INDEX READY','Parent-child links: nodes','Embeddings: source chunks','and all summary/topic blocks','','Same-level groups can run','concurrently when independent.'])]
bframes=[]
for i,(tag,title,sub,visible,active,lines) in enumerate(build):
 im,d=canvas(title,sub); drawtree(d,visible,active); panel(d,'INDEX CONSTRUCTION',lines); footer(d,i,len(build),tag)
 bframes.append(im)
bframes[0].save(OUT/'index-build.gif',save_all=True,append_images=bframes[1:],duration=2600,loop=0)
bframes[-1].save(OUT/'index-structure.png')
walk=[
 ('01 / PLAN','Understand the question and select entry nodes.','The agent uses a compact chapter/ancestor map, embedding search, or both.',[],None,['AGENT WORKSPACE','User intent -> subquestions','Map and/or embedding search','Select m entry nodes','','Example entries: C1 and C2','The index stays unchanged.']),
 ('02 / INSPECT','Inspect several starting nodes.','Directory topics are already read; a search can load other entry nodes.',['C1','C2'],None,['INSPECT ENTRY NODES','C1 contains [b1, b2, b3]','C2 contains [b1, b2, b3]','','Directory nodes count as read.','Do not fetch their text again.','Identify missing evidence.']),
 ('03 / UP','Move up when the information is too specific.','Follow a parent link; reuse the directory when the parent is already read.',['C1','R'],('C1','R'),['TOOL: move_up','C1 -> R','','Here R is already in the map.','Tool returns already_visited.','Reuse known overview topics.','Unread parents return text.']),
 ('04 / DOWN','Move down when more detail is needed.','Explore independent branches via their parent-child links.',['C1','C2','L2','L3'],('C1','L2'),['TOOL: move_down','C1 -> L2','C2 -> L3','','Branches may be explored','concurrently. Original chunks','provide detailed information.']),
 ('05 / COMPACT','Keep the active context within budget.','Compress the workspace while retaining findings and source references.',['L2','L3'],None,['TOOL: compact_context','Keep useful findings','Keep source/node references','Keep unresolved subquestions','','Re-enter search or navigation','when more information is needed.']),
 ('06 / FINISH','Answer when the information is sufficient.','The agent assembles an answer from the information it has gathered.',['L2','L3'],None,['TOOL: finish','User-facing answer','Relevant source references','','Navigation is adaptive.','Every query does not need','every tool shown here.'])]
frames=[]
for si,(tag,title,sub,active,travel,lines) in enumerate(walk):
 for fi in range(12):
  im,d=canvas(title,sub); drawtree(d,list(pos),active); panel(d,'AGENT ACTION / STATE',lines)
  if travel:
   a,b=travel; x,y=pos[a]; xx,yy=pos[b]; t=fi/11
   # Travel on the actual edge between card boundaries, never root-to-leaf jumps.
   direction=1 if yy>y else -1
   sy=y+direction*38; ey=yy-direction*38
   px=x+(xx-x)*t; py=sy+(ey-sy)*t
   d.ellipse((px-6,py-6,px+6,py+6),fill='#ffffff')
  footer(d,si,len(walk),tag); frames.append(im)
frames[0].save(OUT/'agent-walk.gif',save_all=True,append_images=frames[1:],duration=200,loop=0,optimize=True)
frames[42].save(OUT/'agent-walk-poster.png')
print('Generated hero, index construction, index structure, and navigation visuals.')
