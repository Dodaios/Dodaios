"""The video side of a Clips node: its media library, speech, silences, export.

The spec grammar and the page live in :mod:`dodaios.nodes.kinds.motion` and
:mod:`dodaios.nodes.kinds.motion_media`; this package does the heavy work
around them, always on files in the node's own folder (``docs/clips-editor.md``):

* :mod:`.media` imports a file into the library (a copy, or a conversion to a
  codec every browser plays) with its poster, filmstrip and waveform;
* :mod:`.transcribe` turns speech into timed words on this computer;
* :mod:`.captions` maps those words onto the clip's timeline as caption lines;
* :mod:`.silence` finds the quiet parts of a recording;
* :mod:`.export` draws the clip frame by frame and writes an MP4.

Every function here blocks (decoding, encoding, a browser): callers run them
in a worker thread.
"""
