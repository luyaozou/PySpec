#! encoding = utf-8

''' Lockin scanning routine in JPL style '''


from PyQt4 import QtGui, QtCore
import numpy as np
import pyqtgraph as pg
from gui import SharedWidgets as Shared
from api import general as apigen
from api import validator as apival
from api import lockin as apilc
from api import synthesizer as apisyn
from data import save


class JPLScanConfig(QtGui.QDialog):
    '''
        Configuration window preparing for the scan
    '''

    def __init__(self, parent):
        QtGui.QDialog.__init__(self, parent)
        self.parent = parent
        self.setWindowTitle('Lockin scan configuration (JPL style)')
        self.setMinimumSize(900, 350)

        # Add top buttons
        addBatchButton = QtGui.QPushButton('Add batch')
        removeBatchButton = QtGui.QPushButton('Remove last batch')
        saveButton = QtGui.QPushButton('Save File Destination')
        self.fileLabel = QtGui.QLabel('Save Data to: ')
        topButtonLayout = QtGui.QGridLayout()
        topButtonLayout.addWidget(addBatchButton, 0, 0)
        topButtonLayout.addWidget(removeBatchButton, 0, 1)
        topButtonLayout.addWidget(saveButton, 0, 2)
        topButtonLayout.addWidget(self.fileLabel, 1, 0, 1, 3)
        topButtons = QtGui.QWidget()
        topButtons.setLayout(topButtonLayout)

        # Add bottom buttons
        cancelButton = QtGui.QPushButton('Cancel')
        acceptButton = QtGui.QPushButton('Do it!')
        acceptButton.setDefault(True)
        bottomButtonLayout = QtGui.QHBoxLayout()
        bottomButtonLayout.addWidget(cancelButton)
        bottomButtonLayout.addWidget(acceptButton)
        bottomButtons = QtGui.QWidget()
        bottomButtons.setLayout(bottomButtonLayout)

        # Add freq config entries
        self.entryWidgetList = []
        self.entryWidgetList.append(Shared.FreqWinEntryCaption(self.parent))

        self.entryLayout = QtGui.QVBoxLayout()
        self.entryLayout.setSpacing(0)
        for freqEntry in self.entryWidgetList:
            self.entryLayout.addWidget(freqEntry)

        entryWidgets = QtGui.QWidget()
        entryWidgets.setLayout(self.entryLayout)

        entryArea = QtGui.QScrollArea()
        entryArea.setWidgetResizable(True)
        entryArea.setWidget(entryWidgets)

        # Set up main layout
        mainLayout = QtGui.QVBoxLayout(self)
        mainLayout.setSpacing(0)
        mainLayout.addWidget(topButtons)
        mainLayout.addWidget(entryArea)
        mainLayout.addWidget(bottomButtons)
        self.setLayout(mainLayout)

        cancelButton.clicked.connect(self.reject)
        acceptButton.clicked.connect(self.get_settings)
        saveButton.clicked.connect(self.set_file_directory)
        addBatchButton.clicked.connect(self.add_entry)
        removeBatchButton.clicked.connect(self.remove_entry)

    def add_entry(self):
        ''' Add batch entry to this dialog window '''

        # generate a new batch entry
        entry = Shared.FreqWinEntryNoCaption(self.parent)
        # add this entry to the layout and to the entry list
        self.entryWidgetList.append(entry)
        self.entryLayout.addWidget(entry)

    def remove_entry(self):
        ''' Remove last batch entry in this dialog window '''

        # if there is only one entry, skip and pop up warning
        if len(self.entryWidgetList) == 1:
            msg = Shared.MsgWarning(self.parent, 'Cannot remove batch!',
                             'At least one batch entry is required!')
            msg.exec_()
        else:
            # remove this entry
            entry = self.entryWidgetList.pop()
            self.entryLayout.removeWidget(entry)
            entry.deleteLater()

    def set_file_directory(self):

        d = QtGui.QFileDialog(self)
        d.setAcceptMode(QtGui.QFileDialog.AcceptSave)
        d.setFileMode(QtGui.QFileDialog.AnyFile)
        d.setNameFilter("SMAP File (*.lwa)")
        d.setDefaultSuffix("lwa")
        d.exec_()
        self.filename = d.selectedFiles()[0]
        self.fileLabel.setText('Save Data to: {:s}'.format(self.filename))

    def get_settings(self):
        ''' Read batch settings from entries and proceed.
            Returns a list of seting tuples in the format of
            (start_freq <MHz>, stop_freq <MHz>, step <MHz>, averages <int>,
             itgtime <ms>, waittime <ms>, lockin sens_index <int>)
        '''

        vdi_index = self.parent.synCtrl.bandSelect.currentIndex()
        tc_index = apilc.read_tc(self.parent.lcHandle)
        entry_settings = []

        no_error = True

        # get settings from entry
        for entry in self.entryWidgetList:
            # read settings
            status1, start_freq = apival.val_prob_freq(entry.startFreqFill.text(), vdi_index)
            status2, stop_freq = apival.val_prob_freq(entry.stopFreqFill.text(), vdi_index)
            status3, step = apival.val_float(entry.stepFill.text())
            status4, average = apival.val_int(entry.avgFill.text())
            sens_index = entry.sensSel.currentIndex()
            tc_index = entry.tcSel.currentIndex()
            status5, itgtime = apival.val_itgtime(entry.itgTimeFill.text(), tc_index)
            status6, waittime = apival.val_waittime(entry.waitTimeFill.text())
            # put them into a setting tuple
            if not (status1 or status2 or status3 or status4 or status5 or status6):
                no_error *= True
                setting_entry = (start_freq, stop_freq, step, average,
                                 sens_index, tc_index, itgtime, waittime)
                # put the setting tuple into a list
                entry_settings.append(setting_entry)
            else:
                no_error *= False

        if no_error:
            self.accept()
            return entry_settings, self.filename
        else:
            msg = Shared.MsgError(self.parent, 'Invalid input!', 'Please fix invalid inputs before proceeding.')
            msg.exec_()


