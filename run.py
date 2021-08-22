import itertools
import json
import os
import weakref

from docker_registry_client import DockerRegistryClient
from docker_registry_client.Repository import RepositoryV2
from dotenv import load_dotenv

import urwid
from urwid import AttrMap, Columns, Filler, Frame, Pile, Text

from dreg.scrollable import Scrollable


load_dotenv()

line = urwid.Divider("\N{LOWER ONE QUARTER BLOCK}")
divider = urwid.Divider()

palette = [
    (None, "light gray", "black"),
    ("heading", "black", "light gray"),
    ("footer", "black", "light gray"),
    ("line", "black", "light gray"),
    ("options", "dark gray", "black"),
    ("focus heading", "white", "dark red"),
    ("focus line", "black", "dark red"),
    ("focus options", "black", "light gray"),
    ("selected", "white", "dark blue"),
]
focus_map = {
    "heading": "focus heading",
    "footer": "footer",
    "options": "focus options",
    "line": "focus line",
}

screen = urwid.raw_display.Screen()
screen_cols, screen_rows = screen.get_cols_rows()


dclient = DockerRegistryClient(
    host="https://" + os.getenv("REGISTRY_HOSTNAME"),
    username=os.getenv("REGISTRY_USERNAME"),
    password=os.getenv("REGISTRY_PASSWORD"),
    api_version=2,
)
dclient.refresh()


def cb(func):
    def wrap(*args, **kwargs):
        func()
    return wrap


def unwrap(widget: urwid.Widget) -> urwid.Widget:
    while isinstance(widget, urwid.WidgetDecoration):
        widget = widget.original_widget
    return widget


def ppjson(input_json) -> str:
    if isinstance(input_json, str):
        input_json = json.loads(input_json)
    return json.dumps(input_json, indent=2)


def make_menu(choices: list[urwid.WidgetWrap]):
    listbox = urwid.ListBox(
        urwid.SimpleFocusListWalker(choices)
    )
    menu = AttrMap(listbox, "options")
    return menu


def make_menubox(heading: str, choices: list[urwid.WidgetWrap]):
    header = AttrMap(Text(["\n ", heading]), "heading")
    menu = make_menu(choices)
    frame = Frame(menu, header)
    return frame


class MenuButton(urwid.Button):
    def __init__(self, caption, callback):
        super().__init__("")

        urwid.connect_signal(self, "click", callback)
        self._w = AttrMap(
            urwid.SelectableIcon([" \N{BULLET} ", caption], 2),
            None,
            "selected",
        )


class TagChoice(urwid.WidgetWrap):
    def __init__(self, repo: RepositoryV2, tag: str):
        super().__init__(
            MenuButton(tag, cb(self.item_chosen))
        )
        self.repo = repo
        self.tag = tag
        self.menu = None

    def item_chosen(self):
        manifest, digest = self.repo.manifest(self.tag)

        manifest_pp = ppjson(manifest)

        header: Text = unwrap(display_frame.header)
        header.set_text(f"{self.repo.name}: {self.tag}")

        digest_display = Text(digest, wrap=urwid.ANY)
        manifest_display = Text(manifest_pp, wrap=urwid.ANY)
        display = Pile([digest_display, divider, manifest_display])
        display_frame.body = Scrollable(display)

        container.focus_position = 1


class RepositoryMenu(urwid.WidgetWrap):
    def __init__(self, repo: RepositoryV2):
        super().__init__(
            MenuButton(repo.repository, cb(self.open_menu))
        )
        self.repo = repo
        self.menu = None

    def _open_menu(self, heading: str, menu: Frame):
        tags_frame.body = menu

        header: ChangingText = unwrap(tags_frame.header)
        header.change_heading(heading)

        footer = unwrap(tags_frame.footer)
        listbox: urwid.ListBox = unwrap(menu)
        item_count = len(listbox.body)
        if item_count == 1:
            footer.set_text("1 tag")
        else:
            footer.set_text(f"{item_count} tags")

        menus_frame.focus_position = 4

    def open_menu(self):
        menu = self.menu
        if menu:
            actual_menu = menu()
            if actual_menu:
                self._open_menu(self.repo.name, actual_menu)
                return

        tags = self.repo.tags()
        choices = [TagChoice(self.repo, tag) for tag in tags]

        actual_menu = make_menu(choices)
        self.menu = weakref.ref(actual_menu)
        self._open_menu(self.repo.name, actual_menu)


