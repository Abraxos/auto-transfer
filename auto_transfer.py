#!/usr/bin/python3

from os.path import dirname, join, basename, splitext
from os import stat
from os import remove as rm
from subprocess import check_output
from subprocess import call
from re import compile as cmpl
from re import split
import sys
from shutil import move as mv
from traceback import print_exception
from configparser import ConfigParser
from argparse import ArgumentParser

from twisted.internet.inotify import INotify, humanReadableMask
from twisted.python.filepath import FilePath
from twisted.internet import reactor
from twisted.internet.protocol import ProcessProtocol

ACCEPTED_EVENTS = ['attrib', 'moved_to']
IGNORED_EVENTS = ['modify']
PROGRESS_PATTERN = cmpl(r'\s+([\d,]+)\s+(\d\d?)\%\s+(.+s)\s+([\d\:]+)\s*')

def generate_directory_section_mapping(configuration):
    return {bytes(configuration[section]['input_directory'], encoding='UTF-8') : section for section in configuration.sections()}

class RSyncProtocol(ProcessProtocol):
    def __init__(self, config_section, filepath):
        self.config_section  = config_section
        self.filepath = filepath
        self.filename = basename(filepath.decode('UTF-8'))
    def log(self, msg):
        print("[{}][{}]: {}".format(self.config_section, self.filename, msg))
    def connectionMade(self):
        self.log("Connection made...")
        self.transport.closeStdin() # tell them we're done
    def outReceived(self, data):
        data = data.decode('UTF-8')
        m = PROGRESS_PATTERN.match(data)
        if m:
            self.log("SIZE: {} COMPLETE: {}% RATE: {} ETA: {}".format(m.group(1),m.group(2),m.group(3),m.group(4),))
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
        on_complete = CONFIG[self.config_section]['on_complete']
        if on_complete == 'move':
            done_dir = CONFIG[self.config_section]['completed_directory']
            done = join(done_dir, self.filename)
            self.log("Moving to: {}".format(done))
            mv(self.filepath, done)
        elif on_complete == 'delete':
            self.log("Deleting...")
            rm(self.filepath)
        self.log("Closing protocol... Done!")
        # reactor.stop()

def handle_new_file(config_section, filepath, dst_svr, dst_port, dst_dir, err_dir):
    filename = basename(filepath.decode('UTF-8'))
    err = join(err_dir, filename)
    print("[{}]: New File: {}".format(config_section, filepath))
    try:
        print("[{}][{}]: Sending to {}:{}{}".format(config_section, filename, dst_svr, dst_port, dst_dir))
        cmd = ['rsync', '--progress', '-Parvzy', '-e', 'ssh -p {}'.format(dst_port), filepath, dst_svr + ':' + dst_dir]
        # print("[{}][{}]: Executing: {}".format(config_section, filename, cmd))
        # call(cmd)

        rsyncProto = RSyncProtocol(config_section, filepath)
        reactor.spawnProcess(rsyncProto, "rsync", cmd, {})

    except Exception as e: # pylint: disable=W0703
        print("[{}][{}]: ERROR - {} --> {}:{}{}".format(config_section, filename, e, dst_svr, dst_port, dst_dir))
        exc_info = sys.exc_info()
        print_exception(*exc_info)
        try:
            mv(filepath, err)
            # pass
        except Exception as e: # pylint: disable=W0703
            print("[{}][{}]: ERROR - Unable to move to error directory... ".format(config_section, filename))

def on_directory_changed(_, filepath, mask):
    config_section = DIRECTORY_TO_SECTION_MAP[dirname(filepath.path)]
    dst_svr = CONFIG[config_section]['destination'].split(':')[0]
    dst_port = CONFIG[config_section]['destination'].split(':')[1].split('/',1)[0]
    dst_dir = '/' + CONFIG[config_section]['destination'].split('/',1)[1]
    mask = humanReadableMask(mask)
    if not any([a for a in mask if a in IGNORED_EVENTS]):
        print("Event {} on {}".format(mask, filepath))
    if any([a for a in mask if a in ACCEPTED_EVENTS]):
        handle_new_file(config_section, filepath.path,
                        dst_svr, dst_port, dst_dir,
                        CONFIG[config_section]['error_directory'])

if __name__ == '__main__':
    global DIRECTORY_TO_SECTION_MAP
    global CONFIG

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

    notifier = INotify()
    for section in CONFIG.sections():
        notifier.watch(FilePath(CONFIG[section]['input_directory']),
                       callbacks=[on_directory_changed])
        print("[{}] Watching: {} --> {}".format(section, CONFIG[section]['input_directory'], CONFIG[section]['destination']))
    notifier.startReading()
    reactor.run() # pylint: disable=E1101
