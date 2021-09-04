import urwid
from additional_urwid_widgets import SelectableRow as _SelectableRow


class BetterSelectableRow(_SelectableRow):
    def __init__(self, contents, *, align="left", on_select=None, space_between=2, columns_factory=urwid.Columns, column_factory=urwid.Text):
        self.contents = contents

        self._columns = columns_factory(
            [column_factory(c, align=align) for c in contents],
            dividechars=space_between
        )

        super(_SelectableRow, self).__init__(self._columns)

        self.on_select = on_select
