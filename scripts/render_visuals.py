"""Regenerate README artwork. Requires Pillow; no model/API calls."""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets'; OUT.mkdir(exist_ok=True)
W,H=1200,720
BG='#0a1020'; PANEL='#111c30'; INK='#eaf1ff'; MUTED='#94a8c7'; TEAL='#55e3c0'; BLUE='#75aaff'; LINE='#293d5b'
FONT='/System/Library/Fonts/Supplemental/Arial.ttf'
BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
def font(n,b=False): return ImageFont.truetype(BOLD if b else FONT,n)
def text(d,xy,s,n=20,c=INK,b=False): d.text(xy,s,font=font(n,b),fill=c)
def base():
 im=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(im)
 for x in range(0,W,40): d.line((x,0,x,H),fill='#101a2b')
 for y in range(0,H,40): d.line((0,y,W,y),fill='#101a2b')
 return im,d
def pill(d,box,s,c=TEAL):
 d.rounded_rectangle(box, radius=14,fill=PANEL,outline=c,width=1)
 bb=d.textbbox((0,0),s,font=font(16,True)); tw=bb[2]-bb[0]
 text(d,((box[0]+box[2]-tw)/2,box[1]+9),s,16,c,True)
def node(d,x,y,label,active=False,width=156):
 d.rounded_rectangle((x-width/2,y-23,x+width/2,y+23),radius=10,fill='#143b3c' if active else PANEL,outline=TEAL if active else LINE,width=2)
 bb=d.textbbox((0,0),label,font=font(16,True)); text(d,(x-(bb[2]-bb[0])/2,y-9),label,16,TEAL if active else INK,True)
# Static hero: one compact brand surface, with readable text and a miniature tree.
im,d=base(); text(d,(65,58),'STRATAWALK',19,TEAL,True)
text(d,(65,132),'Long documents.',62,INK,True); text(d,(65,207),'Navigable memory.',62,INK,True)
text(d,(68,309),'Give agents the big picture',27,MUTED); text(d,(68,349),'and a path back to the evidence.',27,MUTED)
pill(d,(65,449,276,488),'BUILD BOTTOM-UP'); pill(d,(290,449,505,488),'EXPLORE ANY SCALE',BLUE)
positions=[(925,175),(815,310),(1035,310),(760,445),(870,445),(980,445),(1090,445)]
for a,b in [(0,1),(0,2),(1,3),(1,4),(2,5),(2,6)]: d.line((*positions[a],*positions[b]),fill=LINE,width=3)
for i,(x,y) in enumerate(positions):
 d.ellipse((x-23,y-23,x+23,y+23),fill=PANEL,outline=TEAL if i in (0,1,4) else BLUE,width=3)
for a,b in [(0,1),(1,4)]: d.line((*positions[a],*positions[b]),fill=TEAL,width=3)
text(d,(65,622),'ORDERED SUMMARY TREES  /  MULTI-SCALE SEARCH  /  AGENTIC NAVIGATION',18,MUTED)
text(d,(65,666),'DESIGN PREVIEW',14,TEAL,True)
im.save(OUT/'hero.png')
# Animated mechanism: synthetic report, actual links, no fabricated runtime results.
steps=[
 ('01 / BUILD','Start with source passages.','Overlapping chunks retain document order and source references.',[3,4,5,6],None),
 ('02 / ABSTRACT','Build memory from the bottom up.','Summarize adjacent groups; independent groups can run concurrently.',[1,2],None),
 ('03 / ORIENT','Keep the whole document in view.','A compact overview connects back to chapters and source passages.',[0],None),
 ('04 / SEARCH','Enter at a useful reading scale.','Semantic search finds a relevant chapter summary.',[2],(2,2)),
 ('05 / MOVE UP','Recover the broader context.','Read the document overview before interpreting the result.',[2,0],(2,0)),
 ('06 / MOVE DOWN','Follow the evidence across branches.','Inspect methods and results, then load their original passages.',[0,1,2,4,5],(0,5)),
 ('07 / FINISH','Answer from source evidence.','In this fixture, the quality gain is paired with higher memory use.',[4,5],None),
]
pos=[(440,260),(250,375),(630,375),(165,495),(335,495),(545,495),(715,495)]
labels=['Document overview','Methods','Results','Setup [s1]','Memory [s2]','Quality [s3]','Limits [s4]']
edges=[(0,1),(0,2),(1,3),(1,4),(2,5),(2,6)]
frames=[]
for si,(tag,title,sub,active,travel) in enumerate(steps):
 for fi in range(12):
  im,d=base(); text(d,(42,30),'STRATAWALK / HOW THE WALK WORKS',17,TEAL,True)
  pill(d,(980,25,1158,63),'CONCEPT ANIMATION',MUTED)
  text(d,(42,89),title,34,INK,True); text(d,(44,139),sub,20,MUTED)
  for a,b in edges: d.line((*pos[a],*pos[b]),fill=TEAL if a in active and b in active else LINE,width=3)
  if travel and travel[0]!=travel[1]:
   a,b=travel; t=fi/11; x=pos[a][0]+(pos[b][0]-pos[a][0])*t; y=pos[a][1]+(pos[b][1]-pos[a][1])*t
   d.ellipse((x-7,y-7,x+7,y+7),fill='#ffffff')
  for i,(x,y) in enumerate(pos): node(d,x,y,labels[i],i in active,178 if i==0 else 156)
  d.rounded_rectangle((835,205,1158,555),radius=16,fill=PANEL,outline=LINE)
  text(d,(855,227),'SYNTHETIC REPORT',15,BLUE,True)
  text(d,(855,269),'Question',16,MUTED,True)
  text(d,(855,298),'What improved quality,',20,INK,True); text(d,(855,326),'and at what trade-off?',20,INK,True)
  if si<6:
   text(d,(855,388),'Source fixture',16,TEAL,True)
   text(d,(855,421),'[s2] Extra memory required.',18)
   text(d,(855,452),'[s3] Reranking improved',18); text(d,(894,479),'answer quality.',18)
  else:
   text(d,(855,388),'Evidence-grounded answer',16,TEAL,True)
   text(d,(855,423),'Reranking improved quality',17)
   text(d,(855,451),'[s3], with higher memory',17)
   text(d,(855,479),'requirements [s2].',17)
  text(d,(44,588),tag,18,TEAL,True)
  for k in range(7):
   x=44+k*160; d.rounded_rectangle((x,630,x+143,635),radius=2,fill=TEAL if k<=si else LINE)
  text(d,(44,671),'Illustrative mechanism using a synthetic document. Not a live agent recording or benchmark.',16,MUTED)
  frames.append(im)
frames[0].save(OUT/'agent-walk.gif',save_all=True,append_images=frames[1:],duration=160,loop=0,optimize=True)
frames[58].save(OUT/'agent-walk-poster.png')
print('Generated hero.png, agent-walk.gif, agent-walk-poster.png')
