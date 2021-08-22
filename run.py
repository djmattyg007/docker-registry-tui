import os
import weakref

from docker_registry_client import DockerRegistryClient
from docker_registry_client.Repository import RepositoryV2
from dotenv import load_dotenv
import urwid


load_dotenv()


dclient = DockerRegistryClient(
    host="https://" + os.getenv("REGISTRY_HOSTNAME"),
    username=os.getenv("REGISTRY_USERNAME"),
    password=os.getenv("REGISTRY_PASSWORD"),
)
dclient.refresh()


def cb(func):
    def wrap(*args, **kwargs):
        func()
    return wrap


def make_menu(heading: str, choices: list[urwid.WidgetWrap]):
    header = urwid.AttrMap(urwid.Text(["\n ", heading]), "heading")

    listbox = urwid.ListBox(
        urwid.SimpleFocusListWalker(choices)
    )
    menu = urwid.AttrMap(listbox, "options")
    frame = urwid.Frame(menu, header)
    return frame


class MenuButton(urwid.Button):
    def __init__(self, caption, callback):
        super().__init__("")

        urwid.connect_signal(self, "click", callback)
        self._w = urwid.AttrMap(
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

        heading = urwid.AttrMap(urwid.Text(["\n ", self.tag]), "heading")
        line = urwid.Divider("\N{LOWER ONE QUARTER BLOCK}")
        manifest_display = urwid.Text(str(manifest), wrap=urwid.ANY)
        digest_display = urwid.Text(str(digest), wrap=urwid.ANY)

        response_box = urwid.Filler(urwid.Pile([
            heading,
            urwid.AttrMap(line, "line"),
            urwid.Divider(),
            manifest_display,
            digest_display,
            urwid.Divider(),
        ]))
        top.open_box(response_box)


class RepositoryMenu(urwid.WidgetWrap):
    def __init__(self, repo: RepositoryV2):
        super().__init__(
            MenuButton(repo.repository, cb(self.open_menu))
        )
        self.repo = repo
        self.menu = None

    def open_menu(self):
        menu = self.menu
        if menu:
            actual_menu = menu()
            if actual_menu:
                top.open_box(actual_menu)
                return

        tags = self.repo.tags()
        choices = [TagChoice(self.repo, tag) for tag in tags]

        actual_menu = make_menu(self.repo.name, choices)
        self.menu = weakref.ref(actual_menu)
        top.open_box(actual_menu)


class NamespaceMenu(urwid.WidgetWrap):
    def __init__(self, ns: str):
        super().__init__(
            MenuButton(ns, cb(self.open_menu))
        )
        self.ns = ns
        self.menu = None

    def open_menu(self):
        menu = self.menu
        if menu:
            actual_menu = menu()
            if actual_menu:
                top.open_box(actual_menu)
                return

        repositories = dclient.repositories(namespace=self.ns)
        choices = [RepositoryMenu(repo) for repo in repositories.values()]
        choices += [RepositoryMenu(repo) for repo in repositories.values()]
        choices += [RepositoryMenu(repo) for repo in repositories.values()]

        actual_menu = make_menu(self.ns, choices)
        self.menu = weakref.ref(actual_menu)
        top.open_box(actual_menu)


palette = [
    (None, "light gray", "black"),
    ("heading", "black", "light gray"),
    ("line", "black", "light gray"),
    ("options", "dark gray", "black"),
    ("focus heading", "white", "dark red"),
    ("focus line", "black", "dark red"),
    ("focus options", "black", "light gray"),
    ("selected", "white", "dark blue"),
]
focus_map = {
    "heading": "focus heading",
    "options": "focus options",
    "line": "focus line",
}


class HorizontalBoxes(urwid.Columns):
    def __init__(self):
        super().__init__([], dividechars=1)

    def open_box(self, box):
        if self.contents:
            del self.contents[self.focus_position + 1 :]
        self.contents.append(
            (urwid.AttrMap(box, "options", focus_map), self.options("given", 24))
        )
        self.focus_position = len(self.contents) - 1


menu_top = make_menu(
    "Namespaces",
    [NamespaceMenu(ns) for ns in dclient.namespaces()],
)

top = HorizontalBoxes()
top.open_box(menu_top)
try:
    container = urwid.Filler(top, "middle", 10)
    loop = urwid.MainLoop(container, palette)
    loop.run()
except KeyboardInterrupt:
    pass
