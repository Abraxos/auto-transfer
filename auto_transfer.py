#!/usr/bin/env python3

from os.path import dirname, join, basename, isfile
# from os import stat
from os import listdir as ls
from os import remove as rm
# from subprocess import check_output
# from subprocess import call
from re import compile as cmpl
# from re import split
import sys
from shutil import move as mv
from shutil import rmtree as rmr
from traceback import print_exception
from configparser import ConfigParser
from argparse import ArgumentParser

from twisted.internet.inotify import INotify, humanReadableMask
from twisted.python.filepath import FilePath
from twisted.internet import reactor
from twisted.internet.protocol import ProcessProtocol
from twisted.internet.task import LoopingCall
from twisted.internet.defer import DeferredLock

try:
    import termbox
    from nc_process_display import NCProcessDisplay
    TERMBOX = True
except ImportError:
    print("No Termbox installation detected, using standard printouts...")
    TERMBOX = False

ACCEPTED_EVENTS = ['attrib', 'moved_to']
IGNORED_EVENTS = ['modify']
PROGRESS_PATTERN = cmpl(r'\s+([\d,]+)\s+(\d\d?\d?)\%\s+(.+s)\s+([\d\:]+).*')
NEW_FILE_PATTERN = cmpl(r'\s*(.+\S)\s+([\d,]+)\s+(\d\d?\d?)\%\s+(.+s)\s+([\d\:]+).*')

PROGRAM_NAME = 'auto-transfer'
MAX_SIMULTANEOUS_TRANSFERS = 'max_simultaneous_transfers'

CONFIG = ConfigParser()
NC_PROCESS_DISPLAY = NCProcessDisplay()

def log(msg):
    if TERMBOX:
        NC_PROCESS_DISPLAY.log(msg)
        NC_PROCESS_DISPLAY.draw()
    else:
        print(msg)

def media_sections(config):
    return [s for s in config.sections() if s != PROGRAM_NAME]

def generate_dir_section_mapping(configuration):
    return {bytes(configuration[section]['input_directory'], encoding='UTF-8') \
            : section for section in media_sections(configuration)}

class RSyncProtocol(ProcessProtocol):
    def __init__(self, config_section, filepath, queue):
        self.config_section = config_section
        self.filepath = filepath
        self.filename = basename(filepath.decode('UTF-8'))
        self.active = True
        self.queue = queue
        self.queue.running(self)
    def log(self, msg):
        log("[{}][{}]: {}".format(self.config_section, self.filename, msg))
    def connectionMade(self):
        self.log("Connection made...")
        self.active = True
        self.transport.closeStdin() # tell them we're done
    def outReceived(self, data):
        self.active = True
        data = data.decode('UTF-8').replace('\r', '').replace('\n', '')
        match = PROGRESS_PATTERN.match(data)
        if match:
            status = "SIZE: {} COMPLETE: {}% RATE: {} ETA: {}"\
                     .format(match.group(1), match.group(2), match.group(3),
                             match.group(4))
            if TERMBOX:
                NC_PROCESS_DISPLAY.update_progress_bar('[{}][{}]'.format(self.config_section, self.filename),
                                                       int(match.group(2)),
                                                       status)
                NC_PROCESS_DISPLAY.draw()
            else:
                self.log(status)
        else:
            match = NEW_FILE_PATTERN.match(data)
            if match:
                status = "FILE: {} SIZE: {} COMPLETE: {}% RATE: {} ETA: {}"\
                         .format(match.group(1), match.group(2), match.group(3),
                                 match.group(4), match.group(5))
                if TERMBOX:
                    NC_PROCESS_DISPLAY.update_progress_bar('[{}][{}]'.format(self.config_section, self.filename),
                                                           int(match.group(3)),
                                                           status,
                                                           '[{}][{}]: {}'.format(self.config_section, self.filename, match.group(1)))
                    NC_PROCESS_DISPLAY.draw()
                else:
                    self.log(status)
            else:
                self.log("RSync: {}".format(data))
    def errReceived(self, data):
        self.log("ERROR: {}".format(data.decode('UTF-8')))
    def inConnectionLost(self):
        self.log("RSync process closed their STDIN")
    def outConnectionLost(self):
        self.log("RSync process closed their STDOUT")
    def errConnectionLost(self):
        self.log("RSync process closed their STDERR")

    def processExited(self, reason):
        self.log("Process exited, status %d" % (reason.value.exitCode,))
        self.active = False
    def processEnded(self, reason):
        self.log("Process ended, status %d" % (reason.value.exitCode,))
        self.log("Cleaning up...")
        if TERMBOX:
            NC_PROCESS_DISPLAY.remove_progress_bar('[{}][{}]'.format(self.config_section, self.filename))
        if reason.value.exitCode:
            self.log("Error detected, moving contents to error directory...")
            err_dir = CONFIG[self.config_section]['error_directory']
            err = join(err_dir, self.filename)
            mv(self.filepath, err)
        else:
            on_complete = CONFIG[self.config_section]['on_complete']
            if on_complete == 'move':
                done_dir = CONFIG[self.config_section]['completed_directory']
                done = join(done_dir, self.filename)
                self.log("Moving to: {}".format(done))
                mv(self.filepath, done)
            elif on_complete == 'delete':
                self.log("Deleting...")
                if isfile(self.filepath):
                    try:
                        rm(self.filepath)
                    except: # pylint: disable=W0702
                        self.log("WARNING: Unable to delete file...")
                else:
                    try:
                        rmr(self.filepath)
                    except: # pylint: disable=W0702
                        self.log("WARNING: Unable to delete directory...")
        self.log("Closing protocol... Done!")
        self.active = False
        self.queue.done(self)


