# A module for displaying progress and status of multiple processes
import termbox # pylint: disable=E0401
from time import sleep
from os import get_terminal_size

BOX_HORIZONTAL = 9472
BOX_VERTICAL = 9474
BOX_CORNER_TL = 9484
BOX_CORNER_TR = 9488
BOX_CORNER_BL = 9492
BOX_CORNER_BR = 9496
BOX_VERTICAL_HORIZONTAL_RIGHT = 9500
BOX_VERTICAL_HORIZONTAL_LEFT = 9508
BOX_HORIZONTAL_VERTICAL_TOP = 9524
BOX_HORIZONTAL_VERTICAL_BOTTOM = 9516
BOX_VERTICAL_HORIZONTAL = 9532
BOX_HORIZONTAL_DASHED = 9476
FULL_BLOCK = 9608

class ProgressBar(object):
    def __init__(self, id_str):
        self.id = id_str
        self.percentage = 0
        self.status = ''
        self.display_name = self.id
    def update(self, percentage, status='', display_name=None):
        # Updates the progress bar with a percentage and status
        self.percentage = int(percentage)
        self.status = status
        if display_name:
            self.display_name = display_name
    def draw(self, max_width):
        # Returns a 2-dimensional array that can be drawn using termbox
        m = [[ord(' ') for i in range(max_width)],
             [ord(' ') for i in range(max_width)],
             [ord(' ') for i in range(max_width)]]
        m[0][0] = BOX_CORNER_TL
        m[1][0] = BOX_VERTICAL
        m[2][0] = BOX_CORNER_BL
        m[0][max_width - 1] = BOX_CORNER_TR
        m[1][max_width - 1] = BOX_VERTICAL
        m[2][max_width - 1] = BOX_CORNER_BR
        m[2][1] = ord('[')
        m[2][max_width - 6] = ord(']')
        m[2][max_width - 2] = ord('%')
        p = str(self.percentage)
        for i in range(-1, -1 - len(p), -1):
            m[2][max_width - 2 + i] = ord(p[i])
        for i in range(max_width - 2):
            m[0][1 + i] = BOX_HORIZONTAL
        for i in range(min(len(self.display_name), max_width - 2)):
            m[0][1 + i] = ord(self.display_name[i])
        for i in range(min(len(self.status), max_width - 4)):
            m[1][2 + i] = ord(self.status[i])
        for i in range(int((max_width - 8) / 100 * self.percentage)):
            m[2][i + 2] = FULL_BLOCK
        return m

class ProgressBarDisplay(object):
    def __init__(self):
        self.progress_bars = {}
    def add_progress_bar(self, id_str):
        # Adds a progress bar to the list of progress bars.
        self.progress_bars[id_str] = ProgressBar(id_str)
    def remove_progress_bar(self, id_str):
        # Removes a progress bar from the list
        if id_str in self.progress_bars:
            del self.progress_bars[id_str]
    def update_progress_bar(self, id_str, progress_percentage, status='', display_name=None):
        # Updates a particular progress bar with a given percentage and status message
        if id_str in self.progress_bars:
            p = self.progress_bars[id_str]
            p.update(progress_percentage, status, display_name)
    def draw(self, width, height):
        m = [[ord(' ') for i in range(width)] for j in range(height)]
        m[0][0] = BOX_CORNER_TL
        m[0][width-1] = BOX_HORIZONTAL_VERTICAL_BOTTOM
        m[height-1][0] = BOX_CORNER_BL
        m[height-1][width-1] = BOX_HORIZONTAL_VERTICAL_TOP
        for i in range(width-2):
            m[0][i+1] = BOX_HORIZONTAL
            m[height-1][i+1] = BOX_HORIZONTAL
        for i in range(height-2):
            m[i+1][0] = BOX_VERTICAL
            m[i+1][width-1] = BOX_VERTICAL
        i = 0
        for p in sorted(self.progress_bars.values(), key=lambda x: x.percentage, reverse=True):
            self._draw_progress_bar(m, p, 1 + i * 3, width-2, height-2)
            i += 1
        return m
    def _draw_progress_bar(self, matrix, p, line_idx, width, height):
        if line_idx <= height:
            p = p.draw(width)
            for i in range(len(p)):
                for j in range(len(p[i])):
                    matrix[line_idx+i][j+1] = p[i][j]
                if line_idx + i + 1 >= height:
                    return

