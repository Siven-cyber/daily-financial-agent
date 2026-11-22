"""Validated owner-selected IANA zones and localized timezone setup."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones


def validate_zone(value):
    if not isinstance(value, str) or value not in available_timezones():
        raise ValueError('Unknown IANA timezone')
    return value


def zone_for(db, user_id):
    # Unset preferences are never persisted or inferred from language/currency.
    # UTC is the explicit fallback for internal/legacy service callers only.
    return ZoneInfo(db.get_timezone(user_id) or 'UTC')


def local_date(db, user_id, stamp):
    value = datetime.fromisoformat(stamp)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone_for(db, user_id)).date().isoformat()


def prompt(bot, chat_id, lang):
    text = ('Choose your timezone. Search by city: /timezone New York\n'
            'Or enter an IANA zone: /timezone America/New_York\n'
            'Examples: Jakarta, Singapore, London, Tokyo, UTC.' if lang == 'en' else
            'Pilih zona waktu. Cari berdasarkan kota: /timezone Jakarta\n'
            'Atau masukkan zona IANA: /timezone Asia/Jakarta\n'
            'Contoh: Singapore, London, Tokyo, New York, UTC.')
    bot._tg.send_message(chat_id, text)


def command(bot, chat_id, user_id, lang, text):
    query = text.split(maxsplit=1)
    if len(query) == 1:
        current = bot._db.get_timezone(user_id)
        if current:
            bot._tg.send_message(chat_id, ('Current timezone: ' if lang == 'en' else 'Zona waktu saat ini: ') + current)
        prompt(bot, chat_id, lang)
        return
    query = query[1].strip()
    if query in available_timezones():
        bot._db.set_timezone(user_id, query)
        bot._tg.send_message(chat_id, ('Timezone set: ' if lang == 'en' else 'Zona waktu diatur: ') + query)
        return
    normalized = query.casefold().replace(' ', '_')
    matches = sorted(z for z in available_timezones() if normalized in z.rsplit('/', 1)[-1].casefold())
    if not matches:
        bot._tg.send_message(chat_id, 'City or timezone not found.' if lang == 'en' else 'Kota atau zona waktu tidak ditemukan.')
        prompt(bot, chat_id, lang)
        return
    rows = [[{'text': z, 'callback_data': 'tz:' + z}] for z in matches[:10] if len(('tz:' + z).encode()) <= 64]
    bot._tg.send_message(chat_id, 'Confirm your timezone:' if lang == 'en' else 'Konfirmasi zona waktu:', reply_markup={'inline_keyboard': rows})


def callback(bot, chat_id, user_id, lang, value):
    try:
        bot._db.set_timezone(user_id, value)
    except ValueError:
        prompt(bot, chat_id, lang)
        return
    bot._tg.send_message(chat_id, ('Timezone set: ' if lang == 'en' else 'Zona waktu diatur: ') + value)