def handle_new_file(config_section, filepath, dst_svr, dst_port, dst_dir,
                    err_dir, queue):
    if not dst_dir.endswith('/'): dst_dir += '/'
    filename = basename(filepath.decode('UTF-8'))
    if TERMBOX:
        NC_PROCESS_DISPLAY.add_progress_bar('[{}][{}]'.format(config_section, filename))
    err = join(err_dir, filename)
    log("[{}]: New File: {}".format(config_section, filepath))
    try:
        log("[{}][{}]: Sending to {}:{}{}".format(config_section, filename, dst_svr, dst_port, dst_dir))
        cmd = ['rsync', '--progress', '-Parvzy', '--chmod=Du+w,Dugo+rx,Dgo-w,Fu+w,Fugo+r,Fgo-w,Fugo-x', '-e', 'ssh -p {}'.format(dst_port), filepath, dst_svr + ':' + dst_dir]

        rsync_protocol = RSyncProtocol(config_section, filepath, queue)
        reactor.spawnProcess(rsync_protocol, "rsync", cmd, {}) # pylint: disable=E1101

    except Exception as exc: # pylint: disable=W0703
        log("[{}][{}]: ERROR - {} --> {}:{}{}".format(config_section, filename, exc, dst_svr, dst_port, dst_dir))
        if TERMBOX:
            NC_PROCESS_DISPLAY.remove_progress_bar('[{}][{}]'.format(config_section, filename))
        exc_info = sys.exc_info()
        print_exception(*exc_info)
        try:
            mv(filepath, err)
            # pass
        except Exception as exc: # pylint: disable=W0703
            log("[{}][{}]: ERROR - Unable to move to error directory... ".format(config_section, filename))

