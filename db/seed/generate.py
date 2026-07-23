"""
Generate and load a realistic, internally consistent data set.

* 30 venues in 15 US cities (each in its own time zone), 1,200 events over ~19 months,
  60,000 users, ~300,000 tickets, check-ins, refunds, promo codes, waitlists and ratings.
* Time is relative to --as-of (default: now): events before it are completed and have
  door scans and ratings; events after it are on sale with partial sales.
* Data is loaded with every trigger and constraint ACTIVE, so a successful load proves
  the generated data obeys all the business rules (no double-booked rooms, no oversold
  ticket types, refunds never above payments, ratings only from attendees, ...).
* Deterministic: the same --seed and --as-of produce the same database.

Usage:
    python db/seed/generate.py [--scale 1.0] [--seed 42] [--as-of 2026-07-31]
"""
import argparse
import math
import os
import random
import re
import time
import uuid
from bisect import bisect
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from itertools import accumulate
from zoneinfo import ZoneInfo

import psycopg
from faker import Faker

UTC = timezone.utc

CITIES = [  # city, state, time zone
    ("Boston", "MA", "America/New_York"), ("New York", "NY", "America/New_York"),
    ("Philadelphia", "PA", "America/New_York"), ("Washington", "DC", "America/New_York"),
    ("Atlanta", "GA", "America/New_York"), ("Miami", "FL", "America/New_York"),
    ("Chicago", "IL", "America/Chicago"), ("Austin", "TX", "America/Chicago"),
    ("Nashville", "TN", "America/Chicago"), ("Minneapolis", "MN", "America/Chicago"),
    ("Denver", "CO", "America/Denver"), ("Phoenix", "AZ", "America/Phoenix"),
    ("Seattle", "WA", "America/Los_Angeles"), ("San Francisco", "CA", "America/Los_Angeles"),
    ("Los Angeles", "CA", "America/Los_Angeles"),
]
BIG_VENUES = ["Convention Center", "Expo Center", "Conference Center"]
SMALL_VENUES = ["Music Hall", "Civic Theater", "Riverside Hall", "Union Hall", "Lakeside Pavilion"]
BIG_ROOMS = ["Main Hall", "Ballroom A", "Ballroom B", "Room 101", "Room 102", "Room 201", "Room 202", "Workshop Lab"]
SMALL_ROOMS = ["Main Stage", "Studio", "Lounge", "Gallery"]

CATEGORY_TREE = {
    "Technology": ["Data & AI", "Cloud & DevOps", "Web Development", "Cybersecurity"],
    "Business": ["Startups", "Marketing", "Finance"],
    "Music": ["Concerts", "Festivals", "Jazz Nights"],
    "Arts & Culture": ["Theatre", "Film Screenings", "Exhibitions"],
    "Education": ["Workshops", "Career Fairs"],
    "Community": ["Meetups", "Charity Runs"],
}
TOP_WEIGHTS = {"Technology": 30, "Business": 15, "Music": 18, "Arts & Culture": 12, "Education": 12, "Community": 13}

TOPICS = {
    "Data & AI": ["Data Engineering", "Machine Learning", "Generative AI", "Analytics", "Data Platforms", "MLOps"],
    "Cloud & DevOps": ["Kubernetes", "Cloud Native", "Platform Engineering", "Site Reliability", "Serverless"],
    "Web Development": ["JavaScript", "React", "Web Performance", "Frontend", "API Design"],
    "Cybersecurity": ["Security", "Zero Trust", "Threat Intelligence", "AppSec", "Cloud Security"],
    "Startups": ["Founders", "Venture", "Product-Market Fit", "Startup Growth"],
    "Marketing": ["Growth Marketing", "Brand", "Content Marketing", "Marketing Analytics"],
    "Finance": ["Fintech", "Personal Finance", "Payments", "Investing"],
    "Workshops": ["SQL", "Python", "Excel", "Public Speaking", "Product Design", "Power BI"],
    "Career Fairs": ["Tech Careers", "Engineering Careers", "Healthcare Careers", "Internships"],
    "Meetups": ["Python", "PostgreSQL", "Data", "Women in Tech", "Product", "Design"],
}
TALKS = ["Scaling {t} at {c}", "Introduction to {t}", "{t} in production: lessons learned", "The future of {t}",
         "{t} anti-patterns and how to avoid them", "Building a {t} team from zero", "Hands-on {t}",
         "What we learned running {t} for {n} years", "{t} on a budget", "Case study: {t} at {c}"]
ADJ = ["Midnight", "Electric", "Golden", "Velvet", "Neon", "Silver", "Wild", "Northern", "Paper", "Coastal"]
NOUN = ["Echoes", "Lanterns", "Tides", "Owls", "Rivers", "Satellites", "Foxes", "Harbors", "Comets", "Pines"]
PLAYS = ["Hamlet", "A Doll's House", "The Glass Menagerie", "Our Town", "Twelfth Night", "Death of a Salesman",
         "The Importance of Being Earnest", "Much Ado About Nothing"]
