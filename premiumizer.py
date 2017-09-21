#! /usr/bin/env python
import ConfigParser
import hashlib
import json
import logging
import os
import re
import shelve
import shutil
import smtplib
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler
from string import ascii_letters, digits

import bencode
import gevent
import myjdapi
import requests
import six
from apscheduler.schedulers.gevent import GeventScheduler
from chardet import detect
from flask import Flask, flash, request, redirect, url_for, render_template, send_from_directory
from flask_apscheduler import APScheduler
from flask_compress import Compress
from flask_login import LoginManager, login_required, login_user, logout_user, UserMixin
from flask_reverse_proxy import FlaskReverseProxied
from flask_socketio import SocketIO, emit
from gevent import local
from pySmartDL import SmartDL, utils
from watchdog import events
from watchdog.observers import Observer
from werkzeug.utils import secure_filename

from DownloadTask import DownloadTask

# "https://www.premiumize.me/api"
print ('------------------------------------------------------------------------------------------------------------')
print ('|                                                                                                           |')
print ('-------------------------------------------WELCOME TO PREMIUMIZER-------------------------------------------')
print ('|                                                                                                           |')
print ('------------------------------------------------------------------------------------------------------------')
# Initialize config values
prem_config = ConfigParser.RawConfigParser()
runningdir = os.path.split(os.path.abspath(os.path.realpath(sys.argv[0])))[0]
rootdir = os.path.split(runningdir)
if len(sys.argv) > 1:
    os_arg = sys.argv[1]
else:
    os_arg = ''
if not os.path.isfile(os.path.join(runningdir, 'settings.cfg')):
    shutil.copy(os.path.join(runningdir, 'settings.cfg.tpl'), os.path.join(runningdir, 'settings.cfg'))
prem_config.read(os.path.join(runningdir, 'settings.cfg'))
active_interval = prem_config.getint('global', 'active_interval')
idle_interval = prem_config.getint('global', 'idle_interval')
debug_enabled = prem_config.getboolean('global', 'debug_enabled')

# Initialize logging
syslog = logging.StreamHandler()
if debug_enabled:
    logger = logging.getLogger('')
    logger.setLevel(logging.DEBUG)
    formatterdebug = logging.Formatter('%(asctime)-20s %(name)-41s: %(levelname)-8s : %(message)s',
                                       datefmt='%m-%d %H:%M:%S')
    syslog.setFormatter(formatterdebug)
    logger.addHandler(syslog)
    print ('---------------------------------------------------------------------------------------------------------')
    print ('|                                                                                                        |')
    print ('------------------------PREMIUMIZER IS RUNNING IN DEBUG MODE, THIS IS NOT RECOMMENDED--------------------')
    print ('|                                                                                                        |')
    print ('---------------------------------------------------------------------------------------------------------')
    logger.debug('----------------------------------')
    logger.debug('----------------------------------')
    logger.debug('----------------------------------')
    logger.debug('DEBUG Logger Initialized')
    handler = logging.handlers.RotatingFileHandler(os.path.join(runningdir, 'premiumizerDEBUG.log'),
                                                   maxBytes=(500 * 1024))
    handler.setFormatter(formatterdebug)
    logger.addHandler(handler)
    logger.debug('DEBUG Logfile Initialized')
else:
    logger = logging.getLogger("Rotating log")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)-s: %(levelname)-s : %(message)s', datefmt='%m-%d %H:%M:%S')
    syslog.setFormatter(formatter)
    logger.addHandler(syslog)
    logging.getLogger('apscheduler.executors').addHandler(logging.NullHandler())
    logger.debug('-------------------------------------------------------------------------------------')
    logger.debug('-------------------------------------------------------------------------------------')
    logger.debug('-------------------------------------------------------------------------------------')
    logger.debug('Logger Initialized')
    handler = logging.handlers.RotatingFileHandler(os.path.join(runningdir, 'premiumizer.log'), maxBytes=(500 * 1024))
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.debug('Logfile Initialized')


# Catch uncaught exceptions in log
def uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
        return
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    pass


sys.excepthook = uncaught_exception

# Logging filters for debugging, default is 1
log_apscheduler = 1
log_flask = 1


class ErrorFilter(logging.Filter):
    def __init__(self, *errorfilter):
        self.errorfilter = [logging.Filter(name) for name in errorfilter]

    def filter(self, record):
        return not any(f.filter(record) for f in self.errorfilter)


if not log_apscheduler:
    syslog.addFilter(ErrorFilter('apscheduler'))

if not log_flask:
    syslog.addFilter(
        ErrorFilter('engineio', 'socketio', 'geventwebsocket.handler', 'requests.packages.urllib3.connectionpool'))

# Check if premiumizer has been updated
if prem_config.getboolean('update', 'updated'):
    if os.path.isfile(os.path.join(runningdir, 'premiumizer.log')):
        try:
            with open(os.path.join(runningdir, 'premiumizer.log'), 'w'):
                pass
            logger.info('*************************************************************************************')
            logger.info('----------------Premiumizer.log file has been deleted as a precaution----------------')
            logger.info('*************************************************************************************')
        except:
            logger.error('Could not delete old premiumizer.log file')
    if os.path.isfile(os.path.join(runningdir, 'premiumizerDEBUG.log')):
        try:
            with open(os.path.join(runningdir, 'premiumizerDEBUG.log'), 'w'):
                pass
            logger.info('*************************************************************************************')
            logger.info('---------------PremiumizerDEBUG file has been deleted as a precaution----------------')
            logger.info('*************************************************************************************')
        except:
            logger.error('Could not delete old premiumizerDEBUG.log file')
    if os.path.isfile(os.path.join(runningdir, 'premiumizer.db')):
        try:
            os.remove(os.path.join(runningdir, 'premiumizer.db'))
            logger.info('*************************************************************************************')
            logger.info('---------------Premiumizer.db file has been deleted as a precaution----------------')
            logger.info('*************************************************************************************')
        except:
            logger.error('Could not delete old premiumizer.db file')
    if os.path.isfile(os.path.join(runningdir, 'settings.cfg.old2')):
        try:
            shutil.move(os.path.join(runningdir, 'settings.cfg.old2'), os.path.join(runningdir, 'settings.cfg.old'))
            logger.info('*************************************************************************************')
            logger.info('-------Settings file has been updated, old settings file renamed to .old-------')
            logger.info('*************************************************************************************')
        except:
            logger.error('Could not rename old settings file')
    prem_config.set('update', 'updated', '0')
    with open(os.path.join(runningdir, 'settings.cfg'), 'w') as configfile:
        prem_config.write(configfile)
    logger.info('*************************************************************************************')
    logger.info('---------------------------Premiumizer has been updated!!----------------------------')
    logger.info('*************************************************************************************')
#
logger.info('Running at %s', runningdir)


