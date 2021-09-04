import dataclasses
import itertools
import os
import weakref
from typing import Iterable

from dotenv import load_dotenv
from dreg_client import PlatformImage, Registry, Repository
from humanfriendly import format_size
import simplejson as json

import urwid
from urwid import AttrMap, Columns, Filler, Frame, Pile, SolidFill, Text
from additional_urwid_widgets import IndicativeListBox

from dreg.scrollable import Scrollable
from dreg.selectable_row import BetterSelectableRow


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


dclient = Registry.build_with_manual_client(
    os.getenv("REGISTRY_URL"),
    auth=(os.getenv("REGISTRY_USERNAME"), os.getenv("REGISTRY_PASSWORD")),
)
dclient.refresh()


def asdicts(data_objs: Iterable) -> Iterable[dict]:
    for data_obj in data_objs:
        yield dataclasses.asdict(data_obj)


def sum_layer_sizes(pimage: PlatformImage) -> int:
    return sum(map(lambda layer: layer.size, pimage.layers))


def trim_digest(digest: str) -> str:
    return digest[7:19]


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


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
    return json.dumps(input_json, cls=JSONEncoder, indent=2, allow_nan=False, iterable_as_array=True)


def make_menu(choices: list[urwid.WidgetWrap]):
    listbox = IndicativeListBox(
        urwid.SimpleFocusListWalker(choices)
    )
    menu = AttrMap(listbox, "options")
    return menu


class MenuButton(urwid.Button):
    def __init__(self, caption, callback):
        super().__init__("")

        urwid.connect_signal(self, "click", callback)
        self._w = AttrMap(
            urwid.SelectableIcon([" \N{BULLET} ", caption], 2),
            None,
            "selected",
        )


class PlatformChoice(BetterSelectableRow):
    def __init__(self, pimage: PlatformImage):
        def columns_factory(*args, **kwargs):
            columns = Columns(*args, **kwargs)
            return AttrMap(columns, None, "selected")

        def column_factory(*args, **kwargs):
            return pad_text(urwid.Text(*args, **kwargs))

        image_size = sum_layer_sizes(pimage)
        super().__init__(
            [pimage.platform_name, trim_digest(pimage.digest), format_size(image_size, binary=True)],
            on_select=cb(self.item_chosen),
            space_between=1,
            columns_factory=columns_factory,
            column_factory=column_factory,
        )
        self.pimage = pimage
        self.menu = None

    def item_chosen(self):
        raise urwid.ExitMainLoop()


class TagChoice(urwid.WidgetWrap):
    def __init__(self, repo: Repository, tag: str):
        super().__init__(
            MenuButton(tag, cb(self.open_menu))
        )
        self.repo = repo
        self.tag = tag
        self.menu = None

    def _open_menu(self, menu):
        reset_display()

        header: Text = unwrap(display_frame.header)
        header.set_text(f"{self.repo.name} - {self.tag}")

        platforms_frame.body = menu

        container.focus_position = 1

    def open_menu(self):
        menu = self.menu
        if menu:
            actual_menu = menu()
            if actual_menu:
                self._open_menu(actual_menu)
                return

        image = self.repo.get_image(self.tag)
        pimages = image.get_platform_images()
        choices = [PlatformChoice(pimage) for pimage in pimages]

        actual_menu = make_menu(choices)
        self.menu = weakref.ref(actual_menu)
        self._open_menu(actual_menu)

    # def item_chosen(self):
    #     header: Text = unwrap(display_frame.header)
    #     header.set_text(f"{self.repo.name}: {self.tag}")
    #
    #     try:
    #         image = self.repo.get_image(self.tag)
    #
    #         image_pp = ppjson(image.manifest_list)
    #         digest_display = Text(image.manifest_list.digest, wrap=urwid.ANY)
    #         manifest_display = Text(image_pp * 2, wrap=urwid.ANY)
    #         display_items = [digest_display, divider, manifest_display]
    #     except Exception as e:
    #         display_items = [
    #             Text("An error occurred."),
    #             divider,
    #             Text("{0}: {1}".format(e.__class__.__name__, str(e))),
    #         ]
    #
    #     display = Pile(display_items)
    #     platforms_frame.body = Filler(display)
    #     layers_frame.body = Scrollable(display)
    #
    #     container.focus_position = 1


