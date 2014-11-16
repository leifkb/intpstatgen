import sqlite3
from tempfile import NamedTemporaryFile
import shutil
import os
from collections import namedtuple
from datetime import datetime, date, timedelta
import jinja2
import simplejson as json
import requests
from StringIO import StringIO
import sys
from xml.sax.saxutils import unescape
import re

SKYPE_DB = '/Users/leif/Library/Application Support/Skype/eurleif/main.db'
CHAT_NAME = '19:78317a8dceb646ff9d62ea2e31b4decb@thread.skype'
NEOCITIES_USERNAME = 'intpstats'
NEOCITIES_PASSWORD = sys.argv[1] if len(sys.argv) > 1 else None
URL = 'http://intpstats.neocities.org'
SkypeMessage = namedtuple('SkypeMessage', 'timestamp author message edited'.split())

template_env = jinja2.Environment(loader=jinja2.PackageLoader('intpstatgen', 'templates'))
template_env.filters['tojson'] = json.dumps

def extract_xml_text(data):
    data = re.sub(u'<[^>]+>', u'', data)
    data = unescape(data, {u"&apos;": u"'", u"&quot;": u'"'})
    return data

def open_db():
    with NamedTemporaryFile(delete=False) as f:
        shutil.copy(SKYPE_DB, f.name)
        try:
            db = sqlite3.connect(f.name)
        finally:
            os.unlink(f.name)
        return db

def read_msgs():
    result = []

    with open_db() as db:
        cur = db.cursor()
        cur.execute('SELECT timestamp, author, body_xml, edited_timestamp FROM messages WHERE chatname=? ORDER BY timestamp ASC', [CHAT_NAME])
        for timestamp, author, body, edit_timestamp in cur:
            if body:
                result.append(SkypeMessage(datetime.utcfromtimestamp(timestamp), author, extract_xml_text(body), bool(edit_timestamp)))

    return result

def count_msg_runs(msgs):
    result = 0
    last_author = None

    for msg in msgs:
        if msg.author != last_author:
            last_author = msg.author
            result += 1

    return result

def msgs_by_day(msgs):
    result = []
    last_author = None
    last_day = None
    for msg in msgs:
        day = msg.timestamp.date()
        while last_day is None or last_day < day:
            result.append(0)
            if last_day is None:
                last_day = day
            else:
                last_day += timedelta(days=1)
        if msg.author == last_author:
            continue
        last_author = msg.author
        result[-1] += 1
    return result

def msgs_by_author_by_day(msgs):
    zeroes = []
    authors = {}
    last_author = None
    last_day = None
    for msg in msgs:
        day = msg.timestamp.date()
        while last_day is None or last_day < day:
            zeroes.append(0)
            for v in authors.itervalues():
                v.append(0)
            if last_day is None:
                last_day = day
            else:
                last_day += timedelta(days=1)
        if msg.author == last_author:
            continue
        last_author = msg.author
        if msg.author not in authors:
            authors[msg.author] = zeroes[:]
        authors[msg.author][-1] += 1
    return authors

def msgs_by_author(msgs):
    result = {}
    last_author = None
    for msg in msgs:
        if last_author == msg.author:
            continue
        last_author = msg.author
        result[msg.author] = result.get(msg.author, 0) + 1
    return result

def only_top_authors(d, by_author, n=20):
    top = set(k for k, v in sorted(by_author.iteritems(), key=lambda (k,v): v)[-n:])
    for k in d.keys():
        if k not in top:
            del d[k]
    return d

def date_labels(msgs):
    result = []
    start_date = msgs[0].timestamp.date()
    end_date = msgs[-1].timestamp.date()
    date = start_date
    while date <= end_date:
        result.append(date.isoformat())
        date += timedelta(days=1)
    return result

def words_by_day(msgs):
    result = []
    last_day = None
    for msg in msgs:
        day = msg.timestamp.date()
        while last_day is None or last_day < day:
            result.append(0)
            if last_day is None:
                last_day = day
            else:
                last_day += timedelta(days=1)
        result[-1] += len(msg.message.split())
    return result

def authors_by_day(msgs):
    result = []
    last_day = None
    for msg in msgs:
        day = msg.timestamp.date()
        while last_day is None or last_day < day:
            result.append(0)
            last_authors = set()
            if last_day is None:
                last_day = day
            else:
                last_day += timedelta(days=1)
        if msg.author not in last_authors:
            result[-1] += 1
            last_authors.add(msg.author)
    return result

def words_per_msg(msgs):
    word_counts = {}
    msg_counts = {}
    last_author = None
    for msg in msgs:
        if last_author != msg.author:
            last_author = msg.author
            msg_counts[msg.author] = msg_counts.get(msg.author, 0) + 1
            msg_counts[None] = msg_counts.get(None, 0) + 1
        word_count = len(msg.message.split())
        word_counts[msg.author] = word_counts.get(msg.author, 0) + word_count
        word_counts[None] = word_counts.get(None, 0) + word_count
    result = {}
    for author, msg_count in msg_counts.iteritems():
        result[author] = word_counts.get(author, 0) / float(msg_count)
    return result

def messages_by_day_of_week(msgs):
    days = [0] * 7
    last_author = None
    for msg in msgs:
        if last_author == msg.author:
            continue
        last_author = msg.author
        days[msg.timestamp.date().isoweekday() % 7] += 1
    return days

def messages_by_hour(msgs):
    hours = [0] * 24
    last_author = None
    for msg in msgs:
        if last_author == msg.author:
            continue
        last_author = msg.author
        hours[msg.timestamp.hour] += 1
    return hours

def common_words(msgs, n=50):
    words = {}
    for msg in msgs:
        for word in msg.message.split():
            word = word.lower()
            words[word] = words.get(word, 0) + 1
    return rank_dict(words)[:n]

