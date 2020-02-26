import logging
from collections import Counter
from pathlib import Path

import numpy as np
import mne
from sklearn.metrics import accuracy_score
from bokeh.io import curdoc
from bokeh.plotting import figure
from bokeh.models import Div, Select, Button, Slider, ColumnDataSource
from bokeh.layouts import row, column

from src.models import load_model


class TestWidget:
    def __init__(self):
        self.data_path = Path('../Datasets/Pilots/Pilot_2')
        self.models_path = Path('./saved_models')
        self.encodings = {2: 'Rest', 4: 'Left', 6: 'Right', 8: 'Headlight'}
        self.gd2pred = {2: 0, 4: 1, 6: 2, 8: 3}
        self.pred2encoding = {0: 'Rest', 1: 'Left', 2: 'Right', 3: 'Headlight'}
        self._data = {}
        self.win_len = int(500 * 4)
        self.chrono_source = ColumnDataSource(dict(ts=[], y_true=[],
                                                   y_pred=[]))

    @property
    def available_sessions(self):
        sessions = self.data_path.glob('*')
        return [''] + [s.name for s in sessions]

    @property
    def session_path(self):
        return self.data_path / self.select_session.value

    @property
    def available_runs(self):
        runs = self.session_path.glob('game/*.vhdr')
        return [''] + [r.name for r in runs]

    @property
    def run_path(self):
        return self.session_path / 'game' / self.select_run.value

    @property
    def available_models(self):
        ml_models = [p.name for p in self.models_path.glob('*.pkl')]
        dl_models = [p.name for p in self.models_path.glob('*.h5')]
        return [''] + ml_models + dl_models

    @property
    def model_path(self):
        return self.models_path / self.select_model.value

    @property
    def accuracy(self):
        y_pred = self.chrono_source.data['y_pred']
        y_true = self.chrono_source.data['y_true']
        return accuracy_score(y_true, y_pred)

    def on_session_change(self, attr, old, new):
        logging.info(f'Select session {new}')
        self.update_widgets()

    def on_run_change(self, attr, old, new):
        logging.info(f'Select run {new}')
        self.update_widgets()

        raw = mne.io.read_raw_brainvision(vhdr_fname=self.run_path,
                                          preload=True, verbose=False)

        # Get info
        self.fs = raw.info['sfreq']

        # Drop channels
        remove_ch = ['Fp1', 'Fp2']
        logging.info(f'Removing the following channels: {remove_ch}')
        raw.drop_channels(remove_ch)

        # Preprocessing
        logging.info('Filtering')
        raw.notch_filter(freqs=[50, 100])
        raw = raw.filter(l_freq=0.5, h_freq=100)

        # Get channels
        available_channels = raw.ch_names
        self.channel2idx = {c: i + 1 for i, c in enumerate(available_channels)}

        # Get events & decode
        events = mne.events_from_annotations(raw, verbose=False)[0]
        decoded_events = []
        for ts, _, marker in events:
            raw_label = str(marker)
            if len(raw_label) == 2:
                label = int(raw_label[0])
                if label in self.encodings.keys():
                    decoded_events.append([ts, label])

        # Store signal and events
        self._data['values'], self._data['ts'] = raw.get_data(
            return_times=True)
        self._data['events'] = [(ts/self.fs, action)
                                for ts, action in decoded_events]

        counter = Counter([e[-1] for e in decoded_events])
        logging.info(counter)
        self.div_info.text = f'<b>Frequency</b>: {self.fs} Hz<br>'
        for label, count in counter.items():
            self.div_info.text += f'<b>{label}</b>: {count} <br>'

    def on_model_change(self, attr, old, new):
        logging.info(f'Select model {new}')
        self.model = load_model(self.model_path)
        self.update_widgets()

    def on_validate_start(self):
        assert self.select_run.value != '', 'Select a run first !'
        assert self.select_model.value != '', 'Select a model first !'
        self.button_validate.label = 'Validating...'
        self.button_validate.button_type = 'warning'
        curdoc().add_next_tick_callback(self.on_validate)

    def on_validate(self):
        for ts, groundtruth in self._data['events']:
            # Extract epoch data
            end_idx = np.argmin(abs(ts - self._data['ts']))
            start_idx = end_idx - self.win_len
            epoch = self._data['values'][:, start_idx:end_idx]

            # Predict
            y_pred = self.model.predict(epoch[np.newaxis, :, :])[0]

            self.chrono_source.stream(dict(ts=[ts],
                                           y_true=[self.gd2pred[groundtruth]],
                                           y_pred=[y_pred]))

        self.div_info.text += f'<b>Accuracy:</b> {self.accuracy:.2f} <br>'

        self.button_validate.label = 'Finished'
        self.button_validate.button_type = 'success'

    def update_widgets(self):
        self.select_session.options = self.available_sessions
        self.select_run.options = self.available_runs
        self.select_model.options = self.available_models
        self.button_validate.label = 'Validate'
        self.button_validate.button_type = 'primary'
        self.chrono_source.data = dict(ts=[], y_true=[], y_pred=[])

    def create_widget(self):
        self.select_session = Select(title='Session:')
        self.select_session.options = self.available_sessions
        self.select_session.on_change('value', self.on_session_change)

        self.select_run = Select(title="Run:")
        self.select_run.on_change('value', self.on_run_change)

        self.select_model = Select(title="Pre-trained model:")
        self.select_model.options = self.available_models
        self.select_model.on_change('value', self.on_model_change)

        self.button_validate = Button(label='Validate',
                                      button_type='primary')
        self.button_validate.on_click(self.on_validate_start)

        self.div_info = Div()

        self.plot_chronogram = figure(title='Chronogram',
                                      x_axis_label='Time [s]',
                                      y_axis_label='Action',
                                      plot_height=300,
                                      plot_width=800)
        self.plot_chronogram.line(x='ts', y='y_true', color='blue',
                                  source=self.chrono_source)
        self.plot_chronogram.cross(x='ts', y='y_pred', color='red',
                                   source=self.chrono_source)

        column1 = column(self.select_session, self.select_run,
                         self.select_model, self.button_validate,
                         self.div_info)
        column2 = column(self.plot_chronogram)

        return row(column1, column2)
