from datetime import datetime, timedelta
from threading import Lock

from dateutil.tz import tzoffset
import pytest
import six

from apscheduler.job import Job, MaxInstancesReachedError, JobHandle
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock

lock_type = type(Lock())
local_tz = tzoffset('DUMMYTZ', 3600)
defaults = {'timezone': local_tz}
run_time = datetime(2010, 12, 13, 0, 8, 0, tzinfo=local_tz)


def dummyfunc():
    pass


@pytest.fixture
def trigger():
    return DateTrigger(defaults, run_time)


@pytest.fixture
def job(trigger):
    return Job(trigger, dummyfunc, [], {}, 'testid', 1, False, None, None, 1)


class TestJob(object):
    def test_job_func_ref(self, trigger):
        job = Job(trigger, '%s:dummyfunc' % __name__, [], {}, 'testid', 1, False, None, None, 1)
        assert job.func is dummyfunc

    def test_job_bad_func(self, trigger):
        exc = pytest.raises(TypeError, Job, trigger, 1, [], {}, 'testid', 1, False, None, None, 1)
        assert 'textual reference' in str(exc.value)

    def test_job_invalid_version(self, job):
        exc = pytest.raises(ValueError, job.__setstate__, {'version': 9999})
        assert 'version' in str(exc.value)

    def test_compute_next_run_time(self, job):
        job.compute_next_run_time(run_time - timedelta(microseconds=1))
        assert job.next_run_time == run_time

        job.compute_next_run_time(run_time)
        assert job.next_run_time == run_time

        job.compute_next_run_time(run_time + timedelta(microseconds=1))
        assert job.next_run_time is None

    def test_compute_run_times(self, job):
        expected_times = [run_time + timedelta(seconds=1),
                          run_time + timedelta(seconds=2)]
        job.trigger = IntervalTrigger(defaults, seconds=1, start_date=run_time)
        job.compute_next_run_time(expected_times[0])
        assert job.next_run_time == expected_times[0]

        run_times = job.get_run_times(run_time)
        assert run_times == []

        run_times = job.get_run_times(expected_times[0])
        assert run_times == [expected_times[0]]

        run_times = job.get_run_times(expected_times[1])
        assert run_times == expected_times

    def test_max_runs(self, job):
        job.max_runs = 1
        job.runs += 1
        job.compute_next_run_time(run_time)
        assert job.next_run_time is None

    def test_getstate(self, job, trigger):
        state = job.__getstate__()
        assert state == dict(version=1, trigger=trigger, func_ref='tests.test_job:dummyfunc', name='dummyfunc', args=[],
                             kwargs={}, id='testid', misfire_grace_time=1, coalesce=False, max_runs=None,
                             max_instances=1, runs=0, next_run_time=None)

    def test_setstate(self, job):
        trigger = DateTrigger(defaults, '2010-12-14 13:05:00')
        state = dict(version=1, trigger=trigger, name='testjob.dummyfunc', func_ref='tests.test_job:dummyfunc',
                     args=[], kwargs={}, id='other_id', misfire_grace_time=2, max_runs=2, coalesce=True,
                     max_instances=2, runs=1, next_run_time=None)
        job.__setstate__(state)
        assert job.id == 'other_id'
        assert job.trigger == trigger
        assert job.func == dummyfunc
        assert job.max_runs == 2
        assert job.coalesce is True
        assert job.max_instances == 2
        assert job.runs == 1
        assert job.next_run_time is None

    def test_jobs_equal(self, job):
        assert job == job

        job2 = Job(DateTrigger(defaults, run_time), lambda: None, [], {}, None, 1, False, None, None, 1)
        assert job != job2

        job2.id = job.id = 123
        assert job == job2

        assert not job == 'bleh'

    def test_instances(self, job):
        job.max_instances = 2
        assert job.instances == 0

        job.add_instance()
        assert job.instances == 1

        job.add_instance()
        assert job.instances == 2

        with pytest.raises(MaxInstancesReachedError):
            job.add_instance()

        job.remove_instance()
        assert job.instances == 1

        job.remove_instance()
        assert job.instances == 0

        with pytest.raises(AssertionError):
            job.remove_instance()

    def test_job_repr(self, job):
        job.compute_next_run_time(run_time)
        assert repr(job) == '<Job (id=testid)>'


class TestJobHandle(object):
    @pytest.fixture
    def scheduler(self):
        return MagicMock()

    @pytest.fixture
    def jobhandle(self, job, scheduler):
        return JobHandle(scheduler, 'default', job)

    def test_jobhandle_modify(self, jobhandle, scheduler, job):
        new_handle = JobHandle(scheduler, 'default', job)
        new_handle._job_state['id'] = 'bar'
        new_handle._job_state['max_runs'] = 555
        scheduler.get_job = MagicMock(return_value=new_handle)

        jobhandle.modify(id='foo', max_runs=1234)
        assert scheduler.modify.called_once_with('testid', {'id': 'foo', 'max_runs': 1234})
        assert scheduler.get_job.called_once_with('foo', 'default')
        assert jobhandle.id == 'bar'
        assert jobhandle.max_runs == 555

    def test_jobhandle_remove(self, jobhandle, scheduler):
        jobhandle.remove()
        assert scheduler.remove_job.called_once_with('testid', 'default')

    def test_jobhandle_pending(self, jobhandle, scheduler, job):
        scheduler.get_jobs = MagicMock(return_value=[JobHandle(scheduler, 'default', job)])
        assert jobhandle.pending is True
        scheduler.get_jobs.assert_called_once_with('default', True)

        scheduler.get_jobs = MagicMock(return_value=[])
        assert jobhandle.pending is False
        scheduler.get_jobs.assert_called_once_with('default', True)

    def test_jobhandle_getattr_fail(self, jobhandle):
        exc = pytest.raises(AttributeError, getattr, jobhandle, 'foo')
        assert 'foo' in str(exc.value)

    def test_jobhandle_setattr(self, jobhandle, scheduler, job):
        new_handle = JobHandle(scheduler, 'default', job)
        new_handle._job_state['max_runs'] = 555
        scheduler.get_job = MagicMock(return_value=new_handle)

        jobhandle.max_runs = 1234
        assert scheduler.modify.called_once_with('testid', {'id': 'foo', 'max_runs': 1234})
        assert scheduler.get_job.called_once_with('foo', 'default')
        assert jobhandle.max_runs == 555

    def test_jobhandle_equals(self, jobhandle, job):
        assert jobhandle == JobHandle(None, 'foo', job)
        assert not jobhandle == 'bah'

    def test_jobhandle_repr(self, jobhandle):
        assert repr(jobhandle) == '<JobHandle (id=testid name=dummyfunc)>'

    def test_jobhandle_str(self, jobhandle):
        assert str(jobhandle) == 'dummyfunc (trigger: date[2010-12-13 00:08:00 DUMMYTZ], next run at: None)'

    def test_jobhandle_unicode(self, jobhandle):
        assert jobhandle.__unicode__() == six.u(
            'dummyfunc (trigger: date[2010-12-13 00:08:00 DUMMYTZ], next run at: None)')