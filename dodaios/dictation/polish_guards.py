"""Deterministic drift guards for the dictation polish and translate passes.

Pure regex and set arithmetic (no model call, no I/O). A check returns ``""``
only when the model's answer survived every check; otherwise the caller
delivers the RAW text. :func:`drift_reason` (polish: a language change is the
defect) and :func:`translate_drift_reason` (translate: it is the job) must not
be swapped. Numbers may be ADDED but never lost; language and rare-token checks
skip languages the detector or word list does not cover (silence beats a veto),
but protected terms are always enforced.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from typing import Final

from dodaios.core.turn_language import detect_text_language, normalize_language_tag
from dodaios.dictation.cleanup import count_words
from dodaios.dictation.polish_prompt import RAW_CLOSE_DELIMITER, RAW_OPEN_DELIMITER

#: Every reason :func:`drift_reason` can return, plus ``""`` for "safe to deliver".
DRIFT_REASONS: Final[tuple[str, ...]] = (
    "empty",
    "meta_output",
    "ratio_shrink",
    "ratio_growth",
    "language_flip",
    "lost_number",
    "lost_term",
    "lost_verb",
)

#: Same codes as :data:`DRIFT_REASONS`; precision mode drops one ``lost_term`` check.
PRECISION_DRIFT_REASONS: Final[tuple[str, ...]] = (
    "empty",
    "meta_output",
    "ratio_shrink",
    "ratio_growth",
    "language_flip",
    "lost_number",
    "lost_term",
    "lost_verb",
)

#: Translate set: ``not_translated`` replaces ``language_flip`` (see translate_drift_reason).
TRANSLATE_DRIFT_REASONS: Final[tuple[str, ...]] = (
    "empty",
    "meta_output",
    "ratio_shrink",
    "ratio_growth",
    "not_translated",
    "wrong_language",
    "lost_number",
    "lost_term",
)

_RARE_MIN_CHARS = 4

#: Max Levenshtein share for a replacement to count as a REPAIR (``deskto`` ->
#: ``desktop``), not a loss (``anushka`` -> ``her``). Biased toward repairs.
_REPAIR_MAX_DISTANCE_SHARE = 0.5

#: Max output tokens one misheard token may be split into (``hab Google``).
_REPAIR_MAX_SPLIT = 2

#: Scripts without word spaces (CJK, Thai, ...); Hangul is absent on purpose.
_NO_WORD_BOUNDARY_RE: Final[re.Pattern[str]] = re.compile(
    "[぀-ヿ㐀-䶿一-鿿豈-﫿"
    "฀-๿຀-໿ក-៿က-႟ༀ-࿿]"
)

_NO_WORD_BOUNDARY_SHARE = 0.15

#: Crude character-growth ceiling for translations across spaced/unspaced scripts.
_CROSS_SCRIPT_MAX_CHAR_GROWTH = 6.0

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_WORDLIKE_RE = re.compile(r"[\w']+", re.UNICODE)
_LINE_BREAK_RUN_RE = re.compile(r"\s*\n\s*", re.UNICODE)
_INLINE_SPACE_RE = re.compile(r"[^\S\n]+", re.UNICODE)
_DIGIT_RUN_RE = re.compile(r"\d+")
_DIGIT_SEPARATOR_RE = re.compile("(?<=\\d)[.,'\u2019\u00a0\u202f ](?=\\d)")

# A leading phrase meaning the model started TALKING (unless the RAW text did too).
_META_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    "^\\s*[\"'\u201c\u201e\u00ab]?\\s*(?:"
    r"here(?:'s| is| are)\b"
    r"|sure[,!.:-]"
    r"|certainly\b"
    r"|of course\b"
    r"|as requested\b"
    r"|the (?:corrected|formatted|cleaned|polished|revised)\b"
    r"|(?:corrected|formatted|cleaned|polished|revised)\s+(?:text|version|transcript)\b"
    r"|(?:output|result|transcript|formatted text)\s*:"
    r"|i(?:'ve| have)\s+(?:corrected|formatted|cleaned|polished)\b"
    r"|hier (?:ist|sind|kommt)\b"  # i18n-allow: DE meta-preamble
    r"|der (?:korrigierte|formatierte) text\b"  # i18n-allow: DE meta-preamble
    r"|aqu\u00ed (?:est\u00e1|tienes|te dejo)\b"
    r"|el texto (?:corregido|formateado)\b"
    r"|aqui (?:está|tens|fica)\b"  # i18n-allow: PT meta-preamble
    r"|o texto (?:corrigido|formatado)\b"  # i18n-allow: PT meta-preamble
    r")",
    re.IGNORECASE,
)

# i18n-allow: language-frequency DATA (matching data, not prose). Only tokens
# >= _RARE_MIN_CHARS are looked up; lists include droppable discourse markers.
_COMMON_WORDS_BASE: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({
        "about", "actually", "after", "again", "against", "alright", "also",
        "although", "always", "another", "anyone", "anything", "around", "away",
        "back", "basically", "because", "been", "before", "being", "believe",
        "below", "best", "better", "between", "both", "bring", "came", "cannot",
        "care", "change", "check", "come", "coming", "could", "couldn", "course",
        "definitely", "didn", "does", "doesn", "doing", "done", "down", "each",
        "else", "enough", "even", "ever", "every", "everything", "exactly",
        "example", "fact", "feel", "felt", "find", "first", "from", "full",
        "gave", "gets", "getting", "give", "given", "going", "gone", "good",
        "great", "guess", "hand", "happen", "happened", "hard", "have",
        "having", "hear", "help", "here", "hope", "idea", "into", "issue",
        "just", "keep", "kind", "know", "last", "later", "least", "left",
        "less", "like", "line", "little", "long", "look", "looking", "made",
        "make", "making", "many", "matter", "maybe", "mean", "means", "meant",
        "might", "mind", "more", "most", "move", "much", "must", "need",
        "never", "next", "nice", "nothing", "only", "open", "other", "over",
        "part", "people", "perhaps", "place", "please", "point", "probably",
        "problem", "quick", "quite", "rather", "read", "real", "really",
        "reason", "right", "said", "same", "saying", "says", "seem", "seems",
        "seen", "send", "sense", "several", "should", "shouldn", "show",
        "side", "simply", "since", "some", "something", "sometimes", "soon",
        "sorry", "sort", "sound", "sounds", "start", "still", "stuff", "such",
        "sure", "take", "taken", "talk", "tell", "than", "thank", "thanks",
        "that", "thats", "their", "them", "then", "there", "these", "they",
        "thing", "things", "think", "this", "those", "though", "thought",
        "through", "time", "times", "today", "together", "told",
        "took", "totally", "tried", "true", "turn", "under", "understand",
        "until", "upon", "used", "using", "usually", "very", "want", "wanted",
        "wants", "well", "went", "were", "what", "when", "where", "whether",
        "which", "while", "whole", "will", "with", "without", "word", "words",
        "work", "working", "would", "wouldn", "write", "wrong", "yeah", "year",
        "years", "your", "yours", "yourself",
    }),
    "de": frozenset({  # i18n-allow: German frequency data (§1 list #3)
        "aber", "alle", "allem", "allen", "aller", "alles", "also", "andere",  # i18n-allow
        "anderen", "auch", "beim", "bereits", "besser", "bisschen", "bist",  # i18n-allow
        "bitte", "brauche", "brauchen", "dabei", "daf\u00fcr", "damit", "dann",  # i18n-allow
        "daran", "darauf", "dass", "dein", "deine", "deinen", "denen", "denn",  # i18n-allow
        "deshalb", "dich", "diese", "diesem", "diesen", "dieser", "dieses",  # i18n-allow
        "doch", "dort", "durch", "eben", "eher", "eigentlich", "eine",  # i18n-allow
        "einem", "einen", "einer", "eines", "einfach", "einmal", "etwas",  # i18n-allow
        "euch", "fast", "ganz", "ganze", "ganzen", "gegen", "gehen", "geht",  # i18n-allow
        "gemacht", "genau", "gerade", "gerne", "gesagt", "gibt", "gleich",  # i18n-allow
        "gro\u00dfe", "gute", "guten", "haben", "habe", "halt", "hast", "hatte",  # i18n-allow
        "hatten", "heute", "hier", "hinter", "ihnen", "ihre", "ihrem", "ihren",  # i18n-allow
        "immer", "irgendwie", "jede", "jeden", "jetzt", "kann", "kannst",  # i18n-allow
        "kein", "keine", "keinen", "klar", "kommen", "kommt", "k\u00f6nnen",  # i18n-allow
        "konnte", "lassen", "leicht", "letzte", "letzten", "machen", "macht",  # i18n-allow
        "mache", "mehr", "mein", "meine", "meinen", "meiner", "meist", "mich",  # i18n-allow
        "muss", "m\u00fcssen", "nach", "nachdem", "nicht", "nichts", "noch",  # i18n-allow
        "oben", "oder", "ohne", "quasi", "richtig", "sagen", "sagt", "schnell",  # i18n-allow
        "schon", "sehen", "sehr", "sein", "seine", "seinen", "selbst", "sich",  # i18n-allow
        "sind", "sofort", "soll", "sollen", "sollte", "sondern", "sonst",  # i18n-allow
        "sp\u00e4ter", "stehen", "steht", "super", "tats\u00e4chlich", "\u00fcber",  # i18n-allow
        "\u00fcberhaupt", "unser", "unsere", "unter", "viel", "viele", "vielen",  # i18n-allow
        "vielleicht", "voll", "w\u00e4hrend", "wann", "waren", "warum", "weil",  # i18n-allow
        "weiter", "welche", "wenig", "wenn", "werde", "werden", "wieder",  # i18n-allow
        "wird", "wirklich", "wissen", "wohl", "wollen", "will", "willst",  # i18n-allow
        "wurde", "wurden", "zeit", "ziemlich", "zusammen", "zwar", "zwischen",  # i18n-allow
    }),
    "es": frozenset({  # i18n-allow: Spanish frequency data (§1 list #3)
        "acuerdo", "adem\u00e1s", "ahora", "algo", "alguna", "algunas",  # i18n-allow
        "alguno", "algunos", "all\u00ed", "ante", "antes", "aquel", "aqu\u00ed",  # i18n-allow
        "aunque", "ayer", "bien", "buena", "bueno", "cada", "casi", "cerca",  # i18n-allow
        "cierto", "claro", "como", "c\u00f3mo", "contra", "cosa", "cosas",  # i18n-allow
        "creo", "cual", "cuando", "cu\u00e1nto", "decir", "dejar", "dem\u00e1s",  # i18n-allow
        "dentro", "desde", "despu\u00e9s", "dice", "dicho", "digo", "donde",  # i18n-allow
        "d\u00f3nde", "durante", "ella", "ellas", "ellos", "entonces", "entre",  # i18n-allow
        "eran", "eres", "esas", "esos", "esta", "est\u00e1", "estaba",  # i18n-allow
        "estamos", "est\u00e1n", "estar", "este", "esto", "estos", "estoy",  # i18n-allow
        "exactamente", "favor", "forma", "fuera", "gran", "grande", "gracias",  # i18n-allow
        "hace", "hacer", "hacia", "hasta", "hecho", "hola", "igual", "incluso",  # i18n-allow
        "luego", "lugar", "ma\u00f1ana", "mejor", "menos", "mientras", "mismo",  # i18n-allow
        "mucha", "mucho", "muchos", "nada", "nadie", "ning\u00fan", "nosotros",  # i18n-allow
        "nunca", "otra", "otras", "otro", "otros", "para", "parece", "parte",  # i18n-allow
        "pero", "poco", "poder", "porque", "posible", "propio", "pues",  # i18n-allow
        "puede", "pueden", "puedo", "quiere", "quiero", "quiz\u00e1s", "sabe",  # i18n-allow
        "saber", "seg\u00fan", "siempre", "siendo", "sido", "sino", "sobre",  # i18n-allow
        "solo", "s\u00f3lo", "somos", "tambi\u00e9n", "tampoco", "tanto",  # i18n-allow
        "tarde", "tener", "tengo", "tiene", "tienen", "tiempo", "toda", "todas",  # i18n-allow
        "todo", "todos", "tras", "tuvo", "unos", "usted", "vale", "vamos",  # i18n-allow
        "verdad", "veces",  # i18n-allow
    }),
    "pt": frozenset({  # i18n-allow: European Portuguese frequency data (§1 list #3)
        "acho", "agora", "ainda", "algo", "alguma", "algumas", "algum",  # i18n-allow
        "alguns", "ali", "antes", "aqui", "assim", "até", "atrás",  # i18n-allow
        "bastante", "bem", "boa", "bom", "cada", "certo", "claro", "coisa",  # i18n-allow
        "coisas", "começar", "como", "contra", "dentro", "depois",  # i18n-allow
        "desde", "dessa", "desse", "deste", "desta", "dizer", "disse",  # i18n-allow
        "durante", "ela", "elas", "ele", "eles", "embora", "enquanto",  # i18n-allow
        "então", "entre", "essa", "essas", "esse", "esses", "esta",  # i18n-allow
        "está", "estas", "estão", "estava", "estamos", "estar",  # i18n-allow
        "este", "estes", "estou", "exatamente", "fazer", "favor", "feito",  # i18n-allow
        "fica", "ficar", "forma", "fora", "grande", "isso", "isto", "já",  # i18n-allow
        "lugar", "mais", "mesmo", "mesma", "melhor", "menos", "minha",  # i18n-allow
        "muito", "muita", "muitos", "muitas", "nada", "ninguém", "nossa",  # i18n-allow
        "nosso", "nunca", "obrigado", "obrigada", "onde", "ontem", "outra",  # i18n-allow
        "outras", "outro", "outros", "para", "parece", "parte", "pelo",  # i18n-allow
        "pela", "pelos", "pelas", "pode", "podem", "poder", "posso", "pois",  # i18n-allow
        "porque", "portanto", "pouco", "pronto", "quando", "quanto", "quase",  # i18n-allow
        "quer", "quero", "realmente", "sempre", "sido", "só", "sobre",  # i18n-allow
        "talvez", "também", "tanto", "tarde", "tem", "temos", "tenho",  # i18n-allow
        "ter", "tipo", "toda", "todas", "todo", "todos", "tudo", "vamos",  # i18n-allow
        "vezes", "verdade", "você", "amanhã", "hoje",  # i18n-allow
    }),
}

# Spoken number words and ordinals are common AND may vanish ("seven" -> "7", numbered lists).
_NUMBER_WORDS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
        "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
        "thousand", "million", "billion", "first", "second", "third", "fourth",
        "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "firstly",
        "secondly", "thirdly", "fourthly", "fifthly", "half", "quarter",
        "dozen",
    }),
    "de": frozenset({  # i18n-allow: German number words (§1 list #3)
        "null", "eins", "zwei", "drei", "vier", "f\u00fcnf", "sechs", "sieben",  # i18n-allow
        "acht", "neun", "zehn", "elf", "zw\u00f6lf", "dreizehn", "vierzehn",  # i18n-allow
        "f\u00fcnfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn",  # i18n-allow
        "zwanzig", "drei\u00dfig", "dreissig", "vierzig", "f\u00fcnfzig",  # i18n-allow
        "sechzig", "siebzig", "achtzig", "neunzig", "hundert", "tausend",  # i18n-allow
        "million", "millionen", "erste", "zweite", "dritte", "vierte",  # i18n-allow
        "fünfte", "sechste", "siebte", "achte", "neunte", "zehnte",  # i18n-allow
        "erstens", "zweitens", "drittens", "viertens", "fünftens",  # i18n-allow
        "sechstens", "siebtens", "siebentens", "achtens", "neuntens",  # i18n-allow
        "zehntens", "halb", "viertel", "dutzend",  # i18n-allow
    }),
    "es": frozenset({  # i18n-allow: Spanish number words (§1 list #3)
        "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete",  # i18n-allow
        "ocho", "nueve", "diez", "once", "doce", "trece", "catorce", "quince",  # i18n-allow
        "diecis\u00e9is", "diecisiete", "dieciocho", "diecinueve", "veinte",  # i18n-allow
        "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta",  # i18n-allow
        "noventa", "cien", "ciento", "mil", "mill\u00f3n", "millones",  # i18n-allow
        "primero", "segundo", "tercero", "quinto", "sexto", "séptimo",  # i18n-allow
        "octavo", "noveno", "décimo", "medio", "cuarto", "docena",  # i18n-allow
    }),
    "pt": frozenset({  # i18n-allow: Portuguese number words (§1 list #3)
        "zero", "um", "uma", "dois", "duas", "três", "quatro", "cinco",  # i18n-allow
        "seis", "sete", "oito", "nove", "dez", "onze", "doze", "treze",  # i18n-allow
        "catorze", "quinze", "dezasseis", "dezassete", "dezoito", "dezanove",  # i18n-allow
        "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta",  # i18n-allow
        "oitenta", "noventa", "cem", "cento", "mil", "milhão",  # i18n-allow
        "milhões", "primeiro", "primeira", "segundo", "segunda",  # i18n-allow
        "terceiro", "terceira", "quarto", "quarta", "quinto", "sexto",  # i18n-allow
        "sétimo", "oitavo", "nono", "décimo", "primeiramente",  # i18n-allow
        "meio", "metade", "dúzia",  # i18n-allow
    }),
}

# i18n-allow: spoken formatting commands (§1 list #3). Treated as common words
# and discounted from the word-count band (:func:`_ratio_word_counts`), since a
# command becomes a mark. Carrier words ("neuer" in "neuer Absatz") are listed too.
_FORMAT_COMMAND_WORDS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({
        "period", "comma", "colon", "semicolon", "hyphen", "dash",
        "quote", "unquote", "quotes", "question", "exclamation", "mark",
        "bullet", "bullets", "paragraph", "newline", "ellipsis",
        "parenthesis", "parentheses", "bracket", "brackets", "slash",
        "next", "point",
    }),
    "de": frozenset({  # i18n-allow: German spoken commands (§1 list #3)
        "punkt", "komma", "doppelpunkt", "semikolon", "strichpunkt",  # i18n-allow
        "fragezeichen", "ausrufezeichen", "bindestrich", "gedankenstrich",  # i18n-allow
        "anführungszeichen", "klammer", "klammern", "schrägstrich",  # i18n-allow
        "absatz", "zeile", "zeilenumbruch", "auslassungspunkte",  # i18n-allow
        "stichpunkt", "stichpunkte", "spiegelstrich", "aufzählungszeichen",  # i18n-allow
        "aufzählungspunkt", "neue", "neuer", "neues", "nächste", "nächster",  # i18n-allow
    }),
    "es": frozenset({  # i18n-allow: Spanish spoken commands (§1 list #3)
        "punto", "puntos", "coma", "aparte", "seguido", "interrogación",  # i18n-allow
        "interrogacion", "exclamación", "exclamacion", "guion", "guión",  # i18n-allow
        "raya", "comillas", "paréntesis", "parentesis", "párrafo", "parrafo",  # i18n-allow
        "línea", "linea", "viñeta", "vineta", "salto", "nueva", "nuevo",  # i18n-allow
        "siguiente",  # i18n-allow
    }),
    "pt": frozenset({  # i18n-allow: Portuguese spoken commands (§1 list #3)
        "ponto", "pontos", "vírgula", "virgula", "interrogação",  # i18n-allow
        "interrogacao", "exclamação", "exclamacao", "hífen",  # i18n-allow
        "hifen", "travessão", "aspas", "parênteses", "parenteses",  # i18n-allow
        "parágrafo", "paragrafo", "linha", "marcador", "marcadores",  # i18n-allow
        "nova", "novo", "seguinte", "reticências", "reticencias", "barra",  # i18n-allow
    }),
}

_COMMON_WORDS: Final[dict[str, frozenset[str]]] = {
    code: base
    | _NUMBER_WORDS.get(code, frozenset())
    | _FORMAT_COMMAND_WORDS.get(code, frozenset())
    for code, base in _COMMON_WORDS_BASE.items()
}

# i18n-allow: number-word DATA (§1 list #3). Quantities only: ordinals, fractions
# and "one"/"uno" have common non-numeric senses and may be dropped legitimately.
_QUANTITY_WORDS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({
        "zero", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
        "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
        "thousand", "million", "billion",
    }),
    "de": frozenset({  # i18n-allow: German quantity words (§1 list #3)
        "null", "zwei", "drei", "vier", "fünf", "sechs", "sieben",  # i18n-allow
        "acht", "neun", "zehn", "elf", "zwölf", "dreizehn", "vierzehn",  # i18n-allow
        "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn",  # i18n-allow
        "zwanzig", "dreißig", "dreissig", "vierzig", "fünfzig",  # i18n-allow
        "sechzig", "siebzig", "achtzig", "neunzig", "hundert", "tausend",  # i18n-allow
        "million", "millionen",  # i18n-allow
    }),
    "es": frozenset({  # i18n-allow: Spanish quantity words (§1 list #3)
        "cero", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",  # i18n-allow
        "nueve", "diez", "once", "doce", "trece", "catorce", "quince",  # i18n-allow
        "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte",  # i18n-allow
        "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta",  # i18n-allow
        "noventa", "cien", "ciento", "mil", "millón", "millones",  # i18n-allow
    }),
    "pt": frozenset({  # i18n-allow: Portuguese quantity words (§1 list #3)
        "zero", "dois", "duas", "três", "quatro", "cinco", "seis", "sete",  # i18n-allow
        "oito", "nove", "dez", "onze", "doze", "treze", "catorze", "quinze",  # i18n-allow
        "dezasseis", "dezassete", "dezoito", "dezanove", "vinte", "trinta",  # i18n-allow
        "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa",  # i18n-allow
        "cem", "cento", "mil", "milhão", "milhões",  # i18n-allow
    }),
}


# i18n-allow: grammar DATA (§1 list #3). Finite verbs and negations a formatter may
# never DELETE (a lost copula is invisible to the other checks). Articles,
# pronouns, conjunctions and prepositions are absent: restructuring drops them.
_ESSENTIAL_WORDS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({
        "is", "are", "am", "was", "were", "be", "been",
        "has", "have", "had", "do", "does", "did",
        "will", "would", "can", "could", "shall", "should", "may", "might",
        "must", "ought",
        "not", "no", "never", "none", "nothing", "nobody", "neither", "nor",
        "without", "cannot",
        "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't",
        "haven't", "hasn't", "hadn't", "won't", "wouldn't", "can't",
        "couldn't", "shouldn't", "mustn't",
    }),
    "de": frozenset({  # i18n-allow: German grammar data (§1 list #3)
        "ist", "sind", "bin", "bist", "seid", "war", "warst", "waren",  # i18n-allow
        "wart", "sei", "seien", "wäre", "wären",  # i18n-allow
        "habe", "hast", "hat", "haben", "habt", "hatte", "hattest",  # i18n-allow
        "hatten", "hättest", "hätte", "hätten",  # i18n-allow
        "werde", "wirst", "wird", "werden", "werdet", "wurde", "wurden",  # i18n-allow
        "würde", "würden",  # i18n-allow
        "kann", "kannst", "können", "könnt", "konnte", "konnten",  # i18n-allow
        "könnte", "könnten", "muss", "musst", "müssen", "müsst",  # i18n-allow
        "musste", "mussten", "müsste", "müssten",  # i18n-allow
        "soll", "sollst", "sollen", "sollt", "sollte", "sollten",  # i18n-allow
        "will", "willst", "wollen", "wollt", "wollte", "wollten",  # i18n-allow
        "darf", "darfst", "dürfen", "dürft", "durfte", "durften",  # i18n-allow
        "mag", "mögen", "möchte", "möchten",  # i18n-allow
        "nicht", "kein", "keine", "keinen", "keinem", "keiner", "keines",  # i18n-allow
        "nichts", "nie", "niemals", "niemand", "ohne",  # i18n-allow
    }),
    "es": frozenset({  # i18n-allow: Spanish grammar data (§1 list #3)
        "es", "son", "soy", "eres", "somos", "era", "eran", "eras",  # i18n-allow
        "fue", "fueron", "fui", "sea", "sean",  # i18n-allow
        "está", "están", "estoy", "estás", "estamos", "estaba",  # i18n-allow
        "estaban", "estuvo", "estuvieron",  # i18n-allow
        "ha", "han", "he", "hemos", "había", "habían", "hay", "haya",  # i18n-allow
        "puede", "pueden", "puedo", "puedes", "podemos", "podía",  # i18n-allow
        "podría", "podrían", "debe", "deben", "debo", "debes",  # i18n-allow
        "debería", "deberían", "tiene", "tienen", "tengo", "tienes",  # i18n-allow
        "no", "nunca", "jamás", "nada", "nadie", "ninguno", "ninguna",  # i18n-allow
        "ni", "sin",  # i18n-allow
    }),
    "pt": frozenset({  # i18n-allow: European Portuguese grammar data (§1 list #3)
        "é", "são", "sou", "és", "somos", "era", "eram", "eras",  # i18n-allow
        "foi", "foram", "fui", "seja", "sejam", "fosse",  # i18n-allow
        "está", "estão", "estou", "estás", "estamos", "estava",  # i18n-allow
        "estavam", "esteve", "estiveram",  # i18n-allow
        "há", "havia", "haja", "tem", "têm", "tenho", "tens", "temos",  # i18n-allow
        "tinha", "tinham",  # i18n-allow
        "pode", "podem", "posso", "podes", "podemos", "podia",  # i18n-allow
        "poderia", "poderiam", "deve", "devem", "devo", "deves",  # i18n-allow
        "deveria", "deveriam", "vai", "vão", "vou", "vais",  # i18n-allow
        "não", "nunca", "jamais", "nada", "ninguém", "nenhum", "nenhuma",  # i18n-allow
        "nem", "sem",  # i18n-allow
    }),
}


def normalize_for_compare(text: str) -> str:
    """Collapse *text* to the form used to decide "did anything change at all".

    NFKC plus inline whitespace collapsed; punctuation and case are kept, line
    breaks survive as one newline (paragraph and list work is made of them).
    """
    flat = unicodedata.normalize("NFKC", str(text or ""))
    flat = flat.replace("\r\n", "\n").replace("\r", "\n")
    flat = _LINE_BREAK_RUN_RE.sub("\n", flat)
    return _INLINE_SPACE_RE.sub(" ", flat).strip()


def _compare_tokens(text: str) -> list[str]:
    """Lower-cased word tokens, punctuation stripped — the term-match alphabet."""
    flat = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return _WORDLIKE_RE.findall(flat)


def _token_haystack(text: str) -> str:
    """A space-fenced token string so a multi-word term can be found as a unit."""
    return " " + " ".join(_compare_tokens(text)) + " "


def _language_key(language: object) -> str:
    """The two-letter key into :data:`_COMMON_WORDS`, or ``""`` when unusable.

    Resolved via :func:`normalize_language_tag` because cloud APIs answer with
    language NAMES ("German").
    """
    raw = str(language or "").strip()
    if not raw:
        return ""
    direct = raw.lower().replace("_", "-").split("-", 1)[0]
    if direct in _COMMON_WORDS:
        return direct
    code = normalize_language_tag(raw.lower())
    return code if code in _COMMON_WORDS else ""


def rare_tokens(text: str, *, language: str) -> frozenset[str]:
    """Alphabetic tokens of *text* at least ``_RARE_MIN_CHARS`` long and absent from
    the common-word list of *language* (proper nouns, product names, jargon).

    Empty for a language without a word list, which disables the rare-token half
    of ``lost_term``.
    """
    common = _COMMON_WORDS.get(_language_key(language))
    if common is None:
        return frozenset()
    flat = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return frozenset(
        token
        for token in _TOKEN_RE.findall(flat)
        if len(token) >= _RARE_MIN_CHARS and token not in common
    )


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two short tokens (two rolling rows, no dependency)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ch_a != ch_b),  # substitution
                )
            )
        previous = current
    return previous[-1]


def _is_repair_of(lost: str, candidate: str) -> bool:
    """Whether *candidate* is *lost* spelled correctly, rather than a new word."""
    if not candidate:
        return False
    span = max(len(lost), len(candidate))
    if not span:
        return False
    return _edit_distance(lost, candidate) / span <= _REPAIR_MAX_DISTANCE_SHARE


def _was_repaired(lost: str, out_tokens: Sequence[str]) -> bool:
    """Whether the output carries a corrected spelling of the token *lost*.

    Separates a DROPPED word (``Anushka`` -> ``her``) from a REPAIRED one
    (``deskto`` -> ``desktop``): misrecognized words are always rare, so without
    this the guard rejects the repairs polish exists to make. Candidates are
    single tokens plus runs of up to :data:`_REPAIR_MAX_SPLIT`.
    """
    for size in range(1, _REPAIR_MAX_SPLIT + 1):
        for start in range(len(out_tokens) - size + 1):
            if _is_repair_of(lost, "".join(out_tokens[start : start + size])):
                return True
    return False


def _digit_runs(text: str) -> frozenset[str]:
    """Every number in *text*, with grouping separators flattened away."""
    return frozenset(_DIGIT_RUN_RE.findall(_DIGIT_SEPARATOR_RE.sub("", str(text or ""))))


#: A produced list line ("- ", "3. "): evidence a spoken marker was converted.
_LIST_LINE_RE = re.compile(r"(?m)^[ \t]*(?:[-•*]|\d{1,3}[.)])\s")

_MAX_MARKER_WORDS_PER_LINE = 2


def _list_lines(text: str) -> int:
    """How many list-marker lines *text* contains."""
    return len(_LIST_LINE_RE.findall(str(text or "")))


def _ratio_word_counts(
    raw: str, polished: str, commands: frozenset[str]
) -> tuple[int, int]:
    """The two sides of the word-count band, with formatting commands settled.

    Discount per occurrence: on BOTH sides (content homonym) subtracted from
    both; RAW only (maybe converted) up to ``_MAX_MARKER_WORDS_PER_LINE`` per NEW
    list line, so a prose summary earns none; OUTPUT only never discounted.
    A side that discounts to zero returns zero (the caller skips the band).
    """
    raw_total = count_words(raw)
    out_total = count_words(polished)
    if not commands or not raw_total:
        return raw_total, out_total
    raw_hits = Counter(t for t in _compare_tokens(raw) if t in commands)
    out_hits = Counter(t for t in _compare_tokens(polished) if t in commands)
    shared = sum((raw_hits & out_hits).values())
    converted = sum((raw_hits - out_hits).values())
    evidence = (
        max(0, _list_lines(polished) - _list_lines(raw))
        * _MAX_MARKER_WORDS_PER_LINE
    )
    return (
        max(0, raw_total - shared - min(converted, evidence)),
        max(0, out_total - shared),
    )


def _lost_quantity_word(raw: str, out: str, *, language: str) -> bool:
    """Whether a spoken QUANTITY vanished without a digit taking its place.

    Covers what :func:`_digit_runs` cannot see ("three people" -> "the team").
    Precision mode only: the ordinary pass forbids word replacement. Any new
    digit in the output excuses a vanished number word.
    """
    quantities = _QUANTITY_WORDS.get(_language_key(language))
    if not quantities:
        return False
    spoken = {token for token in _compare_tokens(raw) if token in quantities}
    if not spoken:
        return False
    survivors = set(_compare_tokens(out))
    vanished = spoken - survivors
    if not vanished:
        return False
    return not (_digit_runs(out) - _digit_runs(raw))


def _lost_essential_word(raw: str, out: str, *, language: str) -> bool:
    """Whether a finite verb or a negation was CUT OUT rather than rewritten.

    Decided positionally with :mod:`difflib`: an essential word in a ``delete``
    opcode was cut ("what I've meant is this" -> "I meant this"); in a
    ``replace`` something took its place (agreement repair). The deleted span
    must be NOTHING BUT essential words, which keeps the check off false starts
    and reduced relative clauses. ``autojunk=False`` is load-bearing (frequent
    tokens would be junk); the Counter pre-check skips the O(n^2) diff.
    """
    essential = _ESSENTIAL_WORDS.get(_language_key(language))
    if not essential:
        return False
    before = _compare_tokens(raw)
    after = _compare_tokens(out)
    if not before:
        return False
    if not (essential & set(Counter(before) - Counter(after))):
        return False
    opcodes = difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes()
    return any(
        tag == "delete" and all(token in essential for token in before[i1:i2])
        for tag, i1, i2, _j1, _j2 in opcodes
    )


def _echoes_delimiter(raw: str, polished: str) -> bool:
    """True when the answer repeats the fence the transcript was sent inside
    (a sign the untrusted material was read as an instruction)."""
    for marker in (RAW_OPEN_DELIMITER, RAW_CLOSE_DELIMITER, "<<<", ">>>"):
        if marker in polished and marker not in raw:
            return True
    return False


def _is_meta_output(raw: str, polished: str) -> bool:
    """True when the answer is framed as a REPLY rather than as the text."""
    if _echoes_delimiter(raw, polished):
        return True
    if "```" in polished and "```" not in raw:
        return True
    return bool(_META_PREFIX_RE.match(polished)) and not _META_PREFIX_RE.match(raw)


def drift_reason(
    raw: str,
    polished: str,
    *,
    language: str,
    protected: Sequence[str],
    max_shrink: float,
    max_growth: float,
) -> str:
    """``""`` when *polished* is safe to deliver; otherwise a short reason code.

    Guard for the ORDINARY polish pass. The first check that fires names the
    history reason, so ``language_flip`` precedes the token checks.
    """
    return _polish_drift_reason(
        raw,
        polished,
        language=language,
        protected=protected,
        max_shrink=max_shrink,
        max_growth=max_growth,
        preserve_rare_tokens=True,
    )


def precision_drift_reason(
    raw: str,
    polished: str,
    *,
    language: str,
    protected: Sequence[str],
    max_shrink: float,
    max_growth: float,
) -> str:
    """The guard for a polish run with PRECISION MODE on.

    Same as :func:`drift_reason` minus the rare-token half of ``lost_term``,
    which would reject nearly every answer because precision mode replaces
    uncommon words on purpose. Protected terms, numbers, verbs and the band still
    apply. The trade is the user's, hence the mode ships off.
    """
    return _polish_drift_reason(
        raw,
        polished,
        language=language,
        protected=protected,
        max_shrink=max_shrink,
        max_growth=max_growth,
        preserve_rare_tokens=False,
    )


def _polish_drift_reason(
    raw: str,
    polished: str,
    *,
    language: str,
    protected: Sequence[str],
    max_shrink: float,
    max_growth: float,
    preserve_rare_tokens: bool,
) -> str:
    """The shared body of the two polish guards.

    One function with a keyword-only flag so the two modes cannot drift apart.
    """
    if not str(polished or "").strip():
        return "empty"
    if _is_meta_output(raw, polished):
        return "meta_output"

    raw_language = detect_text_language(raw)
    out_language = detect_text_language(polished)

    commands = _FORMAT_COMMAND_WORDS.get(
        _language_key(raw_language if raw_language != "unknown" else language),
        frozenset(),
    )
    raw_words, out_words = _ratio_word_counts(raw, polished, commands)
    if raw_words:
        ratio = out_words / raw_words
        short_precision = (
            not preserve_rare_tokens and 0 < out_words < raw_words <= 4
            and raw_words - out_words <= 2
        )
        if ratio < max_shrink and not short_precision:
            return "ratio_shrink"
        if ratio > max_growth:
            return "ratio_growth"

    if raw_language != "unknown" and out_language != "unknown":
        if raw_language != out_language:
            return "language_flip"

    if _digit_runs(raw) - _digit_runs(polished):
        return "lost_number"

    # Spelled-out twin of the check above; precision-only (see ``_lost_quantity_word``).
    if not preserve_rare_tokens and _lost_quantity_word(
        raw, polished, language=raw_language if raw_language != "unknown" else language
    ):
        return "lost_number"

    haystack = _token_haystack(polished)
    raw_haystack = _token_haystack(raw)
    for term in protected or ():
        tokens = _compare_tokens(term)
        if not tokens:
            continue
        needle = " " + " ".join(tokens) + " "
        if needle in raw_haystack and needle not in haystack:
            return "lost_term"

    # Both modes: precision licenses word choice, not deleting the clause's verb or negation.
    if _lost_essential_word(
        raw, polished, language=raw_language if raw_language != "unknown" else language
    ):
        return "lost_verb"

    # Skipped in precision mode, where replacing an uncommon word is the job.
    if preserve_rare_tokens:
        # The frequency list must describe the TEXT, not its label (English tagged German
        # would make every ordinary word "rare").
        lookup = raw_language if raw_language != "unknown" else language
        vanished = rare_tokens(raw, language=lookup) - rare_tokens(
            polished, language=lookup
        )
        if vanished:
            out_tokens = _compare_tokens(polished)
            if any(not _was_repaired(token, out_tokens) for token in vanished):
                return "lost_term"

    return ""


def writes_without_word_spaces(text: str) -> bool:
    """Whether *text* is mostly in a script that puts no spaces between words.

    Public because the answer decides whether a word COUNT means anything at
    all, and that question belongs to whoever is comparing two texts — not
    hidden inside one guard.
    """
    body = str(text or "").strip()
    if not body:
        return False
    hits = len(_NO_WORD_BOUNDARY_RE.findall(body))
    return hits / len(body) >= _NO_WORD_BOUNDARY_SHARE


def translate_drift_reason(
    raw: str,
    translated: str,
    *,
    target_language: str,
    protected: Sequence[str],
    max_shrink: float,
    max_growth: float,
) -> str:
    """``""`` when *translated* is safe to deliver; otherwise a short reason code.

    Differs from :func:`drift_reason`: the language check is inverted (output
    must match *target_language*: ``not_translated`` if it came back in the
    input's language, ``wrong_language`` otherwise; a no-op for undetectable
    languages); the word-count band is much wider; rare-token preservation is
    gone, but numbers and protected terms must survive. The FIRST reason that
    fires is returned.
    """
    if not str(translated or "").strip():
        return "empty"
    if _is_meta_output(raw, translated):
        return "meta_output"

    # Word counts compare only within one unit; across spaced/unspaced scripts use a char ceiling.
    if writes_without_word_spaces(raw) != writes_without_word_spaces(translated):
        if len(translated) > len(raw) * _CROSS_SCRIPT_MAX_CHAR_GROWTH:
            return "ratio_growth"
    else:
        commands = _FORMAT_COMMAND_WORDS.get(
            _language_key(detect_text_language(raw)), frozenset()
        )
        raw_words, out_words = _ratio_word_counts(raw, translated, commands)
        if raw_words:
            ratio = out_words / raw_words
            if ratio < max_shrink:
                return "ratio_shrink"
            if ratio > max_growth:
                return "ratio_growth"

    target = _language_key(target_language)
    if target:
        out_language = detect_text_language(translated)
        if out_language != "unknown" and out_language != target:
            if out_language == detect_text_language(raw):
                return "not_translated"
            return "wrong_language"

    # Unchanged from the polish guard; asymmetric so "seven" -> "7" stays legal.
    if _digit_runs(raw) - _digit_runs(translated):
        return "lost_number"

    haystack = _token_haystack(translated)
    raw_haystack = _token_haystack(raw)
    for term in protected or ():
        tokens = _compare_tokens(term)
        if not tokens:
            continue
        needle = " " + " ".join(tokens) + " "
        if needle in raw_haystack and needle not in haystack:
            return "lost_term"

    return ""


__all__ = [
    "DRIFT_REASONS",
    "PRECISION_DRIFT_REASONS",
    "TRANSLATE_DRIFT_REASONS",
    "drift_reason",
    "normalize_for_compare",
    "precision_drift_reason",
    "rare_tokens",
    "translate_drift_reason",
]