# noinspection PyAttributeOutsideInit
class PremConfig:
    def __init__(self):
        self.jd_connected = 0
        self.check_config()

    def check_config(self):
        logger.debug('Initializing config')
        self.bind_ip = prem_config.get('global', 'bind_ip')
        self.web_login_enabled = prem_config.getboolean('security', 'login_enabled')
        if self.web_login_enabled:
            logger.debug('Premiumizer login is enabled')
            self.web_username = prem_config.get('security', 'username')
            self.web_password = prem_config.get('security', 'password')

        self.update_available = 0
        self.update_localcommit = ''
        self.update_diffcommit = ''
        self.update_status = ''
        self.update_date = prem_config.get('update', 'update_date')
        self.auto_update = prem_config.getboolean('update', 'auto_update')
        self.prem_customer_id = prem_config.get('premiumize', 'customer_id')
        self.prem_pin = prem_config.get('premiumize', 'pin')
        self.remove_cloud = prem_config.getboolean('downloads', 'remove_cloud')
        self.download_enabled = prem_config.getboolean('downloads', 'download_enabled')
        if self.download_enabled:
            self.download_builtin = 1
        self.download_max = prem_config.getint('downloads', 'download_max')
        self.download_speed = prem_config.get('downloads', 'download_speed')
        if self.download_speed == '0':
            self.download_enabled = 0
        elif self.download_speed == '-1':
            self.download_speed = int(self.download_speed)
        else:
            self.download_speed = float(self.download_speed)
            self.download_speed = int(self.download_speed * 1048576)

        self.download_location = prem_config.get('downloads', 'download_location')
        if os.path.isfile(os.path.join(runningdir, 'nzbtomedia', 'NzbToMedia.py')):
            self.nzbtomedia_location = (os.path.join(runningdir, 'nzbtomedia', 'NzbToMedia.py'))
            self.nzbtomedia_builtin = 1
        else:
            self.nzbtomedia_location = prem_config.get('downloads', 'nzbtomedia_location')
        self.jd_enabled = prem_config.getboolean('downloads', 'jd_enabled')
        self.jd_username = prem_config.get('downloads', 'jd_username')
        self.jd_password = prem_config.get('downloads', 'jd_password')
        self.jd_device_name = prem_config.get('downloads', 'jd_device_name')
        self.jd_update_available = 0
        if self.jd_enabled and self.download_enabled:
            self.download_builtin = 0
            if not self.jd_connected:
                self.jd = myjdapi.Myjdapi()
                try:
                    self.jd.set_app_key('https://git.io/vaDti')
                    self.jd.connect(self.jd_username, self.jd_password)
                except BaseException as e:
                    logger.error('myjdapi : ' + e.message)
                    logger.error('Could not connect to My Jdownloader')
                try:
                    self.jd_device = self.jd.get_device(self.jd_device_name)
                    self.jd_connected = 1
                except BaseException as e:
                    logger.error('myjdapi : ' + e.message)
                    self.jd = None
                    logger.error('Could not get device name (%s) for My Jdownloader', self.jd_device_name)
            if self.jd_connected:
                try:
                    if self.download_speed == -1:
                        self.jd_device.toolbar.disable_downloadSpeedLimit()
                    else:
                        self.jd_device.toolbar.enable_downloadSpeedLimit()
                        self.download_speed = self.jd_device.toolbar.get_status().get('limitspeed')
                except:
                    logger.error('Could not enable Jdownloader speed limit')
        self.watchdir_enabled = prem_config.getboolean('upload', 'watchdir_enabled')
        self.watchdir_location = prem_config.get('upload', 'watchdir_location')
        if self.watchdir_enabled:
            logger.info('Watchdir is enabled at: %s', self.watchdir_location)
            if not os.path.exists(self.watchdir_location):
                os.makedirs(self.watchdir_location)

        self.categories = []
        self.download_categories = ''
        for x in range(1, 6):
            y = prem_config.get('categories', ('cat_name' + str([x])))
            z = prem_config.get('categories', ('cat_dir' + str([x])))
            if y != '':
                cat_name = y
                if z == '':
                    cat_dir = os.path.join(self.download_location, y)
                else:
                    cat_dir = z
                cat_ext = prem_config.get('categories', ('cat_ext' + str([x]))).split(',')
                cat_delsample = prem_config.getboolean('categories', ('cat_delsample' + str([x])))
                cat_nzbtomedia = prem_config.getboolean('categories', ('cat_nzbtomedia' + str([x])))
                cat = {'name': cat_name, 'dir': cat_dir, 'ext': cat_ext, 'delsample': cat_delsample,
                       'nzb': cat_nzbtomedia}
                self.categories.append(cat)
                self.download_categories += str(cat_name + ',')
                if self.download_enabled:
                    if not os.path.exists(cat_dir):
                        logger.info('Creating Download Path at: %s', cat_dir)
                        os.makedirs(cat_dir)
                if self.watchdir_enabled:
                    sub = os.path.join(self.watchdir_location, cat_name)
                    if not os.path.exists(sub):
                        logger.info('Creating watchdir Path at %s', sub)
                        os.makedirs(sub)
        self.download_categories = self.download_categories[:-1]
        self.download_categories = self.download_categories.split(',')

        self.email_enabled = prem_config.getboolean('notifications', 'email_enabled')
        if self.email_enabled:
            self.email_on_failure = prem_config.getboolean('notifications', 'email_on_failure')
            self.email_from = prem_config.get('notifications', 'email_from')
            self.email_to = prem_config.get('notifications', 'email_to')
            self.email_server = prem_config.get('notifications', 'email_server')
            self.email_port = prem_config.getint('notifications', 'email_port')
            self.email_encryption = prem_config.getboolean('notifications', 'email_encryption')
            self.email_username = prem_config.get('notifications', 'email_username')
            self.email_password = prem_config.get('notifications', 'email_password')

        logger.debug('Initializing config complete')


cfg = PremConfig()


# Automatic update checker
def check_update(auto_update=cfg.auto_update):
    logger.debug('def check_update started')
    time_job = scheduler.scheduler.get_job('check_update').next_run_time.replace(tzinfo=None)
    time_now = datetime.now()
    diff = time_job - time_now
    diff = 21600 - diff.total_seconds()
    if (diff > 120) or (cfg.update_status == ''):
        try:
            subprocess.check_call(['git', '-C', runningdir, 'fetch'])
        except:
            cfg.update_status = 'failed'
            logger.error('Update failed: could not git fetch: %s', runningdir)
        if cfg.update_status != 'failed':
            cfg.update_localcommit = subprocess.check_output(
                ['git', '-C', runningdir, 'log', '-n', '1', '--pretty=format:%h'])
            local_branch = str(
                subprocess.check_output(['git', '-C', runningdir, 'rev-parse', '--abbrev-ref', 'HEAD'])).rstrip('\n')
            remote_commit = subprocess.check_output(
                ['git', '-C', runningdir, 'log', '-n', '1', 'origin/' + local_branch, '--pretty=format:%h'])

            if cfg.update_localcommit != remote_commit:
                cfg.update_diffcommit = subprocess.check_output(
                    ['git', '-C', runningdir, 'log', '--oneline', local_branch + '..origin/' + local_branch])

                cfg.update_available = 1
                cfg.update_status = 'Update Available !!'
                if auto_update:
                    for task in tasks:
                        if task.local_status == (
                                            'downloading' or 'queued' or 'failed: download' or 'failed: nzbToMedia'):
                            scheduler.scheduler.reschedule_job('check_update', trigger='interval', minutes=30)
                            logger.info(
                                'Tried to update but downloads are not done or failed, trying again in 30 minutes')
                            cfg.update_status = \
                                'Update available, but not yet installed because downloads are not done or failed'
                            return
                    update_self()
            else:
                cfg.update_status = 'No update available --- last time checked: ' + datetime.now().strftime(
                    "%d-%m %H:%M:%S") + ' --- last time updated: ' + cfg.update_date
        if cfg.jd_enabled:
            try:
                cfg.jd_update_available = cfg.jd_device.update.update_available()
            except:
                logger.error('Jdownloader update check failed')
        scheduler.scheduler.reschedule_job('check_update', trigger='interval', hours=6)


# noinspection PyProtectedMember
def update_self():
    logger.debug('def update_self started')
    logger.info('Update - will restart')
    cfg.update_date = datetime.now().strftime("%d-%m %H:%M:%S")
    prem_config.set('update', 'update_date', cfg.update_date)
    with open(os.path.join(runningdir, 'settings.cfg'), 'w') as configfile:  # save
        prem_config.write(configfile)
    scheduler.shutdown(wait=False)
    socketio.stop()
    if os_arg == '--windows':
        subprocess.call(['python', os.path.join(runningdir, 'utils.py'), '--update', '--windows'])
        os._exit(1)
    else:
        subprocess.Popen(['python', os.path.join(runningdir, 'utils.py'), '--update', '--none'], shell=False,
                         close_fds=True)
        os._exit(1)


# noinspection PyProtectedMember
def restart():
    logger.info('Restarting')
    scheduler.shutdown(wait=False)
    socketio.stop()
    if os_arg == '--windows':
        # windows service will automatically restart on 'failure'
        os._exit(1)
    else:
        subprocess.Popen(['python', os.path.join(runningdir, 'utils.py'), '--restart', '--none'], shell=False,
                         close_fds=True)
        os._exit(1)


# noinspection PyProtectedMember
def shutdown():
    logger.info('Shutdown recieved')
    scheduler.shutdown(wait=False)
    socketio.stop()
    if os_arg == '--windows':
        subprocess.call([os.path.join(rootdir, 'Installer', 'nssm.exe'), 'stop', 'Premiumizer'])
    else:
        os._exit(1)


#
logger.debug('Initializing Flask')
proxied = FlaskReverseProxied()
app = Flask(__name__)
proxied.init_app(app)
Compress(app)
app.config['SECRET_KEY'] = os.urandom(24)
app.config.update(DEBUG=debug_enabled)
app.logger.addHandler(handler)
socketio = SocketIO(app, async_mode='gevent')

app.config['LOGIN_DISABLED'] = not cfg.web_login_enabled
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
logger.debug('Initializing Flask complete')

# Initialise Database
logger.debug('Initializing Database')
if os.path.isfile(os.path.join(runningdir, 'premiumizer.db')):
    db = shelve.open(os.path.join(runningdir, 'premiumizer.db'))
    if not db.keys():
        db.close()
        os.remove(os.path.join(runningdir, 'premiumizer.db'))
        db = shelve.open(os.path.join(runningdir, 'premiumizer.db'))
        logger.debug('Database cleared')