class RepositoryMenu(urwid.WidgetWrap):
    def __init__(self, repo: Repository):
        super().__init__(
            MenuButton(repo.repository, cb(self.open_menu))
        )
        self.repo = repo
        self.menu = None

    def _open_menu(self, menu):
        reset_display()
        tags_frame.body = menu

        header: ChangingText = unwrap(tags_frame.header)
        header.change_heading(self.repo.name)

        footer: Text = unwrap(tags_frame.footer)
        listbox: IndicativeListBox = unwrap(menu)
        item_count = listbox.body_len()
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
                self._open_menu(actual_menu)
                return

        tags = self.repo.tags()
        choices = [TagChoice(self.repo, tag) for tag in tags]

        actual_menu = make_menu(choices)
        self.menu = weakref.ref(actual_menu)
        self._open_menu(actual_menu)


class NamespaceMenu(urwid.WidgetWrap):
    def __init__(self, ns: str):
        super().__init__(
            MenuButton(ns, cb(self.open_menu))
        )
        self.ns = ns
        self.menu = None

    def _open_menu(self, menu):
        reset_display()
        tags_frame.body = make_menu([])
        images_frame.body = menu

        header: ChangingText = unwrap(images_frame.header)
        header.change_heading(self.ns)

        footer: Text = unwrap(images_frame.footer)
        listbox: IndicativeListBox = unwrap(menu)
        item_count = listbox.body_len()
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
                self._open_menu(actual_menu)
                return

        repositories = dclient.repositories(namespace=self.ns)
        choices = [RepositoryMenu(repo) for repo in repositories.values()]

        actual_menu = make_menu(choices)
        self.menu = weakref.ref(actual_menu)
        self._open_menu(actual_menu)


class ChangingText(Text):
    def __init__(self, markup, change_fmt, *args, **kwargs):
        super().__init__(markup, *args, **kwargs)
        self.change_fmt = change_fmt

    def change_heading(self, value: str):
        self.set_text(self.change_fmt.format(value))


class ResettableFrame(Frame):
    def __init__(self, body, header=None, footer=None, focus_part="body"):
        super().__init__(body, header=header, footer=footer, focus_part=focus_part)

        self.orig_body = body
        self.orig_header_text = None
        self.orig_footer_text = None

        if header:
            header_widget: Text = unwrap(header)
            self.orig_header_text = header_widget.text

        if footer:
            footer_widget: Text = unwrap(footer)
            self.orig_footer_text = footer_widget.text

    def reset(self):
        self.body = self.orig_body

        if self.orig_header_text is not None:
            header_widget: Text = unwrap(self.header)
            header_widget.set_text(self.orig_header_text)

        if self.orig_footer_text is not None:
            footer_widget: Text = unwrap(self.footer)
            footer_widget.set_text(self.orig_footer_text)


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

platforms_frame = ResettableFrame(
    SolidFill(),
)
layers_frame = ResettableFrame(
    SolidFill(),
)

display_pile = Pile([])
display_pile.contents.append((
    platforms_frame, Pile.options(urwid.GIVEN, 7)
))
display_pile.contents.append((
    Filler(divider), Pile.options(urwid.GIVEN, 1)
))
display_pile.contents.append((
    layers_frame, Pile.options(urwid.WEIGHT, 1)
))
display_frame = ResettableFrame(
    Filler(display_pile, height=screen_rows - 1),
    header=AttrMap(
        pad_text(Text("", align=urwid.CENTER)),
        "heading",
    ),
)


def reset_display():
    layers_frame.reset()
    platforms_frame.reset()
    display_frame.reset()


try:
    container = Columns([], dividechars=1, focus_column=0)
    container.contents.append((
        menus_container,
        Columns.options(urwid.GIVEN, 36),
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
