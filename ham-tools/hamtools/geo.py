"""Where and when: the sun (sunrise, sunset, greyline), call sign prefixes to
country and zones, and a short list of cities for a location without GPS.
All offline."""
from __future__ import annotations

import math
import time

# ---- the sun ---------------------------------------------------------------------------
# NOAA's solar position equations (accurate to about a minute for sunrise
# and sunset, plenty for greyline).


def _julian(t: float) -> float:
    return t / 86400.0 + 2440587.5


def sun_position(lat: float, lon: float, t: float) -> tuple[float, float]:
    """(elevation, azimuth) of the sun in degrees at time t (epoch seconds)."""
    jc = (_julian(t) - 2451545.0) / 36525.0
    l0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + math.sin(2 * mr) * (0.019993 - 0.000101 * jc)
         + math.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_long))))
    y = math.tan(math.radians(eps / 2)) ** 2
    l0r = math.radians(l0)
    eqt = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
                           - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    minutes = (t % 86400) / 60.0
    tst = (minutes + eqt + 4 * lon) % 1440
    ha = tst / 4 - 180 if tst / 4 >= 0 else tst / 4 + 180
    latr, decr, har = math.radians(lat), math.radians(decl), math.radians(ha)
    cz = math.sin(latr) * math.sin(decr) + math.cos(latr) * math.cos(decr) * math.cos(har)
    zen = math.degrees(math.acos(max(-1.0, min(1.0, cz))))
    elev = 90 - zen
    den = math.cos(latr) * math.sin(math.radians(zen))
    if abs(den) > 1e-9:
        ca = ((math.sin(latr) * cz) - math.sin(decr)) / den
        az = math.degrees(math.acos(max(-1.0, min(1.0, ca))))
        az = (az + 180) % 360 if ha > 0 else (540 - az) % 360
    else:
        az = 180.0 if lat > 0 else 0.0
    return elev, az


SUN_DOWN = -0.833


def sun_events(lat: float, lon: float, day_start: float) -> dict:
    """Sunrise and sunset (epoch seconds or None) in the UTC day starting at day_start.
    {"rise", "set", "polar": "day" | "night" | None}."""
    step = 600
    out = {"rise": None, "set": None, "polar": None}
    prev = sun_position(lat, lon, day_start)[0] - SUN_DOWN
    always_up = prev > 0
    always_down = prev <= 0
    for i in range(1, 145):
        t = day_start + i * step
        cur = sun_position(lat, lon, t)[0] - SUN_DOWN
        always_up &= cur > 0
        always_down &= cur <= 0
        if (prev <= 0 < cur) or (prev > 0 >= cur):
            a, b = t - step, t
            for _ in range(12):
                mid = (a + b) / 2
                m = sun_position(lat, lon, mid)[0] - SUN_DOWN
                if (m > 0) == (cur > 0):
                    b = mid
                else:
                    a = mid
            key = "rise" if cur > 0 else "set"
            if out[key] is None:
                out[key] = (a + b) / 2
        prev = cur
    if always_up:
        out["polar"] = "day"
    elif always_down:
        out["polar"] = "night"
    return out


def day_start(t: float) -> float:
    return t - t % 86400


def greyline_now(lat: float, lon: float, t: float) -> bool:
    """True when the place is near the terminator (sun -6 to +3 degrees)."""
    return -6.0 <= sun_position(lat, lon, t)[0] <= 3.0


def daylight_word(lat: float, lon: float, t: float) -> str:
    el = sun_position(lat, lon, t)[0]
    if el > 3:
        return "day"
    if el > -6:
        return "greyline"
    return "night"


def hhmm(t: float | None) -> str:
    return time.strftime("%H:%M", time.gmtime(t)) if t is not None else "--:--"


# ---- call sign prefixes ----------------------------------------------------------------------
# (prefixes, country, CQ zone, ITU zone, lat, lon). Longest match wins. The
# common DXCC entities; positions are a typical spot in the country.

