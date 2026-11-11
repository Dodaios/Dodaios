"""The fragment shader a ``jarvis-shader-pet/1`` pet is allowed to ship.

The checks in this file are regular expressions over the shader text. They
are not a GLSL parser. A hostile upload may still get through.

The app owns the vertex shader and the uniforms (``uTime``, ``uState``,
``uStateFrom``, ``uBlend``, ``uLevel``, ``uLevelFrom``, plus the sphere
varyings). The file is the fragment body: helpers and ``void main``, writing
``gl_FragColor``. It is checked here the way a sprite sheet is checked for
size, because a shader is code the GPU runs.

A ``while`` or an open-ended ``for`` is rejected. A ``for`` may only count
a fixed number of times, at most :data:`MAX_LOOP_BOUND`, and the same
counter must appear in the test and the increment. The counter cannot be
written inside the body. Nested loops multiply: together they may run at
most :data:`MAX_LOOP_PRODUCT` times (the shipped Wisp Swarm shader is 32×5).
Sequential loops are counted on their own. Samplers and ``uniform``
declarations are rejected too: the pet cannot fetch an image or replace
the uniforms the app provides. ``#undef`` is rejected so a pet cannot
take the wrapper's ``uState`` / ``uLevel`` macros apart.
"""

from __future__ import annotations

import re

#: File name written for every uploaded shader. The upload's own name is ignored.
SHADER_FILE = "shader.frag"

#: Largest fragment source, in bytes of UTF-8.
MAX_SHADER_BYTES = 16 * 1024

#: Most times one ``for`` loop may run.
MAX_LOOP_BOUND = 32

#: Most times nested loops may run together. One loop of 32 inside a loop of
#: 5 is Wisp Swarm; two loops of 32 inside each other are not.
MAX_LOOP_PRODUCT = MAX_LOOP_BOUND * 5

_BANNED_DIRECTIVES = ("#include", "#version", "#extension", "#define", "#pragma", "#undef")
_BANNED_WORDS = ("sampler", "uniform", "varying", "attribute", "while", "precision")
_MAIN = re.compile(r"\bvoid\s+main\s*\(")
_ANY_FOR = re.compile(r"\bfor\s*\(")
_LINE_CONTINUATION = re.compile(r"\\\r?\n")
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
# The same name in the initializer, the test and the increment, then a brace
# body so the counter can be scanned. ``\1`` is that name.
_CONST_FOR = re.compile(
    r"\bfor\s*\(\s*int\s+([A-Za-z_]\w*)\s*=\s*\d+\s*;\s*\1\s*<\s*(\d+)\s*;\s*\1\s*\+\+\s*\)\s*\{"
)


def _scan_source(source: str) -> str:
    """Drop line continuations and comments before the word and loop scans.

    ``wh\\\\\\nile`` would otherwise miss the ``while`` ban. A comment is
    replaced with a space so ``wh/* */ile`` still joins into ``while``.
    """
    return _COMMENT.sub(" ", _LINE_CONTINUATION.sub("", source))


def _brace_body(source: str, open_at: int) -> str | None:
    """The text inside the brace at ``open_at``, or ``None`` when it never closes."""
    if open_at >= len(source) or source[open_at] != "{":
        return None
    depth = 0
    for index in range(open_at, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_at + 1 : index]
    return None


def _index_written(body: str, name: str) -> bool:
    """True when ``body`` assigns to ``name`` or steps it (``i =``, ``i++``, ``++i``)."""
    ident = re.escape(name)
    return (
        re.search(
            rf"(?:\+\+|--)\s*(?<![\w.]){ident}(?![\w.])"
            rf"|(?<![\w.]){ident}\s*(?:\+\+|--|[+\-*/%]=|(?<![=!<>])=(?!=))",
            body,
        )
        is not None
    )


def _check_loops(source: str) -> None:
    from dodaios.ui.pets.manifest import PetManifestError

    loops = _ANY_FOR.findall(source)
    bounded = list(_CONST_FOR.finditer(source))
    if len(loops) != len(bounded):
        raise PetManifestError(
            "A for loop must count a fixed number of times, like 'for (int i = 0; i < 8; i++)'."
        )
    # (bound, brace depth of that loop's body). Sequential loops sit at the
    # same depth and do not multiply; a loop inside another one does.
    opens: list[tuple[int, int]] = []
    depth = 0
    cursor = 0
    positions = {match.start(): match for match in bounded}
    while cursor < len(source):
        match = positions.get(cursor)
        if match is not None:
            bound = int(match.group(2))
            if bound > MAX_LOOP_BOUND:
                raise PetManifestError(f"A for loop may run at most {MAX_LOOP_BOUND} times.")
            product = bound
            for parent, _parent_depth in opens:
                product *= parent
            if product > MAX_LOOP_PRODUCT:
                raise PetManifestError(
                    f"Nested for loops may run at most {MAX_LOOP_PRODUCT} times together."
                )
            body = _brace_body(source, match.end() - 1)
            if body is None:
                raise PetManifestError("A for loop needs a brace body.")
            if _index_written(body, match.group(1)):
                raise PetManifestError("A for loop cannot change its counter inside the body.")
            opens.append((bound, depth + 1))
            cursor = match.end()
            depth += 1
            continue
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            while opens and depth < opens[-1][1]:
                opens.pop()
        cursor += 1


def check_shader_source(source: str) -> None:
    """Raise :class:`PetManifestError` when ``source`` breaks the shader rules."""
    from dodaios.ui.pets.manifest import PetManifestError

    if not isinstance(source, str) or not source.strip():
        raise PetManifestError("The shader is empty.")
    if "\x00" in source:
        raise PetManifestError("The shader must be plain text.")
    try:
        size = len(source.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise PetManifestError("The shader must be plain text.") from exc
    if size > MAX_SHADER_BYTES:
        raise PetManifestError("The shader is larger than 16 KB.")
    scanned = _scan_source(source)
    for directive in _BANNED_DIRECTIVES:
        if directive in scanned:
            raise PetManifestError(f"The shader cannot use {directive}.")
    for word in _BANNED_WORDS:
        # No trailing boundary: ``sampler`` has to catch ``sampler2D``.
        if re.search(rf"\b{word}", scanned):
            raise PetManifestError(f"The shader cannot use '{word}'.")
    if not _MAIN.search(scanned):
        raise PetManifestError("The shader needs a main function.")
    _check_loops(scanned)
