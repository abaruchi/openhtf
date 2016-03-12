# Copyright 2014 Google Inc. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""TestState module for handling the lifetime of a test.

Test timing, failures, and the UI are handled by this module.
"""
import json
import logging

from enum import Enum

import openhtf

from openhtf import util
from openhtf.exe import phase_data
from openhtf.io import test_record
from openhtf.util import logs

_LOG = logging.getLogger(__name__)


class BlankDutIdError(Exception):
  """DUT serial cannot be blank at the end of a test."""


class FrameworkError(Exception):
  """Raised when we end up in an invalid internal state somehow."""



class TestRecordAlreadyFinishedError(Exception):
  """Raised when trying to finalize a test record that is already finished."""


class TestState(object):
  """This class handles tracking the state of the test.

  Args:
    test: openhtf.Test instance describing the test to run.
    plug_map: dict mapping plug name to instances.
    dut_id: DUT identifier, if it's known, otherwise None.
  """
  State = Enum('State', ['CREATED', 'RUNNING', 'COMPLETED'])

  def __init__(self, test, plug_map, dut_id, station_id):
    self._state = self.State.CREATED
    self.record = test_record.TestRecord(
        dut_id=dut_id, station_id=config.station_id, code_info=test.code_info)
    self.logger = logging.getLogger(logs.RECORD_LOGGER)
    self._record_handler = logs.RecordHandler(self.record)
    self.logger.addHandler(self._record_handler)
    self.phase_data = phase_data.PhaseData(self.logger, plug_map, self.record)
    self.running_phase_record = None
    self.pending_phases = list(test.phases)

  def __del__(self):
    self.logger.removeHandler(self._record_handler)

  def AsJSON(self):
    """Return JSON representation of the test's serialized state."""
    return json.dumps(util.convert_to_dict(self))

  def _asdict(self):
    """Return a dict representation of the test's state."""
    return {
        'status': self._state.name,
        'record': self.record,
        'phase_data': self.phase_data,
        'running_phase_record': self.running_phase_record,
        'pending_phases': [(phase.func.__name__, phase.func.__doc__)
                           for phase in self.pending_phases]}

  def SetStateFromPhaseOutcome(self, phase_outcome):
    """Set our internal state based on the given phase outcome.

    Args:
      phase_outcome: An instance of phase_executor.PhaseOutcome

    Returns: True if the test has finished prematurely (failed).
    """
    # Handle a few cases where the test is ending prematurely.
    if phase_outcome.raised_exception:
      self.record.outcome = 'ERROR'
      code = str(type(phase_outcome.phase_result).__name__)
      details = str(phase_outcome.phase_result).decode('utf8', 'replace')
      self.record.AddOutcomeDetails(self._state.name, code, details)
      self._state = self.State.COMPLETED
    elif phase_outcome.is_timeout:
      self.record.outcome = 'TIMEOUT'
      self._state = self.State.COMPLETED
    elif phase_outcome.phase_result == openhtf.PhaseResult.FAIL:
      self.record.outcome = 'FAIL'
      self._state = self.State.COMPLETED

    return self._state == self.State.COMPLETED

  def SetStateRunning(self):
    """Mark the test as actually running (as opposed to CREATED)."""
    self._state = self.State.RUNNING

  def SetStateFinished(self):
    """Mark the state as finished, only called if the test ended normally."""
    if any(not meas.outcome
           for phase in self.record.phases
           for meas in phase.measurements.itervalues()):
      self.record.outcome = 'FAIL'
    else:
      self.record.outcome = 'PASS'

  def GetFinishedRecord(self):
    """Get a test_record.TestRecord for the finished test.

    Should only be called once at the conclusion of a test run, and will raise
    an exception if end_time_millis is already set.

    Returns:  An updated test_record.TestRecord that is ready for output.

    Raises: TestRecordAlreadyFinishedError if end_time_millis already set.
    """
    if self.record.end_time_millis:
      raise TestRecordAlreadyFinishedError('Test already finished at',
                                           self.record.end_time_millis)

    if not self.record.dut_id:
      raise BlankDutIdError(
          'Blank or missing DUT ID, HTF requires a non-blank ID.')

    if not self.record.outcome:
      raise FrameworkError(
          'Internal framework error, test outcome unset!')

    self.logger.debug('Finishing test execution with outcome %s.',
                      self.record.outcome)

    self.record.end_time_millis = util.TimeMillis()
    self.logger.removeHandler(self._record_handler)
    return self.record

  def __str__(self):
    return '<%s: %s@%s>' % (
        type(self).__name__, self.record.dut_id, self.record.station_id
    )
  __repr__ = __str__