PREFIXES = [
    ("K W N AA AB AC AD AE AF AG AI AJ AK", "United States", 5, 8, 39.0, -77.0),
    ("KH6 WH6 NH6 AH6 KH7 WH7 NH7 AH7", "Hawaii", 31, 61, 21.3, -157.8),
    ("KL7 WL7 NL7 AL7 KL AL NL WL", "Alaska", 1, 1, 61.2, -149.9),
    ("KP4 WP4 NP4 KP3 WP3 NP3 KP KP2 WP2 NP2", "Puerto Rico / US Virgin Is.", 8, 11, 18.4, -66.1),
    ("KH2 WH2 NH2 AH2", "Guam", 27, 64, 13.5, 144.8),
    ("KH0 AH0 NH0 WH0", "Mariana Is.", 27, 64, 15.2, 145.7),
    ("VE VA VO VY CY CZ XL XM", "Canada", 5, 9, 45.4, -75.7),
    ("VE7 VA7", "Canada (BC)", 3, 2, 49.3, -123.1),
    ("VE6 VA6", "Canada (Alberta)", 4, 2, 51.0, -114.1),
    ("VE5 VA5", "Canada (Saskatchewan)", 4, 3, 52.1, -106.7),
    ("VE4 VA4", "Canada (Manitoba)", 4, 3, 49.9, -97.1),
    ("VE3 VA3", "Canada (Ontario)", 4, 4, 43.7, -79.4),
    ("VE2 VA2", "Canada (Quebec)", 2, 4, 45.5, -73.6),
    ("VO1", "Canada (Newfoundland)", 5, 9, 47.6, -52.7),
    ("VY1", "Canada (Yukon)", 1, 2, 60.7, -135.1),
    ("XE XF 4A 6D", "Mexico", 6, 10, 19.4, -99.1),
    ("CO CM CL T4", "Cuba", 8, 11, 23.1, -82.4),
    ("HI", "Dominican Rep.", 8, 11, 18.5, -69.9),
    ("6Y", "Jamaica", 8, 11, 18.0, -76.8),
    ("ZF", "Cayman Is.", 8, 11, 19.3, -81.4),
    ("C6", "Bahamas", 8, 11, 25.0, -77.3),
    ("VP2E", "Anguilla", 8, 11, 18.2, -63.1),
    ("V3", "Belize", 7, 11, 17.3, -88.8),
    ("TG", "Guatemala", 7, 11, 14.6, -90.5),
    ("TI", "Costa Rica", 7, 11, 9.9, -84.1),
    ("HP", "Panama", 7, 11, 9.0, -79.5),
    ("YN", "Nicaragua", 7, 11, 12.1, -86.3),
    ("HR", "Honduras", 7, 11, 14.1, -87.2),
    ("YS", "El Salvador", 7, 11, 13.7, -89.2),
    ("PY PP PQ PR PS PT PU PV PW PX ZV ZW ZX ZY ZZ", "Brazil", 11, 15, -23.5, -46.6),
    ("LU LO LP LQ LR LS LT LV LW AY AZ L2 L3 L4 L5 L6 L7 L8 L9", "Argentina", 13, 14, -34.6, -58.4),
    ("CE CA CB CC CD XQ XR 3G", "Chile", 12, 14, -33.4, -70.6),
    ("CX CV CW", "Uruguay", 13, 14, -34.9, -56.2),
    ("ZP", "Paraguay", 11, 14, -25.3, -57.6),
    ("CP", "Bolivia", 10, 12, -16.5, -68.1),
    ("OA OB OC 4T", "Peru", 10, 12, -12.0, -77.0),
    ("HC HD", "Ecuador", 10, 12, -0.2, -78.5),
    ("HC8 HD8", "Galapagos Is.", 10, 12, -0.7, -90.3),
    ("HK HJ 5J 5K", "Colombia", 9, 12, 4.7, -74.1),
    ("YV YW YX YY 4M", "Venezuela", 9, 12, 10.5, -66.9),
    ("9Y 9Z", "Trinidad & Tobago", 9, 11, 10.7, -61.5),
    ("P4", "Aruba", 9, 11, 12.5, -70.0),
    ("PJ2", "Curacao", 9, 11, 12.1, -68.9),
    ("PJ4", "Bonaire", 9, 11, 12.2, -68.3),
    ("8P", "Barbados", 8, 11, 13.1, -59.6),
    ("J3", "Grenada", 8, 11, 12.1, -61.7),
    ("FG", "Guadeloupe", 8, 11, 16.2, -61.5),
    ("FM", "Martinique", 8, 11, 14.6, -61.0),
    ("V2", "Antigua & Barbuda", 8, 11, 17.1, -61.8),
    ("ZS ZR ZT ZU", "South Africa", 38, 57, -26.2, 28.0),
    ("5Z 5Y", "Kenya", 37, 48, -1.3, 36.8),
    ("5H 5I", "Tanzania", 37, 53, -6.8, 39.3),
    ("5N 5O", "Nigeria", 35, 46, 6.5, 3.4),
    ("9G", "Ghana", 35, 46, 5.6, -0.2),
    ("6W", "Senegal", 35, 46, 14.7, -17.4),
    ("D4", "Cape Verde", 35, 46, 14.9, -23.5),
    ("CN 5C 5D 5E 5F 5G", "Morocco", 33, 37, 34.0, -6.8),
    ("7X", "Algeria", 33, 37, 36.8, 3.1),
    ("3V TS", "Tunisia", 33, 37, 36.8, 10.2),
    ("SU SS", "Egypt", 34, 38, 30.0, 31.2),
    ("ET", "Ethiopia", 37, 48, 9.0, 38.7),
    ("EA8 EB8 EC8 ED8 EE8 EF8 EG8 EH8", "Canary Is.", 33, 36, 28.1, -15.4),
    ("CT3 CQ3 CR3", "Madeira", 33, 36, 32.6, -16.9),
    ("CU", "Azores", 14, 36, 37.7, -25.7),
    ("FR", "Reunion", 39, 53, -20.9, 55.5),
    ("3B8", "Mauritius", 39, 53, -20.2, 57.5),
    ("5R", "Madagascar", 39, 53, -18.9, 47.5),
    ("A2", "Botswana", 38, 57, -24.7, 25.9),
    ("V5", "Namibia", 38, 57, -22.6, 17.1),
    ("Z2", "Zimbabwe", 38, 53, -17.8, 31.0),
    ("9J", "Zambia", 36, 53, -15.4, 28.3),
    ("G M 2E 2M GX MX", "England", 14, 27, 51.5, -0.1),
    ("GM MM 2M GS MS", "Scotland", 14, 27, 55.9, -3.2),
    ("GW MW 2W GC MC", "Wales", 14, 27, 51.5, -3.2),
    ("GI MI 2I GN MN", "Northern Ireland", 14, 27, 54.6, -5.9),
    ("GD MD 2D GT MT", "Isle of Man", 14, 27, 54.2, -4.5),
    ("GJ MJ 2J GH MH", "Jersey", 14, 27, 49.2, -2.1),
    ("GU MU 2U GP MP", "Guernsey", 14, 27, 49.5, -2.5),
    ("EI EJ", "Ireland", 14, 27, 53.3, -6.3),
    ("F TM TK", "France", 14, 27, 48.9, 2.4),
    ("TK", "Corsica", 15, 28, 41.9, 8.7),
    ("ON OO OP OQ OR OS OT", "Belgium", 14, 27, 50.8, 4.4),
    ("PA PB PC PD PE PF PG PH PI", "Netherlands", 14, 27, 52.4, 4.9),
    ("LX", "Luxembourg", 14, 27, 49.6, 6.1),
    ("DL DA DB DC DD DE DF DG DH DI DJ DK DM DN DO DP DQ DR", "Germany", 14, 28, 52.5, 13.4),
    ("OE", "Austria", 15, 28, 48.2, 16.4),
    ("HB HE", "Switzerland", 14, 28, 46.9, 7.4),
    ("HB0", "Liechtenstein", 14, 28, 47.1, 9.5),
    ("I IK IZ IU IW IQ IN IR", "Italy", 15, 28, 41.9, 12.5),
    ("IS0 IM0", "Sardinia", 15, 28, 39.2, 9.1),
    ("IT9 IH9", "Sicily", 15, 28, 38.1, 13.4),
    ("9H", "Malta", 15, 28, 35.9, 14.5),
    ("T7", "San Marino", 15, 28, 43.9, 12.4),
    ("HV", "Vatican", 15, 28, 41.9, 12.5),
    ("EA EB EC ED EE EF EG EH AM AN AO", "Spain", 14, 37, 40.4, -3.7),
    ("EA6 EB6 EC6 ED6 EE6 EF6 EG6 EH6", "Balearic Is.", 14, 37, 39.6, 2.6),
    ("CT CQ CR CS", "Portugal", 14, 37, 38.7, -9.1),
    ("C3", "Andorra", 14, 27, 42.5, 1.5),
    ("3A", "Monaco", 14, 27, 43.7, 7.4),
    ("ZB2", "Gibraltar", 14, 37, 36.1, -5.4),
    ("OZ OU OV OW 5P 5Q", "Denmark", 14, 18, 55.7, 12.6),
    ("OX XP", "Greenland", 40, 5, 64.2, -51.7),
    ("OY", "Faroe Is.", 14, 18, 62.0, -6.8),
    ("LA LB LC LD LE LF LG LH LI LJ LK LL LM LN", "Norway", 14, 18, 59.9, 10.8),
    ("JW", "Svalbard", 40, 18, 78.2, 15.6),
    ("SM SA SB SC SD SE SF SG SH SI SJ SK SL 7S 8S", "Sweden", 14, 18, 59.3, 18.1),
    ("OH OF OG OI", "Finland", 15, 18, 60.2, 24.9),
    ("OH0", "Aland Is.", 15, 18, 60.1, 19.9),
    ("TF", "Iceland", 40, 17, 64.1, -21.9),
    ("ES", "Estonia", 15, 29, 59.4, 24.8),
    ("YL", "Latvia", 15, 29, 56.9, 24.1),
    ("LY", "Lithuania", 15, 29, 54.7, 25.3),
    ("SP SN SO SQ SR 3Z HF", "Poland", 15, 28, 52.2, 21.0),
    ("OK OL", "Czech Republic", 15, 28, 50.1, 14.4),
    ("OM", "Slovakia", 15, 28, 48.1, 17.1),
    ("HA HG", "Hungary", 15, 28, 47.5, 19.0),
    ("YO YP YQ YR", "Romania", 20, 28, 44.4, 26.1),
    ("LZ", "Bulgaria", 20, 28, 42.7, 23.3),
    ("SV SW SX SY SZ J4", "Greece", 20, 28, 37.98, 23.7),
    ("SV9 SW9 SX9 SY9 SZ9 J49", "Crete", 20, 28, 35.3, 25.1),
    ("SV5 J45", "Dodecanese", 20, 28, 36.4, 28.2),
    ("TA TB TC YM", "Turkey", 20, 39, 39.9, 32.9),
    ("5B C4 H2 P3", "Cyprus", 20, 39, 35.2, 33.4),
    ("9A", "Croatia", 15, 28, 45.8, 16.0),
    ("S5", "Slovenia", 15, 28, 46.1, 14.5),
    ("E7", "Bosnia-Herzegovina", 15, 28, 43.9, 18.4),
    ("YU YT", "Serbia", 15, 28, 44.8, 20.5),
    ("4O", "Montenegro", 15, 28, 42.4, 19.3),
    ("Z3", "North Macedonia", 15, 28, 42.0, 21.4),
    ("ZA", "Albania", 15, 28, 41.3, 19.8),
    ("Z6", "Kosovo", 15, 28, 42.7, 21.2),
    ("ER", "Moldova", 16, 29, 47.0, 28.9),
    ("UR US UT UU UV UW UX UY UZ EM EN EO", "Ukraine", 16, 29, 50.5, 30.5),
    ("EW EU EV", "Belarus", 16, 29, 53.9, 27.6),
    ("UA UB UC UD UE UF UG UH UI R RA RB RC RD RE RF RG RH RI RJ RK RL RM RN RO RP RQ RR RS RT RU RV RW RX RY RZ",
     "European Russia", 16, 29, 55.8, 37.6),
    ("UA2 RA2 R2F RA2F UA2F", "Kaliningrad", 15, 29, 54.7, 20.5),
    ("UA9 RA9 R9 UA0 RA0 R0 UI9 UI0", "Asiatic Russia", 17, 30, 55.0, 82.9),
    ("UN UO UP UQ", "Kazakhstan", 17, 29, 43.2, 76.9),
    ("4L", "Georgia", 21, 29, 41.7, 44.8),
    ("EK", "Armenia", 21, 29, 40.2, 44.5),
    ("4J 4K", "Azerbaijan", 21, 29, 40.4, 49.9),
    ("4X 4Z", "Israel", 20, 39, 32.1, 34.8),
    ("JY", "Jordan", 20, 39, 31.9, 35.9),
    ("OD", "Lebanon", 20, 39, 33.9, 35.5),
    ("HZ 7Z 8Z", "Saudi Arabia", 21, 39, 24.7, 46.7),
    ("A6", "United Arab Emirates", 21, 39, 25.2, 55.3),
    ("A7", "Qatar", 21, 39, 25.3, 51.5),
    ("A9", "Bahrain", 21, 39, 26.2, 50.6),
    ("9K", "Kuwait", 21, 39, 29.4, 48.0),
    ("A4", "Oman", 21, 39, 23.6, 58.4),
    ("EP EQ", "Iran", 21, 40, 35.7, 51.4),
    ("YI", "Iraq", 21, 39, 33.3, 44.4),
    ("AP 6P 6Q 6R 6S", "Pakistan", 21, 41, 33.7, 73.1),
    ("VU AT AU AV AW 8T 8U 8V 8W 8X 8Y", "India", 22, 41, 28.6, 77.2),
    ("4S", "Sri Lanka", 22, 41, 6.9, 79.9),
    ("S2", "Bangladesh", 22, 41, 23.8, 90.4),
    ("9N", "Nepal", 22, 42, 27.7, 85.3),
    ("BY BA BD BG BH BI BJ BL BT BZ B", "China", 24, 44, 39.9, 116.4),
    ("BV BM BN BO BP BQ BU BW BX", "Taiwan", 24, 44, 25.0, 121.5),
    ("VR", "Hong Kong", 24, 44, 22.3, 114.2),
    ("XX9", "Macao", 24, 44, 22.2, 113.5),
    ("JA JE JF JG JH JI JJ JK JL JM JN JO JP JQ JR JS 7J 7K 7L 7M 7N 8J 8N", "Japan", 25, 45, 35.7, 139.7),
    ("HL DS DT 6K 6L 6M 6N D7 D8 D9", "South Korea", 25, 44, 37.6, 127.0),
    ("JT JU JV", "Mongolia", 23, 32, 47.9, 106.9),
    ("HS E2", "Thailand", 26, 49, 13.8, 100.5),
    ("XV 3W", "Vietnam", 26, 49, 21.0, 105.8),
    ("XU", "Cambodia", 26, 49, 11.6, 104.9),
    ("XW", "Laos", 26, 49, 18.0, 102.6),
    ("XZ", "Myanmar", 26, 49, 16.8, 96.2),
    ("9M2 9M4 9W2", "West Malaysia", 28, 54, 3.1, 101.7),
    ("9M6 9M8 9W6 9W8", "East Malaysia", 28, 54, 5.98, 116.1),
    ("9V S6", "Singapore", 28, 54, 1.35, 103.8),
    ("YB YC YD YE YF YG YH 7A 7B 7C 7D 7E 7F 7G 7H 7I 8A 8B 8C 8D 8E 8F 8G 8H 8I", "Indonesia", 28, 51,
     -6.2, 106.8),
    ("DU DV DW DX DY DZ 4D 4E 4F 4G 4H 4I", "Philippines", 27, 50, 14.6, 121.0),
    ("V8", "Brunei", 28, 54, 4.9, 114.9),
    ("VK AX VH VI VJ VL VM VN VZ", "Australia", 30, 59, -33.9, 151.2),
    ("VK6 VK8", "Australia (west and north)", 29, 58, -31.95, 115.9),
    ("VK9N", "Norfolk Is.", 32, 60, -29.0, 167.9),
    ("ZL ZK ZM", "New Zealand", 32, 60, -41.3, 174.8),
    ("ZL7", "Chatham Is.", 32, 60, -43.9, -176.5),
    ("FK", "New Caledonia", 32, 56, -22.3, 166.4),
    ("FO", "French Polynesia", 32, 63, -17.5, -149.6),
    ("3D2", "Fiji", 32, 56, -18.1, 178.4),
    ("5W", "Samoa", 32, 62, -13.8, -171.8),
    ("A3", "Tonga", 32, 62, -21.1, -175.2),
    ("E5", "Cook Is.", 32, 62, -21.2, -159.8),
    ("P2", "Papua New Guinea", 28, 51, -9.4, 147.2),
    ("H4", "Solomon Is.", 28, 51, -9.4, 159.9),
    ("YJ", "Vanuatu", 32, 56, -17.7, 168.3),
    ("T2", "Tuvalu", 31, 65, -8.5, 179.2),
    ("T30", "Western Kiribati", 31, 65, 1.4, 173.0),
    ("V7", "Marshall Is.", 31, 65, 7.1, 171.4),
    ("V6", "Micronesia", 27, 65, 6.9, 158.2),
    ("T8", "Palau", 27, 64, 7.5, 134.6),
    ("VP8", "Falkland Is.", 13, 16, -51.7, -57.9),
    ("CE0Y XQ0Y 3G0Y", "Easter Is.", 12, 63, -27.1, -109.4),
    ("VP9", "Bermuda", 5, 11, 32.3, -64.8),
    ("FP", "St Pierre & Miquelon", 5, 9, 46.8, -56.2),
]

