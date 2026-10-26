"""WakeSync Premium 10.2.2: grotere bediening, dezelfde vier ontwerpen.

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
        # De indeling blijft gelijk; de tabs zijn hoger en staan 6 px lager.
        self.card(216,18,566,60,radius=14,alpha=240)
        tabs=(("main","Vandaag","home"),("agenda","Agenda","calendar"),
              ("alarm","Alarm","clock"),("settings","Instellingen","settings"))
        for index,(screen,title,icon) in enumerate(tabs):
            x=224+index*138
            active=page==screen
            self.rect((x,20,x+130,74),
                      self.pal.raised if active else self.pal.card, radius=11,
                      outline=self.pal.accent if active else self.pal.border)
            if active:
                self.rect((x+24,72,x+106,74),self.pal.accent,2)
            self._icon(icon,x+15,47,self.pal.accent if active else self.pal.muted)
            self.text(x+78,48,title,13,bold=active,
                      color=self.pal.text if active else self.pal.muted,anchor="mm")
            self.hit(x,19,132,58,"nav",screen)

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


def _draw_today(p: Painter, layout: dict, now: datetime) -> None:
    """Rustig startscherm met echte les-/alarmgegevens en temperatuurplaceholder."""
    p.card(18, 83, 310, 289, alpha=224)
    p.clock(173, 222, 127, _safe(layout.get("time"), "07:30"), now)

    p.card(342, 84, 439, 126)
    p._icon("calendar", 364, 111, p.pal.accent)
    p.text(387, 99, _safe(layout.get("lesson_label"), "VOLGENDE LES"), 11, bold=True)
    p.text(363, 133, _safe(layout.get("lesson_subject"), "Geen lessen"), 22,
           bold=True, max_width=385)
    meta = " · ".join(str(v) for v in (
        layout.get("lesson_time"), layout.get("lesson_room")
    ) if v)
    p.text(365, 178, meta or _safe(layout.get("agenda_status")), 11,
           color=p.pal.muted, max_width=380)
    if layout.get("lesson_teacher"):
        p.text(365, 195, "Docent: " + str(layout["lesson_teacher"]), 9,
               color=p.pal.muted, max_width=370)
    p._icon("chevron", 762, 148, p.pal.accent)
    p.hit(342, 84, 439, 126, "nav", "agenda")

    p.card(342, 222, 439, 126)
    p._icon("bell", 364, 252, p.pal.accent)
    p.text(387, 239, "VOLGEND ALARM", 11, bold=True)
    p.text(363, 276, _safe(layout.get("alarm")), 29, bold=True, max_width=186)
    p.pill(573, 270, 159, 35, _safe(layout.get("alarm_day"), "Alarm"),
           font_size=10)
    p.text(363, 324, "Tik om je alarmen te beheren", 10, color=p.pal.muted)
    p._icon("chevron", 762, 289, p.pal.accent)
    p.hit(342, 222, 439, 126, "nav", "alarm")

    # Drie compacte informatietegels zonder motiverende teksten of fictief weer.
    p.card(18, 384, 244, 78, alpha=233)
    p._icon("sun", 42, 414, p.pal.accent_alt)
    p.text(60, 399, "TEMPERATUUR", 9, color=p.pal.muted, bold=True)
    p.text(60, 423, "--", 22, bold=True)
    p.text(109, 431, "°C", 10, color=p.pal.muted)

    p.card(273, 384, 242, 78, alpha=233)
    p._icon("calendar", 294, 414, p.pal.accent_alt)
    p.text(314, 399, "VANDAAG", 9, color=p.pal.muted, bold=True)
    p.text(314, 421, _safe(layout.get("agenda_status"), "Agenda gereed"),
           12, bold=True, max_width=185)
    p.hit(273, 384, 242, 78, "nav", "agenda")

    p.artwork_card(527, 384, 254, 78, darken=.57)
    p._icon("moon", 553, 413, p.pal.accent_alt)
    text_color = p.pal.text if not p.pal.dark else "#FFFFFF"
    p.text(574, 398, "SLAAPSTAND", 9, color=text_color, bold=True)
    p.text(574, 421, "Druk op P om te bekijken", 11, color=text_color,
           max_width=185)

def _draw_agenda(p:Painter,layout:dict,now:datetime) -> None:
    p.card(18,82,535,52)
    p._icon("calendar",39,108,p.pal.accent)
    p.text(61,95,_safe(layout.get("day"),"Vandaag"),14,bold=True,max_width=290)
    p.pill(361,87,51,42,"‹",font_size=22)
    p.pill(419,87,51,42,"›",font_size=22)
    p.pill(477,87,62,42,"Nu",font_size=13)
    p.hit(361,87,51,42,"agenda-day","-1")
    p.hit(419,87,51,42,"agenda-day","1")
    p.hit(477,87,62,42,"agenda-today")

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
    p.pill(580,389,90,48,"‹ Vorige",font_size=12)
    p.pill(676,389,90,48,"Volgende ›",font_size=12)
    if page>1:
        p.hit(580,389,90,48,"agenda-page","-1")
    if page<total:
        p.hit(676,389,90,48,"agenda-page","1")
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
    p.pill(604,89,164,44,"+ Alarm toevoegen",active=True,font_size=12)
    p.hit(604,89,164,44,"new-alarm")

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
        p.text(463,y+7,_alarm_display_name(item),11,bold=True,max_width=87)
        p.text(463,y+31,_safe(item.get("day_label")),10,color=p.pal.muted,max_width=87)
        p._icon("clock",583,y+17,p.pal.accent)
        p.text(583,y+43,f'{item.get("snooze_minutes",9)} m',11,
               color=p.pal.muted,anchor="mm")
        # Eén groot geluidsvlak vervangt de lampoptie totdat die hardware er is.
        p.rect((614,y+8,706,y+54),p.pal.raised,10,200,p.pal.border)
        p._icon("speaker",635,y+31,p.pal.accent if item.get("speaker_enabled") else p.pal.muted)
        p.text(652,y+24,"Aan" if item.get("speaker_enabled") else "Uit",10,
               bold=True,color=p.pal.text)
        p.toggle(716,y+15,bool(item.get("enabled")),w=48,h=32)
        p.hit(352,y,201,62,"select-alarm",alarm_id)
        p.hit(554,y,59,62,"cycle-snooze",alarm_id)
        p.hit(614,y,92,62,"toggle-speaker",alarm_id)
        p.hit(710,y,56,62,"toggle-alarm",alarm_id)
    if page_count>1:
        p.pill(461,420,77,38,"‹",font_size=20)
        p.text(560,439,f"{page+1}/{page_count}",11,color=p.pal.muted,anchor="mm")
        p.pill(584,420,77,38,"›",font_size=20)
        if page>0:
            p.hit(461,420,77,38,"alarm-page","-1")
        if page+1<page_count:
            p.hit(584,420,77,38,"alarm-page","1")
    else:
        p.text(362,441,"Tik op een alarm voor alle instellingen",9,color=p.pal.muted)


def _settings_tile(p:Painter,x:int,y:int,w:int,h:int,title:str,
                   value:str,icon:str,action:str,payload:str="") -> None:
    p.card(x,y,w,h,radius=13)
    p._icon(icon,x+21,y+22,p.pal.accent)
    p.text(x+39,y+10,title,14,bold=True,max_width=w-56)
    p.text(x+20,y+42,value,12,color=p.pal.muted,max_width=w-37)
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
        x=34+i*64
        p.rect((x,392,x+55,446),PALETTES[theme_id].card,10,255,
               p.pal.accent if p.theme==theme_id else "#A0A0A0")
        p.circle(x+27,419,8,PALETTES[theme_id].accent)
        p.hit(x,392,55,54,"theme",theme_id)

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
                   "Updates & versie","settings","settings","software")
    _settings_tile(p,552,370,230,89,"Diagnose",
                   "Systeeminformatie","settings","settings","diagnostics")


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


# ---------------------------------------------------------------------------
# Uitgebreide themavensters voor de instellingen en bestaande alarmprofielen
# ---------------------------------------------------------------------------

def _detail_top(p: Painter, title: str, subtitle: str) -> None:
    p.card(18, 18, 764, 60, alpha=245)
    p.pill(28, 24, 137, 48, "‹ Terug", font_size=15)
    p.hit(28, 24, 137, 48, "close-detail")
    p.text(184, 27, title, 18, bold=True, max_width=400)
    p.text(184, 53, subtitle, 10, color=p.pal.muted, max_width=510)
    p._icon("settings", 753, 47, p.pal.accent)


def _detail_setting(
    p: Painter, x: int, y: int, w: int, title: str, value: str,
    icon: str, action: str, payload: str = "",
) -> None:
    p.card(x, y, w, 83, radius=14)
    p._icon(icon, x + 23, y + 27, p.pal.accent)
    p.text(x + 42, y + 12, title, 14, bold=True, max_width=w - 60)
    p.text(x + 18, y + 49, value, 12, color=p.pal.muted, max_width=w - 38)
    p._icon("chevron", x + w - 19, y + 56, p.pal.accent)
    p.hit(x, y, w, 83, action, payload)


def _format_sleep_after(seconds: int) -> str:
    if seconds == 0:
        return "Uit"
    if seconds < 60:
        return f"{seconds} seconden"
    return f"{seconds // 60} minuten"


def render_detail_screen(
    kind: str, theme: str, now: datetime, asset_dir: Path,
    *, settings: Any = None, item: dict[str, Any] | None = None,
) -> tuple[Image.Image, list[HitTarget]]:
    """Themagebonden en touchbedienbare alarmpagina en weergave-instellingen."""
    p = Painter(theme, asset_dir, logo_path=None)
    if kind not in {"display", "alarm"}:
        raise ValueError("Onbekende detailweergave")
    if kind == "display":
        _detail_top(p, "Weergave & thema", "Kies een stijl en stel de slaapstand in")
        p.artwork_card(18, 82, 274, 379, darken=.52)
        # Een subtiele glasplaat bewaart contrast boven de illustratie.
        p.rect((29, 100, 281, 172), p.pal.bg, 12, 200)
        p.text(45, 113, "GESELECTEERD THEMA", 10, color=p.pal.accent_alt, bold=True)
        p.text(45, 139, THEME_TITLES[p.theme], 18, bold=True,
               max_width=222)
        p.text(38, 333, "Kies een thema", 10, bold=True,
               color="#FFFFFF" if p.pal.dark else p.pal.text)
        for i, theme_id in enumerate(THEME_IDS):
            x = 37 + i * 62
            pal = PALETTES[theme_id]
            p.rect((x, 358, x + 56, 422), pal.card, 10, 255,
                   pal.accent if p.theme == theme_id else p.pal.muted)
            p.circle(x + 28, 390, 11, pal.accent)
            p.hit(x, 358, 56, 64, "theme", theme_id)
        p.text(38, 429, "Van blauw tot warm amber", 10,
               color="#FFFFFF" if p.pal.dark else p.pal.text)

        locale = settings.locale
        display = settings.display
        timezone_name = str(locale.timezone).replace("Europe/", "").replace("_", " ")
        sleep_effect_name = dict((
            ("off", "Uit"), ("soft_glow", "Zachte gloed"),
            ("pulse_glow", "Pulserende gloed"), ("aurora", "Aurora"),
            ("liquid_motion", "Liquid Motion"),
        )).get(display.sleep_effect, display.sleep_effect)
        view_name = dict((
            ("logo", "Alleen logo"), ("logo_time", "Logo en tijd"),
            ("logo_time_date", "Logo, tijd en datum"),
        )).get(display.sleep_view, str(display.sleep_view))
        _detail_setting(p, 307, 82, 227, "Tijdzone", timezone_name,
                        "clock", "next-timezone")
        _detail_setting(p, 546, 82, 237, "Tijdsnotatie",
                        "24 uur" if locale.time_format == "24h" else "12 uur",
                        "clock", "time-format")
        _detail_setting(p, 307, 176, 227, "Slaapstand na",
                        _format_sleep_after(int(display.sleep_after_seconds)),
                        "moon", "next-sleep-after")
        _detail_setting(p, 546, 176, 237, "Slaapscherm toont",
                        view_name, "moon", "next-sleep-view")
        _detail_setting(p, 307, 270, 227, "Slaapeffect", sleep_effect_name,
                        "sun", "next-sleep-effect")
        _detail_setting(p, 546, 270, 237, "Gloedsterkte",
                        f"{int(display.sleep_glow_intensity)}%", "sun",
                        "next-glow")
        _detail_setting(p, 307, 364, 227, "Helderheid",
                        f"{int(display.brightness)}%", "sun", "next-brightness")
        _detail_setting(p, 546, 364, 237, "Sleepscreen testen",
                        "Druk op P", "moon", "preview-sleep")
    else:
        if item is None:
            raise ValueError("Alarmgegevens ontbreken")
        _detail_top(p, "Alarm aanpassen", "Geluid en snooze voor je alarm")
        p.artwork_card(18, 82, 274, 379, darken=.62)
        p.rect((30, 100, 280, 230), p.pal.bg, 16, 206)
        p.text(155, 112, "GESELECTEERD ALARM", 10, color=p.pal.accent_alt,
               bold=True, anchor="mt")
        p.text(155, 151, _safe(item.get("time"), "07:30"), 46, bold=True,
               anchor="mt", max_width=230)
        p.text(155, 211, _safe(item.get("day_label"), "Dagelijks"), 11,
               color=p.pal.muted, anchor="mm")
        p.pill(42, 249, 228, 46,
               "Ingeschakeld" if item.get("enabled") else "Uitgeschakeld",
               active=bool(item.get("enabled")), font_size=14)
        p.hit(42, 249, 228, 46, "alarm-enabled")
        p.pill(42, 342, 228, 46, "Geluid testen", font_size=14)
        p.hit(42, 342, 228, 46, "test-audio")
        p.pill(42, 402, 228, 46, "Alarm verwijderen", font_size=14,
               bg=p.pal.card, fg="#F38A92" if p.pal.dark else "#BA3039")
        p.hit(42, 402, 228, 46, "alarm-delete")

        sound = str(item.get("sound", "beep")).capitalize()
        _detail_setting(p, 307, 82, 227, "Snooze",
                        f'{int(item.get("snooze_minutes", 9))} minuten',
                        "clock", "alarm-snooze")
        _detail_setting(p, 546, 82, 237, "Geluid", sound,
                        "speaker", "alarm-sound")
        _detail_setting(p, 307, 176, 227, "Speaker",
                        "Aan" if item.get("speaker_enabled") else "Uit",
                        "speaker", "alarm-speaker")
        _detail_setting(p, 546, 176, 237, "Volume",
                        f'{int(item.get("volume", 70))}% · tik voor +10',
                        "speaker", "alarm-volume")
        _detail_setting(p, 307, 270, 227, "Opbouw",
                        f'{int(item.get("ramp_up_seconds", 30))} seconden',
                        "clock", "alarm-ramp")
        # Deze informatiekaarten zijn niet klikbaar. Geen verwijzingen naar
        # nog niet aangesloten fysieke lampen of knoppen.
        p.card(546, 270, 237, 83, radius=14)
        p._icon("clock", 569, 297, p.pal.accent)
        p.text(588, 282, "Bediening", 14, bold=True, max_width=175)
        p.text(564, 319, "Snooze en stop op scherm", 11,
               color=p.pal.muted, max_width=196)
        p.card(307, 364, 476, 83, radius=14)
        p._icon("speaker", 330, 392, p.pal.accent)
        p.text(349, 376, "Geluid controleren", 14, bold=True)
        p.text(325, 414, "Gebruik 'Geluid testen' links om de luidspreker te horen.",
               11, color=p.pal.muted, max_width=430)
    return p.finish()


def render_sleep_screen(
    theme: str, now: datetime, asset_dir: Path,
    *, logo_path: Path | None = None, time_text: str | None = None,
    view: str = "logo_time_date", glow: int = 65,
) -> Image.Image:
    """Rustig 800×480-slaapscherm; de goedgekeurde C9-logopixels blijven intact.

    Deze afbeelding wordt één keer aangelegd. De tijd wordt daarna in Tk
    bijgewerkt; er is geen dure volledige renderloop tijdens slaapmodus.
    """
    theme = theme if theme in PALETTES else "midnight"
    pal = PALETTES[theme]
    source = _art_source(theme, str(asset_dir.resolve()))
    if source is None:
        source = Image.new("RGBA", (WIDTH, HEIGHT), pal.bg)
    image = source.resize((WIDTH*SCALE, HEIGHT*SCALE), Image.Resampling.LANCZOS).convert("RGBA")
    overlay_color = {
        "midnight": (3, 8, 22, 115),
        "ocean": (1, 7, 27, 102),
        "light": (11, 24, 50, 170),
        "amber": (13, 7, 10, 123),
    }[theme]
    image.alpha_composite(Image.new("RGBA", image.size, overlay_color))
    d = ImageDraw.Draw(image, "RGBA")

    def xy(v: float) -> int:
        return round(v*SCALE)

    accent = pal.accent
    if theme == "light":
        accent = "#9BCFFF"
    # Ring of lijnaccent geeft de vier sleepscreens hun eigen karakter.
    strength = max(0.0, min(1.0, int(glow)/100))
    if theme in {"midnight", "amber"}:
        radius = 134 if theme == "midnight" else 117
        box = (xy(400-radius), xy(246-radius), xy(400+radius), xy(246+radius))
        for width, alpha in ((19, 21), (11, 41), (3, 210)):
            d.arc(box, 10, 350, fill=(*_rgb(accent), round(alpha*strength)),
                  width=xy(width))
    elif theme == "ocean":
        d.arc((xy(260),xy(100),xy(540),xy(380)), 185, 355,
              fill=(*_rgb("#60F6E4"), round(180*strength)), width=xy(3))
        d.arc((xy(272),xy(111),xy(528),xy(369)), 20, 180,
              fill=(*_rgb("#9F89FF"), round(130*strength)), width=xy(3))
    else:
        d.arc((xy(264),xy(108),xy(536),xy(380)), 20, 160,
              fill=(*_rgb("#D1E4FC"), round(182*strength)), width=xy(2))

    # Logoplaat altijd boven de klok, niet over de cijfers.
    d.rounded_rectangle((xy(294),xy(24),xy(506),xy(91)),radius=xy(15),
                        fill=(255,255,255,234))
    if logo_path is not None and logo_path.is_file():
        with Image.open(logo_path) as original:
            logo = original.convert("RGBA")
        logo.thumbnail((191*SCALE, 58*SCALE), Image.Resampling.LANCZOS)
        image.alpha_composite(logo, ((image.width-logo.width)//2, xy(27)+(xy(61)-logo.height)//2))
    else:
        d.text((xy(400), xy(59)), "WakeSync", fill=(15,34,59,255),
               font=_font(21, True), anchor="mm")

    if view in {"logo_time", "logo_time_date"}:
        shown = time_text if time_text is not None else now.strftime("%H:%M")
        d.text((xy(400),xy(265)), str(shown),
               font=_font(67 if len(shown)<=5 else 53,True), anchor="mm",
               fill=(251,253,255,255),
               stroke_width=xy(1), stroke_fill=(12,22,37,100))
    if view == "logo_time_date":
        day = f"{DAY_NAMES[now.weekday()].capitalize()} {now.day} {MONTH_NAMES[now.month]}"
        d.text((xy(400),xy(329)), day, fill=(224,236,250,245),
               font=_font(15), anchor="mm")
    d.text((xy(400),xy(457)), "Tik op het scherm om te openen",
           font=_font(9), fill=(225,238,252,177), anchor="mm")
    return image.convert("RGB").resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS)