class NamespaceMenu(urwid.WidgetWrap):
    def __init__(self, ns: str):
        super().__init__(
            MenuButton(ns, cb(self.open_menu))
        )
        self.ns = ns
        self.menu = None

    def _open_menu(self, heading: str, menu):
        images_frame.body = menu

        header = unwrap(images_frame.header)
        header.change_heading(heading)

        footer = unwrap(images_frame.footer)
        listbox: urwid.ListBox = unwrap(menu)
        item_count = len(listbox.body)
        if item_count == 1:
            footer.set_text("1 image")
        else:
            footer.set_text(f"{item_count} images")

        menus_frame.focus_position = 2

    def open_menu(self):
        menu = self.menu
        if menu:
            actual_menu = menu()
            if actual_menu:
                self._open_menu(self.ns, actual_menu)
                return

        repositories = dclient.repositories(namespace=self.ns)
        choices = [RepositoryMenu(repo) for repo in repositories.values()]

        actual_menu = make_menu(choices)
        self.menu = weakref.ref(actual_menu)
        self._open_menu(self.ns, actual_menu)


class ChangingText(Text):
    def __init__(self, markup, change_fmt, *args, **kwargs):
        super().__init__(markup, *args, **kwargs)
        self.change_fmt = change_fmt

    def change_heading(self, value: str):
        self.set_text(self.change_fmt.format(value))


class PileMenu(Pile):
    def __init__(self, widget_list):
        super().__init__([])

        widget_count = len(widget_list)
        menu_height = screen_rows // widget_count
        reduce_height_pool = screen_rows - (widget_count * menu_height) - (widget_count - 1)

        dividers = itertools.repeat(divider, widget_count - 1)
        for i, (menu, _divider) in enumerate(itertools.zip_longest(widget_list, dividers)):
            height = menu_height
            if reduce_height_pool < 0:
                height -= 1
                reduce_height_pool += 1

            self.contents.append((
                AttrMap(menu, "options", focus_map),
                (urwid.GIVEN, height),
            ))

            if _divider:
                self.contents.append((_divider, (urwid.WEIGHT, 1)))

        self.focus_position = 0


def pad_text(widget: Text):
    return urwid.Padding(widget, left=1, right=1)


namespaces = dclient.namespaces()
namespaces_frame = Frame(
    make_menu([NamespaceMenu(ns) for ns in namespaces]),
    header=AttrMap(
        pad_text(Text("Namespaces")),
        "heading",
    ),
    footer=AttrMap(
        pad_text(Text([str(len(namespaces)), " namespaces"])),
        "footer",
    )
)
images_frame = Frame(
    make_menu([]),
    header=AttrMap(
        pad_text(ChangingText("Images", "Images: {}")),
        "heading",
    ),
    footer=AttrMap(
        pad_text(Text("")),
        "footer",
    ),
)
tags_frame = Frame(
    make_menu([]),
    header=AttrMap(
        pad_text(ChangingText("Tags", "Tags: {}")),
        "heading",
    ),
    footer=AttrMap(
        pad_text(Text("")),
        "footer",
    ),
)

menus_frame = PileMenu([namespaces_frame, images_frame, tags_frame])
menus_container = Filler(menus_frame, valign=urwid.TOP)

display_frame = Frame(
    urwid.SolidFill(),
    header=AttrMap(
        pad_text(Text("", align=urwid.CENTER)),
        "heading",
    ),
)

try:
    container = Columns([], dividechars=1, focus_column=0)
    container.contents.append((
        menus_container,
        Columns.options(urwid.GIVEN, 40),
    ))
    container.contents.append((
        Filler(
            AttrMap(display_frame, "options", focus_map),
            valign=urwid.TOP,
            height=screen_rows,
        ),
        Columns.options(),
    ))

    loop = urwid.MainLoop(container, palette=palette, screen=screen, handle_mouse=False)
    loop.run()
except KeyboardInterrupt:
    pass