class JPLScanWindow(QtGui.QDialog):
    ''' Scanning window '''

    # define a pyqt signal to control batch scans
    move_to_next_entry = QtCore.pyqtSignal()

    def __init__(self, parent, entry_settings, filename):
        QtGui.QWidget.__init__(self, parent)
        self.parent = parent
        self.setWindowTitle('Lockin scan monitor')
        self.setMinimumSize(800, 600)

        # set up batch list display
        self.entry_settings = entry_settings
        entry_setting_list = []
        for entry in entry_settings:
            entry_str = '{:.3f} -- {:.3f} MHz;\n    step={:.3f} MHz; avg={:d}; '.format(*entry[:4])
            entry_str += 'sens={:s}; '.format(Shared.LIASENSLIST[entry[4]])
            entry_str += 'tc={:s}\n'.format(Shared.LIATCLIST[entry[5]])
            entry_str += 'itgtime={:.0g} ms; waittime={:.0g} ms'.format(*entry[6:])
            entry_setting_list.append(entry_str)

        self.batchList = QtGui.QListWidget()
        self.batchList.addItems(entry_setting_list)
        self.batchList.setSelectionMode(1)
        self.batchList.setCurrentRow(0)
        batchArea = QtGui.QScrollArea()
        batchArea.setWidgetResizable(True)
        batchArea.setWidget(self.batchList)

        batchDisplay = QtGui.QGroupBox()
        batchDisplay.setTitle('Batch List')
        batchLayout = QtGui.QVBoxLayout()
        batchLayout.addWidget(batchArea)
        batchDisplay.setLayout(batchLayout)

        # set up single scan monitor + daq class
        self.singleScan = TestClass(self, parent, filename)

        # set up progress bar
        currentProgress = QtGui.QLabel('Current Progress')
        totalProgress = QtGui.QLabel('Total Progress')
        progressDisplay = QtGui.QWidget()
        progressLayout = QtGui.QVBoxLayout()
        progressLayout.addWidget(currentProgress)
        progressLayout.addWidget(totalProgress)
        progressDisplay.setLayout(progressLayout)

        mainLayout = QtGui.QGridLayout()
        mainLayout.addWidget(batchDisplay, 0, 0)
        mainLayout.addWidget(self.singleScan, 0, 1, 1, 2)
        mainLayout.addWidget(progressDisplay, 1, 0, 1, 3)
        self.setLayout(mainLayout)


        self.move_to_next_entry.connect(self.next_entry)
        self.current_entry_index = -1   # make sure batch starts at index 0
        self.move_to_next_entry.emit()

    def next_entry(self):

        self.current_entry_index += 1
        if self.current_entry_index < len(self.batchList):
            self.batchList.setCurrentRow(self.current_entry_index)
            self.singleScan.update_setting(self.entry_settings[self.current_entry_index])
        else:
            self.finish()

    def stop_timers(self):

        # stop timers
        self.singleScan.itgTimer.stop()
        self.singleScan.waitTimer.stop()

    def finish(self):

        msg = Shared.MsgInfo(self, 'Job Finished!',
                             'Congratulations! Now it is time to grab some coffee.')
        msg.exec_()
        self.stop_timers()
        self.accept()

    def reject(self):

        q = QtGui.QMessageBox.question(self, 'Scan In Progress!',
                       'The batch scan is still in progress. Are you SURE to abort the process?', QtGui.QMessageBox.Yes |
                       QtGui.QMessageBox.No, QtGui.QMessageBox.No)

        if q == QtGui.QMessageBox.Yes:
            self.stop_timers()
            self.accept()
        else:
            pass