COMMENTS = {5: ["Fantastic event, well organized.", "Best one yet, will come back!", "Great speakers and smooth check-in."],
            4: ["Really good, a bit crowded at lunch.", "Enjoyed it. Wi-Fi could be better.", "Good content overall."],
            3: ["It was okay. Some sessions ran late.", "Mixed: great keynote, weak afternoon.", "Average venue, good people."],
            2: ["Long queues at the door.", "Sound was poor in the main hall.", "Too expensive for what it was."],
            1: ["Disorganized and started an hour late.", "Would not recommend.", "Very disappointing."]}

# kind -> (days, local start hour, duration hours, capacity range, tiers, sessions?)
# tiers: (name, share of capacity, price range)
PROFILES = {
    "conference": dict(days=(1, 3), start=9, hours=8.5, cap=(200, 1500), sessions="conference",
                       tiers=[("Early Bird", .15, (149, 399)), ("General Admission", .62, (249, 799)),
                              ("VIP", .08, (899, 1499)), ("Student", .10, (49, 149))]),
    "workshop":   dict(days=(1, 1), start=9, hours=7, cap=(25, 80), sessions="workshop",
                       tiers=[("General Admission", .9, (49, 249))]),
    "concert":    dict(days=(1, 1), start=19, hours=3.5, cap=(300, 3000), sessions="show",
                       tiers=[("General Admission", .82, (35, 120)), ("VIP", .1, (150, 350))]),
    "festival":   dict(days=(2, 3), start=12, hours=10, cap=(1500, 5000), sessions="festival",
                       tiers=[("Early Bird", .2, (79, 149)), ("General Admission", .65, (129, 249)), ("VIP", .08, (299, 599))]),
    "jazz":       dict(days=(1, 1), start=20, hours=2.5, cap=(100, 300), sessions="show",
                       tiers=[("General Admission", .95, (25, 60))]),
    "theatre":    dict(days=(1, 1), start=19.5, hours=2.5, cap=(200, 1200), sessions="show",
                       tiers=[("Orchestra", .45, (60, 150)), ("Balcony", .5, (35, 80))]),
    "film":       dict(days=(1, 1), start=19, hours=2.5, cap=(100, 300), sessions="show",
                       tiers=[("General Admission", .95, (12, 20))]),
    "exhibition": dict(days=(1, 2), start=10, hours=8, cap=(300, 1000), sessions=None,
                       tiers=[("General Admission", .8, (15, 30)), ("Student", .15, (5, 10))]),
    "career":     dict(days=(1, 1), start=10, hours=6, cap=(500, 1500), sessions="panels",
                       tiers=[("Free Registration", .95, (0, 0))]),
    "meetup":     dict(days=(1, 1), start=18, hours=3, cap=(40, 150), sessions="meetup",
                       tiers=[("Free RSVP", .95, (0, 0))]),
    "run":        dict(days=(1, 1), start=8, hours=3, cap=(300, 2000), sessions=None,
                       tiers=[("5K Entry", .6, (25, 45)), ("10K Entry", .35, (35, 55))]),
}
LEAF_KIND = {"Data & AI": "conference", "Cloud & DevOps": "conference", "Web Development": "conference",
             "Cybersecurity": "conference", "Startups": "conference", "Marketing": "conference", "Finance": "conference",
             "Concerts": "concert", "Festivals": "festival", "Jazz Nights": "jazz", "Theatre": "theatre",
             "Film Screenings": "film", "Exhibitions": "exhibition", "Workshops": "workshop",
             "Career Fairs": "career", "Meetups": "meetup", "Charity Runs": "run"}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class Generator:
    def __init__(self, seed: int, scale: float, as_of: datetime):
        self.r = random.Random(seed)
        self.fake = Faker("en_US")
        self.fake.seed_instance(seed)
        self.scale = scale
        self.now = as_of
        self.t = defaultdict(list)          # table name -> rows
        self.ids = defaultdict(int)

    def next_id(self, table: str) -> int:
        self.ids[table] += 1
        return self.ids[table]

    def uuid4(self) -> uuid.UUID:
        return uuid.UUID(int=self.r.getrandbits(128), version=4)

    # ------------------------------------------------------------------ reference data
    def categories(self):
        self.leaves = []
        for top, leaves in CATEGORY_TREE.items():
            pid = self.next_id("categories")
            self.t["event_categories"].append((pid, top, None))
            for leaf in leaves:
                cid = self.next_id("categories")
                self.t["event_categories"].append((cid, leaf, pid))
                self.leaves.append((cid, leaf, top))

    def users(self):
        n = int(150000 * self.scale)
        self.users_by_city = defaultdict(list)
        domains = ["gmail.com", "outlook.com", "yahoo.com", "icloud.com", "proton.me", "northeastern.edu"]
        for i in range(n):
            uid = self.next_id("users")
            first, last = self.fake.first_name(), self.fake.last_name()
            city = self.r.choice(CITIES)[0]
            email = f"{slugify(first)}.{slugify(last)}{uid}@{self.r.choice(domains)}".replace("-", "")
            created = self.now - timedelta(days=self.r.randint(30, 900), minutes=self.r.randint(0, 1439))
            phone = f"+1{self.r.randint(201, 989)}{self.r.randint(2000000, 9999999)}" if self.r.random() < .6 else None
            self.t["users"].append((uid, email, f"{first} {last}", phone, city, created, self.r.random() > .01))
            self.users_by_city[city].append(uid)
        # A few heavy attendees and many occasional ones: skewed sampling weights.
        self.user_cum = list(accumulate(1 / (k + 1) ** 0.35 for k in range(n)))
        self.user_order = list(range(1, n + 1))
        self.r.shuffle(self.user_order)
        self.user_by_id = {row[0]: row for row in self.t["users"]}

    def pick_user(self, city: str) -> int:
        if self.r.random() < .6 and self.users_by_city[city]:
            return self.r.choice(self.users_by_city[city])
        return self.user_order[bisect(self.user_cum, self.r.random() * self.user_cum[-1])]

    def orgs(self):
        n = max(10, int(60 * self.scale))
        kinds = ["Labs", "Collective", "Events", "Society", "Group", "Productions", "Foundation", "Institute"]
        seen = set()
        self.org_ids = []
        while len(self.org_ids) < n:
            name = f"{self.fake.last_name()} {self.r.choice(kinds)}"
            if name in seen:
                continue
            seen.add(name)
            oid = self.next_id("orgs")
            self.org_ids.append(oid)
            self.t["organizations"].append((oid, name, slugify(name), f"hello@{slugify(name)}.org",
                                            self.now - timedelta(days=self.r.randint(500, 1500))))
            members = self.r.sample(range(1, len(self.t["users"]) + 1), self.r.randint(3, 8))
            for j, uid in enumerate(members):
                role = "owner" if j == 0 else ("admin" if j < 3 else "staff")
                self.t["org_members"].append((oid, uid, role, self.now - timedelta(days=self.r.randint(30, 500))))
        self.org_members = defaultdict(list)
        for oid, uid, role, _ in self.t["org_members"]:
            self.org_members[oid].append(uid)

    def venues(self):
        self.venue_rooms = {}
        self.venue_info = {}
        streets = ["Main St", "Harbor Blvd", "Market St", "Congress Ave", "Lake Shore Dr", "Broadway", "Summer St"]
        for city, state, tz in CITIES:
            for big in (True, False):
                vid = self.next_id("venues")
                name = f"{city} {self.r.choice(BIG_VENUES if big else SMALL_VENUES)}"
                cap = self.r.randint(3000, 10000) if big else self.r.randint(400, 1500)
                self.t["venues"].append((vid, name, f"{self.r.randint(10, 999)} {self.r.choice(streets)}", city, state,
                                         f"{self.r.randint(10000, 99999)}", "US", tz, cap))
                rooms = BIG_ROOMS[: self.r.randint(5, 8)] if big else SMALL_ROOMS[: self.r.randint(2, 4)]
                ids = []
                for k, rname in enumerate(rooms):
                    rid = self.next_id("rooms")
                    rcap = (cap if k == 0 else self.r.randint(60, 400)) if big else (cap if k == 0 else self.r.randint(40, 150))
                    self.t["rooms"].append((rid, vid, rname, rcap))
                    ids.append(rid)
                self.venue_rooms[vid] = ids
                self.venue_info[vid] = dict(city=city, tz=ZoneInfo(tz), cap=cap, big=big)
        self.venue_busy = defaultdict(list)

    def speakers(self):
        n = int(900 * self.scale) + 50
        companies = [self.fake.company() for _ in range(150)]
        for _ in range(n):
            sid = self.next_id("speakers")
            name = self.fake.name()
            self.t["speakers"].append((sid, name, f"{slugify(name)}.{sid}@speakers.example.org".replace("-", "."),
                                       self.r.choice(companies), self.fake.sentence(nb_words=14)))
        self.speaker_ids = list(range(1, n + 1))
        self.companies = companies

    # ------------------------------------------------------------------ events
    def title_for(self, kind, leaf, city, start):
        topic = self.r.choice(TOPICS.get(leaf, [leaf]))
        if kind == "conference":
            return self.r.choice([f"{topic} Summit {start.year}", f"{city} {topic} Conference",
                                  f"{topic} World {start.year}", f"{topic} Days {city}"]), topic
        if kind == "workshop":
            return f"Hands-on {topic} Workshop", topic
        if kind == "career":
            return f"{city} {topic} Fair", topic
        if kind == "meetup":
            return f"{city} {topic} Meetup #{self.r.randint(10, 120)}", topic
        if kind in ("concert", "jazz"):
            band = f"{self.r.choice(ADJ)} {self.r.choice(NOUN)}"
            return (f"{band} Live in {city}" if kind == "concert" else f"Jazz Night: {self.fake.last_name()} Quartet"), band
        if kind == "festival":
            return f"{city} {self.r.choice(['Summer', 'Harbor', 'Sunset', 'Riverfront'])} Music Festival {start.year}", "music"
        if kind == "theatre":
            play = self.r.choice(PLAYS)
            return f"{play}", play
        if kind == "film":
            return f"Film Night: {self.r.choice(ADJ)} {self.r.choice(NOUN)}", "film"
        if kind == "exhibition":
            return f"{self.r.choice(['Modern', 'Contemporary', 'Photography', 'Design'])} Art Exhibition", "art"
        return f"{city} Charity {self.r.choice(['5K', 'Fun Run', 'Run for Good'])}", "running"

    def describe(self, kind, topic, city):
        if kind in ("conference", "workshop", "meetup", "career"):
            return (f"Join practitioners in {city} for talks and hands-on sessions on {topic}. "
                    f"Learn how teams design, build and operate {topic.lower()} systems, meet speakers from "
                    f"{self.r.choice(self.companies)} and {self.r.choice(self.companies)}, and network with peers.")
        return (f"An evening of {topic} in {city}. Doors open one hour before the start. "
                f"All ages welcome; food and drinks available at the venue.")

    def find_venue(self, city_venues, start, end, need_cap, big_only):
        for vid in self.r.sample(city_venues, len(city_venues)):
            info = self.venue_info[vid]
            if big_only and not info["big"]:
                continue
            if info["cap"] < need_cap * 0.5:
                continue
            if all(end <= s or start >= e for s, e in self.venue_busy[vid]):
                return vid
        return None

    def events(self):
        n = int(1000 * self.scale)
        span_start, span_end = self.now - timedelta(days=420), self.now + timedelta(days=150)
        venues_by_city = defaultdict(list)
        for vid, info in self.venue_info.items():
            venues_by_city[info["city"]].append(vid)
        tops = list(TOP_WEIGHTS)
        made = 0
        while made < n:
            top = self.r.choices(tops, weights=[TOP_WEIGHTS[t] for t in tops])[0]
            cid, leaf, _ = self.r.choice([l for l in self.leaves if l[2] == top])
            kind = LEAF_KIND[leaf]
            p = PROFILES[kind]
            city = self.r.choice(CITIES)[0]
            day = span_start + timedelta(days=self.r.randint(0, (span_end - span_start).days))
            if kind in ("conference", "festival", "career", "exhibition") and day.weekday() == 6:
                day += timedelta(days=1)
            days = self.r.randint(*p["days"])
            vid_probe = venues_by_city[city][0]
            tz = self.venue_info[vid_probe]["tz"]
            h = p["start"]
            local_start = datetime(day.year, day.month, day.day, int(h), int((h % 1) * 60), tzinfo=tz)
            start = local_start.astimezone(UTC)
            end = (local_start + timedelta(days=days - 1, hours=p["hours"])).astimezone(UTC)
            want_cap = self.r.randint(*p["cap"])
            vid = self.find_venue(venues_by_city[city], start - timedelta(hours=6), end + timedelta(hours=6),
                                  want_cap, big_only=kind in ("conference", "festival", "career"))
            if vid is None:
                continue
            self.venue_busy[vid].append((start - timedelta(hours=6), end + timedelta(hours=6)))
            cap = min(want_cap, self.venue_info[vid]["cap"])
            eid = self.next_id("events")
            title, topic = self.title_for(kind, leaf, city, local_start)
            org = self.r.choice(self.org_ids)
            created = start - timedelta(days=self.r.randint(60, 200))
            created = min(created, self.now - timedelta(days=1))
            published = created + timedelta(days=self.r.randint(1, 10))
            if start > self.now:
                status = self.r.choices(["published", "draft", "cancelled"], [91, 7, 2])[0]
            elif end > self.now:
                status = "published"                          # happening right now
            else:
                status = self.r.choices(["completed", "cancelled"], [98.5, 1.5])[0]
            if published > self.now:
                status = "draft"
            cancel_at = None
            if status == "cancelled":
                lo, hi = published + timedelta(days=1), min(start - timedelta(days=1), self.now)
                if hi <= lo:
                    status = "draft" if start > self.now else "completed"
                else:
                    cancel_at = lo + (hi - lo) * self.r.random()
            pub = None if status == "draft" else published
            self.event_org[eid] = org
            self.t["events"].append((eid, org, vid, cid, title, f"{slugify(title)}-{eid}", self.describe(kind, topic, city),
                                     status, start, end, cap, pub, created, max(created, pub or created)))
            quality = self.r.uniform(3.1, 4.8)
            ev = dict(id=eid, kind=kind, city=city, start=start, end=end, cap=cap, vid=vid, status=status,
                      published=published, cancel_at=cancel_at, topic=topic, local_start=local_start, days=days, org=org,
                      quality=quality,
                      popularity=max(.15, min(1.0, self.r.betavariate(4, 2.2) + (quality - 3.95) * .3)),
                      hot=status == "published" and start > self.now + timedelta(days=7) and self.r.random() < .12)
            self.sessions_for(ev)
            if status != "draft":
                self.tickets_for(ev)
            made += 1

    def sessions_for(self, ev):
        mode = PROFILES[ev["kind"]]["sessions"]
        if not mode:
            return
        rooms = self.venue_rooms[ev["vid"]]
        tz = ev["local_start"].tzinfo

        def add(room, title, track, ls, minutes, n_speakers=1, role="speaker"):
            sid = self.next_id("sessions")
            s = ls.astimezone(UTC)
            self.t["sessions"].append((sid, ev["id"], room, title, track, s, s + timedelta(minutes=minutes)))
            for k, spk in enumerate(self.r.sample(self.speaker_ids, n_speakers)):
                self.t["session_speakers"].append((sid, spk, role if k == 0 else "panelist"))

        for d in range(ev["days"]):
            day0 = ev["local_start"] + timedelta(days=d)
            base = datetime(day0.year, day0.month, day0.day, tzinfo=tz)
            if mode == "conference":
                add(rooms[0], f"Keynote: The state of {ev['topic']}", "Keynote", base.replace(hour=9, minute=15), 60)
                tracks = rooms[1:min(len(rooms), 4)]
                for slot, (hh, mm) in enumerate([(10, 30), (11, 30), (13, 30), (14, 30), (15, 30)]):
                    for k, room in enumerate(tracks):
                        t = self.r.choice(TALKS).format(t=ev["topic"], c=self.r.choice(self.companies), n=self.r.randint(3, 10))
                        panel = t.startswith("The future")
                        add(room, ("Panel: " if panel else "") + t, f"Track {chr(65 + k)}",
                            base.replace(hour=hh, minute=mm), 45, 3 if panel else 1, "moderator" if panel else "speaker")
                add(rooms[0], "Closing remarks and networking", "Keynote", base.replace(hour=16, minute=30), 60)
            elif mode == "workshop":
                for hh, label in [(9, "Setup and fundamentals"), (11, "Guided exercises"), (14, "Capstone project")]:
                    add(rooms[-1], f"{ev['topic']}: {label}", "Workshop", base.replace(hour=hh), 105)
            elif mode == "show":
                ls = ev["local_start"]
                add(rooms[0], "Opening act", "Main Stage", ls, 45)
                add(rooms[0], "Main performance", "Main Stage", ls + timedelta(minutes=60), int(PROFILES[ev["kind"]]["hours"] * 60) - 70)
            elif mode == "festival":
                for k, room in enumerate(rooms[:3]):
                    for hh in range(12, 21, 2):
                        add(room, f"{self.r.choice(ADJ)} {self.r.choice(NOUN)}", f"Stage {k + 1}", base.replace(hour=hh), 90)
            elif mode == "panels":
                for hh in (10, 12, 14):
                    add(rooms[1], f"Panel: Breaking into {ev['topic']}", "Panels", base.replace(hour=hh), 60, 3, "moderator")
            elif mode == "meetup":
                ls = ev["local_start"]
                add(rooms[-1], f"Lightning talks: {ev['topic']}", "Talks", ls + timedelta(minutes=30), 50, 2)
                add(rooms[-1], f"{ev['topic']} deep dive", "Talks", ls + timedelta(minutes=90), 45)

    # ------------------------------------------------------------------ ticketing
    def sale_time(self, lo, hi):
        # Most tickets sell close to the event: density rises towards the end of the window.
        x = math.sqrt(self.r.random()) if self.r.random() > .25 else self.r.random() * .3
        return lo + (hi - lo) * x

    def tickets_for(self, ev):
        p = PROFILES[ev["kind"]]
        tiers = []
        for name, share, (lo, hi) in p["tiers"]:
            ttid = self.next_id("ticket_types")
            qty = max(1, int(ev["cap"] * share))
            price = round(self.r.uniform(lo, hi) / 5) * 5 - (1 if hi > 0 and self.r.random() < .5 else 0)
            price = max(price, 0)
            s_start = ev["published"]
            s_end = ev["start"] - timedelta(days=30) if name == "Early Bird" else ev["start"]
            if s_end <= s_start + timedelta(days=1):
                s_end = ev["start"]
            maxpo = 4 if name == "VIP" else 10
            tiers.append(dict(id=ttid, name=name, qty=qty, price=price, start=s_start, end=s_end, sold=0, maxpo=maxpo))
        promos = []
        if p["tiers"][0][2][1] > 0 and self.r.random() < .4:
            for _ in range(self.r.randint(1, 2)):
                pid = self.next_id("promo")
                code = self.r.choice(["EARLY", "STUDENT", "FRIENDS", "VIP", "SPRING", "FALL", "TEAM", "NEU"]) + str(self.r.randint(10, 99))
                if any(pc["code"] == code for pc in promos):
                    continue
                pct = self.r.random() < .7
                promos.append(dict(id=pid, code=code, type="percent" if pct else "amount",
                                   value=self.r.choice([10, 15, 20, 25, 50]) if pct else self.r.choice([5, 10, 20]),
                                   max_uses=self.r.choice([None, 50, 100, 200]), used=0,
                                   start=ev["published"], end=ev["start"]))
        ev["tiers"] = tiers

        cutoff = min(self.now, ev["cancel_at"] or ev["start"])
        user_tickets = []                                        # (order_id, user, [ticket ids])
        for tier in tiers:
            demand = {"Early Bird": 1.4, "Student": 1.15, "VIP": .8}.get(tier["name"], 1.0)
            target = int(tier["qty"] * min(1.0, ev["popularity"] * demand * self.r.uniform(.85, 1.1)))
            # Hot events sell out before today; their waitlists fill up.
            sell_end = min(tier["end"], self.now - timedelta(hours=12)) if ev["hot"] else tier["end"]
            if ev["hot"] and sell_end > tier["start"]:
                target = tier["qty"]
            while tier["sold"] < target:
                q = min(self.r.choices([1, 2, 3, 4, 6], [50, 30, 10, 7, 3])[0], tier["maxpo"], target - tier["sold"])
                when = self.sale_time(tier["start"], sell_end)
                if when > cutoff:
                    tier["sold"] += q                            # would sell later; not in the data yet
                    continue
                self.order(ev, tier, q, when, promos, user_tickets)
                tier["sold_real"] = tier.get("sold_real", 0) + q
                tier["sold"] += q
            # a few failed card payments: cancelled orders with no tickets
            for _ in range(self.r.randint(0, max(1, target // 60))):
                when = self.sale_time(tier["start"], tier["end"])
                if when <= cutoff:
                    self.order(ev, tier, 1, when, [], None, failed=True)

        refunded_qty = defaultdict(int)
        for oid, uid, tids, tt_qty, when in user_tickets:
            cancel_all = ev["status"] == "cancelled"
            if cancel_all:
                rtime = ev["cancel_at"]
            elif self.r.random() < .03:
                lo, hi = when + timedelta(hours=1), min(ev["start"], self.now)
                if hi <= lo:
                    continue
                rtime = lo + (hi - lo) * self.r.random()
            else:
                continue
            self.refund(oid, rtime, "Event cancelled by organizer" if cancel_all else
                        self.r.choice(["Can no longer attend", "Bought the wrong ticket type", "Duplicate purchase",
                                       "Schedule conflict"]))
            for tid in tids:
                self.ticket_status[tid] = "cancelled"
            for tt, q in tt_qty.items():
                refunded_qty[tt] += q

        for tier in tiers:
            sold = tier.get("sold_real", 0) - refunded_qty[tier["id"]]
            self.t["ticket_types"].append((tier["id"], ev["id"], tier["name"], tier["price"], "USD", tier["qty"], sold,
                                           tier["start"], tier["end"], tier["maxpo"]))
            tier["sold_now"] = sold
        for pc in promos:
            self.t["promo_codes"].append((pc["id"], ev["id"], pc["code"], pc["type"], pc["value"], pc["max_uses"],
                                          pc["used"], pc["start"], pc["end"]))

        if ev["status"] == "completed":
            self.door(ev, user_tickets)
        elif ev["status"] == "published":
            self.waitlist(ev)

    def order(self, ev, tier, q, when, promos, user_tickets, failed=False):
        oid = self.next_id("orders")
        uid = self.pick_user(ev["city"])
        subtotal = round(q * tier["price"], 2)
        promo_id, discount = None, 0
        usable = [pc for pc in promos if pc["start"] <= when <= pc["end"]
                  and (pc["max_uses"] is None or pc["used"] < pc["max_uses"])]
        if usable and subtotal > 0 and self.r.random() < .12:
            pc = self.r.choice(usable)
            promo_id = pc["id"]
            discount = round(subtotal * pc["value"] / 100, 2) if pc["type"] == "percent" else min(pc["value"], subtotal)
            pc["used"] += 1
        total = round(subtotal - discount, 2)
        paid = None if failed else when + timedelta(seconds=self.r.randint(2, 40))
        status = "cancelled" if failed else "paid"
        self.order_rows[oid] = [oid, uid, ev["id"], promo_id, status, subtotal, discount, total, when, paid, paid or when]
        item_id = self.next_id("order_items")
        self.t["order_items"].append((item_id, oid, tier["id"], q, tier["price"]))
        pay_id = self.next_id("payments")
        method = self.r.choices(["card", "paypal", "apple_pay", "bank_transfer"], [70, 15, 12, 3])[0]
        self.payment_rows[oid] = [pay_id, oid, total, method, "failed" if failed else "captured",
                                  f"pay_{self.uuid4().hex}", when + timedelta(seconds=1)]
        if failed:
            return
        buyer = self.user_by_id[uid]
        tids = []
        for k in range(q):
            tid = self.next_id("tickets")
            name, email = (buyer[2], buyer[1]) if k == 0 else (self.fake.name(), f"guest{tid}@example.com")
            code = self.uuid4()
            self.ticket_rows.append([tid, item_id, ev["id"], code, name, email, paid])
            self.ticket_status[tid] = "valid"
            self.ticket_code[tid] = code
            tids.append(tid)
        user_tickets.append((oid, uid, tids, {tier["id"]: q}, when))

    def refund(self, oid, when, reason):
        o = self.order_rows[oid]
        o[4] = "refunded"
        o[10] = when
        pay = self.payment_rows[oid]
        if o[7] > 0:
            pay[4] = "refunded"
            rid = self.next_id("refunds")
            staff = self.r.choice(self.org_members[self.event_org[o[2]]])
            self.t["refunds"].append((rid, oid, pay[0], o[7], reason, staff, when))

    def door(self, ev, user_tickets):
        tz = ev["local_start"].tzinfo
        gates = ["Gate A", "Gate B", "Gate C"] if ev["cap"] > 500 else ["Main Entrance"]
        staff = self.org_members[ev["org"]]
        free = all(t["price"] == 0 for t in ev["tiers"])
        show = self.r.uniform(.55, .72) if free else self.r.uniform(.84, .95)
        attended_users = set()
        for oid, uid, tids, _, _ in user_tickets:
            for k, tid in enumerate(tids):
                if self.ticket_status[tid] != "valid" or self.r.random() > show:
                    continue
                offset = max(-90, min(150, self.r.gauss(-15, 30)))
                when = ev["start"] + timedelta(minutes=offset, seconds=self.r.randint(0, 59))
                cid = self.next_id("check_ins")
                gate = self.r.choice(gates)
                self.t["check_ins"].append((cid, tid, ev["id"], gate, self.r.choice(staff), when))
                self.ticket_status[tid] = "checked_in"
                self.t["scan_attempts"].append((self.ticket_code[tid], gate, "admitted", when))
                if self.r.random() < .015:              # someone tries the same ticket again
                    self.t["scan_attempts"].append((self.ticket_code[tid], gate, "already_checked_in",
                                                    when + timedelta(minutes=self.r.randint(1, 90))))
                attended_users.add((oid, uid))
            if self.ticket_status[tids[0]] == "cancelled" and self.r.random() < .1:
                self.t["scan_attempts"].append((self.ticket_code[tids[0]], gates[0], "cancelled", ev["start"]))
        for _ in range(self.r.randint(0, 5)):
            self.t["scan_attempts"].append((self.uuid4(), gates[0], "not_found",
                                            ev["start"] + timedelta(minutes=self.r.randint(-60, 60))))
        rated = set()
        for oid, uid in attended_users:
            if uid in rated or self.r.random() > .3:
                continue
            rated.add(uid)
            rating = max(1, min(5, round(self.r.gauss(ev["quality"], .9))))
            comment = self.r.choice(COMMENTS[rating]) if self.r.random() < .4 else None
            fid = self.next_id("feedback")
            self.t["feedback"].append((fid, ev["id"], uid, rating, comment,
                                       ev["end"] + timedelta(hours=self.r.randint(2, 96))))

    def waitlist(self, ev):
        for tier in ev["tiers"]:
            if tier.get("sold_now", 0) < tier["qty"]:
                continue
            for uid in set(self.pick_user(ev["city"]) for _ in range(self.r.randint(5, 40))):
                wid = self.next_id("waitlist")
                joined = min(self.now, tier["end"]) - timedelta(hours=self.r.randint(1, 240))
                self.t["waitlist"].append((wid, tier["id"], uid, self.r.choice([1, 1, 1, 2]), "waiting", joined, None, None))

    # ------------------------------------------------------------------ driver
    def build(self):
        self.order_rows, self.payment_rows = {}, {}
        self.ticket_rows, self.ticket_status, self.ticket_code = [], {}, {}
        self.event_org = {}
        self.categories(); self.users(); self.orgs(); self.venues(); self.speakers()
        self.events()
        self.t["orders"] = list(map(tuple, self.order_rows.values()))
        self.t["payments"] = list(map(tuple, self.payment_rows.values()))
        self.t["tickets"] = [(tid, item, eid, code, name, email, self.ticket_status[tid], issued)
                             for tid, item, eid, code, name, email, issued in self.ticket_rows]


# table, columns, identity column (None if none)
LOAD_ORDER = [
    ("event_categories", "category_id, name, parent_id", "category_id"),
    ("users", "user_id, email, full_name, phone, city, created_at, is_active", "user_id"),
    ("organizations", "org_id, name, slug, contact_email, created_at", "org_id"),
    ("org_members", "org_id, user_id, role, joined_at", None),
    ("venues", "venue_id, name, address_line, city, state, postal_code, country, timezone, capacity", "venue_id"),
    ("rooms", "room_id, venue_id, name, capacity", "room_id"),
    ("speakers", "speaker_id, full_name, email, company, bio", "speaker_id"),
    ("events", "event_id, org_id, venue_id, category_id, title, slug, description, status, starts_at, ends_at, "
               "capacity, published_at, created_at, updated_at", "event_id"),
    ("sessions", "session_id, event_id, room_id, title, track, starts_at, ends_at", "session_id"),
    ("session_speakers", "session_id, speaker_id, role", None),
    ("ticket_types", "ticket_type_id, event_id, name, price, currency, quantity_total, quantity_sold, "
                     "sales_start, sales_end, max_per_order", "ticket_type_id"),
    ("promo_codes", "promo_id, event_id, code, discount_type, discount_value, max_uses, times_used, "
                    "valid_from, valid_until", "promo_id"),
    ("orders", "order_id, user_id, event_id, promo_id, status, subtotal, discount, total, created_at, paid_at, "
               "updated_at", "order_id"),
    ("order_items", "order_item_id, order_id, ticket_type_id, quantity, unit_price", "order_item_id"),
    ("payments", "payment_id, order_id, amount, method, status, provider_ref, created_at", "payment_id"),
    ("refunds", "refund_id, order_id, payment_id, amount, reason, processed_by, created_at", "refund_id"),
    ("tickets", "ticket_id, order_item_id, event_id, code, attendee_name, attendee_email, status, issued_at", "ticket_id"),
    ("check_ins", "check_in_id, ticket_id, event_id, gate, scanned_by, checked_in_at", "check_in_id"),
    ("scan_attempts", "code, gate, result, attempted_at", None),
    ("waitlist", "waitlist_id, ticket_type_id, user_id, quantity, status, joined_at, offered_at, offer_expires_at",
     "waitlist_id"),
    ("feedback", "feedback_id, event_id, user_id, rating, comment, created_at", "feedback_id"),
]


def load(url: str, g: Generator) -> dict:
    counts = {}
    with psycopg.connect(url) as con:
        with con.transaction():
            con.execute("SET LOCAL app.user_id = 'seed'")
            for table, cols, ident in LOAD_ORDER:
                if ident:
                    con.execute(f"ALTER TABLE app.{table} ALTER COLUMN {ident} SET GENERATED BY DEFAULT")
                t0 = time.time()
                rows = g.t[table]
                with con.cursor().copy(f"COPY app.{table} ({cols}) FROM STDIN") as cp:
                    for row in rows:
                        cp.write_row(row)
                if ident:
                    con.execute(f"ALTER TABLE app.{table} ALTER COLUMN {ident} SET GENERATED ALWAYS")
                    con.execute(f"SELECT setval(pg_get_serial_sequence('app.{table}', '{ident}'), "
                                f"(SELECT coalesce(max({ident}), 0) + 1 FROM app.{table}), false)")
                con.execute(f"ANALYZE app.{table}")              # later triggers need real statistics
                counts[table] = len(rows)
                print(f"  {table:<18} {len(rows):>9,} rows  {time.time() - t0:5.1f}s")
            con.execute("TRUNCATE audit.change_log")            # seed history isn't real user activity
        con.autocommit = True
        con.execute("SELECT report.refresh()")
        con.execute("ANALYZE")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=float, default=1.0, help="1.0 = 60k users, 1,200 events")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="reference date (default: today)")
    args = ap.parse_args()
    as_of = datetime.combine(args.as_of, datetime.min.time(), UTC) + timedelta(hours=12) if args.as_of \
        else datetime.now(UTC).replace(microsecond=0)
    url = os.getenv("DATABASE_URL", "postgresql:///event_mgmt")
    t0 = time.time()
    g = Generator(args.seed, args.scale, as_of)
    g.build()
    print(f"generated in {time.time() - t0:.1f}s (as of {as_of:%Y-%m-%d %H:%M} UTC); loading with all constraints on:")
    load(url, g)
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
