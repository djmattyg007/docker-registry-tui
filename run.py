import os
import weakref

from docker_registry_client import DockerRegistryClient
from docker_registry_client.Repository import RepositoryV2
from dotenv import load_dotenv

import urwid
from urwid import AttrMap, Filler, Frame, Pile


load_dotenv()

line = urwid.Divider("\N{LOWER ONE QUARTER BLOCK}")
divider = urwid.Divider()


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


def unwrap(widget):
    while isinstance(widget, urwid.WidgetDecoration):
        widget = widget.original_widget
    return widget


def make_menu(choices: list[urwid.WidgetWrap]):
    listbox = urwid.ListBox(
        urwid.SimpleFocusListWalker(choices)
    )
    menu = AttrMap(listbox, "options")
    return menu


def make_menubox(heading: str, choices: list[urwid.WidgetWrap]):
    header = AttrMap(urwid.Text(["\n ", heading]), "heading")
    menu = make_menu(choices)
    frame = Frame(menu, header)
    return frame


class MenuButton(urwid.Button):
    def __init__(self, caption, callback):
        super().__init__("")

        urwid.connect_signal(self, "click", callback)
        self._w = AttrMap(
            urwid.SelectableIcon(["  \N{BULLET} ", caption], 2),
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

        heading = AttrMap(urwid.Text(["\n ", self.tag]), "heading")
        manifest_display = urwid.Text(str(manifest), wrap=urwid.ANY)
        digest_display = urwid.Text(str(digest), wrap=urwid.ANY)

        response_box = Filler(Pile([
            heading,
            AttrMap(line, "line"),
            divider,
            manifest_display,
            digest_display,
            divider,
        ]))
        raise urwid.ExitMainLoop()
        top.open_box(response_box)


class RepositoryMenu(urwid.WidgetWrap):
    def __init__(self, repo: RepositoryV2):
        super().__init__(
            MenuButton(repo.repository, cb(self.open_menu))
        )
        self.repo = repo
        self.menu = None

    def _open_menu(self, heading: str, menu: Frame):
        tags_frame.body = menu

        header = unwrap(tags_frame.header)
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
        choices += [RepositoryMenu(repo) for repo in repositories.values()]
        choices += [RepositoryMenu(repo) for repo in repositories.values()]

        actual_menu = make_menu(choices)
        self.menu = weakref.ref(actual_menu)
        self._open_menu(self.ns, actual_menu)


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


class ChangingText(urwid.Text):
    def __init__(self, markup, change_fmt, *args, **kwargs):
        super().__init__(markup, *args, **kwargs)
        self.change_fmt = change_fmt

    def change_heading(self, value: str):
        self.set_text(self.change_fmt.format(value))


class HorizontalBoxes(urwid.Columns):
    def __init__(self):
        super().__init__([], dividechars=1)

    def open_box(self, box):
        if self.contents:
            del self.contents[self.focus_position + 1 :]
        self.contents.append(
            (AttrMap(box, "options", focus_map), self.options("given", 24))
        )
        self.focus_position = len(self.contents) - 1


namespaces = dclient.namespaces()
# menu_top = make_menubox(
#     "Namespaces",
#     [NamespaceMenu(ns) for ns in namespaces],
# )

screen = urwid.raw_display.Screen()
screen_cols, screen_rows = screen.get_cols_rows()

menu_frame_height = screen_rows // 3
namespaces_frame_height = images_frame_height = tags_frame_height = menu_frame_height
if (menu_frame_height * 3) >= screen_rows - 1:
    namespaces_frame_height -= 1
if (menu_frame_height * 3) >= screen_rows:
    images_frame_height -= 1


def pad_text(widget: urwid.Text):
    return urwid.Padding(widget, left=1, right=1)


namespaces_frame = Frame(
    Filler(
        make_menu([NamespaceMenu(ns) for ns in dclient.namespaces()]),
        valign=urwid.TOP,
        height=menu_frame_height,
    ),
    header=AttrMap(
        pad_text(urwid.Text("Namespaces")),
        "heading",
    ),
    footer=AttrMap(
        pad_text(urwid.Text([str(len(namespaces)), " namespaces"])),
        "footer",
    )
)
images_frame = Frame(
    Filler(
        make_menu([]),
        valign=urwid.TOP,
        height=menu_frame_height,
    ),
    header=AttrMap(
        pad_text(ChangingText("Images", "Images: {}")),
        "heading",
    ),
    footer=AttrMap(
        pad_text(urwid.Text("")),
        "footer",
    ),
)
tags_frame = Frame(
    Filler(
        make_menu([]),
        valign=urwid.TOP,
        height=menu_frame_height,
    ),
    header=AttrMap(
        pad_text(ChangingText("Tags", "Tags: {}")),
        "heading",
    ),
    footer=AttrMap(
        pad_text(urwid.Text("")),
        "footer",
    ),
)

menus_list = [
    (namespaces_frame_height, namespaces_frame),
    divider,
    (images_frame_height, images_frame),
    divider,
    (tags_frame_height, tags_frame),
]
menus_frame = Pile(menus_list, focus_item=0)

#top = HorizontalBoxes()
#top.open_box(menu_top)
try:
    container = urwid.Padding(
        Filler(menus_frame, valign=urwid.TOP),
        width=40,
    )
    # container = Filler(top, "middle", 10)
    loop = urwid.MainLoop(container, palette=palette, screen=screen)
    loop.run()
except KeyboardInterrupt:
    pass