# US call areas: (CQ zone, ITU zone, lat, lon) of a typical spot
US_AREAS = {"1": (5, 8, 42.4, -71.1), "2": (5, 8, 40.7, -74.0), "3": (5, 8, 40.0, -77.0),
            "4": (5, 8, 33.7, -84.4), "5": (4, 7, 32.8, -97.0), "6": (3, 6, 36.8, -119.8),
            "7": (3, 6, 43.0, -114.0), "8": (4, 8, 40.4, -82.9), "9": (4, 8, 41.9, -87.6),
            "0": (4, 7, 40.0, -97.0)}
US_FIRST = ("K", "W", "N", "A")

_INDEX: dict | None = None


def _index() -> dict:
    global _INDEX
    if _INDEX is None:
        idx = {}
        for prefixes, country, cq, itu, lat, lon in PREFIXES:
            for p in prefixes.split():
                idx.setdefault(p, (country, cq, itu, lat, lon))
        _INDEX = idx
    return _INDEX


def lookup_call(call: str) -> dict | None:
    """Country, zones and a rough position for a call sign (longest prefix wins).
    A "/" part that is a prefix (like VP2E/N0TNT or N0TNT/KH6) counts."""
    c = (call or "").upper().strip()
    if not c:
        return None
    parts = [p for p in c.split("/") if p]
    if len(parts) > 1:
        tails = [p for p in parts if p not in ("P", "M", "MM", "AM", "QRP", "A") and not p.isdigit()]
        short = min(tails, key=len) if tails else parts[0]
        c = short if len(short) < len(max(parts, key=len)) else parts[0]
    idx = _index()
    hit = None
    for n in range(min(len(c), 5), 0, -1):
        if c[:n] in idx:
            hit = idx[c[:n]]
            break
    if not hit:
        return None
    country, cq, itu, lat, lon = hit
    if country == "United States":
        digit = next((ch for ch in c if ch.isdigit()), None)
        if digit in US_AREAS:
            cq, itu, lat, lon = US_AREAS[digit]
    return {"country": country, "cq": cq, "itu": itu, "lat": lat, "lon": lon}


