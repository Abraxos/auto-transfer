# Auto-Transfer

A utility that can be configured to watch a set of media directories. Each input directory would have corresponding destination (most likely on a remote server), done, and error directories. When a file in placed in an input directory, it is sent to its destination. The original source file is placed in the done directory if it was properly converted, otherwise it is placed in the error directory. This utility primarily uses Twisted/iNotify to react to new files and `rsync/ssh` to send the files across as needed.

The program includes an optional NCurses UI that is easier to view for humans rather than the normal STDOUT printouts the program typically uses. It is capable of detecting whether termbox is installed, and if it is, the program will use the NCurses UI, otherwise it will default to the printouts.

## Development Setup

This project should be developed inside of a python virtualenv which means that you should install `virtualenvwrapper` and several other utilities required to build some of the packages.

```
$ sudo apt install virtualenvwrapper python3-dev build-essential
```

Then you need to install pip for Python 3:

```
$ wget https://bootstrap.pypa.io/get-pip.py
$ sudo python3 get-pip.py
$ rm get-pip.py
```

Then you want to use `virtualenvwrapper` to create the development environment for auto-converter (if you just installed `virtualenvwrapper` you may need to close and open your terminal again or use the `reset` command):

```
$ mkvirtualenv -p /usr/bin/python3 auto-transfer
(auto-transfer) $
```

From now on, all commands in this document that are supposed to be executed from the virtual environment will be prefaced with `(auto-transfer) $` whereas any commands that should be executed outside of a virtual environment as a normal user will be prefaced with just `$` (root user commands will be prefaced with `#`).

Inside the virtual environment you need to install the following python packages:

```
(auto-transfer) $ pip install twisted
```

### Termbox

In order to run the NCurses GUI, you will also need to install termbox for python 3 from here: https://github.com/nsf/termbox. Simply download or clone the git repository. Inside there will be a `setup.py` file. Execute the following from inside your virtual environment:

```
(auto-transfer) $ pip install cython
(auto-transfer) $ python setup.py install
```

## Upcoming Features

As of right now, the program runs either with an NCurses GUI or just as a standard commandline utility that prints to STDOUT (depending on whether termbox is installed). Another addition would be to allow it to run as a daemon/service.

## Installation/Usage

To install the program, simply clone the git repo, for the purposes of this, we will say that its in `/home/user/Repos/auto-transfer/` and do the following:

```
$ wget https://bootstrap.pypa.io/get-pip.py
$ sudo python3 get-pip.py
$ rm get-pip.py
$ sudo pip3 install twisted
```

Once the pre-requisites are installed, you need to symlink the script to a directory in your path. For example:

```
$ sudo ln -s /home/user/Repos/auto-transfer/auto_transfer.py /usr/local/bin/auto-transfer
```

### Termbox

In order to run the NCurses GUI, you will also need to install termbox for python 3 from here: https://github.com/nsf/termbox. Simply download or clone the git repository. Inside there will be a `setup.py` file. Execute the following from inside your virtual environment:

```
$ sudo pip3 install cython
$ sudo python3 setup.py install
```

### Usage

Now to use the program, simply set up your configuration file (see examples directory) and then execute:

```
$ auto-transfer /path/to/your/config.ini
```

This will make it so that any files and/or directories placed in the watched directory will be transferred to the destination automatically. Please note that only top-level files/directories will be given their own transfer stream. So, for example, if you place three files and a directory containing 100 files and subdirectories in the watched directory, there will be four separate rsync processes running as a result. The first three will be transferring the top-level files simultaneously and the fourth will be transferring the directory. Please understand that the fourth process will be responsible for transferring the entire directory and that each file/subdirectory will not receive its own process like they would if they were direct children of the watched directory. Any directories places inside the watched directory are treated as a single unit.

As of right now this program does not do SSH passwords and I have no plans to include this functionality. Therefore, access to the destination server using SSH Keys must be configured before this program becomes usable.

The utility simply runs inside the shell and not as a daemon or service of any kind. I am considering how to set this up with sufficiently good logging so that I can view what's going on but not have to keep the shell open. For now, if you want to just keep running this consider using a program like Screen or Tmux.

I personally use Tmux, and you can rather easily set up a session like so:

```
$ tmux new-session -s auto-transfer
```

A new session will be created and your shell will be attached to it automatically, now you can launch auto-converter

```
$ auto-transfer /path/to/your/config.ini
```

Now you can exit from the terminal, or just detach from the session (`[Ctrl] + B`, `D`) and auto-transfer will keep running inside the tmux session. You can re-attach to the session by executing:

```
$ tmux attach-session -t auto-transfer
```

#### Configuration

The configuration should be defined inside of a .ini file and given to the executable when running the program. There are several unique things to be aware of inside the configuration:

+ The auto-transfer utility works based on configuration sections. Each section corresponds to a single input directory that is to be watched for changes, as well as its destination and error directories. There can be as many sections as you like, but their names need to be unique (see example)
+ There are several fields in each configuration section:
  + `input_directory`: Should be set to an existing directory to watch.
  + `destination`: Needs to be set to a destination, likely on a remote server using the following format: `<server>:<port>/path/to/destination/directory/`
  ; can be either 'delete', 'move', or 'nothing'
  + `on_complete`: Instructs the utility on what to do when the transfer is complete. There are three options as of right now: `delete`, `move`, and `nothing`. Be careful when using the delete option as the files will obviously be irreversibly deleted. If the `move` option is set, then the `completed_directory` field must be set in this section.
  ; Enable completed directory if you want finished files moved there
  + `completed_directory`: Should be set to an existing directory if `on_complete` is set to `move`. Otherwise can be ignored.
  + `error_directory`: Should be set to an existing directory. This is where files that generate any kind of errors will end up.