else:
    db = shelve.open(os.path.join(runningdir, 'premiumizer.db'))
logger.debug('Initializing Database complete')

# Initialise Globals
tasks = []
greenlet = local.local()
client_connected = 0
prem_session = requests.Session()
last_email = {'time': datetime.now() - timedelta(days=1), 'subject': ""}
if cfg.jd_enabled:
    jd_packages = {'time': datetime.now(), 'packages': []}


#
def gevent_sleep_time():
    global client_connected
    if client_connected:
        gevent.sleep(2)
    else:
        gevent.sleep(10)


class User(UserMixin):
    def __init__(self, userid, password):
        self.id = userid
        self.password = password


def to_unicode(original, *args):
    logger.debug('def to_unicode started')
    try:
        if isinstance(original, unicode):
            return original
        else:
            try:
                return six.text_type(original, *args)
            except:
                try:
                    detected = detect(original)
                    try:
                        if detected.get('confidence') > 0.8:
                            return original.decode(detected.get('encoding'))
                    except:
                        pass

                    return ek(original, *args)
                except:
                    raise
    except:
        import traceback
        logger.error('Unable to decode value "%s..." : %s ', (repr(original)[:20], traceback.format_exc()))
        return 'ERROR DECODING STRING'


def ek(original, *args):
    logger.debug('def ek started')
    if isinstance(original, (str, unicode)):
        try:
            return original.decode('UTF-8', 'ignore')
        except UnicodeDecodeError:
            raise
    return original


#
def clean_name(original):
    logger.debug('def clean_name started')
    valid_chars = "-_.,()[]{}&!@ %s%s" % (ascii_letters, digits)
    cleaned_filename = unicodedata.normalize('NFKD', to_unicode(original)).encode('ASCII', 'ignore')
    valid_string = ''.join(c for c in cleaned_filename if c in valid_chars)
    return ' '.join(valid_string.split())


def notify_nzbtomedia():
    logger.debug('def notify_nzbtomedia started')
    if os.path.isfile(cfg.nzbtomedia_location):
        try:
            subprocess.check_output(
                ['python', cfg.nzbtomedia_location, greenlet.task.dldir, greenlet.task.name, greenlet.task.category,
                 greenlet.task.hash, 'generic'],
                stderr=subprocess.STDOUT, shell=False)
            returncode = 0
            logger.info('Send to nzbToMedia: %s', greenlet.task.name)
        except subprocess.CalledProcessError as e:
            logger.error('nzbToMedia failed for: %s', greenlet.task.name)
            errorstr = ''
            tmp = str.splitlines(e.output)
            for line in tmp:
                if '[ERROR]' in line:
                    errorstr += line
            logger.error('%s: output: %s', greenlet.task.name, errorstr)
            returncode = 1
    else:
        logger.error('Error unable to locate nzbToMedia.py for: %s', greenlet.task.name)
        returncode = 1
    return returncode


def email(subject, text=None):
    logger.debug('def email started')
    global last_email
    if subject == 'download success':
        subject = 'Success for "%s"' % greenlet.task.name
        text = 'Download of %s: "%s" has successfully completed.' % (greenlet.task.type, greenlet.task.name)
        text += '\nStatus: SUCCESS'
        text += '\n\nStatistics:'
        text += '\nDownloaded size: %s' % utils.sizeof_human(greenlet.task.size)
        text += '\nDownload Time: %s' % utils.time_human(greenlet.task.dltime, fmt_short=True)
        text += '\nAverage download speed: %s' % greenlet.avgspeed
        text += '\n\nFiles:'
        for download in greenlet.task.download_list:
            text += '\n' + os.path.basename(download['path'])
        text += '\n\nLocation: %s' % greenlet.task.dldir

    elif subject == 'download failed':
        subject = 'Failure for "%s"' % greenlet.task.name
        text = 'Download of %s: "%s" has failed.' % (greenlet.task.type, greenlet.task.name)
        text += '\nStatus: FAILED\nError: %s' % greenlet.task.local_status
        text += '\n\nLog:\n'
        try:
            if debug_enabled:
                log = 'premiumizerDEBUG.log'
            else:
                log = 'premiumizer.log'
            with open(os.path.join(runningdir, log), 'r') as f:
                for line in f:
                    if greenlet.task.name in line:
                        text += line
        except:
            text += 'could not add log'

    else:
        if text is None:
            text = subject

    if datetime.now() - timedelta(hours=1) < last_email['time'] and subject == last_email['subject']:
        return
    last_email['time'] = datetime.now()
    last_email['subject'] = subject

    # Create message
    msg = MIMEText(text)
    msg['Subject'] = subject
    msg['From'] = cfg.email_from
    msg['To'] = cfg.email_to
    msg['Date'] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg['X-Application'] = 'Premiumizer'

    # Send message
    try:
        smtp = smtplib.SMTP(cfg.email_server, cfg.email_port)

        if cfg.email_encryption:
            smtp.starttls()

        if cfg.email_username != '' and cfg.email_password != '':
            smtp.login(cfg.email_username, cfg.email_password)

        smtp.sendmail(cfg.email_from, cfg.email_to, msg.as_string())

        smtp.quit()
        try:
            log = 'Email send for: %s' % greenlet.task.name
        except:
            log = 'Email send for: %s' % subject
        logger.info(log)
    except Exception as err:
        try:
            log = 'Email error for: %s error: %s' % (greenlet.task.name, err)
        except:
            log = 'Email error for: %s' % subject
            logger.info(log)
        logger.error(log)


def jd_query_packages(id=None):
    count = 0
    global jd_packages
    if client_connected:
        seconds = 2
    else:
        seconds = 10
    if jd_packages['time'] < (datetime.now() - timedelta(seconds=seconds)):
        jd_packages['time'] = datetime.now()
        try:
            response = cfg.jd_device.downloads.query_packages()
        except BaseException as e:
            response = None
            logger.error('myjdapi : ' + e.message)
        while not response:
            gevent.sleep(5)
            if not jd_packages['time'] < (datetime.now() - timedelta(seconds=seconds)):
                response = jd_packages['packages']
            else:
                try:
                    response = cfg.jd_device.downloads.query_packages()
                except BaseException as e:
                    logger.error('myjdapi : ' + e.message)
            count += 1
            if count == 6:
                logger.error('JD did not return package status for: %s', greenlet.task.name)
                return False
        while not len(response):
            gevent.sleep(5)
            if not jd_packages['time'] < (datetime.now() - timedelta(seconds=seconds)):
                response = jd_packages['packages']
            else:
                try:
                    response = cfg.jd_device.downloads.query_packages()
                except BaseException as e:
                    logger.error('myjdapi : ' + e.message)
            count += 1
            if count == 12:
                logger.error('Could not find package in JD for: %s', greenlet.task.name)
                return False

        jd_packages['packages'] = response

    if id:
        for package in jd_packages['packages']:
            try:
                if id == str(package['uuid']):
                    while 'status' not in package:
                        try:
                            package = package[0]
                            if 'status' in package:
                                break
                        except:
                            pass
                        gevent.sleep(5)
                        try:
                            package = cfg.jd_device.downloads.query_packages([{"packageUUIDs": [id]}])
                        except BaseException as e:
                            logger.error('myjdapi : ' + e.message)
                        count += 1
                        if count == 24:
                            package = {'status': 'Failed'}
                            logger.error('JD did not return package status for: %s', greenlet.task.name)
                    return package
            except:
                return False

    return jd_packages['packages']


