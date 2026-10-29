"""TCPA-oriented US area-code → timezone checks (safe calling window)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import pytz

# Inclusive local window: 9:00 AM through 7:59 PM → safe; 8:00 PM and later is not.
# Spec: "strictly between 9:00 AM and 8:00 PM" → [09:00, 20:00)
CALL_WINDOW_START_HOUR = 9
CALL_WINDOW_END_HOUR = 20  # exclusive

# US NANP area codes → IANA timezone (approximate; AZ without DST uses America/Phoenix)
# Unlisted valid US codes default to America/New_York (conservative East Coast).
AREA_CODE_TIMEZONES: dict[str, str] = {
    # Eastern
    "201": "America/New_York", "202": "America/New_York", "203": "America/New_York",
    "207": "America/New_York", "212": "America/New_York", "215": "America/New_York",
    "216": "America/New_York", "220": "America/New_York", "223": "America/New_York",
    "227": "America/New_York", "228": "America/Chicago", "229": "America/New_York",
    "231": "America/New_York", "234": "America/New_York", "239": "America/New_York",
    "240": "America/New_York", "248": "America/New_York", "251": "America/Chicago",
    "252": "America/New_York", "260": "America/New_York", "267": "America/New_York",
    "269": "America/New_York", "270": "America/New_York", "272": "America/New_York",
    "276": "America/New_York", "301": "America/New_York", "302": "America/New_York",
    "304": "America/New_York", "305": "America/New_York", "313": "America/New_York",
    "315": "America/New_York", "317": "America/New_York", "321": "America/New_York",
    "324": "America/New_York", "330": "America/New_York", "332": "America/New_York",
    "336": "America/New_York", "339": "America/New_York", "341": "America/Los_Angeles",
    "347": "America/New_York", "351": "America/New_York", "352": "America/New_York",
    "386": "America/New_York", "401": "America/New_York", "404": "America/New_York",
    "407": "America/New_York", "410": "America/New_York", "412": "America/New_York",
    "413": "America/New_York", "419": "America/New_York", "423": "America/New_York",
    "434": "America/New_York", "440": "America/New_York", "443": "America/New_York",
    "445": "America/New_York", "458": "America/Los_Angeles", "463": "America/New_York",
    "464": "America/Chicago", "470": "America/New_York", "475": "America/New_York",
    "478": "America/New_York", "484": "America/New_York", "502": "America/New_York",
    "508": "America/New_York", "513": "America/New_York", "516": "America/New_York",
    "517": "America/New_York", "518": "America/New_York", "540": "America/New_York",
    "551": "America/New_York", "561": "America/New_York", "567": "America/New_York",
    "570": "America/New_York", "571": "America/New_York", "574": "America/New_York",
    "580": "America/Chicago", "585": "America/New_York", "586": "America/New_York",
    "603": "America/New_York", "606": "America/New_York", "607": "America/New_York",
    "609": "America/New_York", "610": "America/New_York", "614": "America/New_York",
    "616": "America/New_York", "617": "America/New_York", "631": "America/New_York",
    "640": "America/New_York", "646": "America/New_York", "649": "America/New_York",
    "656": "America/New_York", "659": "America/Chicago", "660": "America/Chicago",
    "667": "America/New_York", "678": "America/New_York", "680": "America/New_York",
    "681": "America/New_York", "689": "America/New_York", "703": "America/New_York",
    "704": "America/New_York", "706": "America/New_York", "716": "America/New_York",
    "717": "America/New_York", "718": "America/New_York", "724": "America/New_York",
    "727": "America/New_York", "732": "America/New_York", "734": "America/New_York",
    "740": "America/New_York", "743": "America/New_York", "754": "America/New_York",
    "757": "America/New_York", "762": "America/New_York", "763": "America/Chicago",
    "765": "America/New_York", "770": "America/New_York", "772": "America/New_York",
    "774": "America/New_York", "781": "America/New_York", "786": "America/New_York",
    "802": "America/New_York", "803": "America/New_York", "804": "America/New_York",
    "810": "America/New_York", "812": "America/New_York", "813": "America/New_York",
    "814": "America/New_York", "828": "America/New_York", "833": "America/New_York",
    "843": "America/New_York", "845": "America/New_York", "848": "America/New_York",
    "850": "America/New_York", "854": "America/New_York", "856": "America/New_York",
    "857": "America/New_York", "859": "America/New_York", "860": "America/New_York",
    "862": "America/New_York", "863": "America/New_York", "864": "America/New_York",
    "865": "America/New_York", "878": "America/New_York", "904": "America/New_York",
    "906": "America/New_York", "908": "America/New_York", "910": "America/New_York",
    "912": "America/New_York", "914": "America/New_York", "917": "America/New_York",
    "919": "America/New_York", "929": "America/New_York", "930": "America/New_York",
    "931": "America/Chicago", "934": "America/New_York", "937": "America/New_York",
    "941": "America/New_York", "947": "America/New_York", "954": "America/New_York",
    "959": "America/New_York", "973": "America/New_York", "978": "America/New_York",
    "980": "America/New_York", "984": "America/New_York", "989": "America/New_York",
    # Central
    "205": "America/Chicago", "210": "America/Chicago", "214": "America/Chicago",
    "217": "America/Chicago", "218": "America/Chicago", "219": "America/Chicago",
    "224": "America/Chicago", "225": "America/Chicago", "254": "America/Chicago",
    "256": "America/Chicago", "262": "America/Chicago", "281": "America/Chicago",
    "309": "America/Chicago", "312": "America/Chicago", "314": "America/Chicago",
    "316": "America/Chicago", "318": "America/Chicago", "319": "America/Chicago",
    "320": "America/Chicago", "325": "America/Chicago", "331": "America/Chicago",
    "334": "America/Chicago", "337": "America/Chicago", "346": "America/Chicago",
    "361": "America/Chicago", "405": "America/Chicago", "409": "America/Chicago",
    "414": "America/Chicago", "417": "America/Chicago", "430": "America/Chicago",
    "432": "America/Chicago", "469": "America/Chicago", "479": "America/Chicago",
    "501": "America/Chicago", "504": "America/Chicago", "507": "America/Chicago",
    "512": "America/Chicago", "515": "America/Chicago", "563": "America/Chicago",
    "573": "America/Chicago", "601": "America/Chicago", "608": "America/Chicago",
    "612": "America/Chicago", "618": "America/Chicago", "620": "America/Chicago",
    "630": "America/Chicago", "636": "America/Chicago", "641": "America/Chicago",
    "651": "America/Chicago", "662": "America/Chicago", "682": "America/Chicago",
    "701": "America/Chicago", "708": "America/Chicago", "712": "America/Chicago",
    "713": "America/Chicago", "715": "America/Chicago", "720": "America/Denver",
    "731": "America/Chicago", "737": "America/Chicago", "769": "America/Chicago",
    "773": "America/Chicago", "779": "America/Chicago", "785": "America/Chicago",
    "806": "America/Chicago", "815": "America/Chicago", "816": "America/Chicago",
    "817": "America/Chicago", "830": "America/Chicago", "832": "America/Chicago",
    "847": "America/Chicago", "870": "America/Chicago", "872": "America/Chicago",
    "901": "America/Chicago", "903": "America/Chicago", "913": "America/Chicago",
    "915": "America/Denver", "918": "America/Chicago", "920": "America/Chicago",
    "936": "America/Chicago", "940": "America/Chicago", "945": "America/Chicago",
    "956": "America/Chicago", "972": "America/Chicago", "979": "America/Chicago",
    "985": "America/Chicago",
    # Mountain
    "303": "America/Denver", "307": "America/Denver", "385": "America/Denver",
    "406": "America/Denver", "435": "America/Denver", "505": "America/Denver",
    "575": "America/Denver", "719": "America/Denver", "801": "America/Denver",
    "970": "America/Denver", "983": "America/Denver",
    # Arizona (no DST)
    "480": "America/Phoenix", "520": "America/Phoenix", "602": "America/Phoenix",
    "623": "America/Phoenix", "928": "America/Phoenix",
    # Pacific
    "206": "America/Los_Angeles", "208": "America/Boise", "209": "America/Los_Angeles",
    "213": "America/Los_Angeles", "253": "America/Los_Angeles", "279": "America/Los_Angeles",
    "310": "America/Los_Angeles", "323": "America/Los_Angeles", "360": "America/Los_Angeles",
    "408": "America/Los_Angeles", "415": "America/Los_Angeles", "424": "America/Los_Angeles",
    "425": "America/Los_Angeles", "442": "America/Los_Angeles", "503": "America/Los_Angeles",
    "509": "America/Los_Angeles", "510": "America/Los_Angeles", "530": "America/Los_Angeles",
    "541": "America/Los_Angeles", "559": "America/Los_Angeles", "562": "America/Los_Angeles",
    "619": "America/Los_Angeles", "626": "America/Los_Angeles", "628": "America/Los_Angeles",
    "650": "America/Los_Angeles", "657": "America/Los_Angeles", "661": "America/Los_Angeles",
    "669": "America/Los_Angeles", "702": "America/Los_Angeles", "707": "America/Los_Angeles",
    "714": "America/Los_Angeles", "725": "America/Los_Angeles", "747": "America/Los_Angeles",
    "760": "America/Los_Angeles", "775": "America/Los_Angeles", "805": "America/Los_Angeles",
    "818": "America/Los_Angeles", "820": "America/Los_Angeles", "831": "America/Los_Angeles",
    "858": "America/Los_Angeles", "909": "America/Los_Angeles", "916": "America/Los_Angeles",
    "925": "America/Los_Angeles", "949": "America/Los_Angeles", "951": "America/Los_Angeles",
    "971": "America/Los_Angeles",
    # Alaska / Hawaii
    "907": "America/Anchorage",
    "808": "Pacific/Honolulu",
}

DEFAULT_TIMEZONE = "America/New_York"

TZ_LABELS = {
    "America/New_York": "EST",
    "America/Chicago": "CST",
    "America/Denver": "MST",
    "America/Phoenix": "MST",
    "America/Los_Angeles": "PST",
    "America/Boise": "MST",
    "America/Anchorage": "AKST",
    "Pacific/Honolulu": "HST",
}


def normalize_us_digits(phone_number: str) -> str:
    """Return 10-digit US national number, or empty if invalid."""
    digits = re.sub(r"\D", "", str(phone_number or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return ""
    # NANP: area code and exchange cannot start with 0 or 1
    if digits[0] in "01" or digits[3] in "01":
        return ""
    return digits


def extract_area_code(phone_number: str) -> Optional[str]:
    digits = normalize_us_digits(phone_number)
    return digits[:3] if digits else None


def timezone_for_phone(phone_number: str) -> str:
    """Return IANA timezone for a US number (defaults to Eastern)."""
    area = extract_area_code(phone_number)
    if not area:
        return DEFAULT_TIMEZONE
    return AREA_CODE_TIMEZONES.get(area, DEFAULT_TIMEZONE)


def timezone_label(phone_number: str) -> str:
    """Return EST/CST/MST/PST-style label for logging."""
    tz_name = timezone_for_phone(phone_number)
    return TZ_LABELS.get(tz_name, "EST")


def local_now_for_phone(
    phone_number: str,
    *,
    now_utc: datetime | None = None,
) -> datetime:
    tz = pytz.timezone(timezone_for_phone(phone_number))
    if now_utc is None:
        now_utc = datetime.now(pytz.UTC)
    elif now_utc.tzinfo is None:
        now_utc = pytz.UTC.localize(now_utc)
    else:
        now_utc = now_utc.astimezone(pytz.UTC)
    return now_utc.astimezone(tz)


def is_safe_to_call(
    phone_number: str,
    *,
    now_utc: datetime | None = None,
) -> bool:
    """
    Return True if local time at the phone's area code is in [9:00 AM, 8:00 PM).

    Invalid / non-US numbers return False (do not dial).
    """
    if not normalize_us_digits(phone_number):
        return False
    local = local_now_for_phone(phone_number, now_utc=now_utc)
    minutes = local.hour * 60 + local.minute
    start = CALL_WINDOW_START_HOUR * 60
    end = CALL_WINDOW_END_HOUR * 60
    return start <= minutes < end
