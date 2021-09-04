import urwid
from additional_urwid_widgets import SelectableRow as _SelectableRow


class BetterSelectableRow(_SelectableRow):
    def __init__(
        self,
        contents,
        /,
        *,
        align=urwid.LEFT,
        on_select=None,
        space_between=2,
        columns_factory=urwid.Columns,
        column_factory=urwid.Text,
    ):
        self.contents = contents
        self.on_select = on_select

        column_widgets = []
        for c in contents:
            if isinstance(c, tuple):
                c_text, c_align = c
                column = column_factory(c_text, align=c_align)
            else:
                column = column_factory(c, align=align)
            column_widgets.append(column)

        self._columns = columns_factory(column_widgets, dividechars=space_between)

        super(_SelectableRow, self).__init__(self._columns)
