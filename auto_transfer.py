#!/usr/bin/python3

from os.path import dirname, join, basename, splitext, isfile
from os import stat
from os import listdir as ls
from os import remove as rm
from subprocess import check_output
from subprocess import call
from re import compile as cmpl
from re import split
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

try:
    import termbox
    from nc_process_display import NCProcessDisplay
    from twisted.internet.task import LoopingCall
    TERMBOX = True
except:
    print("No Termbox installation detected, using standard printouts...")
    TERMBOX = False

ACCEPTED_EVENTS = ['attrib', 'moved_to']
IGNORED_EVENTS = ['modify']
PROGRESS_PATTERN = cmpl(r'\s+([\d,]+)\s+(\d\d?\d?)\%\s+(.+s)\s+([\d\:]+).*')
NEW_FILE_PATTERN = cmpl(r'\s*(.+\S)\s+([\d,]+)\s+(\d\d?\d?)\%\s+(.+s)\s+([\d\:]+).*')

def log(msg):
    if TERMBOX:
        NC_PROCESS_DISPLAY.log(msg)
        NC_PROCESS_DISPLAY.draw()
    else:
        print(msg)

def generate_directory_section_mapping(configuration):
    return {bytes(configuration[section]['input_directory'], encoding='UTF-8') : section for section in configuration.sections()}

class RSyncProtocol(ProcessProtocol):
    def __init__(self, config_section, filepath):
        self.config_section  = config_section
        self.filepath = filepath
        self.filename = basename(filepath.decode('UTF-8'))
    def log(self, msg):
        log("[{}][{}]: {}".format(self.config_section, self.filename, msg))
    def connectionMade(self):
        self.log("Connection made...")
        self.transport.closeStdin() # tell them we're done
    def outReceived(self, data):
        data = data.decode('UTF-8').replace('\r','').replace('\n','')
        m = PROGRESS_PATTERN.match(data)
        if m:
            status = "SIZE: {} COMPLETE: {}% RATE: {} ETA: {}".format(m.group(1),m.group(2),m.group(3),m.group(4))
            if TERMBOX:
                NC_PROCESS_DISPLAY.update_progress_bar('[{}][{}]'.format(self.config_section, self.filename),
                                                       int(m.group(2)),
                                                       status)
                NC_PROCESS_DISPLAY.draw()
            else:
                self.log(status)
        else:
            m = NEW_FILE_PATTERN.match(data)
            if m:
                status = "SIZE: {} COMPLETE: {}% RATE: {} ETA: {}".format(m.group(2),m.group(3),m.group(4),m.group(5))
                if TERMBOX:
                    NC_PROCESS_DISPLAY.update_progress_bar('[{}][{}]'.format(self.config_section, self.filename),
                                                           int(m.group(3)),
                                                           status,
                                                           m.group(1))
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
                    except:
                        self.log("WARNING: Unable to delete file for some reason...")
                else:
                    try:
                        rmr(self.filepath)
                    except:
                        self.log("WARNING: Unable to delete directory for some reason...")
        self.log("Closing protocol... Done!")
        # reactor.stop()

def handle_new_file(config_section, filepath, dst_svr, dst_port, dst_dir, err_dir):
    if not dst_dir.endswith('/'): dst_dir += '/'
    filename = basename(filepath.decode('UTF-8'))
    if TERMBOX:
        NC_PROCESS_DISPLAY.add_progress_bar('[{}][{}]'.format(config_section, filename))
    err = join(err_dir, filename)
    log("[{}]: New File: {}".format(config_section, filepath))
    try:
        log("[{}][{}]: Sending to {}:{}{}".format(config_section, filename, dst_svr, dst_port, dst_dir))
        cmd = ['rsync', '--progress', '-Parvzy', '--chmod=Du+w,Dugo+rx,Dgo-w,Fu+w,Fugo+r,Fgo-w,Fugo-x', '-e', 'ssh -p {}'.format(dst_port), filepath, dst_svr + ':' + dst_dir]

        rsyncProto = RSyncProtocol(config_section, filepath)
        reactor.spawnProcess(rsyncProto, "rsync", cmd, {}) # pylint: disable=E1101

    except Exception as e: # pylint: disable=W0703
        log("[{}][{}]: ERROR - {} --> {}:{}{}".format(config_section, filename, e, dst_svr, dst_port, dst_dir))
        if TERMBOX:
            NC_PROCESS_DISPLAY.remove_progress_bar('[{}][{}]'.format(config_section, filename))
        exc_info = sys.exc_info()
        print_exception(*exc_info)
        try:
            mv(filepath, err)
            # pass
        except Exception as e: # pylint: disable=W0703
            log("[{}][{}]: ERROR - Unable to move to error directory... ".format(config_section, filename))

def handle_directory_change(filepath):
    config_section = DIRECTORY_TO_SECTION_MAP[dirname(filepath.path)]
    dst_svr = CONFIG[config_section]['destination'].split(':')[0]
    dst_port = CONFIG[config_section]['destination'].split(':')[1].split('/', 1)[0]
    dst_dir = '/' + CONFIG[config_section]['destination'].split('/', 1)[1]
    handle_new_file(config_section, filepath.path,
                    dst_svr, dst_port, dst_dir,
                    CONFIG[config_section]['error_directory'])

def on_directory_changed(_, filepath, mask):
    mask = humanReadableMask(mask)
    if not any([a for a in mask if a in IGNORED_EVENTS]):
        log("Event {} on {}".format(mask, filepath))
    if any([a for a in mask if a in ACCEPTED_EVENTS]):
        handle_directory_change(filepath)

def check_for_exit():
    event = NC_PROCESS_DISPLAY.tb.peek_event(1)
    if event:
        event_type, character, key  = event[:3]
        if key == termbox.KEY_CTRL_Q or key == termbox.KEY_CTRL_C:
            NC_PROCESS_DISPLAY.tb.clear()
            reactor.stop() # pylint: disable=E1101
            print("Exit key pressed")
            exit(0)

if __name__ == '__main__':
    global DIRECTORY_TO_SECTION_MAP
    global CONFIG
    if TERMBOX:
        global NC_PROCESS_DISPLAY

    arg_parser = ArgumentParser(description='A utility that can be configured \
                                             to watch a set of directories for \
                                             new files and when a new file \
                                             appears, it will be automatically \
                                             transferred to a pre-configured \
                                             destination')
    arg_parser.add_argument('configuration_file', help='An INI format \
                            configuration file detailing the directories to be \
                            watched and their destinations.')
    args = arg_parser.parse_args()

    CONFIG = ConfigParser()
    CONFIG.read(args.configuration_file)
    DIRECTORY_TO_SECTION_MAP = generate_directory_section_mapping(CONFIG)
    if TERMBOX:
        NC_PROCESS_DISPLAY = NCProcessDisplay()
        l = LoopingCall(check_for_exit)
        l.start(0.1) # call every tenth of a second

    notifier = INotify()
    for section in CONFIG.sections():
        input_dir = CONFIG[section]['input_directory']
        dst_dir = CONFIG[section]['destination']
        notifier.watch(FilePath(input_dir),
                       callbacks=[on_directory_changed])
        log("[{}] Watching: {} --> {}".format(section, input_dir, dst_dir))

        # Look for any existing files in the directory:
        for f in ls(input_dir):
            log("[{}] Pre-existing file detected: {}".format(section, f))
            handle_directory_change(FilePath(bytes(join(input_dir, f),'UTF-8')))
    notifier.startReading()

    reactor.run() # pylint: disable=E1101