def get_download_stats_jd(package_name):
    count = 0
    gevent.sleep(10)
    query_packages = jd_query_packages()
    while not any(package['name'] in package_name for package in query_packages):
        gevent.sleep(5)
        query_packages = jd_query_packages()
        count += 1
        if count == 10:
            logger.error('Could not find package in JD for: %s', greenlet.task.name)
            return 1
    for package in query_packages:
        if package['name'] in package_name:
            start_time = time.time()
            package_id = str(package['uuid'])
            while 'finished' not in package and package['status'] != 'Failed':
                if greenlet.task.local_status == 'stopped':
                    try:
                        cfg.jd_device.downloads.cleanup("DELETE_ALL", "REMOVE_LINKS_AND_DELETE_FILES", "SELECTED",
                                                        packages_ids=[package_id])
                    except BaseException as e:
                        logger.error('myjdapi : ' + e.message)
                        logger.error('Could not delete package in JD for : %s', greenlet.task.name)
                        pass
                    return 1
                try:
                    speed = package['speed']
                except:
                    speed = 0
                if speed == 0:
                    if 'Download' not in package['status']:
                        eta = package['status']
                    else:
                        eta = ' '
                else:
                    eta = " " + utils.time_human(package['eta'], fmt_short=True)
                try:
                    bytestotal = utils.sizeof_human(package["bytesTotal"])
                except:
                    logger.error('JD did not return package bytesTotal for: %s', greenlet.task.name)
                    return 1
                progress = round(float(package['bytesLoaded']) * 100 / package["bytesTotal"], 1)
                greenlet.task.update(speed=(utils.sizeof_human(speed) + '/s --- '), dlsize=utils.sizeof_human(
                    package['bytesLoaded']) + ' / ' + bytestotal + ' --- ',
                                     progress=progress,
                                     eta=eta)
                gevent_sleep_time()
                package = jd_query_packages(package_id)
            # cfg.jd_device.disconnect()

            stop_time = time.time()
            dltime = int(stop_time - start_time)
            greenlet.task.update(dltime=dltime)

            while 'Extracting' in package['status']:
                try:
                    eta = package['status'].split('ETA: ', 1)[1].split(')', 1)[0]
                except:
                    eta = ''
                greenlet.task.update(speed=" ", progress=99, eta=' Extracting ' + eta)
                gevent_sleep_time()
                package = jd_query_packages(package_id)

            if package['status'] == 'Failed':
                logger.error('JD returned failed for: %s', greenlet.task.name)
                return 1

            try:
                cfg.jd_device.downloads.cleanup("DELETE_FINISHED", "REMOVE_LINKS_ONLY", "ALL",
                                                packages_ids=[package_id])
            except BaseException as e:
                logger.error('myjdapi : ' + e.message)
                logger.error('Could not delete package in JD for: %s', greenlet.task.name)
                pass
            return 0


def get_download_stats(downloader, total_size_downloaded):
    logger.debug('def get_download_stats started')
    if downloader.get_status() == 'downloading':
        size_downloaded = total_size_downloaded + downloader.get_dl_size()
        progress = round(float(size_downloaded) * 100 / greenlet.task.size, 1)
        speed = downloader.get_speed(human=False)
        if speed == 0:
            eta = ' '
        else:
            tmp = (greenlet.task.size - size_downloaded) / speed
            eta = ' ' + utils.time_human(tmp, fmt_short=True)
        greenlet.task.update(speed=utils.sizeof_human(speed) + '/s --- ',
                             dlsize=utils.sizeof_human(size_downloaded) + ' / ' + utils.sizeof_human(
                                 greenlet.task.size) + ' --- ', progress=progress, eta=eta)

    elif downloader.get_status() == 'combining':
        greenlet.task.update(progress=99, speed=' ', eta=' Combining files')
    elif downloader.get_status() == 'paused':
        greenlet.task.update(progress=99, speed=' ', eta=' Download paused')
    else:
        logger.debug('Want to update stats, but downloader status is invalid.')


def download_file():
    logger.debug('def download_file started')
    count = 0
    files_downloaded = 0
    total_size_downloaded = 0
    dltime = 0
    returncode = 0
    if cfg.jd_enabled:
        try:
            query_links = cfg.jd_device.downloads.query_links()
        except BaseException as e:
            query_links = False
            pass
        if query_links is False:
            try:
                cfg.jd = myjdapi.Myjdapi()
                cfg.jd.connect(cfg.jd_username, cfg.jd_password)
                cfg.jd_device = cfg.jd.get_device(cfg.jd_device_name)
                cfg.jd_connected = 1
            except BaseException as e:
                logger.error('myjdapi : ' + e.message)
                logger.error(
                    'Could not connect to My Jdownloader check username/password & device name, task failed: %s',
                    greenlet.task.name)
                cfg.jd_connected = 0
                return 1
            try:
                query_links = cfg.jd_device.downloads.query_links()
            except BaseException as e:
                logger.error('myjdapi : ' + e.message)
            while query_links is False:
                gevent.sleep(5)
                query_links = cfg.jd_device.downloads.query_links()
                count = + 1
                if count == 5:
                    return 1
        package_name = str(re.sub('[^0-9a-zA-Z]+', ' ', greenlet.task.name).lower())
    for download in greenlet.task.download_list:
        if greenlet.task.type == 'FILEHOST':
            payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin, 'src': download['url']}
            r = prem_connection("post", "https://www.premiumize.me/api/transfer/create", payload)
            try:
                download['url'] = r.text.split('"location":"', 1)[1].splitlines()[0].split('",', 1)[0].replace('\\', '')
            except:
                return 1
            download['path'] = os.path.join(greenlet.task.dldir, download['path'])
        logger.debug('Downloading file: %s', download['path'])
        filename = os.path.basename(download['path'])
        if not os.path.isfile(download['path']) or not os.path.isfile(os.path.join(greenlet.task.dldir, filename)):
            files_downloaded = 1
            if cfg.download_builtin:
                downloader = SmartDL(download['url'], download['path'], progress_bar=False, logger=logger,
                                     threads_count=1, fix_urls=False)
                downloader.start(blocking=False)
                while not downloader.isFinished():
                    if cfg.download_speed != -1:
                        jobs = len(scheduler.scheduler._lookup_executor('downloads')._instances)
                        if jobs != 0:
                            downloader.limit_speed(kbytes=((cfg.download_speed / 1000) / jobs))
                        else:
                            downloader.limit_speed(kbytes=cfg.download_speed / 1000)
                    get_download_stats(downloader, total_size_downloaded)
                    # if greenlet.task.local_status == "paused":            #   When paused to long
                    #   downloader.pause()                                  #   PysmartDl fails with WARNING :
                    #   while greenlet.task.local_status == "paused":       #   Diff between downloaded files and expected
                    #       gevent_sleep_time()                               #   filesizes is .... Retrying...
                    #   downloader.unpause()
                    if greenlet.task.local_status == "stopped":
                        while not downloader.isFinished():  # Have to use while loop
                            downloader.stop()  # does not stop when called once ..
                            gevent.sleep(0.5)  # let's hammer the stop call..
                        return 1
                    gevent_sleep_time()
                if downloader.isSuccessful():
                    dltime += downloader.get_dl_time()
                    total_size_downloaded += downloader.get_dl_size()
                    logger.debug('Finished downloading file: %s', download['path'])
                    greenlet.task.update(dltime=dltime)
                else:
                    logger.error('Error for %s: while downloading file: %s', greenlet.task.name, download['path'])
                    for e in downloader.get_errors():
                        logger.error(str(greenlet.task.name + ": " + e))
                    returncode = 1
            elif cfg.jd_connected:
                url = str(download['url'])
                if len(query_links):
                    if any(link['name'] == filename for link in query_links):
                        continue
                try:
                    cfg.jd_device.linkgrabber.add_links([{"autostart": True, "links": url, "packageName": package_name,
                                                          "destinationFolder": greenlet.task.dldir,
                                                          "overwritePackagizerRules": True}])
                except BaseException as e:
                    logger.error('myjdapi : ' + e.message)
        else:
            logger.info('File not downloaded it already exists at: %s', download['path'])

    if cfg.jd_enabled and files_downloaded:
        if cfg.jd_connected:
            returncode = get_download_stats_jd(package_name)

    return returncode


def is_sample(dir_content):
    media_extensions = [".mkv", ".avi", ".divx", ".xvid", ".mov", ".wmv", ".mp4", ".mpg", ".mpeg", ".vob", ".iso"]
    media_size = 150 * 1024 * 1024
    if dir_content['size'] < media_size:
        if dir_content['url'].lower().endswith(tuple(media_extensions)):
            if ('sample' or 'rarbg.com' in dir_content['url'].lower()) and (
                        'sample' not in greenlet.task.name.lower()):
                return True
    return False


def process_dir(dir_content, path):
    logger.debug('def processing_dir started')
    total_size = 0
    download_list = []
    if not dir_content:
        return None
    for x in dir_content:
        type = dir_content[x]['type']
        if type == 'dir':
            new_path = os.path.join(path, clean_name(x))
            if os.path.basename(os.path.normpath(path)) == os.path.basename(os.path.normpath(new_path)):
                process_dir(dir_content[x]['children'], path)
            else:
                process_dir(dir_content[x]['children'], new_path)
        elif type == 'file':
            if dir_content[x]['url'].lower().endswith(tuple(greenlet.task.dlext)):
                if greenlet.task.delsample:
                    sample = is_sample(dir_content[x])
                    if sample:
                        continue
                if cfg.download_enabled:
                    if not os.path.exists(path):
                        os.makedirs(path)
                    download = {'path': os.path.join(path, clean_name(x)), 'url': dir_content[x]['url']}
                    download_list.append(download)
                    total_size += dir_content[x]['size']
                    greenlet.task.update(download_list=download_list, size=total_size)


