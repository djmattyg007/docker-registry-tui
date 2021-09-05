from __future__ import annotations

import dataclasses
import itertools
import os
import weakref
from typing import Iterable, Optional

from dotenv import load_dotenv
from dreg_client import Platform, PlatformImage, Registry, Repository
from humanfriendly import format_size as base_format_size
import simplejson as json

import urwid
from urwid import AttrMap, Columns, Filler, Frame, Pile, SolidFill, Text
from additional_urwid_widgets import IndicativeListBox

from dreg.scrollable import Scrollable
from dreg.selectable_row import BetterSelectableRow


LAYER_HISTORY_INSTR_PREFIX = "/bin/sh -c #(nop)"
LAYER_HISTORY_INSTR_SUFFIX_BUILDKIT = "# buildkit"


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


preferred_platform_name = os.getenv("DREG_PREFERRED_PLATFORM")
preferred_platform: Optional[Platform]
if preferred_platform_name:
    preferred_platform = Platform.from_name(preferred_platform_name)
else:
    preferred_platform = None

dclient = Registry.build_with_manual_client(
    os.getenv("REGISTRY_URL"),
    auth=(os.getenv("REGISTRY_USERNAME"), os.getenv("REGISTRY_PASSWORD")),
)
dclient.refresh()


def asdicts(data_objs: Iterable) -> Iterable[dict]:
    for data_obj in data_objs:
        yield dataclasses.asdict(data_obj)


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    return base_format_size(num_bytes, binary=True)


def sum_layer_sizes(pimage: PlatformImage) -> int:
    return sum(map(lambda layer: layer.size, pimage.layers))


def trim_digest(digest: str) -> str:
    return digest[7:19]


def clean_created_by(created_by: str) -> str:
    created_by = created_by.strip()

    if created_by.startswith(LAYER_HISTORY_INSTR_PREFIX):
        created_by = created_by[len(LAYER_HISTORY_INSTR_PREFIX):].strip()
    if created_by.endswith(LAYER_HISTORY_INSTR_SUFFIX_BUILDKIT):
        created_by = created_by[:-len(LAYER_HISTORY_INSTR_SUFFIX_BUILDKIT)].strip()

    return created_by


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


