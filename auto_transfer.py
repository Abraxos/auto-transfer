#!/usr/bin/python3

from os.path import dirname, join, basename, splitext
from os import stat
from os import remove as rm
from subprocess import check_output
from subprocess import call
from re import compile as cmpl
import sys
from shutil import move as mv
from traceback import print_exception
from configparser import ConfigParser
from argparse import ArgumentParser

from twisted.internet.inotify import INotify, humanReadableMask
from twisted.python.filepath import FilePath
from twisted.internet import reactor

ACCEPTED_EVENTS = ['attrib', 'moved_to']

def generate_directory_section_mapping(configuration):
    return {bytes(configuration[section]['input_directory'], encoding='UTF-8') : section for section in configuration.sections()}

def handle_new_file(config_section, filepath, dst_svr, dst_port, dst_dir, err_dir):
    filename = basename(filepath.decode('UTF-8'))
    err = join(err_dir, filename)
    print("[{}]: New File: {}".format(config_section, filepath))
    try:
        print("[{}][{}]: Sending to {}:{}{}".format(config_section, filename, dst_svr, dst_port, dst_dir))
        cmd = ['rsync', '--progress', '-Parvzy', '-e', 'ssh -p {}'.format(dst_port), filepath, dst_svr + ':' + dst_dir]
        # print("[{}][{}]: Executing: {}".format(config_section, filename, cmd))
        call(cmd)
        on_complete = CONFIG[config_section]['on_complete']
        if on_complete == 'move':
            done_dir = CONFIG[config_section]['completed_directory']
            done = join(done_dir, filename)
            mv(filepath, done)
        elif on_complete == 'delete':
            rm(filepath)
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