def download_process():
    logger.debug('def download_process started')
    returncode = 0
    greenlet.task.update(local_status='downloading', progress=0, speed=' ', eta=' ')
    greenlet.task.dldir = os.path.join(greenlet.task.dldir, clean_name(greenlet.task.name))
    if not greenlet.task.type == 'FILEHOST':
        payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin, 'hash': greenlet.task.hash}
        r = prem_connection("post", "https://www.premiumize.me/api/torrent/browse", payload)
        if 'failed' in r:
            return 1
        process_dir(json.loads(r.content)['content'], greenlet.task.dldir)
    logger.info('Downloading: %s', greenlet.task.name)
    if greenlet.task.download_list:
        returncode = download_file()
    else:
        logger.error('Error for %s: Nothing to download .. Filtered out or bad torrent/nzb ?')
        returncode = 1
    if returncode == 0:
        greenlet.task.update(progress=100, speed=' ', eta=' ')
    return returncode


def download_task(task):
    logger.debug('def download_task started')
    greenlet.task = task
    greenlet.failed = 0
    failed = download_process()
    if failed and task.local_status != 'stopped':
        dldir = get_cat_var(task.category)
        dldir = dldir[0]
        task.update(local_status='failed: download retrying', dldir=dldir)
        logger.warning('Retrying failed download in 10 minutes for: %s', task.name)
        gevent.sleep(600)
        failed = download_process()
        if failed:
            task.update(local_status='failed: download')
            logger.error('Download failed for: %s', task.name)
    elif task.local_status == 'stopped':
        logger.warning('Download stopped for: %s', greenlet.task.name)
        gevent.sleep(3)
        try:
            shutil.rmtree(task.dldir)
        except:
            if not cfg.jd_enabled:
                logger.warning('Could not delete folder for: %s', greenlet.task.name)
        if task.progress == 100:
            task.update(category='', local_status='waiting')
    if not failed:
        try:
            greenlet.avgspeed = str(utils.sizeof_human((task.size / task.dltime)) + '/s')
        except:
            greenlet.avgspeed = "0"
        logger.info('Download finished: %s -- info: %s --  %s --  %s -- location: %s', task.name,
                    utils.sizeof_human(task.size), greenlet.avgspeed, utils.time_human(task.dltime, fmt_short=True),
                    task.dldir)
        if task.dlnzbtomedia:
            failed = notify_nzbtomedia()
            if failed:
                task.update(local_status='failed: nzbToMedia')

    if cfg.email_enabled and task.local_status != 'stopped' and task.local_status != 'waiting':
        if not failed:
            if not cfg.email_on_failure:
                email('download success')
        else:
            email('download failed')

    if cfg.remove_cloud:
        if not failed:
            delete_task(task.hash)
    else:
        task.update(local_status='finished')

    scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=1)


def prem_connection(method, url, payload, files=None):
    logger.debug('def prem_connection started')
    r = None
    r_count = 0
    while r is None:
        r_count += 1
        try:
            if method == 'post':
                r = prem_session.post(url, payload, timeout=5)
            elif method == 'postfile':
                r = prem_session.post(url, payload, files=files, timeout=5)
            elif method == 'get':
                r = prem_session.get(url, params=payload, timeout=5)
            if 'Not logged in. Please log in first' in r.text:
                msg = 'premiumize.me login error: %s' % r.text
                logger.error(msg)
                if cfg.email_enabled:
                    email('Premiumize.me login error', msg)
                return 'failed: premiumize.me login error'
            if r.status_code != 200:
                raise
        except:
            if r_count == 10:
                try:
                    message = r.text
                except:
                    message = ' '
                try:
                    msg = 'premiumize.me error: %s for: %s' % (message, greenlet.task.name)
                except:
                    msg = 'premiumize.me error: %s' % message
                logger.error(msg)
                if cfg.email_enabled:
                    email('Premiumize.me error', msg)
                return 'failed'
            gevent.sleep(3)
            r = None
            continue
    return r


def update():
    logger.debug('def update started')
    idle = True
    update_interval = idle_interval
    payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin}
    r = prem_connection("post", "https://www.premiumize.me/api/transfer/list", payload)
    if 'failed' not in r:
        response_content = json.loads(r.content)
        if response_content['status'] == "success":
            if not response_content['transfers']:
                update_interval *= 3
            transfers = response_content['transfers']
            idle = parse_tasks(transfers)
        else:
            socketio.emit('premiumize_connect_error', {})
    else:
        socketio.emit('premiumize_connect_error', {})
    if not idle:
        update_interval = active_interval
    scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=update_interval)


def parse_tasks(transfers):
    logger.debug('def parse_task started')
    hashes_online = []
    hashes_local = []
    idle = True
    for task in tasks:
        hashes_local.append(task.hash)
        if task.type == 'FILEHOST':
            try:
                x = db[task.hash]
            except:
                task.callback = None
                db[task.hash] = task
                task.callback = socketio.emit
            task.update()
    for transfer in reversed(transfers):
        task = get_task(transfer['hash'].encode("utf-8"))
        if not task:
            if transfer['name'] is None or transfer['name'] == 0:
                name = 'Loading name'
            else:
                name = transfer['name']
            type = str.upper(transfer['type'].encode("utf-8"))
            add_task(transfer['hash'].encode("utf-8"), transfer['size'], name, '', type)
            task = get_task(transfer['hash'].encode("utf-8"))
            hashes_local.append(task.hash)
            task.update(progress=(int(transfer['progress'] * 100)), cloud_status=transfer['status'],
                        speed=transfer['speed_down'])
        if task.local_status is None:
            if task.cloud_status != 'finished':
                progress = int(transfer['progress'] * 100)
                if transfer['name'] is None or transfer['name'] == 0:
                    if task.name is None:
                        name = 'Loading name'
                    else:
                        name = task.name
                else:
                    name = transfer['name']
                if transfer['eta'] is None or transfer['eta'] == 0:
                    try:
                        if 'ETA is' in transfer['message']:
                            eta = transfer['message'].split("ETA is", 1)[1]
                        else:
                            eta = ' '
                    except:
                        eta = ' '
                else:
                    eta = utils.time_human(transfer['eta'], fmt_short=True)
                if transfer['speed_down'] is None or transfer['speed_down'] == 0:
                    try:
                        if 'Downloading at' in transfer['message']:
                            speed = transfer['message'].split("Downloading at", 1)[1].split(". ", 1)[0]
                        else:
                            speed = ' '
                    except:
                        speed = ' '
                else:
                    speed = utils.sizeof_human(transfer['speed_down']) + '/s '
                if transfer['size'] is None or transfer['size'] == 0:
                    try:
                        if '% of' in transfer['message']:
                            size = transfer['message'].split("s.", 1)[1].split(" finished", 1)[0]
                        else:
                            size = ' '
                    except:
                        size = ' '
                else:
                    size = utils.sizeof_human(transfer['size'] / 100 * progress) + ' / ' + utils.sizeof_human(
                        transfer['size'])
                task.update(progress=(int(transfer['progress'] * 100)), cloud_status=transfer['status'],
                            name=name,
                            dlsize=size + ' --- ', speed=speed + ' --- ', eta=eta)
                idle = False
            elif task.cloud_status == 'finished':
                if cfg.download_enabled:
                    if task.category in cfg.download_categories:
                        if not task.local_status == ('queued' or 'downloading'):
                            task.update(local_status='queued')
                            gevent.sleep(3)
                            scheduler.scheduler.add_job(download_task, args=(task,), name=task.name,
                                                        misfire_grace_time=7200, coalesce=False, max_instances=1,
                                                        jobstore='downloads', executor='downloads',
                                                        replace_existing=True)
                    elif task.category == '':
                        task.update(local_status='waiting')
                else:
                    task.update(local_status='finished', speed=None)
        else:
            if task.local_status == 'downloading':
                dlsize = task.dlsize
                hash = task.hash
                if task.name not in str(scheduler.scheduler.get_jobs('check_downloads')):
                    scheduler.scheduler.add_job(check_downloads, args=(dlsize, hash),
                                                name=(task.name + ' check_downloads'), misfire_grace_time=7200,
                                                jobstore='check_downloads', replace_existing=True, max_instances=1,
                                                coalesce=True, next_run_time=(datetime.now() + timedelta(minutes=1)))
            task.update(cloud_status=transfer['status'])
        hashes_online.append(task.hash)
        task.callback = None
        db[task.hash] = task
        task.callback = socketio.emit

    # Delete local task.hash that are removed from cloud
    hash_diff = [aa for aa in hashes_local if aa not in set(hashes_online)]
    for task_hash in hash_diff:
        for task in tasks:
            if task.type != 'FILEHOST' and task.hash == task_hash:
                tasks.remove(task)
                del db[task_hash]
    db.sync()
    socketio.emit('tasks_updated', {})
    return idle


