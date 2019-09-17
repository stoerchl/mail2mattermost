#!/usr/bin/env python
# Copyright (c) 2019 @stoerchl
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# Usage:
# - python mail2mattermost.py start mail2mattermost.conf
# - python mail2mattermost.py stop mail2mattermost.conf
# - python mail2mattermost.py restart mail2mattermost.conf
#

import re
import ast
import sys
import time
import configparser
import json
import requests
import hashlib
import os
import multiprocessing
import inspect
from imbox import Imbox
from daemon import Daemon

class EmailListener(object):

    def run(self, config):
        SERVER_URL = str(config['mt_server_url'])
        CHANNEL_ID = str(config['mt_channel_id'])
        BEARER_TOKEN = str(config['mt_bearer'])
        DATA_FOLDER = str(config['data_folder'])

        while True:
            try:
                imbox = Imbox(config["server"],
                        username=config["username"],
                        password=config["password"],
                        ssl=config["ssl"] == 'True',
                        ssl_context=config["ssl_context"],
                        starttls=config["starttls"] == 'True')
            except Exception as e:
                sys.exit(2)

            try:
                unread_inbox_messages = imbox.messages(unread=True, raw='has:attachment')

                for uid, message in unread_inbox_messages:
                    for att in message.attachments:
                        try:
                            if not "image" in str(att['content-type']):
                                readable_hash = hashlib.sha256(att['content'].read()).hexdigest();
                                FILE_PATH = str(config['workingdir'])+DATA_FOLDER+str(readable_hash)
                                att['content'].seek(0)

                                if not os.path.isfile(FILE_PATH):
                                    with open(FILE_PATH, 'wb') as file:
                                        file.write(att['content'].read())

                                    s = requests.Session()
                                    s.headers.update({"Authorization": "Bearer " + BEARER_TOKEN})

                                    form_data = {
                                        "channel_id": ('', CHANNEL_ID),
                                        "client_ids": ('', str(readable_hash)),
                                        "files": (os.path.basename(FILE_PATH), open(FILE_PATH, 'rb')),
                                    }

                                    r = s.post(SERVER_URL + '/api/v4/files', files=form_data)
                                    FILE_ID = r.json()["file_infos"][0]["id"]

                                    msg = "---\r\n"
                                    try:
                                        msg += "Subject: `"+str(message.subject)+"`\r\n"
                                    except:
                                        pass

                                    try:
                                        msg += "Sender: `"+str(message.sent_from)+"`\r\n"
                                    except:
                                        pass

                                    try:
                                        msg += "Date: `"+str(message.date)+"`\r\n"
                                    except:
                                        pass

                                    try:
                                        msg += "Attachment: `"+str(att['filename'])+"`\r\n"
                                    except:
                                        pass

                                    try:
                                        msg += "sha256: `"+str(readable_hash)+"`\r\n"
                                    except:
                                        pass

                                    try:
                                        msg += "TLP: `RED`"
                                    except:
                                        pass

                                    p = s.post(SERVER_URL + '/api/v4/posts', data=json.dumps({
                                        "channel_id": CHANNEL_ID,
                                        "message": msg,
                                        "file_ids": [ FILE_ID ]
                                    }))

                        except Exception as e:
                            pass

                    imbox.mark_seen(uid) # mark as read

            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                uid = None
                if "uid" in sys.exc_info()[2].tb_next.tb_frame.f_locals:
                    uid = sys.exc_info()[2].tb_next.tb_frame.f_locals["uid"]
                if uid is not None:
                    imbox.mark_seen(uid) # mark as read

            time.sleep(int(config["sleep"]))


class ELDaemon(Daemon):
    _config = None

    def __init__(self, pid_file, config):
        self._config = config
        Daemon.__init__(self, pid_file)

    def run(self):
        email_listener = EmailListener()
        email_listener.run(self._config)


def worker(arguments):
    s = arguments[0]
    x = arguments[1]
    config = arguments[2]

    daemon = ELDaemon('/tmp/daemon-email-listener_'+str(s)+'.pid', config)

    if 'start' == x:
        daemon.start()
    elif 'stop' == x:
        daemon.stop()
    elif 'restart' == x:
        daemon.restart()
    else:
        print("unknown command")
        sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        configParser = configparser.RawConfigParser()
        configParser.read(sys.argv[2])
        jobs = []

        for s in configParser.sections():
            cfg=dict()
            for o in configParser.options(s):
                cfg[o] = configParser.get(s, o)

            arguments = [s, sys.argv[1], cfg]
            p = multiprocessing.Process(target=worker, args=(arguments, ))
            jobs.append(p)
            p.start()

        sys.exit(0)
    else:
        print("usage: %s start <config_name>|stop <config_name>|restart <config_name>" % sys.argv[0])
        sys.exit(2)
