"""Colours and ttk styles of the application shell and warehouse pages.

Light (default): navy navigation, light-gray background, white content
cards, blue primary actions, green success, amber warnings, red errors.
Dark: the existing "fsr_night" navy look, with cards one step lighter.

Chart colours follow the reference data-viz palette: categorical slot 1
(blue) = Receiving, slot 2 (orange) = Withdrawal; the reserved status
colours (good / warning / critical) are used only for states and always
come with a text label.
"""

DAY_THEME = "fsr_day"

DAY_COLORS = {
    "primary": "#1f6feb", "secondary": "#5b6b82", "success": "#1e8e5a",
    "info": "#2f80c9", "warning": "#c98500", "danger": "#c9372c",
    "light": "#eef1f5", "dark": "#14213d", "bg": "#f3f5f8", "fg": "#1d2939",
    "selectbg": "#1f6feb", "selectfg": "#ffffff", "border": "#ccd4df",
    "inputfg": "#1d2939", "inputbg": "#ffffff", "active": "#e4e9f0",
}

TOKENS = {
    "light": {
        "sidebar": "#14213d", "sidebar_hover": "#1f3058",
        "sidebar_active": "#1f6feb", "sidebar_fg": "#c9d3e6",
        "sidebar_fg_active": "#ffffff", "sidebar_muted": "#7d8bab",
        "page": "#f3f5f8", "card": "#ffffff", "card_border": "#dde3eb",
        "text": "#1d2939", "text_muted": "#5b6b82", "grid": "#e6eaf0",
        "receiving": "#2a78d6", "withdrawal": "#eb6834",
        "good": "#0ca30c", "warning": "#c98500", "critical": "#d03b3b",
        "neutral": "#8a96a8", "demo": "#fff4d6", "demo_fg": "#7a5200",
        "ramp": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
    },
    "dark": {
        "sidebar": "#0a1226", "sidebar_hover": "#15234a",
        "sidebar_active": "#2a78d6", "sidebar_fg": "#b9c4dd",
        "sidebar_fg_active": "#ffffff", "sidebar_muted": "#6b7894",
        "page": "#0f1a38", "card": "#17254a", "card_border": "#2a3f6f",
        "text": "#e8eefc", "text_muted": "#a9b5cf", "grid": "#26375f",
        "receiving": "#3987e5", "withdrawal": "#d95926",
        "good": "#0ca30c", "warning": "#fab219", "critical": "#e66767",
        "neutral": "#7d8bab", "demo": "#4a3a10", "demo_fg": "#ffe2a0",
        "ramp": ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95"],
    },
}

STATUS_TONES = {        # inventory status -> token (always shown with text)
    "In Stock": "receiving", "Partially Withdrawn": "withdrawal",
    "Fully Withdrawn": "neutral", "Over-Withdrawn": "critical",
    "Reconciliation Required": "warning",
}

FONT = "Segoe UI"


def register_day_theme(style):
    try:
        from ttkbootstrap.style import ThemeDefinition
    except ImportError:
        return False
    for options in ({"mode": "light"}, {"themetype": "light"}):
        try:
            style.register_theme(ThemeDefinition(DAY_THEME, dict(DAY_COLORS),
                                                 **options))
            return True
        except TypeError:
            continue
        except Exception:
            return False
    return False


def is_dark(style):
    try:
        theme = style.theme
        name = theme.name
    except Exception:
        return False
    if name == DAY_THEME:
        return False
    if name in ("fsr_night", "superhero", "darkly", "cyborg", "solar"):
        return True
    return str(getattr(theme, "mode", getattr(theme, "type", ""))) == "dark"


def tokens(style):
    return TOKENS["dark" if is_dark(style) else "light"]


def apply_styles(style):
    """(Re)define the custom styles; styles belong to a theme, so this runs
    again after every theme change."""
    t = tokens(style)
    s = style.configure
    s("Sidebar.TFrame", background=t["sidebar"])
    s("Sidebar.TLabel", background=t["sidebar"], foreground=t["sidebar_fg"],
      font=(FONT, 9))
    s("SidebarBrand.TLabel", background=t["sidebar"], foreground="#ffffff",
      font=(FONT, 13, "bold"))
    s("SidebarMuted.TLabel", background=t["sidebar"],
      foreground=t["sidebar_muted"], font=(FONT, 8, "bold"))
    for name, bg, fg in (("Sidebar.TButton", t["sidebar"], t["sidebar_fg"]),
                         ("SidebarActive.TButton", t["sidebar_active"],
                          t["sidebar_fg_active"])):
        s(name, background=bg, foreground=fg, borderwidth=0, relief="flat",
          anchor="w", padding=(18, 9), font=(FONT, 10), focuscolor=bg,
          bordercolor=bg, lightcolor=bg, darkcolor=bg)
        style.map(name, background=[("active", t["sidebar_hover"]
                                     if name == "Sidebar.TButton"
                                     else t["sidebar_active"])],
                  foreground=[("active", "#ffffff")],
                  bordercolor=[("active", bg)])
    s("Page.TFrame", background=t["page"])
    s("Page.TLabel", background=t["page"], foreground=t["text"])
    s("PageTitle.TLabel", background=t["page"], foreground=t["text"],
      font=(FONT, 16, "bold"))
    s("PageMuted.TLabel", background=t["page"], foreground=t["text_muted"],
      font=(FONT, 9))
    s("Card.TFrame", background=t["card"], bordercolor=t["card_border"],
      relief="solid", borderwidth=1)
    s("CardPlain.TFrame", background=t["card"])
    s("Card.TLabel", background=t["card"], foreground=t["text"],
      font=(FONT, 9))
    s("CardMuted.TLabel", background=t["card"], foreground=t["text_muted"],
      font=(FONT, 8))
    s("CardTitle.TLabel", background=t["card"], foreground=t["text"],
      font=(FONT, 10, "bold"))
    s("KpiName.TLabel", background=t["card"], foreground=t["text_muted"],
      font=(FONT, 9, "bold"))
    s("KpiValue.TLabel", background=t["card"], foreground=t["text"],
      font=(FONT, 18, "bold"))
    s("KpiValueSmall.TLabel", background=t["card"], foreground=t["text"],
      font=(FONT, 11, "bold"))
    for tone in ("good", "warning", "critical", "receiving"):
        s(f"Kpi{tone.title()}.TFrame", background=t[tone])
    s("Card.TCheckbutton", background=t["card"], foreground=t["text"])
    s("Card.TRadiobutton", background=t["card"], foreground=t["text"])
    s("Demo.TFrame", background=t["demo"])
    s("Demo.TLabel", background=t["demo"], foreground=t["demo_fg"],
      font=(FONT, 9, "bold"))
    s("Treeview", rowheight=24)
    s("Treeview.Heading", font=(FONT, 9, "bold"))
    return t
