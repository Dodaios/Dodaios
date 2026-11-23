"""The desktop window opens WebView2's own menu for text only."""
from __future__ import annotations

from types import SimpleNamespace

from dodaios.ui import native_text_menu as ntm


class _Items(list):
    @property
    def Count(self) -> int:  # noqa: N802 - .NET shape
        return len(self)

    def RemoveAt(self, index: int) -> None:  # noqa: N802 - .NET shape
        del self[index]


def _args(*, editable: bool, selection: bool, names: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        ContextMenuTarget=SimpleNamespace(IsEditable=editable, HasSelection=selection),
        MenuItems=_Items(
            SimpleNamespace(Name=n, Kind="Separator" if n == "-" else "Command")
            for n in names
        ),
        Handled=False,
    )


def test_text_field_keeps_spelling_and_edit_items_but_drops_page_items() -> None:
    args = _args(
        editable=True,
        selection=False,
        names=["Hallo", "spellCheck", "cut", "copy", "paste", "selectAll", "print", "reload"],
    )
    ntm.on_context_menu_requested(None, args)
    assert args.Handled is False
    assert [i.Name for i in args.MenuItems] == [
        "Hallo", "spellCheck", "cut", "copy", "paste", "selectAll",
    ]


def test_selected_text_opens_the_native_menu() -> None:
    args = _args(editable=False, selection=True, names=["copy", "back"])
    ntm.on_context_menu_requested(None, args)
    assert args.Handled is False
    assert [i.Name for i in args.MenuItems] == ["copy"]


def test_plain_page_gets_no_native_menu() -> None:
    args = _args(editable=False, selection=False, names=["back", "reload", "print"])
    ntm.on_context_menu_requested(None, args)
    assert args.Handled is True


def test_enable_sets_the_page_flag_after_the_filter() -> None:
    calls: list[str] = []

    class _Event:
        def __iadd__(self, handler):  # noqa: ANN001, ANN204
            calls.append("subscribed")
            return self

    core = SimpleNamespace(
        ContextMenuRequested=_Event(),
        Settings=SimpleNamespace(AreDefaultContextMenusEnabled=False),
        AddScriptToExecuteOnDocumentCreatedAsync=lambda s: calls.append(s),
        ExecuteScriptAsync=lambda s: calls.append(s),
    )
    assert ntm.enable_on_core(core) is True
    assert core.Settings.AreDefaultContextMenusEnabled is True
    assert calls == ["subscribed", ntm.PAGE_FLAG_SCRIPT, ntm.PAGE_FLAG_SCRIPT]


def test_submenus_go_and_no_separator_is_left_dangling() -> None:
    items = _Items(
        [
            SimpleNamespace(Name="emoji", Kind="Command"),
            SimpleNamespace(Name="-", Kind="Separator"),
            SimpleNamespace(Name="copy", Kind="Command"),
            SimpleNamespace(Name="-", Kind="Separator"),
            SimpleNamespace(Name="writingDirection", Kind="Submenu"),
            SimpleNamespace(Name="-", Kind="Separator"),
            SimpleNamespace(Name="moreTools", Kind="Submenu"),
        ]
    )
    ntm.prune_menu(items)
    assert [i.Name for i in items] == ["emoji", "-", "copy"]