def words_following_hello(msgs):
    words = {}
    for msg in msgs:
        m = re.search(ur"^.{,6}\b(?:hello|hey|ha?i+|greetings|morning),?\s+([a-z0-9'-]+).{,4}$", msg.message, re.I)
        if m:
            word = m.group(1).lower()
            words[word] = words.get(word, 0) + 1
    return rank_dict(words)

def msgs_matching(msgs, pattern):
    result = {}
    last_author = None
    last_counted = False
    for msg in msgs:
        if last_author != msg.author:
            last_author = msg.author
            last_counted = False
        if last_counted:
            continue
        if pattern.search(msg.message):
            result[msg.author] = result.get(msg.author, 0) + 1
            last_counted = True
    return result

def top_msgs_matching(msgs, pattern, n=15):
    return rank_dict(msgs_matching(msgs, pattern))[:n]

def edit_percentages(msgs):
    msg_counts = {}
    edited = {}
    last_author = None
    last_counted = False
    for msg in msgs:
        if last_author != msg.author:
            last_author = msg.author
            msg_counts[msg.author] = msg_counts.get(msg.author, 0) + 1
            msg_counts[None] = msg_counts.get(None, 0) + 1
            last_counted = False
        if last_counted:
            continue
        if msg.edited:
            last_counted = True
            edited[msg.author] = edited.get(msg.author, 0) + 1
            edited[None] = edited.get(None, 0) + 1
    result = {}
    for author, msg_count in msg_counts.iteritems():
        result[author] = 100 * float(edited.get(author, 0)) / msg_count
    return result

def active_days_by_author(msgs):
    result = {}
    last_author = None
    last_day = None
    for msg in msgs:
        if last_author == msg.author:
            continue
        last_author = msg.author
        day = msg.timestamp.date()
        if day != last_day:
            last_day = day
            day_active = set()
        if msg.author not in day_active:
            day_active.add(msg.author)
            result[msg.author] = result.get(msg.author, 0) + 1
    return result

def rank_dict(d):
    return sorted(d.iteritems(), key=lambda (k, v): v, reverse=True)

def percent_uppercase(msgs):
    letter_counts = {}
    upper_counts = {}
    for msg in msgs:
        for char in msg.message:
            if not char.isalpha():
                continue
            letter_counts[None] = letter_counts.get(None, 0) + 1
            letter_counts[msg.author] = letter_counts.get(msg.author, 0) + 1
            if char.isupper():
                upper_counts[None] = upper_counts.get(None, 0) + 1
                upper_counts[msg.author] = upper_counts.get(msg.author, 0) + 1
    result = {}
    for author, letter_count in letter_counts.iteritems():
        result[author] = 100 * float(upper_counts.get(author, 0)) / letter_count
    return result

def generate_page():
    msgs = read_msgs()
    by_author = msgs_by_author(msgs)
    top_authors = rank_dict(by_author)[:15]
    wpm = words_per_msg(msgs)
    wpm_overall = wpm[None]
    wpm = rank_dict(only_top_authors(wpm, by_author))
    edited = edit_percentages(msgs)
    edited_overall = edited[None]
    edited = rank_dict(only_top_authors(edited, by_author))
    pct_uppercase = percent_uppercase(msgs)
    pct_uppercase_overall = pct_uppercase[None]
    pct_uppercase = rank_dict(only_top_authors(pct_uppercase, by_author))
    return template_env.get_template('stats.html').render(
        top_authors=top_authors,
        date_labels=date_labels(msgs),
        last_updated=datetime.utcnow().isoformat()[:19].replace('T', ' '),
        msg_count=count_msg_runs(msgs),
        msgs_by_day=msgs_by_day(msgs),
        authors_by_day=authors_by_day(msgs),
        msgs_by_author_by_day=only_top_authors(msgs_by_author_by_day(msgs), by_author),
        words_per_msg=wpm,
        overall_words_per_msg=wpm_overall,
        days_of_week=messages_by_day_of_week(msgs),
        hours=messages_by_hour(msgs),
        hellos=words_following_hello(msgs)[:20],
        love=top_msgs_matching(msgs, re.compile(ur'\b(love|loving)', re.I)),
        hate=top_msgs_matching(msgs, re.compile(ur'\b(hate|hatred|hating)', re.I)),
        penis=top_msgs_matching(msgs, re.compile(ur'\b(cock|dick|penis|wang|boner|dong)', re.I)),
        boobs=top_msgs_matching(msgs, re.compile(ur'\b(tit|boob|breast|clit|pussy|vagina)', re.I)),
        fuck=top_msgs_matching(msgs, re.compile(ur'fuck', re.I)),
        shit=top_msgs_matching(msgs, re.compile(ur'shit', re.I)),
        edited=edited,
        edited_overall=edited_overall,
        active_days_by_author=rank_dict(active_days_by_author(msgs))[:15],
        laughers=top_msgs_matching(msgs, re.compile(ur'\blol([lo]*)\b|\bha[ah]*\b|\brofl\b', re.I)),
        percent_uppercase=pct_uppercase,
        percent_uppercase_overall=pct_uppercase_overall
    )

if __name__ == '__main__':
    page = generate_page()
    if NEOCITIES_PASSWORD is not None:
        f = StringIO(page)
        requests.post('https://neocities.org/api/upload', auth=(NEOCITIES_USERNAME, NEOCITIES_PASSWORD), files={'index.html': f})
        url = URL
    else:
        with open('/tmp/intp.html', 'w') as f:
            f.write(page)
        url = 'file:///tmp/intp.html'
        import webbrowser
        webbrowser.open(url)