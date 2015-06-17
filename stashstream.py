#!/usr/bin/env python
# Stash Stream server side script
# 2015 by Christian Loosli, IT Services of Biel
# Licensed under MIT License, see Copying.txt

import os
import sys
import cgi
import json
import base64
import urllib2
import requests
import datetime
import logging
from requests.auth import HTTPBasicAuth
from dateutil import tz

SERVICEUSER = 'username'
SERVICEPASSWORD = 'user password'
STASHBASEURL = 'https://stash.yourdomain.tld'
JIRARESTURL = 'https://jira.yourdomain.tld/rest/activities/1.0/'
CERT = '/opt/certificate/CertificateForHttps.crt'
DISPLAYNAME = 'Stash Git'


def main():
    """The data is received here as json payload in a stash web commit hook,
    This method calls getDetailsFromStash per commit.
    """

    # Already print the http header as a reply
    print "Content-type: text/html\n\n"

    data = sys.stdin.read()
    myjson = json.loads(data)

    repo = myjson['repository']['name']
    project = myjson['repository']['project']['key']
    commitIds = set([changeset['toCommit']['id'] for changeset in myjson['changesets']['values']])

    for commitid in commitIds:
        try:
            getDetailsFromStash(project, repo, commitid)
        except:
            pass

def getDetailsFromStash(project, repo, commitid):
    """ Unfortunately the post hook doesn't contain all information we need,
    this method uses the project, repo and commit id to fetch the remaining
    information directly from stash via its REST API.
    """

    stashurl = '%s/rest/api/1.0/projects/%s/repos/%s/commits/%s' \
        % (STASHBASEURL, project, repo, commitid)

    try:
        # Get a json representation of the commit
        request = urllib2.Request(stashurl)
        base64string = base64.encodestring('%s:%s' % (SERVICEUSER,
                                           SERVICEPASSWORD)).replace('\n', '')
        # Manually add authentication, because the server doesn't ask for it,
        # but only shows public repos without it.
        request.add_header("Authorization", "Basic %s" % base64string)

        response = urllib2.urlopen(request).read()

        commit = json.loads(response)

        # Author might not be present, check before reading
        userid = 'unknown'
        username = 'Unknown User'
        if 'author' in commit:
            if 'slug' in commit['author']:
                userid = commit['author']['slug']
            if 'displayName' in commit['author']:
                username = commit['author']['displayName']

        # Currently it has to be a commit, because the web hook
        # is only ever called on these
        type = 'commit'
        url = '%s/projects/%s/repos/%s/commits/%s' % (STASHBASEURL,
                                                      project, repo, commitid)
        shortid = commit['displayId']

        # Ticket might not be present, check before reading
        ticket = ''
        if 'attributes' in commit:
            if 'jira-key' in commit['attributes']:
                ticket = commit['attributes']['jira-key'].pop()
        comment = commit['message']

        authorTimestamp = str(commit['authorTimestamp'])
        # We have to trim a bit, as numbers (usually 0s)
        # are added, then we format it
        unixTimestamp = authorTimestamp[0:10]
        timestamp = datetime.datetime.fromtimestamp(int(unixTimestamp))
        # Convert time around, since it is UTC,
        # but python thinks it is local
        from_zone = tz.tzlocal()
        to_zone = tz.tzutc()

        timestamp = timestamp.replace(tzinfo=from_zone)
        utc = timestamp.astimezone(to_zone)
        timestamp = utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        sendActivity(userid, username, type, url, shortid,
                     ticket, repo, project, comment, timestamp)
    except:
        logging.exception("Oops:")
        raise


def sendActivity(userid, username, type, url, shortid, ticket,
                 repo, project, comment, timestamp):
    """ This method uses the information gathered before to craft the json
    which is understood by the JIRA REST API for activity streams.
    """
    contenttype = 'application/vnd.atl.streams.thirdparty+json'
    jiraurl = JIRARESTURL

    try:
        if not repo:
            log.info("[EE] An error occured: no repo was specified")
            return

        if not userid:
            userid = 'unknown'
        if not username:
            username = 'Unknown User'
        if not type:
            type = 'unknown'

        userurl = "%s/users/%s" % (STASHBASEURL, userid)
        comurl = "https://awebserver.yourdomain.tld/stashicons/commit.png"

        if type == 'commit':
            iconurl = comurl
            verb = 'commited'
            object = "in %s / %s" % (project, repo)
        else:
            log.info("[EE] An unknown action was used in sendActivity")
            return

        if not url:
            url = ''

        if not shortid:
            shortid = ''

        if not ticket:
            ticket = ''

        if not comment:
            comment = 'No comment was set'

        title = "<b>%s</b> %s %s" % (username, verb, object)
        content = "Commited <a href=\"%s\">%s</a> with message <br /><blockquote>%s</blockquote>" % (url, shortid, comment)

        data = {
            'published': timestamp,
            'actor': {'id': userid},
            'icon': {'url': iconurl, 'width': '16', 'height': '16'},
            'object': {'id': url, 'objectType': type, 'url': url},
            'generator': {'id': STASHBASEURL,
                          'displayName': DISPLAYNAME},
            'target': {'url': ticket},
            'id': userurl,
            'title': title,
            'content': content,
            }

        payload = json.dumps(data)

        headers = {'Content-Type': contenttype}
    except:
        logging.exception("Oops:")
        raise

    try:
        r = requests.post(jiraurl, data=payload, headers=headers,
                          auth=HTTPBasicAuth(SERVICEUSER,
                                             SERVICEPASSWORD),
                          verify=CERT)
        print "<html><body>%s</body></html>" % r.text
    except:
        raise

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        filename='/var/log/stashstream.log')
    try:
        main()
    except:
        logging.exception("Oops:")
        print "<html><body>Errors occured. Failed.</body></html>"
