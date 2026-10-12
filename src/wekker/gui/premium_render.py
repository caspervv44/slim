"""WakeSync Premium: vier hoogwaardige 800×480-schermontwerpen.

Dit bestand heeft geen afhankelijkheid van de wekkerlogica. Het tekent uitsluitend
een afbeelding van het bestaande schermmodel. Alle acties worden elders
gekoppeld aan de reeds aanwezige WakeSync-bedieningsfuncties.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageEnhance

WIDTH, HEIGHT = 800, 480
SCALE = 2

THEME_TITLES = {
    "midnight": "Midnight Glass",
    "ocean": "Aurora Slate",
    "light": "Light Executive",
    "amber": "Ember Noir",
}
THEME_IDS = tuple(THEME_TITLES)
DAY_NAMES = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")
MONTH_NAMES = (
    "", "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
)

@dataclass(frozen=True)
class Palette:
    bg: str
    card: str
    raised: str
    text: str
    muted: str
    accent: str
    accent_alt: str
    border: str
    success: str
    dark: bool = True

PALETTES = {
    "midnight": Palette("#060F20", "#0D1D32", "#142A49", "#F6F8FF",
                        "#A8BBD7", "#4A9DFF", "#A9D9FF", "#37547C", "#43D0A8"),
    "ocean": Palette("#041725", "#09243A", "#10334D", "#F3FCFF",
                     "#A6CCD9", "#48DFD7", "#A787FF", "#2B6477", "#57F0C0"),
    "light": Palette("#EFF3F6", "#FFFFFF", "#EDF3F9", "#1F344F",
                     "#74859A", "#5D83A8", "#E5AE6C", "#D5E2EC", "#30947C", False),
    "amber": Palette("#0E1015", "#1B1E25", "#28252A", "#FFF5EB",
                     "#C7B3A0", "#FFB458", "#FAD79A", "#6C5140", "#72D9AD"),
}

@dataclass(frozen=True)
class HitTarget:
    x0: int
    y0: int
    x1: int
    y1: int
    action: str
    payload: str = ""

    def contains(self, x: int, y: int) -> bool:
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1


@lru_cache(maxsize=40)
def _font(px: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/share/fonts/truetype/liberation2") /
        ("LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), max(6, px * SCALE))
    return ImageFont.truetype(name, max(6, px * SCALE))


@lru_cache(maxsize=8)
def _art_source(theme: str, asset_dir_str: str) -> Image.Image | None:
    path = Path(asset_dir_str) / f"premium_{theme}.png"
    if not path.is_file():
        return None
    try:
        with Image.open(path) as source:
            return source.convert("RGBA")
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=12)
def _background(theme: str, asset_dir_str: str) -> Image.Image:
    """Laad sfeerillustratie één keer; nooit bij elke kloktick opnieuw."""
    p = PALETTES[theme]
    image_path = Path(asset_dir_str) / f"premium_{theme}.png"
    surface = Image.new("RGBA", (WIDTH*SCALE, HEIGHT*SCALE), p.bg)
    if image_path.is_file():
        with Image.open(image_path) as source:
            art = source.convert("RGBA").resize(surface.size, Image.Resampling.LANCZOS)
        if p.dark:
            art = ImageEnhance.Brightness(art).enhance(0.65)
            dim_alpha = 165 if theme == "midnight" else 173 if theme == "ocean" else 174
            art.alpha_composite(Image.new("RGBA", art.size, (*_rgb(p.bg), dim_alpha)))
        else:
            art = ImageEnhance.Brightness(art).enhance(1.12)
            art.alpha_composite(Image.new("RGBA", art.size, (247, 250, 253, 205)))
        surface.alpha_composite(art)
    return surface


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i+2], 16) for i in (1, 3, 5))


def _rgba(color: str, a: int = 255) -> tuple[int, int, int, int]:
    return (*_rgb(color), a)


def _hex_blend(first: str, second: str, fraction: float) -> str:
    a, b = _rgb(first), _rgb(second)
    x = max(0, min(fraction, 1.0))
    return "#" + "".join(f"{round(ai*(1-x)+bi*x):02x}" for ai, bi in zip(a, b))


class Painter:
    """Tekenhulpen met dubbele resolutie en anti-aliasing."""
    def __init__(self, theme: str, asset_dir: Path, logo_path: Path | None) -> None:
        self.theme = theme if theme in PALETTES else "midnight"
        self.pal = PALETTES[self.theme]
        self.image = _background(self.theme, str(asset_dir.resolve())).copy()
        self.d = ImageDraw.Draw(self.image, "RGBA")
        self.hits: list[HitTarget] = []
        self.asset_dir = asset_dir
        self.logo_path = logo_path

    @staticmethod
    def xy(x: float) -> int:
        return round(x*SCALE)

    def rect(self, box: tuple[float, float, float, float], color: str,
             radius: int = 13, alpha: int = 255, outline: str | None = None,
             width: int = 1) -> None:
        x0,y0,x1,y1 = (self.xy(v) for v in box)
        if alpha == 255 and not outline:
            self.d.rounded_rectangle((x0,y0,x1,y1),radius=self.xy(radius),
                                     fill=_rgba(color))
            return
        # RGBA rechtstreeks op het bestaande canvas tekenen zou alpha wissen.
        # Eerst lokaal tekenen en dan echt compositen levert doorschijnend glas.
        patch=Image.new("RGBA",(x1-x0+1,y1-y0+1))
        pen=ImageDraw.Draw(patch)
        pen.rounded_rectangle((0,0,x1-x0,y1-y0),radius=self.xy(radius),
                              fill=_rgba(color,alpha) if alpha else None,
                              outline=_rgba(outline,160) if outline else None,
                              width=self.xy(width))
        self.image.alpha_composite(patch,(x0,y0))

    def card(self, x: int, y: int, w: int, h: int, *,
             active: bool = False, radius: int = 15, alpha: int | None = None) -> None:
        p = self.pal
        # Een kleine, gelaagde slagschaduw geeft de kaarten materiaalgevoel.
        if p.dark:
            self.rect((x+1,y+5,x+w+1,y+h+5), "#000000", radius, 53)
            self.rect((x,y+2,x+w,y+h+2), "#000000", radius, 48)
        else:
            self.rect((x+1,y+5,x+w+1,y+h+5), "#A5B4C3", radius, 32)
        self.rect((x,y,x+w,y+h), p.raised if active else p.card,
                  radius, alpha if alpha is not None else (230 if p.dark else 242),
                  p.accent if active else p.border)
        # Zacht doorschijnend highlight langs de bovenzijde.
        highlight = _hex_blend(p.card,"#FFFFFF",0.14 if p.dark else 0.36)
        self.d.line([(self.xy(x+radius),self.xy(y+1)),
                     (self.xy(x+w-radius),self.xy(y+1))],
                    fill=_rgba(highlight), width=self.xy(1))

    def text(self, x: float, y: float, string: Any, size: int = 14, *,
             color: str | None = None, bold: bool = False,
             anchor: str = "lt", max_width: int | None = None,
             align: str = "left") -> None:
        s = str(string or "")
        font = _font(size, bold)
        if max_width:
            ceiling = self.xy(max_width)
            if self.d.textlength(s, font=font) > ceiling:
                while s and self.d.textlength(s+"…",font=font) > ceiling:
                    s=s[:-1]
                s = s.rstrip()+"…"
        self.d.text((self.xy(x),self.xy(y)), s, font=font,
                    fill=_rgba(color or self.pal.text), anchor=anchor, align=align)

    def label(self, x: float, y: float, value: str, *, max_width: int | None = None) -> None:
        self.text(x,y,value,10,color=self.pal.muted,bold=True,max_width=max_width)

    def line(self, coords: list[tuple[float,float]], color: str,
             width: float = 1.5, alpha: int = 240) -> None:
        self.d.line([(self.xy(x),self.xy(y)) for x,y in coords],
                    fill=_rgba(color,alpha),width=max(1,self.xy(width)),joint="curve")

    def circle(self, cx: float, cy: float, r: float, color: str,
               alpha: int=255, outline: str | None=None, width: float=1.5) -> None:
        x0,y0,x1,y1=(self.xy(cx-r),self.xy(cy-r),self.xy(cx+r),self.xy(cy+r))
        if alpha == 255 and not outline:
            self.d.ellipse((x0,y0,x1,y1),fill=_rgba(color))
            return
        patch=Image.new("RGBA",(x1-x0+1,y1-y0+1))
        pen=ImageDraw.Draw(patch)
        pen.ellipse((0,0,x1-x0,y1-y0),
                    fill=_rgba(color,alpha) if alpha else None,
                    outline=_rgba(outline,190) if outline else None,
                    width=self.xy(width))
        self.image.alpha_composite(patch,(x0,y0))

    def pill(self, x: int, y: int, w: int, h: int, label: str, *,
             active: bool = False, font_size: int = 11,
             fg: str | None = None, bg: str | None = None) -> None:
        p=self.pal
        fill = bg or (p.accent if active else p.raised)
        self.rect((x,y,x+w,y+h),fill,round(h/2),245,
                  p.accent if active else p.border)
        self.text(x+w/2,y+h/2, label,font_size,bold=active,
                  color=fg or (p.bg if active else p.text),anchor="mm",max_width=w-12)

    def toggle(self, x: int, y: int, value: bool, *, w: int = 43, h: int = 23) -> None:
        p=self.pal
        self.rect((x,y,x+w,y+h), p.accent if value else p.raised,
                  radius=h//2,alpha=255,outline=p.accent if value else p.border)
        dot_x = x+w-h/2-2 if value else x+h/2+2
        self.circle(dot_x,y+h/2,h/2-4, "#FFFFFF" if value else p.muted)

    def hit(self, x: int, y: int, w: int, h: int, action: str, payload: str = "") -> None:
        self.hits.append(HitTarget(x,y,x+w,y+h,action,payload))

    def _icon(self, name: str, x: int, y: int, color: str | None = None) -> None:
        """Eenvoudige vectoriconen; niet afhankelijk van emoji/fonts."""
        c=color or self.pal.muted
        if name == "clock":
            self.d.ellipse((self.xy(x-7),self.xy(y-7),self.xy(x+7),self.xy(y+7)),
                           outline=_rgba(c),width=self.xy(1.5))
            self.line([(x,y),(x,y-4),(x+4,y-4)],c,1.6)
        elif name == "calendar":
            self.rect((x-7,y-7,x+7,y+7),c,2,0,c)
            self.line([(x-7,y-3),(x+7,y-3)],c,1.2)
            self.line([(x-4,y-9),(x-4,y-5)],c,1.6)
            self.line([(x+4,y-9),(x+4,y-5)],c,1.6)
        elif name == "home":
            self.line([(x-7,y-1),(x,y-7),(x+7,y-1)],c,1.5)
            self.line([(x-5,y-3),(x-5,y+6),(x+5,y+6),(x+5,y-3)],c,1.5)
        elif name == "settings":
            self.circle(x,y,7,c,0,c,1.5)
            self.circle(x,y,2,c,0,c,1)
            for k in range(8):
                a=k*math.pi/4
                self.line([(x+math.cos(a)*7,y+math.sin(a)*7),
                           (x+math.cos(a)*9,y+math.sin(a)*9)],c,1.2)
        elif name == "sun":
            self.circle(x,y,4,c)
            for k in range(8):
                a=k*math.pi/4
                self.line([(x+math.cos(a)*7,y+math.sin(a)*7),
                           (x+math.cos(a)*11,y+math.sin(a)*11)],c,1.7)
        elif name == "moon":
            self.circle(x,y,8,c)
            self.circle(x+4,y-4,7,self.pal.card)
        elif name == "bell":
            self.d.arc((self.xy(x-6),self.xy(y-6),self.xy(x+6),self.xy(y+7)),
                       start=190,end=350,fill=_rgba(c),width=self.xy(2))
            self.line([(x-7,y+6),(x+7,y+6)],c,1.4)
            self.circle(x,y+8,1.5,c)
        elif name == "speaker":
            self.line([(x-7,y-3),(x-3,y-3),(x+1,y-7),(x+1,y+7),(x-3,y+3),(x-7,y+3),(x-7,y-3)],c,1.3)
            self.d.arc((self.xy(x-2),self.xy(y-7),self.xy(x+11),self.xy(y+7)),
                       290,70,fill=_rgba(c),width=self.xy(1.5))
        elif name == "lamp":
            self.circle(x,y-3,6,c,0,c,1.5)
            self.line([(x-4,y+3),(x-3,y+8),(x+3,y+8),(x+4,y+3)],c,1.4)
        elif name == "chevron":
            self.line([(x-2,y-5),(x+3,y),(x-2,y+5)],c,1.7)
        elif name == "cloud":
            self.d.arc((self.xy(x-9),self.xy(y-5),self.xy(x+8),self.xy(y+10)),
                       178,360,fill=_rgba(c),width=self.xy(1.6))

    def logo(self) -> None:
        """Merkplaat gebruikt exact het bestaande, door de gebruiker goedgekeurde PNG."""
        self.rect((18,14,205,67),"#FFFFFF",radius=12,alpha=250)
        if self.logo_path and self.logo_path.is_file():
            try:
                with Image.open(self.logo_path) as file:
                    source=file.convert("RGBA")
                source.thumbnail((168*SCALE,42*SCALE),Image.Resampling.LANCZOS)
                left=self.xy(18)+(self.xy(187)-source.width)//2
                top=self.xy(14)+(self.xy(53)-source.height)//2
                self.image.alpha_composite(source,(left,top))
                return
            except (OSError, ValueError):
                pass
        # Neutraal tekstnoodlabel: het origineel wordt nooit vervangen.
        self.text(112,38,"WakeSync",18,color="#172338",bold=True,anchor="mm")

    def navigation(self, page: str) -> None:
        self.logo()
        self.card(216,14,566,54,radius=14,alpha=240)
        tabs=(("main","Vandaag","home"),("agenda","Agenda","calendar"),
              ("alarm","Alarm","clock"),("settings","Instellingen","settings"))
        for index,(screen,title,icon) in enumerate(tabs):
            x=224+index*138
            active=page==screen
            if active:
                self.rect((x,20,x+130,62),self.pal.raised,radius=11,
                          outline=self.pal.accent)
                self.rect((x+24,60,x+106,62),self.pal.accent,2)
            self._icon(icon,x+15,41,self.pal.accent if active else self.pal.muted)
            self.text(x+77,42,title,11,bold=active,
                      color=self.pal.text if active else self.pal.muted,anchor="mm")
            self.hit(x,18,132,46,"nav",screen)

    def artwork_card(self,x:int,y:int,w:int,h:int, *,
                     darken:float=0.35,radius:int=14) -> None:
        source = _art_source(self.theme, str(self.asset_dir.resolve()))
        if source is None:
            self.card(x,y,w,h)
            return
        region=source.copy()
        src_width,src_height=region.size
        ratio=max(w/src_width,h/src_height)
        rw,rh=math.ceil(src_width*ratio),math.ceil(src_height*ratio)
        region=region.resize((rw*SCALE,rh*SCALE),Image.Resampling.LANCZOS)
        crop_x=max(0,(rw-w)*SCALE//2)
        crop_y=max(0,round((rh-h)*SCALE*0.67))
        region=region.crop((crop_x,crop_y,crop_x+w*SCALE,crop_y+h*SCALE))
        # Donkere overlay voor de leesbaarheid van tekst over de foto.
        overlay=Image.new("RGBA",region.size,(10,13,23,int(255*darken)) if self.pal.dark
                          else (255,254,249,130))
        region=Image.alpha_composite(region,overlay)
        mask=Image.new("L",region.size,0)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,region.width-1,region.height-1),
                                                radius=radius*SCALE,fill=255)
        self.image.paste(region,(x*SCALE,y*SCALE),mask)
        self.rect((x,y,x+w,y+h),self.pal.border,radius,0,self.pal.border)

    def clock(self, cx:int, cy:int, radius:int, time_str:str, now:datetime, *,
              show_greeting: bool = False) -> None:
        p=self.pal
        # Hoogwaardige binnenring met geïntegreerde bergillustratie.
        source = _art_source(self.theme, str(self.asset_dir.resolve()))
        if source is not None:
            scenic=source.copy()
            d=round(2*radius*SCALE)
            scenic=scenic.resize((d,d),Image.Resampling.LANCZOS)
            scenic.alpha_composite(Image.new("RGBA",(d,d),
                                             _rgba(p.bg,103 if p.dark else 158)))
            mask=Image.new("L",(d,d),0)
            ImageDraw.Draw(mask).ellipse((0,0,d-1,d-1),fill=255)
            self.image.paste(scenic,((cx-radius)*SCALE,(cy-radius)*SCALE),mask)
        else:
            self.circle(cx,cy,radius,p.raised)
        self.circle(cx,cy,radius+2,p.card,0,p.border,1.5)
        self.circle(cx,cy,radius-7,p.card,0,p.accent,2)
        # 60 wijzerplaatmarkeringen, netjes rond de cirkel.
        for step in range(60):
            a=-math.pi/2+step*math.pi*2/60
            large=(step%5==0)
            r0=radius-(18 if large else 13)
            r1=radius-(9 if large else 8)
            self.line([(cx+math.cos(a)*r0,cy+math.sin(a)*r0),
                       (cx+math.cos(a)*r1,cy+math.sin(a)*r1)],
                      p.accent_alt if large else p.muted,1.3 if large else 0.65,
                      alpha=220 if large else 100)
        self.d.arc(
            (self.xy(cx-radius-3),self.xy(cy-radius-3),
             self.xy(cx+radius+3),self.xy(cy+radius+3)),
            start=-91,end=-91+260,fill=_rgba(p.accent,235),width=self.xy(5))
        day=f"{DAY_NAMES[now.weekday()].capitalize()} {now.day} {MONTH_NAMES[now.month]}"
        self.text(cx,cy-39,day,11,anchor="mm",color=p.text)
        base_size=48 if len(str(time_str))<=5 else 36
        self.text(cx,cy+3,time_str,base_size,bold=True,anchor="mm",color=p.text,max_width=radius*1.68)
        if show_greeting:
            greeting="Goedemorgen!" if now.hour<12 else "Goedemiddag!" if now.hour<18 else "Goedenavond!"
            self._icon("sun" if 6<=now.hour<19 else "moon",cx,cy+55,p.accent_alt)
            self.text(cx,cy+73,greeting,10,color=p.muted,anchor="mm")

    def finish(self) -> tuple[Image.Image,list[HitTarget]]:
        return self.image.convert("RGB").resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS),self.hits


def _safe(value: Any, default: str = "—") -> str:
    s=str(value or "").strip()
    return s if s else default


def _title_and_sub(p: Painter,title:str,sub:str) -> None:
    p.text(28,85,title,17,bold=True)
    p.text(28,111,sub,10,color=p.pal.muted)


def _draw_today(p:Painter,layout:dict,now:datetime) -> None:
    p.card(18,83,310,288,alpha=219)
    p.clock(173,222,128,_safe(layout.get("time"),"07:30"),now,show_greeting=True)

    p.card(342,84,439,126)
    p._icon("calendar",362,106,p.pal.accent)
    p.text(381,94,_safe(layout.get("lesson_label"),"VOLGENDE LES"),11,bold=True)
    p.text(363,124,_safe(layout.get("lesson_subject"),"Geen lessen"),22,bold=True,max_width=390)
    meta=" · ".join(x for x in (layout.get("lesson_time"),layout.get("lesson_room")) if x)
    p.text(364,169,meta or _safe(layout.get("agenda_status"),""),11,color=p.pal.muted,max_width=382)
    if layout.get("lesson_teacher"):
        p.text(365,190,"Docent: "+str(layout["lesson_teacher"]),9,color=p.pal.muted,max_width=355)
    p._icon("chevron",761,148,p.pal.accent)
    p.hit(342,84,439,126,"nav","agenda")

    p.card(342,222,439,125)
    p._icon("bell",363,247,p.pal.accent)
    p.text(382,236,"VOLGEND ALARM",11,bold=True)
    p.text(363,272,_safe(layout.get("alarm")),29,bold=True,max_width=200)
    p.pill(580,267,154,35,_safe(layout.get("alarm_day"),"Alarm"),font_size=10)
    p.text(364,321,"Tik om je wekkers te beheren",10,color=p.pal.muted)
    p.hit(342,222,439,125,"nav","alarm")

    p.artwork_card(18,383,310,79,darken=.42)
    p._icon("sun",43,414,p.pal.accent_alt)
    p.text(62,398,"EEN NIEUWE DAG",10,color=p.pal.text if not p.pal.dark else "#FFFFFF",bold=True)
    p.text(62,422,"Rustig beginnen. Sterk eindigen.",10,color=p.pal.text if not p.pal.dark else "#FFFFFF")
    p.card(342,359,439,103,alpha=235)
    p.text(363,372,"WAKE SYNC",10,bold=True,color=p.pal.accent)
    p.text(363,395,"Jouw dag, in balans.",17,bold=True)
    p.text(363,428,_safe(layout.get("agenda_status"),"Rooster beschikbaar"),
           10,color=p.pal.muted,max_width=385)
    if layout.get("notice"):
        p.text(363,446,str(layout["notice"]),10,color=p.pal.accent_alt,max_width=382)


def _draw_agenda(p:Painter,layout:dict,now:datetime) -> None:
    p.card(18,82,535,52)
    p._icon("calendar",39,108,p.pal.accent)
    p.text(61,95,_safe(layout.get("day"),"Vandaag"),14,bold=True,max_width=290)
    p.pill(381,94,40,28,"‹",font_size=17)
    p.pill(427,94,40,28,"›",font_size=17)
    p.pill(473,94,64,28,"Nu",font_size=10)
    p.hit(378,91,44,33,"agenda-day","-1")
    p.hit(425,91,45,33,"agenda-day","1")
    p.hit(471,91,65,33,"agenda-today")

    rows=list(layout.get("rows",[]))[:6]
    p.card(18,145,535,309)
    if not rows:
        p.text(285,256,_safe(layout.get("empty_text"),"Geen lessen vandaag"),
               16,color=p.pal.muted,anchor="mm",max_width=440)
    for i,row in enumerate(rows):
        y=153+i*49
        current=bool(row.get("current"))
        p.rect((29,y,542,y+45),p.pal.raised if current else p.pal.card,
               10,alpha=237 if current else 144,
               outline=p.pal.accent if current else p.pal.border)
        p.circle(44,y+22,4,[p.pal.accent,p.pal.success,p.pal.accent_alt,
                           "#DB8FB7", "#DEB771", "#8CB7EF"][i%6])
        p.text(57,y+12,_safe(row.get("start")),12,bold=True,max_width=65)
        p.text(126,y+15,_safe(row.get("subject")),11,bold=True,max_width=184)
        p.text(325,y+15,_safe(row.get("room"),""),10,color=p.pal.muted,max_width=112)
        p._icon("chevron",521,y+23,p.pal.accent if current else p.pal.muted)
        p.hit(29,y,513,45,"agenda-row",str(i))

    p.card(565,82,216,156)
    p.artwork_card(572,89,202,64,darken=.48)
    p.text(583,159,"SCHOOLAGENDA",9,bold=True,color=p.pal.muted)
    p.text(582,179,f'{layout.get("total_rows",len(rows))} lessen',20,bold=True)
    p.text(583,210,_safe(layout.get("provider"),"Agenda"),10,
           color=p.pal.muted,max_width=190)
    p.card(565,250,216,204)
    p.text(584,267,"PAGINA",10,bold=True,color=p.pal.muted)
    page=int(layout.get("page",0))+1
    total=max(1,int(layout.get("page_count",1)))
    p.text(584,292,f"{page} / {total}",27,bold=True)
    p.text(584,334,_safe(layout.get("status_text"),"Agenda geladen"),
           10,color=p.pal.muted,max_width=182)
    p.pill(582,393,82,37,"‹ Vorige",font_size=10)
    p.pill(673,393,88,37,"Volgende ›",font_size=10)
    if page>1:
        p.hit(580,389,88,44,"agenda-page","-1")
    if page<total:
        p.hit(671,389,94,44,"agenda-page","1")
    if layout.get("simulated") and rows:
        p.text(37,440,"VOORBEELDROOSTER",9,color=p.pal.muted,bold=True)


def _alarm_display_name(item:dict) -> str:
    return "Eenmalig" if item.get("date") else "Dagelijks"


def _draw_alarm(p:Painter,layout:dict,now:datetime,selected_alarm_id:str|None) -> None:
    p.card(18,82,307,276,alpha=226)
    p.clock(171,219,117,_safe(layout.get("_clock_time"),now.strftime("%H:%M")),
            now,show_greeting=True)
    p.artwork_card(18,370,307,91,darken=.43)
    p._icon("bell",43,399,p.pal.accent_alt)
    p.text(63,382,"MIJN VOLGENDE ALARM",10,bold=True,color=p.pal.text if not p.pal.dark else "#FFFFFF")
    first=next((i for i in layout.get("items",[]) if i.get("enabled")),None)
    p.text(64,409,_safe(first.get("time") if first else None,"Geen actief alarm"),
           22,bold=True,color=p.pal.text if not p.pal.dark else "#FFFFFF",max_width=245)
    if first:
        p.text(64,439,_safe(first.get("day_label")),10,color=p.pal.text if not p.pal.dark else "#FFFFFF")

    p.card(339,82,443,379)
    p.text(357,98,"Mijn alarmen",17,bold=True)
    p.pill(628,94,136,34,"+ Alarm toevoegen",active=True,font_size=10)
    p.hit(625,91,144,38,"new-alarm")

    items=list(layout.get("items") or [])
    count=len(items)
    page=int(layout.get("_list_page",0))
    page_count=max(1,math.ceil(count/4))
    page=max(0,min(page,page_count-1))
    show=items[page*4:page*4+4]
    if not show:
        p.text(561,265,"Nog geen alarmen",17,color=p.pal.muted,anchor="mm")
    for j,item in enumerate(show):
        y=142+j*70
        active=(str(item.get("id"))==selected_alarm_id)
        p.card(351,y,418,62,active=active,radius=12)
        alarm_id=str(item.get("id"))
        p.text(361,y+11,_safe(item.get("time")),21,bold=True,max_width=113)
        p.text(463,y+7,_alarm_display_name(item),11,bold=True,max_width=100)
        p.text(463,y+31,_safe(item.get("day_label")),9,color=p.pal.muted,max_width=125)
        p._icon("clock",586,y+18,p.pal.accent)
        p.text(600,y+10,f'{item.get("snooze_minutes",9)} m',9,color=p.pal.muted)
        p._icon("speaker",642,y+20,p.pal.accent if item.get("speaker_enabled") else p.pal.muted)
        p._icon("lamp",680,y+20,p.pal.accent if item.get("lamp_blink") else p.pal.muted)
        p.toggle(717,y+19,bool(item.get("enabled")),w=38,h=23)
        p.hit(352,y,226,62,"select-alarm",alarm_id)
        p.hit(580,y,49,62,"cycle-snooze",alarm_id)
        p.hit(629,y,34,62,"toggle-speaker",alarm_id)
        p.hit(666,y,35,62,"toggle-lamp",alarm_id)
        p.hit(707,y,57,62,"toggle-alarm",alarm_id)
    if page_count>1:
        p.pill(484,427,61,26,"‹",font_size=15)
        p.text(560,440,f"{page+1}/{page_count}",9,color=p.pal.muted,anchor="mm")
        p.pill(580,427,61,26,"›",font_size=15)
        if page>0:
            p.hit(483,426,61,29,"alarm-page","-1")
        if page+1<page_count:
            p.hit(580,426,61,29,"alarm-page","1")
    else:
        p.text(362,441,"Tik op een alarm voor alle instellingen",9,color=p.pal.muted)


def _settings_tile(p:Painter,x:int,y:int,w:int,h:int,title:str,
                   value:str,icon:str,action:str,payload:str="") -> None:
    p.card(x,y,w,h,radius=13)
    p._icon(icon,x+21,y+22,p.pal.accent)
    p.text(x+37,y+11,title,11,bold=True,max_width=w-52)
    p.text(x+20,y+38,value,10,color=p.pal.muted,max_width=w-37)
    p._icon("chevron",x+w-14,y+h-17,p.pal.muted)
    p.hit(x,y,w,h,action,payload)


def _draw_settings(p:Painter,layout:dict,now:datetime) -> None:
    p.artwork_card(18,83,284,378,darken=.45)
    p.text(37,100,"UITSTRALING",10,color=p.pal.text if not p.pal.dark else "#FFFFFF",bold=True)
    p.text(37,124,"Jouw WakeSync.",21,color=p.pal.text if not p.pal.dark else "#FFFFFF",bold=True)
    p.text(37,159,"Vier stijlen, dezelfde rust.",11,color=p.pal.text if not p.pal.dark else "#FFFFFF")
    p.text(37,331,"GESELECTEERD THEMA",9,color=p.pal.text if not p.pal.dark else "#FFFFFF",bold=True)
    p.text(37,353,THEME_TITLES[p.theme],17,color=p.pal.text if not p.pal.dark else "#FFFFFF",bold=True)
    theme_ids=tuple(THEME_TITLES)
    for i,theme_id in enumerate(theme_ids):
        x=36+i*62
        p.rect((x,397,x+51,440),PALETTES[theme_id].card,9,255,
               p.pal.accent if p.theme==theme_id else "#A0A0A0")
        p.circle(x+25,418,6,PALETTES[theme_id].accent)
        p.hit(x,395,53,48,"theme",theme_id)

    zone=_safe(layout.get("timezone"),"Europe/Amsterdam")
    if zone.startswith("Europe/"):
        zone=zone.split("/",1)[1].replace("_"," ")
    _settings_tile(p,316,83,224,84,"Thema",
                   THEME_TITLES[p.theme],"sun","display")
    _settings_tile(p,552,83,230,84,"Tijdzone",
                   zone,"clock","display")
    _settings_tile(p,316,179,224,84,"Tijdsnotatie",
                   "24-uurs klok" if layout.get("time_format")=="24h" else "12-uurs klok",
                   "clock","time-format")
    sleep_value=int(layout.get("sleep_after_seconds",60))
    sleep_label=("Nooit" if not sleep_value else f"Na {sleep_value} seconden")
    _settings_tile(p,552,179,230,84,"Slaapmodus",
                   sleep_label,"moon","display")
    _settings_tile(p,316,275,224,83,"Gloedeffect",
                   f'{int(layout.get("sleep_glow_intensity",65))}% sterkte',
                   "sun","display")
    _settings_tile(p,552,275,230,83,"Online beheer",
                   _safe(layout.get("cloud_status"),"Cloudinstellingen"),
                   "cloud","cloud")
    _settings_tile(p,316,370,224,89,"Software",
                   "Updates & versie","settings","software")
    _settings_tile(p,552,370,230,89,"Diagnose",
                   "Systeeminformatie","settings","diagnostics")


def render_screen(layout:dict,theme:str,now:datetime,asset_dir:Path,
                  logo_path:Path|None=None,selected_alarm_id:str|None=None,
                  alarm_list_page:int=0) -> tuple[Image.Image,list[HitTarget]]:
    """Render 800×480 met dezelfde werkende WakeSync-data als de huidige GUI.

    Resultaat bevat beeld én raakvlakken; geen fictieve backendacties.
    """
    p=Painter(theme,asset_dir,logo_path)
    screen=str(layout.get("screen","main"))
    p.navigation(screen)
    if screen=="main":
        _draw_today(p,layout,now)
    elif screen=="agenda":
        _draw_agenda(p,layout,now)
    elif screen=="alarm":
        _draw_alarm(p,{**layout,"_list_page":alarm_list_page},now,selected_alarm_id)
    elif screen=="settings":
        _draw_settings(p,layout,now)
    return p.finish()