def check_downloads(dlsize, hash):
    logger.debug('def check_downloads started')
    gevent.sleep(60)
    try:
        task = get_task(hash)
    except:
        return
    if dlsize == task.dlsize:
        dldir = get_cat_var(task.category)
        dldir = dldir[0]
        task.update(local_status=None, dldir=dldir)
        msg = 'Download: %s stuck restarting task' % task.name
        logger.warning(msg)
        if cfg.email_enabled:
            email('Download stuck', msg)
        scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=1)


def get_task(hash):
    logger.debug('def get_task started')
    for task in tasks:
        if task.hash == hash:
            return task
    return None


# noinspection PyUnboundLocalVariable
def get_cat_var(category):
    logger.debug('def get_cat_var started')
    if category != '':
        for cat in cfg.categories:
            if cat['name'] == category:
                dldir = cat['dir']
                dlext = cat['ext']
                delsample = cat['delsample']
                dlnzbtomedia = cat['nzb']
    else:
        dldir = None
        dlext = None
        delsample = 0
        dlnzbtomedia = 0
    return dldir, dlext, delsample, dlnzbtomedia


def add_task(hash, size, name, category, type):
    logger.debug('def add_task started')
    task = ''
    exists = get_task(hash)
    if not exists:
        dldir, dlext, delsample, dlnzbtomedia = get_cat_var(category)
        name = name.replace('%5B', '[').replace('%5D', ']').replace('%20', ' ')
        task = DownloadTask(socketio.emit, hash, size, name, category, dldir, dlext, delsample, dlnzbtomedia, type)
        tasks.append(task)
        if not task.type == 'FILEHOST':
            logger.info('Added: %s -- Category: %s -- Type: %s', task.name, task.category, task.type)
    else:
        task = 'duplicate'
    scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=1)
    return task


def upload_torrent(filename):
    logger.debug('def upload_torrent started')
    payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin, 'type': 'torrent'}
    files = {'src': open(filename, 'rb')}
    logger.debug('Uploading torrent to the cloud: %s', filename)
    r = prem_connection("postfile", "https://www.premiumize.me/api/transfer/create", payload, files)
    if 'failed' not in r:
        response_content = json.loads(r.content)
        if response_content['status'] == "success":
            logger.debug('Upload successful: %s', filename)
            return 0
        else:
            msg = 'Upload of torrent: %s failed, message: %s' % (filename, response_content['message'])
            logger.error(msg)
            if cfg.email_enabled:
                email('Upload of torrent failed', msg)
            return 1
    else:
        return 1


def upload_magnet(magnet):
    logger.debug('def upload_magnet started')
    payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin, 'type': 'torrent', 'src': magnet}
    r = prem_connection("post", "https://www.premiumize.me/api/transfer/create", payload)
    if 'failed' not in r:
        response_content = json.loads(r.content)
        if response_content['status'] == "success":
            logger.debug('Upload magnet successful')
            return 0
        else:
            msg = 'Upload of magnet: %s failed, message: %s' % (magnet, response_content['message'])
            logger.error(msg)
            if cfg.email_enabled:
                email('Upload of magnet failed', msg)
            return 1
    else:
        return 1


def upload_filehost(urls):
    logger.debug('def upload_filehost started')
    download_list = []
    hash = hashlib.sha1(bencode.bencode(urls)).hexdigest()
    total_filesize = 0
    failed = 0
    name = ''
    task = add_task(hash, 0, name, '', 'FILEHOST')
    if task == 'duplicate':
        return
    for url in urls.splitlines():
        payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin, 'src': url}
        r = prem_connection("post", "https://www.premiumize.me/api/transfer/create", payload)
        try:
            full_name = r.text.split('"filename":"', 1)[1].splitlines()[0].split('",', 1)[0].encode("utf-8")
            if task.name == '':
                name = os.path.splitext(full_name)[0]
                if name.endswith('.part1'):
                    name = name.split('.part1', 1)[0]
            download = {'path': clean_name(full_name), 'url': url}
            download_list.append(download)
            try:
                filesize = int(r.text.split('"filesize":"', 1)[1].splitlines()[0].split('",', 1)[0].encode("utf-8"))
                total_filesize += filesize
            except:
                pass
        except:
            failed = 1
            try:
                logger.error('filehost error: %s for %s', r.text, urls)
            except:
                logger.error('filehost error for %s', urls)
            break
    logger.info('Added: %s -- Category: %s -- Type: %s', name, task.category, task.type)
    if failed:
        try:
            eta = r.text
        except:
            eta = ""
        task.update(name=urls, local_status='failed: filehost', cloud_status='finished', speed="", progress=0, eta=eta)
    else:
        task.update(name=name, local_status='waiting', cloud_status='finished', progress=100,
                    download_list=download_list, size=total_filesize)


def upload_nzb(filename):
    logger.debug('def upload_nzb started')
    payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin, 'type': 'nzb'}
    files = {'src': open(filename, 'rb')}
    logger.debug('Uploading nzb to the cloud: %s', filename)
    r = prem_connection("postfile", "https://www.premiumize.me/api/transfer/create", payload, files)
    if 'failed' not in r:
        response_content = json.loads(r.content)
        if response_content['status'] == "success":
            logger.debug('Upload nzb successful: %s', filename)
            return 0
        else:
            msg = 'Upload of nzb: %s failed, message: %s' % (filename, response_content['message'])
            logger.error(msg)
            if cfg.email_enabled:
                email('Upload of nzb failed', msg)
            return 1
    else:
        return 1


def send_categories():
    logger.debug('def send_categories started')
    emit('download_categories', {'data': cfg.download_categories})


class MyHandler(events.PatternMatchingEventHandler):
    patterns = ["*.torrent", "*.magnet", "*.nzb"]

    # noinspection PyMethodMayBeStatic
    def process(self, event):
        failed = 1
        if event.event_type == 'created' and event.is_directory is False:
            gevent.sleep(10)
            watchdir_file = event.src_path
            if not os.path.isfile(watchdir_file):
                logger.error('watchdir file %s no longer exists', watchdir_file)
                return
            logger.debug('New file detected at: %s', watchdir_file)
            dirname = os.path.basename(os.path.normpath(os.path.dirname(watchdir_file)))
            if dirname in cfg.download_categories:
                category = dirname
            else:
                category = ''

            if watchdir_file.endswith('.torrent'):
                hash, name = torrent_metainfo(watchdir_file)
                add_task(hash, 0, name, category, 'TORRENT')
                failed = upload_torrent(watchdir_file)
            elif watchdir_file.endswith('.magnet'):
                with open(watchdir_file) as f:
                    magnet = f.read()
                    if not magnet:
                        logger.error('Magnet file empty? for: %s', watchdir_file)
                        return
                    else:
                        try:
                            hash = re.search('btih:(.+?)&', magnet).group(1)
                            name = re.search('&dn=(.+?)&', magnet).group(1)
                        except AttributeError:
                            logger.error('Extracting hash / name from .magnet failed for: %s', watchdir_file)
                            return
                        add_task(hash, 0, name, category, 'TORRENT')
                        failed = upload_magnet(magnet)
            elif watchdir_file.endswith('.nzb'):
                hash = hash_file(watchdir_file)
                name = os.path.basename(watchdir_file)
                add_task(hash, 0, name, category, 'NZB')
                failed = upload_nzb(watchdir_file)
            if not failed:
                logger.debug('Deleting file from watchdir: %s', watchdir_file)
                os.remove(watchdir_file)

    def on_created(self, event):
        self.process(event)


def hash_file(filename):
    """"This function returns the SHA-1 hash
    of the file passed into it"""

    # make a hash object
    h = hashlib.sha1()

    # open file for reading in binary mode
    with open(filename, 'rb') as file:
        # loop till the end of the file
        chunk = 0
        while chunk != b'':
            # read only 1024 bytes at a time
            chunk = file.read(1024)
            h.update(chunk)

    # return the hex representation of digest
    return h.hexdigest()