class LoggingDisplay(object):
    def __init__(self, max_entries=500):
        self.max_entries = max_entries
        self.entries = []
    def add_entry(self, msg):
        self.entries.append(msg)
        if len(self.entries) > self.max_entries:
            for _ in range(len(self.entries) - self.max_entries):
                self.entries.pop(0)
    def draw(self, width, height):
        m = [[ord(' ') for i in range(width)] for j in range(height)]
        m[0][0] = BOX_HORIZONTAL_VERTICAL_BOTTOM
        m[0][width-1] = BOX_CORNER_TR
        m[height-1][0] = BOX_HORIZONTAL_VERTICAL_TOP
        m[height-1][width-1] = BOX_CORNER_BR
        for i in range(width-2):
            m[0][i+1] = BOX_HORIZONTAL
            m[height-1][i+1] = BOX_HORIZONTAL
        for i in range(height-2):
            m[i+1][0] = BOX_VERTICAL
            m[i+1][width-1] = BOX_VERTICAL
        self._draw_lines(m, self._entries_to_lines(width, height), width, height)
        # self._draw_entry(m, 20, self.entries[0], width)
        return m
    def _msg_to_lines(self, msg, width):
        return [msg[i:i+width-2] for i in range(0,len(msg),width-2)]
    def _entries_to_lines(self, width, height):
        lines = []
        for entry in reversed(self.entries):
            msg_lines = self._msg_to_lines(entry, width)
            for l in reversed(msg_lines):
                lines.insert(0,l)
                if len(lines) == height-2:
                    return lines
        return lines
    def _draw_lines(self, matrix, lines, width, height):
        assert(len(lines) <= height-2)
        for j in range(len(lines)):
            for i in range(len(lines[j])):
                assert(len(lines[j]) <= width-2)
                matrix[j+1][i+1] = ord(lines[j][i])

class NCProcessDisplay(object):
    '''
    An NCruses display, based on termbox, which diplays two simple panels: The
    left one shows progress bars for ongoing tasks, while the right shows a log
    with messages from said tasks that cannot be represented via the progress
    bars. The class provides an interface that allows users to either update
    a progress bar or to log a message.
    '''
    def __init__(self, log_limit=500):
        self.tb = termbox.Termbox()
        self.logging_display = LoggingDisplay(log_limit)
        self.progress_bar_display = ProgressBarDisplay()
    def add_progress_bar(self, id_str):
        # Adds a progress bar to the list of progress bars.
        self.progress_bar_display.add_progress_bar(id_str)
    def remove_progress_bar(self, id_str):
        # Removes a progress bar from the list
        self.progress_bar_display.remove_progress_bar(id_str)
    def update_progress_bar(self, id_str, progress_percentage, status='', display_name=None):
        # Updates a particular progress bar with a given percentage and status message
        self.progress_bar_display.update_progress_bar(id_str, progress_percentage, status, display_name)
    def log(self, msg):
        # log a message
        self.logging_display.add_entry(msg)
    def draw(self):
        self.tb.clear()
        sz = get_terminal_size()
        l = self.progress_bar_display.draw(sz.columns // 2, sz.lines)
        r = self.logging_display.draw(sz.columns // 2+1, sz.lines)
        m = [l[i] + r[i] for i in range(sz.lines)]
        # test_print(m)
        for r in range(len(m)):
            for c in range(len(m[0])):
                self.tb.change_cell(c,r,m[r][c],termbox.WHITE,termbox.DEFAULT)
        self.tb.present()