class TaskQueue(object):
    def __init__(self, max_transfers):
        self.max_transfers = max_transfers
        self.queue = []
        self.active = set([])
        self._queue_lock = DeferredLock()
        self._active_set_lock = DeferredLock()

    def enqueue_task(self, filepath):
        return self._queue_lock.run(self._enqueue_task, filepath)

    def _enqueue_task(self, filepath):
        log('Enqueueing({}): {}'.format(len(self.queue), filepath))
        self.queue.append(filepath)
        self._execute_next_task()

    def execute_next_task(self):
        return self._queue_lock.run(self._execute_next_task)

    def _execute_next_task(self):
        while len(self.active) < self.max_transfers and self.queue:
            filepath = self.queue.pop(0)
            self.handle_directory_change(filepath)

    def running(self, protocol):
        return self._active_set_lock.run(self.active.add, protocol)

    def done(self, protocol):
        self._active_set_lock.run(self.active.remove, protocol)
        return self.execute_next_task()

    def handle_directory_change(self, filepath):
        config_section = DIRECTORY_TO_SECTION_MAP[dirname(filepath.path)]
        dst_svr = CONFIG[config_section]['destination'].split(':')[0]
        dst_port = CONFIG[config_section]['destination'].split(':')[1].split('/', 1)[0]
        dst_dir = '/' + CONFIG[config_section]['destination'].split('/', 1)[1]
        handle_new_file(config_section, filepath.path,
                        dst_svr, dst_port, dst_dir,
                        CONFIG[config_section]['error_directory'], self)

def on_directory_changed(_, filepath, mask):
    mask = humanReadableMask(mask)
    if not any([a for a in mask if a in IGNORED_EVENTS]):
        log("Event {} on {}".format(mask, filepath))
    if any([a for a in mask if a in ACCEPTED_EVENTS]):
        QUEUE.enqueue_task(filepath)

def shutdown():
    for process_protocol in QUEUE.active:
        process_protocol.transport.signalProcess('KILL')
    reactor.stop() # pylint: disable=E1101
    if TERMBOX:
        NC_PROCESS_DISPLAY.tb.clear()
        NC_PROCESS_DISPLAY.tb.shutdown()

def check_for_exit():
    if TERMBOX:
        event = NC_PROCESS_DISPLAY.tb.peek_event(1)
        if event:
            key = event[2]
            if key == termbox.KEY_CTRL_Q or key == termbox.KEY_CTRL_C: # pylint: disable=E1101
                shutdown()
                print("Exit key pressed")

def update_display():
    if TERMBOX:
        NC_PROCESS_DISPLAY.draw()

if __name__ == '__main__':
    try:
        ARG_PARSER = ArgumentParser(description='A utility that can be configured \
                                                 to watch a set of directories for \
                                                 new files and when a new file \
                                                 appears, it will be automatically \
                                                 transferred to a pre-configured \
                                                 destination')
        ARG_PARSER.add_argument('configuration_file', help='An INI format \
                                configuration file detailing the directories to be \
                                watched and their destinations.')
        ARGS = ARG_PARSER.parse_args()


        CONFIG.read(ARGS.configuration_file)
        DIRECTORY_TO_SECTION_MAP = generate_dir_section_mapping(CONFIG)

        if TERMBOX:
            CHECK_FOR_EXIT_LOOP = LoopingCall(check_for_exit)
            CHECK_FOR_EXIT_LOOP.start(0.1) # call every tenth of a second
            UPDATE_SCREEN_LOOP = LoopingCall(update_display)
            UPDATE_SCREEN_LOOP.start(1) # call every second

        QUEUE = TaskQueue(int(CONFIG[PROGRAM_NAME][MAX_SIMULTANEOUS_TRANSFERS]))

        NOTIFIER = INotify()
        NOTIFIER.startReading()

        for section in media_sections(CONFIG):
            input_dir = CONFIG[section]['input_directory']
            dst = CONFIG[section]['destination']
            NOTIFIER.watch(FilePath(input_dir),
                           callbacks=[on_directory_changed])
            log("[{}] Watching: {} --> {}".format(section, input_dir, dst))

            # Check if "on_complete" is set to something other than "nothing"
            if 'on_complete' in CONFIG[section] and \
                CONFIG[section]['on_complete'] != "nothing":
                # Look for any existing files in the directory
                for f in ls(input_dir):
                    log("[{}] Pre-existing file detected: {}".format(section, f))
                    QUEUE.enqueue_task(FilePath(bytes(join(input_dir, f), 'UTF-8')))

        NOTIFIER.startReading()
        reactor.run() # pylint: disable=E1101
    except KeyboardInterrupt:
        print("Termination signal received. Exiting...")
        shutdown()
