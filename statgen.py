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
SkypeMessage = namedtuple('SkypeMessage', 'timestamp author message'.split())

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
        cur.execute('SELECT timestamp, author, body_xml FROM messages WHERE chatname=? ORDER BY timestamp ASC', [CHAT_NAME])
        for timestamp, author, body in cur:
            if body:
                result.append(SkypeMessage(datetime.utcfromtimestamp(timestamp), author, extract_xml_text(body)))

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

def only_top_authors(d, by_author, n=20, include_none=True):
    top = set(k for k, v in sorted(by_author.iteritems(), key=lambda (k,v): v)[-n:])
    for k in d.keys():
        if (not include_none or k is not None) and k not in top:
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
    return sorted(words.iteritems(), key=lambda (k, v): v, reverse=True)[:n]

def words_following_hello(msgs):
    words = {}
    for msg in msgs:
        m = re.search(ur"^.{,6}\b(?:hello|hey|hi+|greetings|morning),?\s+([a-z0-9'-]+).{,4}$", msg.message, re.I)
        if m:
            word = m.group(1).lower()
            words[word] = words.get(word, 0) + 1
    return sorted(words.iteritems(), key=lambda (k, v): v, reverse=True)

def generate_page():
    msgs = read_msgs()
    by_author = msgs_by_author(msgs)
    top_authors = sorted(by_author.iteritems(), key=lambda (k, v): v, reverse=True)[:10]
    wpm = only_top_authors(words_per_msg(msgs), by_author)
    wpm_overall = wpm[None]
    wpm = sorted(wpm.iteritems(), key=lambda (k, v): v, reverse=True)
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