# ---- cities (for a location without GPS) ----------------------------------------------------

CITIES = [
    ("Anchorage AK", 61.22, -149.90), ("Atlanta GA", 33.75, -84.39), ("Austin TX", 30.27, -97.74),
    ("Baltimore MD", 39.29, -76.61), ("Billings MT", 45.78, -108.50), ("Birmingham AL", 33.52, -86.80),
    ("Boise ID", 43.62, -116.20), ("Boston MA", 42.36, -71.06), ("Buffalo NY", 42.89, -78.88),
    ("Charleston SC", 32.78, -79.93), ("Charlotte NC", 35.23, -80.84), ("Cheyenne WY", 41.14, -104.82),
    ("Chicago IL", 41.88, -87.63), ("Cincinnati OH", 39.10, -84.51), ("Cleveland OH", 41.50, -81.69),
    ("Columbus OH", 39.96, -83.00), ("Dallas TX", 32.78, -96.80), ("Denver CO", 39.74, -104.99),
    ("Des Moines IA", 41.59, -93.62), ("Detroit MI", 42.33, -83.05), ("El Paso TX", 31.76, -106.49),
    ("Fargo ND", 46.88, -96.79), ("Hartford CT", 41.76, -72.69), ("Honolulu HI", 21.31, -157.86),
    ("Houston TX", 29.76, -95.37), ("Indianapolis IN", 39.77, -86.16), ("Jackson MS", 32.30, -90.18),
    ("Jacksonville FL", 30.33, -81.66), ("Kansas City MO", 39.10, -94.58), ("Las Vegas NV", 36.17, -115.14),
    ("Little Rock AR", 34.75, -92.29), ("Los Angeles CA", 34.05, -118.24), ("Louisville KY", 38.25, -85.76),
    ("Memphis TN", 35.15, -90.05), ("Miami FL", 25.76, -80.19), ("Milwaukee WI", 43.04, -87.91),
    ("Minneapolis MN", 44.98, -93.27), ("Nashville TN", 36.16, -86.78), ("New Orleans LA", 29.95, -90.07),
    ("New York NY", 40.71, -74.01), ("Newington CT (ARRL)", 41.71, -72.73), ("Oklahoma City OK", 35.47, -97.52),
    ("Omaha NE", 41.26, -95.93), ("Orlando FL", 28.54, -81.38), ("Philadelphia PA", 39.95, -75.17),
    ("Phoenix AZ", 33.45, -112.07), ("Pittsburgh PA", 40.44, -79.99), ("Portland ME", 43.66, -70.26),
    ("Portland OR", 45.52, -122.68), ("Raleigh NC", 35.78, -78.64), ("Reno NV", 39.53, -119.81),
    ("Richmond VA", 37.54, -77.44), ("Sacramento CA", 38.58, -121.49), ("Salt Lake City UT", 40.76, -111.89),
    ("San Antonio TX", 29.42, -98.49), ("San Diego CA", 32.72, -117.16), ("San Francisco CA", 37.77, -122.42),
    ("Seattle WA", 47.61, -122.33), ("Sioux Falls SD", 43.55, -96.73), ("Spokane WA", 47.66, -117.43),
    ("St. Louis MO", 38.63, -90.20), ("Tampa FL", 27.95, -82.46), ("Tucson AZ", 32.22, -110.97),
    ("Washington DC", 38.91, -77.04), ("Wichita KS", 37.69, -97.34),
    ("Calgary AB", 51.05, -114.07), ("Montreal QC", 45.50, -73.57), ("Toronto ON", 43.65, -79.38),
    ("Vancouver BC", 49.28, -123.12), ("Winnipeg MB", 49.90, -97.14), ("Halifax NS", 44.65, -63.58),
    ("Mexico City", 19.43, -99.13), ("Havana", 23.11, -82.37), ("San Juan PR", 18.47, -66.11),
    ("Bogota", 4.71, -74.07), ("Lima", -12.05, -77.04), ("Santiago", -33.45, -70.67),
    ("Buenos Aires", -34.60, -58.38), ("Sao Paulo", -23.55, -46.63),
    ("London", 51.51, -0.13), ("Dublin", 53.35, -6.26), ("Paris", 48.86, 2.35), ("Madrid", 40.42, -3.70),
    ("Lisbon", 38.72, -9.14), ("Berlin", 52.52, 13.40), ("Rome", 41.90, 12.50), ("Vienna", 48.21, 16.37),
    ("Stockholm", 59.33, 18.07), ("Oslo", 59.91, 10.75), ("Helsinki", 60.17, 24.94), ("Warsaw", 52.23, 21.01),
    ("Athens", 37.98, 23.73), ("Istanbul", 41.01, 28.98), ("Moscow", 55.76, 37.62), ("Reykjavik", 64.15, -21.94),
    ("Cairo", 30.04, 31.24), ("Nairobi", -1.29, 36.82), ("Johannesburg", -26.20, 28.05), ("Lagos", 6.52, 3.38),
    ("Tel Aviv", 32.09, 34.78), ("Dubai", 25.20, 55.27), ("Delhi", 28.61, 77.21), ("Mumbai", 19.08, 72.88),
    ("Bangkok", 13.76, 100.50), ("Singapore", 1.35, 103.82), ("Hong Kong", 22.32, 114.17),
    ("Beijing", 39.90, 116.41), ("Seoul", 37.57, 126.98), ("Tokyo", 35.68, 139.69), ("Manila", 14.60, 120.98),
    ("Jakarta", -6.21, 106.85), ("Sydney", -33.87, 151.21), ("Perth", -31.95, 115.86),
    ("Auckland", -36.85, 174.76), ("Honolulu (Pacific)", 21.31, -157.86),
]