class SingleScan(QtGui.QWidget):
    ''' Take a scan in a single freq window '''

    def __init__(self, parent, main, filename):
        ''' parent is the JPL scan dialog window. It contains shared settings.
            main is the main GUI window. It containts instrument handles
        '''
        QtGui.QWidget.__init__(self, parent)
        self.main = main
        self.parent = parent
        self.filename = filename

        # Initialize shared settings
        self.multiplier = apival.MULTIPLIER[self.main.synCtrl.bandSelect.currentIndex()]

        # Initialize scan entry settings
        self.start_rf_freq = 0
        self.stop_rf_freq = 0
        self.current_rf_freq = 0
        self.current_avg = 0
        self.step = 0
        self.sens_index = 0
        self.itgtime = 60
        self.waittime = 10

        # Set up timers
        self.itgTimer = QtCore.QTimer()
        self.itgTimer.setInterval(self.itgtime)
        self.itgTimer.setSingleShot(True)
        self.itgTimer.timeout.connect(self.query_lockin_buffer)

        self.waitTimer = QtCore.QTimer()
        self.waitTimer.setInterval(self.waittime)
        self.waitTimer.setSingleShot(True)
        self.waitTimer.timeout.connect(self.set_lockin_buffer)

        # set up main layout
        buttons = QtGui.QWidget()
        self.pauseButton = QtGui.QPushButton('Pause Current Scan')
        self.pauseButton.setCheckable(True)
        self.redoButton = QtGui.QPushButton('Redo Current Scan')
        self.abortCurrentButton = QtGui.QPushButton('Abort Current Scan')
        self.abortAllButton = QtGui.QPushButton('Abort Batch Project')
        buttonLayout = QtGui.QHBoxLayout()
        buttonLayout.addWidget(self.pauseButton)
        buttonLayout.addWidget(self.redoButton)
        buttonLayout.addWidget(self.abortCurrentButton)
        buttonLayout.addWidget(self.abortAllButton)
        buttons.setLayout(buttonLayout)

        pgWin = pg.GraphicsWindow(title='Live Monitor')
        self.yPlot = pgWin.addPlot(1, 0, title='Current sweep')
        self.yPlot.setLabels(left='Intensity', bottom='Frequency (MHz)')
        self.ySumPlot = pgWin.addPlot(0, 0, title='Sum sweep')
        self.ySumPlot.setLabels(left='Intensity')
        self.yCurve = self.yPlot.plot()
        self.yCurve.setDownsampling(auto=True)
        self.yCurve.setPen(pg.mkPen(220, 220, 220))
        self.ySumCurve = self.ySumPlot.plot()
        self.ySumCurve.setDownsampling(auto=True)
        self.ySumCurve.setPen(pg.mkPen(219, 112, 147))
        mainLayout = QtGui.QVBoxLayout()
        mainLayout.addWidget(pgWin)
        mainLayout.addWidget(buttons)
        self.setLayout(mainLayout)

        self.pauseButton.clicked.connect(self.pause_scan)

    def update_setting(self, entry_setting):
        ''' Update scan entry setting. Starts a scan after setting update.
            entry = (start_freq <MHz>, stop_freq <MHz>, step <MHz>, averages <int>,
            lockin sens_index <int>, lockin tc_index <int>, itgtime <ms>, waittime <ms>)
        '''

        self.x = Shared.gen_x_array(*entry_setting[0:3])
        self.current_x_index = 0
        self.avg = entry_setting[3]
        self.current_avg = 0
        self.sens_index = entry_setting[4]
        self.tc_index = entry_setting[5]
        self.itgtime = entry_setting[6]
        self.waittime = entry_setting[7]
        self.itgTimer.setInterval(self.itgtime)
        self.waitTimer.setInterval(self.waittime)
        self.y = np.zeros_like(self.x)
        self.y_sum = np.zeros_like(self.x)
        self.ySumCurve.setData(self.x, self.y_sum)

        # set lockin properties
        apilc.set_sens(self.main.lcHandle, self.sens_index)
        apilc.set_tc(self.main.lcHandle, self.tc_index)
        self.tune_syn()

    def tune_syn(self):
        ''' Tune synthesizer frequency '''

        apisyn.set_syn_freq(self.main.synHandle, self.x[self.current_x_index]/self.multiplier)
        self.waitTimer.start()

    def set_lockin_buffer(self):
        ''' Set up lockin to be ready. Triggered by waitTimer.timeout() '''

        # clear buffer
        self.main.lcHandle.write('REST')
        # set update rate to be 512 Hz
        self.main.lcHandle.write('SRAT13')
        # set buffer to single shot
        self.main.lcHandle.write('SEND0')
        # start buffer and timer
        self.main.lcHandle.write('STRT')
        self.itgTimer.start()

    def query_lockin_buffer(self):
        ''' Query lockin data. Triggered by itgTimer.timeout() '''

        # pause buffer
        lcHandle.write('PAUS')
        # get buffer length
        n = lcHandle.query('SPTS?')
        buffer_data = lcHandle.query('TRCA1,0,{:d}'.format(int(n.strip())-1))
        # parse buffer_data
        y = np.array(buffer_data.split(','), dtype=float)
        y_avg = np.average(y)
        # append data to data list
        self.y[self.current_x_index] = y_avg
        # free memory
        del y
        del buffer_data
        # update plot
        self.yCurve.setData(self.x, self.y)
        # move to the next frequency, update freq index and average counter
        self.next_freq()
        # if done
        if self.current_avg > self.avg:
            self.save_data()
        else:
            self.tune_syn()

    def next_freq(self):
        ''' move to the next frequency point '''

        # odd average, increase index
        if self.current_avg % 2:
            if self.current_x_index < len(self.x)-1:
                self.current_x_index += 1
            else:
                self.current_avg += 1
                self.update_ysum()
        else:   # even average, decrease index (sweep back)
            if self.current_x_index > 0:
                self.current_x_index -= 1
            else:
                self.current_avg += 1
                self.update_ysum()

    def update_ysum(self):
        ''' Update sum plot '''

        # add current y array to y_sum
        self.y_sum += self.y
        # update plot
        self.ySumCurve.setData(self.x, self.y_sum)

    def save_data(self):
        ''' Save data array '''

        tc = apilc.read_tc(self.main.lcHandle)

        h_info = (self.itgtime, apival.LIASENSLIST[self.sens_index],
                  apival.LIATCLIST[tc]*1e-3, 15, 75)

        save.save_lwa(self.filename, self.y_sum / self.current_avg, h_info)
        self.parent.move_to_next_entry.emit()

    def pause_scan(self, btn_pressed):

        if btn_pressed:
            self.pauseButton.setText('Resume Current Scan')
            self.waitTimer.timeout.disconnect(self.tune_syn)
        else:
            self.pauseButton.setText('Pause Current Scan')
            self.waitTimer.timeout.connect(self.tune_syn)
            self.waitTimer.start()



