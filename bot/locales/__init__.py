from bot.locales import en, ru, uz

LANGS = {"uz": uz.TEXTS, "ru": ru.TEXTS, "en": en.TEXTS}
DEFAULT_LANG = "ru"


def t(lang: str | None, key: str, **kwargs) -> str:
    texts = LANGS.get(lang or DEFAULT_LANG, LANGS[DEFAULT_LANG])
    template = texts.get(key) or LANGS[DEFAULT_LANG].get(key) or key
    return template.format(**kwargs) if kwargs else template