def torrent_metainfo(torrent):
    logger.debug('def torrent_metainfo started')
    metainfo = bencode.bdecode(open(torrent, 'rb').read())
    info = metainfo['info']
    name = info['name']
    hash = hashlib.sha1(bencode.bencode(info)).hexdigest()
    return hash, name


def load_tasks():
    logger.debug('def load_tasks started')
    for hash in db.keys():
        task = db[hash.encode("utf-8")]
        task.callback = socketio.emit
        tasks.append(task)


def watchdir():
    try:
        logger.debug('Initializing watchdog')
        observer = Observer()
        watchdog_handler = MyHandler()
        observer.schedule(watchdog_handler, path=cfg.watchdir_location, recursive=True)
        observer.start()
        logger.debug('Initializing watchdog complete')
        for dirpath, dirs, files in os.walk(cfg.watchdir_location):
            for file in files:
                filepath = os.path.join(dirpath, file)
                watchdog_handler.on_created(events.FileCreatedEvent(filepath))
    except:
        raise


# Flask
@app.route('/')
@login_required
def home():
    if cfg.jd_enabled:
        try:
            download_speed = cfg.jd_device.toolbar.get_status().get('limitspeed')
            if download_speed == 0:
                cfg.download_speed = -1
            else:
                cfg.download_speed = download_speed
        except:
            pass

    if not cfg.download_speed == -1:
        download_speed = utils.sizeof_human(cfg.download_speed)
    else:
        download_speed = cfg.download_speed
    return render_template('index.html', download_speed=download_speed, debug_enabled=debug_enabled,
                           update_available=cfg.update_available, jd_update_available=cfg.jd_update_available)


@app.route('/upload', methods=["POST"])
@login_required
def upload():
    if request.files:
        upload_file = request.files['file']
        filename = secure_filename(upload_file.filename)
        tmp = os.path.join(runningdir, 'tmp')
        if not os.path.isdir(tmp):
            os.makedirs(tmp)
        upload_file.save(os.path.join(tmp, filename))
        upload_file = os.path.join(tmp, filename)
        if upload_file.endswith('.torrent'):
            failed = upload_torrent(upload_file)
        if upload_file.endswith('.nzb'):
            failed = upload_nzb(upload_file)
        if not failed:
            os.remove(upload_file)
            scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=1)
    elif request.data:
        if str(request.data).startswith('magnet:'):
            upload_magnet(request.data)
        else:
            upload_filehost(request.data)
        scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=1)
    return 'OK'


def history_update(history, line, status, success):
    if status == 'check_name':
        try:
            taskname = line.split("Downloading: ", 1)[1].splitlines()[0]
        except:
            try:
                taskname = line.split("Deleted from the cloud: ", 1)[1].splitlines()[0]
            except:
                return
        for item in history:
            if item['name'] == 'Loading name' or taskname[:-7] in item['name']:
                item['name'] = taskname
                return
    else:
        for item in history:
            if item['name'] in line:
                item[status] = success
                return


@app.route('/history')
@login_required
def history():
    history = []
    try:
        if debug_enabled:
            log = 'premiumizerDEBUG.log'
        else:
            log = 'premiumizer.log'
        with open(os.path.join(runningdir, log), 'r') as f:
            for line in f:
                if 'Added:' in line:
                    taskname = line.split("Added: ", 1)[1].splitlines()[0].split(" --", 1)[0]
                    if debug_enabled:
                        taskdate = line.split("root", 1)[0].splitlines()[0]
                    else:
                        taskdate = line.split(": INFO ", 1)[0].splitlines()[0]
                    taskcat = line.split("Category: ", 1)[1].splitlines()[0].split(" --", 1)[0]
                    tasktype = line.split("Type: ", 1)[1].splitlines()[0]
                    history.append(
                        {'date': taskdate, 'name': taskname, 'category': taskcat, 'type': tasktype, 'downloaded': '',
                         'deleted': '',
                         'nzbtomedia': '', 'email': '', 'info': '', })
                elif 'Downloading:' in line:
                    history_update(history, line, 'check_name', '')
                elif 'Download finished:' in line:
                    taskinfo = line.split(" -- info: ", 1)[1].split(" -- location:", 1)[0].replace(' -- ', '\n')
                    history_update(history, line, 'downloaded', '1')
                    history_update(history, line, 'info', taskinfo)
                elif 'Deleted' in line:
                    if 'Automatically Deleted:' not in line:
                        history_update(history, line, 'check_name', '1')
                    history_update(history, line, 'deleted', '1')
                elif 'Send to nzbToMedia:' in line:
                    history_update(history, line, 'nzbtomedia', '1')
                elif 'Email send for:' in line:
                    history_update(history, line, 'email', '1')
                elif 'Category set to:' in line:
                    taskcat = line.split("Category set to: ", 1)[1].splitlines()[0]
                    history_update(history, line, 'category', taskcat)
                elif 'Download failed for:' in line:
                    history_update(history, line, 'downloaded', '0')
                elif 'Download could not be deleted from the cloud for:' in line:
                    history_update(history, line, 'deleted', '0')
                elif 'nzbToMedia failed for:' in line or 'Error unable to locate nzbToMedia.py for:' in line:
                    history_update(history, line, 'nzbtomedia', '0')
                elif 'Email error for:' in line:
                    history_update(history, line, 'email', '0')
    except:
        history = ['History is based on premiumizer.log file, error opening or it does not exist.']
    return render_template("history.html", history=history)


@app.route('/settings', methods=["POST", "GET"])
@login_required
def settings():
    if request.method == 'POST':
        if 'Restart' in request.form.values():
            gevent.spawn_later(1, restart)
            return 'Restarting, please try and refresh the page in a few seconds...'
        elif 'Shutdown' in request.form.values():
            gevent.spawn_later(1, shutdown)
            return 'Shutting down...'
        elif 'Update' in request.form.values():
            gevent.spawn_later(1, update_self)
            return 'Updating, please try and refresh the page in a few seconds...'
        elif 'JDUP' in request.form.values():
            try:
                cfg.jd_device.update.restart_and_update()
            except:
                logger.error('Jdownloader update failed')
        elif 'Send Test Email' in request.form.values():
            email('Test Email from premiumizer !')
            flash('Email send!', 'info')
        else:
            global prem_config
            enable_watchdir = 0
            if request.form.get('debug_enabled'):
                prem_config.set('global', 'debug_enabled', '1')
            else:
                prem_config.set('global', 'debug_enabled', '0')
            if request.form.get('login_enabled'):
                prem_config.set('security', 'login_enabled', '1')
            else:
                prem_config.set('security', 'login_enabled', '0')
            if request.form.get('download_enabled'):
                prem_config.set('downloads', 'download_enabled', '1')
            else:
                prem_config.set('downloads', 'download_enabled', '0')
            if request.form.get('remove_cloud'):
                prem_config.set('downloads', 'remove_cloud', '1')
            else:
                prem_config.set('downloads', 'remove_cloud', '0')
            if request.form.get('jd_enabled'):
                prem_config.set('downloads', 'jd_enabled', '1')
            else:
                prem_config.set('downloads', 'jd_enabled', '0')
            if request.form.get('watchdir_enabled'):
                prem_config.set('upload', 'watchdir_enabled', '1')
                if not cfg.watchdir_enabled:
                    enable_watchdir = 1
            else:
                prem_config.set('upload', 'watchdir_enabled', '0')

            if request.form.get('email_enabled'):
                prem_config.set('notifications', 'email_enabled', '1')
            else:
                prem_config.set('notifications', 'email_enabled', '0')
            if request.form.get('email_on_failure'):
                prem_config.set('notifications', 'email_on_failure', '1')
            else:
                prem_config.set('notifications', 'email_on_failure', '0')
            if request.form.get('email_encryption'):
                prem_config.set('notifications', 'email_encryption', '1')
            else:
                prem_config.set('notifications', 'email_encryption', '0')
            if request.form.get('auto_update'):
                prem_config.set('update', 'auto_update', '1')
            else:
                prem_config.set('update', 'auto_update', '0')

            prem_config.set('downloads', 'jd_username', request.form.get('jd_username'))
            prem_config.set('downloads', 'jd_password', request.form.get('jd_password'))
            prem_config.set('downloads', 'jd_device_name', request.form.get('jd_device_name'))
            prem_config.set('notifications', 'email_from', request.form.get('email_from'))
            prem_config.set('notifications', 'email_to', request.form.get('email_to'))
            prem_config.set('notifications', 'email_server', request.form.get('email_server'))
            prem_config.set('notifications', 'email_port', request.form.get('email_port'))
            prem_config.set('notifications', 'email_username', request.form.get('email_username'))
            prem_config.set('notifications', 'email_password', request.form.get('email_password'))
            prem_config.set('global', 'server_port', request.form.get('server_port'))
            prem_config.set('global', 'bind_ip', request.form.get('bind_ip'))
            prem_config.set('global', 'idle_interval', request.form.get('idle_interval'))
            prem_config.set('security', 'username', request.form.get('username'))
            prem_config.set('security', 'password', request.form.get('password'))
            prem_config.set('premiumize', 'customer_id', request.form.get('customer_id'))
            prem_config.set('premiumize', 'pin', request.form.get('pin'))
            prem_config.set('downloads', 'download_location', request.form.get('download_location'))
            prem_config.set('downloads', 'download_max', request.form.get('download_max'))
            prem_config.set('downloads', 'download_speed', request.form.get('download_speed'))
            prem_config.set('upload', 'watchdir_location', request.form.get('watchdir_location'))
            prem_config.set('downloads', 'nzbtomedia_location', request.form.get('nzbtomedia_location'))
            for x in range(1, 6):
                prem_config.set('categories', ('cat_name' + str([x])), request.form.get('cat_name' + str([x])))
                prem_config.set('categories', ('cat_dir' + str([x])), request.form.get('cat_dir' + str([x])))
                prem_config.set('categories', ('cat_ext' + str([x])), request.form.get('cat_ext' + str([x])))
                if request.form.get('cat_delsample' + str([x])):
                    prem_config.set('categories', ('cat_delsample' + str([x])), '1')
                else:
                    prem_config.set('categories', ('cat_delsample' + str([x])), '0')
                if request.form.get('cat_nzbtomedia' + str([x])):
                    prem_config.set('categories', ('cat_nzbtomedia' + str([x])), '1')
                else:
                    prem_config.set('categories', ('cat_nzbtomedia' + str([x])), '0')

            with open(os.path.join(runningdir, 'settings.cfg'), 'w') as configfile:
                prem_config.write(configfile)
            logger.info('Settings saved, reloading configuration')
            cfg.check_config()
            if enable_watchdir:
                watchdir()
            flash('settings saved', 'info')
    check_update(0)
    return render_template('settings.html', settings=prem_config, cfg=cfg)