class TestClass(QtGui.QWidget):
    ''' Test class. Analog to SingleScan, but remove all instrument handles '''

    def __init__(self, parent, main, filename):

        QtGui.QWidget.__init__(self, parent)
        self.parent = parent
        self.filename = filename

        # Initialize shared settings
        self.multiplier = 6

        # Initialize scan entry settings
        self.start_rf_freq = 0
        self.stop_rf_freq = 0
        self.current_rf_freq = 0
        self.current_avg = 0
        self.step = 0
        self.sens_index = 0
        self.itgtime = 60
        self.waittime = 10

        # Set up timers
        self.itgTimer = QtCore.QTimer()
        self.itgTimer.setInterval(self.itgtime)
        self.itgTimer.setSingleShot(True)
        self.itgTimer.timeout.connect(self.query_lockin_buffer)

        self.waitTimer = QtCore.QTimer()
        self.waitTimer.setInterval(self.waittime)
        self.waitTimer.setSingleShot(True)
        self.waitTimer.timeout.connect(self.set_lockin_buffer)

        # set up main layout
        buttons = QtGui.QWidget()
        self.abortCurrentButton = QtGui.QPushButton('Abort Current Scan')
        self.abortAllButton = QtGui.QPushButton('Abort Batch Project')
        self.pauseButton = QtGui.QPushButton('Pause Current Scan')
        self.pauseButton.setCheckable(True)
        self.redoButton = QtGui.QPushButton('Redo Current Scan')
        buttonLayout = QtGui.QHBoxLayout()
        buttonLayout.addWidget(self.pauseButton)
        buttonLayout.addWidget(self.redoButton)
        buttonLayout.addWidget(self.abortCurrentButton)
        buttonLayout.addWidget(self.abortAllButton)
        buttons.setLayout(buttonLayout)

        pgWin = pg.GraphicsWindow(title='Live Monitor')
        self.yPlot = pgWin.addPlot(1, 0, title='Current sweep')
        self.yPlot.setLabels(left='Intensity', bottom='Frequency (MHz)')
        self.ySumPlot = pgWin.addPlot(0, 0, title='Sum sweep')
        self.ySumPlot.setLabels(left='Intensity')
        self.yCurve = self.yPlot.plot()
        self.yCurve.setDownsampling(auto=True)
        self.yCurve.setPen(pg.mkPen(220, 220, 220))
        self.ySumCurve = self.ySumPlot.plot()
        self.ySumCurve.setDownsampling(auto=True)
        self.ySumCurve.setPen(pg.mkPen(219, 112, 147))
        mainLayout = QtGui.QVBoxLayout()
        mainLayout.addWidget(pgWin)
        mainLayout.addWidget(buttons)
        self.setLayout(mainLayout)

        self.pauseButton.clicked.connect(self.pause_scan)

    def update_setting(self, entry_setting):
        ''' Update scan entry setting. Starts a scan after setting update.
            entry = (start_freq <MHz>, stop_freq <MHz>, step <MHz>, averages <int>,
            lockin sens_index <int>, lockin tc_index <int>, itgtime <ms>, waittime <ms>)
        '''

        self.x = Shared.gen_x_array(*entry_setting[0:3])
        self.current_x_index = 0
        self.avg = entry_setting[3]
        self.current_avg = 0
        self.sens_index = entry_setting[4]
        self.tc_index = entry_setting[5]
        self.itgtime = entry_setting[6]
        self.waittime = entry_setting[7]
        self.itgTimer.setInterval(self.itgtime)
        self.waitTimer.setInterval(self.waittime)
        self.y = np.zeros_like(self.x)
        self.y_sum = np.zeros_like(self.x)
        self.ySumCurve.setData(self.x, self.y_sum)

        print('tune lockin sensitivity to {:s}'.format(Shared.LIASENSLIST[self.sens_index]))
        print('tune lockin time constant to {:s}'.format(Shared.LIATCLIST[self.tc_index]))
        self.tune_syn()

    def tune_syn(self):
        print('tune syn freq to {:.3f} MHz'.format(self.x[self.current_x_index]/self.multiplier))
        self.waitTimer.start()

    def set_lockin_buffer(self):
        print('clear lockin buffer')
        self.itgTimer.start()

    def query_lockin_buffer(self):
        print('query_lockin_buffer')
        # append data to data list
        y_avg = np.random.random_sample()
        self.y[self.current_x_index] = y_avg
        # update plot
        self.yCurve.setData(self.x, self.y)
        # move to the next frequency, update freq index and average counter
        self.next_freq()
        # if done
        if self.current_avg > self.avg:
            self.save_data()
        else:
            self.tune_syn()

    def next_freq(self):
        ''' move to the next frequency point '''

        # odd average, increase index
        if self.current_avg % 2:
            if self.current_x_index < len(self.x)-1:
                self.current_x_index += 1
            else:
                self.current_avg += 1
                self.update_ysum()
        else:   # even average, decrease index (sweep back)
            if self.current_x_index > 0:
                self.current_x_index -= 1
            else:
                self.current_avg += 1
                self.update_ysum()

    def update_ysum(self):
        ''' Update sum plot '''

        # add current y array to y_sum
        self.y_sum += self.y
        # update plot
        self.ySumCurve.setData(self.x, self.y_sum)

    def save_data(self):
        print('save data')
        self.parent.move_to_next_entry.emit()

    def pause_scan(self, btn_pressed):

        if btn_pressed:
            self.pauseButton.setText('Resume Current Scan')
            self.waitTimer.timeout.disconnect()
        else:
            self.pauseButton.setText('Pause Current Scan')
            self.waitTimer.timeout.connect(self.set_lockin_buffer)
            self.waitTimer.start()