def make_menu(choices: list[urwid.WidgetWrap], **kwargs):
    listbox = IndicativeListBox(
        urwid.SimpleFocusListWalker(choices),
        **kwargs,
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


class LayerChoice(BetterSelectableRow):
    def __init__(self, pimage: PlatformImage, history_idx: int):
        def columns_factory(*args, **kwargs):
            columns = Columns(*args, **kwargs)
            return AttrMap(columns, None, "selected")

        def column_factory(*args, **kwargs):
            return pad_text(Text(*args, **kwargs))

        history_item = pimage.config.history[history_idx]
        if history_item.empty_layer:
            size_str = format_size(0)
        else:
            layer_idx = None
            non_empty_history = filter(lambda item: not item.empty_layer, pimage.config.history)
            for non_empty_layer_idx, non_empty_history_item in enumerate(non_empty_history):
                if non_empty_history_item is history_item:
                    layer_idx = non_empty_layer_idx
                    break

            if layer_idx is None:
                raise Exception("Logic failure.")

            relevant_layer = pimage.layers[layer_idx]
            size_str = format_size(relevant_layer.size)

        history_label = clean_created_by(history_item.created_by)
        if len(history_label) > 25:
            history_label = history_label[:22] + "..."

        super().__init__(
            [
                history_label,
                (size_str, urwid.RIGHT),
            ],
            space_between=1,
            columns_factory=columns_factory,
            column_factory=column_factory,
        )

        self.pimage = pimage
        self.history_idx = history_idx


class PlatformChoice(BetterSelectableRow):
    def __init__(self, pimage: PlatformImage):
        def columns_factory(*args, **kwargs):
            columns = Columns(*args, **kwargs)
            return AttrMap(columns, None, "selected")

        def column_factory(*args, **kwargs):
            return pad_text(Text(*args, **kwargs))

        image_size = sum_layer_sizes(pimage)
        super().__init__(
            [
                pimage.platform_name,
                trim_digest(pimage.digest),
                (format_size(image_size), urwid.RIGHT),
            ],
            on_select=cb(self.open_menu),
            space_between=1,
            columns_factory=columns_factory,
            column_factory=column_factory,
        )

        self.pimage = pimage
        self.menu = None
        self.viewer = None

    def _open_menu(self, menu, viewer):
        layer_view_container = Columns([], dividechars=1, focus_column=0)
        layer_view_container.contents.append((
            menu, Columns.options(urwid.GIVEN, 54)
        ))
        layer_view_container.contents.append((
            viewer, Columns.options()
        ))

        layers_frame.body = layer_view_container
        display_pile.focus_position = 2

    def _make_view_text(self, idx: int) -> Text:
        history_item = self.pimage.config.history[idx]
        text = clean_created_by(history_item.created_by)
        return Text(text, wrap=urwid.ANY)

    def open_menu(self):
        menu = self.menu
        viewer = self.viewer
        if menu and viewer:
            actual_menu = menu()
            actual_viewer = viewer()
            if actual_menu and actual_viewer:
                self._open_menu(actual_menu, actual_viewer)
                return

        choices = [LayerChoice(self.pimage, idx) for idx, _ in enumerate(self.pimage.config.history)]
        actual_menu = make_menu(
            choices,
            on_selection_change=self.layer_selection_change,
            initialization_is_selection_change=True,
        )

        initial_view = self._make_view_text(0)
        actual_viewer = Scrollable(initial_view)

        self.menu = weakref.ref(actual_menu)
        self.viewer = weakref.ref(actual_viewer)

        self._open_menu(actual_menu, actual_viewer)

    def layer_selection_change(self, _prev_idx, new_idx):
        viewer = self.viewer
        if not viewer:
            return
        actual_viewer: Optional[Scrollable] = viewer()
        if not actual_viewer:
            return

        new_view = self._make_view_text(new_idx)
        actual_viewer.original_widget = new_view


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
        display_pile.focus_position = 0

    def open_menu(self):
        menu = self.menu
        if menu:
            actual_menu = menu()
            if actual_menu:
                self._open_menu(actual_menu)
                return

        image = self.repo.get_image(self.tag)

        if preferred_platform:
            pimages = []
            preferred_pimage = None
            for pimage in image.get_platform_images():
                if pimage.config.platform == preferred_platform:
                    preferred_pimage = pimage
                else:
                    pimages.append(pimage)
            if preferred_pimage:
                pimages.insert(0, preferred_pimage)
        else:
            pimages = image.get_platform_images()

        choices = [PlatformChoice(pimage) for pimage in pimages]

        actual_menu = make_menu(choices)
        self.menu = weakref.ref(actual_menu)
        self._open_menu(actual_menu)


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
        tags_frame.reset()
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
        self.initial_markup = markup
        self.change_fmt = change_fmt

    def change_heading(self, value: str):
        self.set_text(self.change_fmt.format(value))

    def reset(self):
        self.set_text(self.initial_markup)


class ResettableFrame(Frame):
    def __init__(self, body, header=None, footer=None, focus_part="body"):
        super().__init__(body, header=header, footer=footer, focus_part=focus_part)

        self.orig_body = body
        self.orig_header_text = None
        self.orig_footer_text = None

        if header:
            header_widget: Text = unwrap(header)
            if not isinstance(header_widget, ChangingText):
                self.orig_header_text = header_widget.text

        if footer:
            footer_widget: Text = unwrap(footer)
            if not isinstance(footer_widget, ChangingText):
                self.orig_footer_text = footer_widget.text

    def reset(self):
        self.body = self.orig_body

        if self.header:
            header_widget: Text = unwrap(self.header)
            if isinstance(header_widget, ChangingText):
                header_widget.reset()
            elif self.orig_footer_text is not None:
                header_widget.set_text(self.orig_header_text)

        if self.footer:
            footer_widget: Text = unwrap(self.footer)
            if isinstance(footer_widget, ChangingText):
                footer_widget.reset()
            elif self.orig_footer_text is not None:
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
tags_frame = ResettableFrame(
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
        pad_text(ChangingText("", "{}", align=urwid.CENTER)),
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
