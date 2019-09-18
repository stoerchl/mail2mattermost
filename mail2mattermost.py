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

    def config_boolean(self, value):
        if value == "True":
            return True
        else:
            return False


    def write_error_log(self, msg):
        try:
            file_path = '/tmp/daemon-email-listener_'+self._title+'.log'
            with open(file_path, 'a+') as file:
                file.write(str(time.strftime("%Y-%m-%d %H:%M:%S")) + " - " + msg + "\r\n")
        except:
            pass # Really messed up when here..


    def add_message_field(self, name, field):
        try:
            return "|"+str(name)+"| `"+str(field)+"`|\r\n"
        except:
            self.write_error_log("Failed to add Field to message.")


    def run(self, config, title):
        self._title = title
        SERVER_URL = str(config['mt_server_url'])
        CHANNEL_ID = str(config['mt_channel_id'])

        while True:
            try:
                imbox = Imbox(config["server"],
                        username=config["username"],
                        password=config["password"],
                        ssl=config["ssl"] == 'True',
                        ssl_context=config["ssl_context"],
                        starttls=config["starttls"] == 'True')
            except:
                self.write_error_log("Failed to connect to Mailserver.")
                sys.exit(2)

            try:
                unread_inbox_messages = imbox.messages(unread=True)

                for uid, message in unread_inbox_messages:

                    s = requests.Session()
                    s.headers.update({"Authorization": "Bearer " + str(config['mt_bearer'])})

                    msg = "---\r\n|Field|Value|\r\n|---|---|\r\n"

                    if self.config_boolean(config["mail_subject"]):
                        msg += self.add_message_field("Subject", message.subject)

                    if self.config_boolean(config["mail_sent_from"]):
                        msg += self.add_message_field("Sender", message.sent_from)

                    if self.config_boolean(config["mail_sent_to"]):
                        msg += self.add_message_field("Recipient", message.sent_to)

                    if self.config_boolean(config["mail_date"]):
                        msg += self.add_message_field("Date", message.date)

                    FILE_IDS = list()
                    if self.config_boolean(config["mail_attachments"]):
                        try:
                            att_counter = 0
                            for att in message.attachments:
                                try:
                                    if att_counter < 5: # max. 5 attachments per post
                                        readable_hash = hashlib.sha256(att['content'].read()).hexdigest();
                                        FILE_PATH = str(config['workingdir'])+str(config['data_folder'])+str(att['filename'])#str(readable_hash)
                                        att['content'].seek(0)

                                        with open(FILE_PATH, 'wb') as file:
                                            file.write(att['content'].read())

                                        form_data = {
                                            "channel_id": ('', CHANNEL_ID),
                                            "client_ids": ('', str(readable_hash)),
                                            "files": (os.path.basename(FILE_PATH), open(FILE_PATH, 'rb')),
                                        }

                                        r = s.post(SERVER_URL + '/api/v4/files', files=form_data)
                                        FILE_IDS.append(str(r.json()["file_infos"][0]["id"]))
                                        att_counter += 1

                                        msg += "|Attachment| `"+str(att['filename'])+" [sha256: "+readable_hash+"]`|\r\n"
                                except:
                                    self.write_error_log("Failed to save attachment to disk and post to Mattermost.")
                        except:
                            self.write_error_log("Failed to parse attachment.")

                    if self.config_boolean(config["mail_message_id"]):
                        msg += self.add_message_field("Message-ID", message.message_id)

                    if self.config_boolean(config["mail_headers"]):
                        msg += self.add_message_field("Headers", message.headers)

                    if self.config_boolean(config["mail_body_plain"]):
                        msg += self.add_message_field("Body", message.body["plain"])
                    elif self.config_boolean(config["mail_body_html"]):
                        msg += self.add_message_field("Body", message.body["html"])

                    if str(config["mail_tlp"]) != "":
                        msg += self.add_message_field("TLP", config["mail_tlp"])

                    data_dict = {
                        "channel_id": CHANNEL_ID,
                        "message": msg,
                        "file_ids":  []
                    }
                    data_dict["file_ids"] = FILE_IDS
                    data=json.dumps(data_dict)

                    p = s.post(SERVER_URL + '/api/v4/posts', data)

                    imbox.mark_seen(uid)

            except Exception as e:
                self.write_error_log("Failed to parse email message.")
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                uid = None
                if "uid" in sys.exc_info()[2].tb_next.tb_frame.f_locals:
                    uid = sys.exc_info()[2].tb_next.tb_frame.f_locals["uid"]
                if uid is not None:
                    imbox.mark_seen(uid)

            time.sleep(int(config["sleep"]))


class ELDaemon(Daemon):
    _config = None

    def __init__(self, title, config):
        self._config = config
        self._title = title
        pid_file = '/tmp/daemon-email-listener_'+title+'.pid'
        Daemon.__init__(self, pid_file)

    def run(self):
        email_listener = EmailListener()
        email_listener.run(self._config, self._title)


def worker(arguments):
    s = arguments[0]
    x = arguments[1]
    config = arguments[2]

    daemon = ELDaemon(str(s), config)

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