@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    username = request.form['username']
    password = request.form['password']
    if username == cfg.web_username and password == cfg.web_password:
        login_user(User(username, password))
        return redirect(url_for('home'))
    else:
        flash('Username or password incorrect', 'error')
        return render_template('login.html')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/log', methods=["GET", "POST"])
@login_required
def log():
    if request.method == 'POST':
        if 'Clear' in request.form.values():
            try:
                with open(os.path.join(runningdir, 'premiumizer.log'), 'w'):
                    pass
            except:
                pass
            try:
                with open(os.path.join(runningdir, 'premiumizerDEBUG.log'), 'w'):
                    pass
            except:
                pass
            logger.info('Logfile Cleared')
    try:
        with open(os.path.join(runningdir, 'premiumizer.log'), "r") as f:
            log = unicode(f.read(), "utf-8")
    except:
        log = 'Error opening logfile'

    try:
        with open(os.path.join(runningdir, 'premiumizerDEBUG.log'), "r") as f:
            debuglog = unicode(f.read(), "utf-8")
    except:
        debuglog = 'no debug log file or corrupted'
    return render_template("log.html", log=log, debuglog=debuglog)


@app.route('/about')
@login_required
def about():
    return render_template("about.html")


@app.route('/list')
@login_required
def list():
    payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin}
    r = prem_connection("get", "https://www.premiumize.me/api/transfer/list", payload)
    return r.text


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static', 'img'), 'favicon.ico')


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@login_manager.user_loader
def load_user(userid):
    return User(cfg.web_username, cfg.web_password)


@socketio.on('delete_task')
def delete_task(message):
    try:
        hash = message['data']
    except:
        hash = message
    task = get_task(hash)
    try:
        if task.local_status != 'stopped':
            task.update(local_status='stopped')
            if cfg.download_builtin:
                gevent.sleep(8)
    except:
        pass
    if task.type == 'FILEHOST':
        try:
            tasks.remove(task)
            del db[task.hash]
            db.sync()
            socketio.emit('delete_success', {'data': hash})
        except:
            msg = 'Download could not be deleted from the database: %s' % task.name
            logger.error(msg)
            if cfg.email_enabled:
                email('Download could not be deleted', msg)
            socketio.emit('delete_failed', {'data': hash})
    else:
        payload = {'customer_id': cfg.prem_customer_id, 'pin': cfg.prem_pin, 'type': 'torrent', 'id': hash}
        r = prem_connection("post", "https://www.premiumize.me/api/transfer/delete", payload)
        if 'failed' not in r:
            responsedict = json.loads(r.content)
            if responsedict['status'] == "success":
                logger.info('Deleted from the cloud: %s', task.name)
                socketio.emit('delete_success', {'data': hash})
            else:
                msg = 'Download could not be deleted from the cloud for: %s, message: %s' % (
                    task.name, responsedict['message'])
                logger.error(msg)
                if cfg.email_enabled:
                    email('Download could not be deleted', msg)
                socketio.emit('delete_failed', {'data': hash})
        else:
            logger.error('Download could not be removed from cloud: %s', task.name)
            socketio.emit('delete_failed', {'data': hash})
    scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=1)


# @socketio.on('pause_task')
# def pause_task(message):
#    task = get_task(message['data'])
#    if task.local_status != 'paused':
#        task.update(local_status='paused')
#    elif task.local_status == 'paused':
#        task.update(local_status='downloading')


@socketio.on('stop_task')
def stop_task(message):
    task = get_task(message['data'])
    if task.local_status != 'stopped':
        task.update(dlsize='', progress=100, local_status='stopped')


@socketio.on('connect')
def test_message():
    global client_connected
    client_connected = 1
    emit('hello_client', {'data': 'Server says hello!'})


@socketio.on('disconnect')
def test_disconnect():
    global client_connected
    client_connected = 0
    print('Client disconnected')


@socketio.on('hello_server')
def hello_server(message):
    send_categories()
    scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=1)
    print(message['data'])


@socketio.on('message')
def handle_message(message):
    print('received message: ' + message)


@socketio.on('json')
def handle_json(json):
    print('received json: ' + str(json))


@socketio.on('change_category')
def change_category(message):
    data = message['data']
    task = get_task(data['hash'])
    dldir, dlext, delsample, dlnzbtomedia = get_cat_var(data['category'])
    if task.type == 'FILEHOST':
        if task.local_status != 'failed: filehost':
            task.update(local_status=None, process=None, speed=None, category=data['category'], dldir=dldir,
                        dlext=dlext, delsample=delsample, dlnzbtomedia=dlnzbtomedia)
            if cfg.download_enabled:
                if task.category in cfg.download_categories:
                    if not task.local_status == ('queued' or 'downloading'):
                        task.update(local_status='queued')
                        gevent.sleep(3)
                        scheduler.scheduler.add_job(download_task, args=(task,), name=task.name,
                                                    misfire_grace_time=7200, coalesce=False, max_instances=1,
                                                    jobstore='downloads', executor='downloads', replace_existing=True)
    else:
        task.update(local_status=None, process=None, speed=None, category=data['category'], dldir=dldir, dlext=dlext,
                    delsample=delsample, dlnzbtomedia=dlnzbtomedia)
        logger.info('Task: %s -- Category set to: %s', task.name, task.category)
        scheduler.scheduler.reschedule_job('update', trigger='interval', seconds=1)


# start the server with the 'run()' method
logger.info('Starting server on %s:%s ', prem_config.get('global', 'bind_ip'),
            prem_config.getint('global', 'server_port'))
if __name__ == '__main__':
    try:
        load_tasks()
        scheduler = APScheduler(GeventScheduler())
        scheduler.init_app(app)
        scheduler.scheduler.add_jobstore('memory', alias='downloads')
        scheduler.scheduler.add_jobstore('memory', alias='check_downloads')
        scheduler.scheduler.add_executor('threadpool', alias='downloads', max_workers=cfg.download_max)
        scheduler.start()
        scheduler.scheduler.add_job(update, 'interval', id='update',
                                    seconds=active_interval, replace_existing=True, max_instances=1, coalesce=True)
        scheduler.scheduler.add_job(check_update, 'interval', id='check_update',
                                    seconds=1, replace_existing=True, max_instances=1, coalesce=True)
        if cfg.watchdir_enabled:
            gevent.spawn_later(2, watchdir)
        socketio.run(app, host=prem_config.get('global', 'bind_ip'), port=prem_config.getint('global', 'server_port'),
                     use_reloader=False)
    except:
        raise
