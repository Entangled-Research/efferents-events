"""Exercise the real participant CLI while recording role interval telemetry."""
import argparse
import contextvars
from datetime import datetime, timezone
import fcntl
import functools
import json
import os
from pathlib import Path
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--submission', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--guard-port', type=int, required=True)
    parser.add_argument('--iterations', type=int, default=100)
    args = parser.parse_args()
    sub = args.submission.resolve()
    lab = sub.name
    os.environ['EFFERENTS_CADENCE_RESEARCHER_MIN_INTERVAL_S'] = '45'
    os.environ['EFFERENTS_CADENCE_STEP_PAUSE_S'] = '5'
    os.environ['EFFERENTS_CADENCE_EMPTY_QUEUE_SLEEP_S'] = '10'
    os.environ['EFFERENTS_MAX_CONCURRENT_CALLS'] = '4'
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    from efferents.agents.model_client import PROVIDER_KEY_ENV
    for key in set(PROVIDER_KEY_ENV.values()):
        os.environ.pop(key, None)
    from efferents import event
    from efferents.envfile import load_dotenv
    load_dotenv(sub / '.env')
    original_configure = event.configure_model_environment

    def configure(*positional, **kwargs):
        result = original_configure(*positional, **kwargs)
        os.environ['EFFERENTS_API_BASE'] = f'http://127.0.0.1:{args.guard_port}/lab/{lab}/proxy/openai/v1'
        return result
    event.configure_model_environment = configure
    configure(sub)

    def record(event_name, **details):
        with (args.run_dir / 'activity.jsonl').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps({'ts':datetime.now(timezone.utc).isoformat(), 'clock':time.monotonic(),
                                     'event':event_name, 'lab':lab, 'pid':os.getpid(), **details})+'\n')
            stream.flush()

    phase = contextvars.ContextVar("rehearsal_phase", default={})

    def instrument(module, name, role):
        original = getattr(module, name)
        @functools.wraps(original)
        def wrapped(*positional, **kwargs):
            identifier = uuid.uuid4().hex
            student = kwargs.get('student_id') or (kwargs.get('proposal') or {}).get('student_id')
            phase_token = phase.set({'role':role, 'student':student, 'id':identifier})
            record('begin', id=identifier, role=role, student=student)
            try:
                result = original(*positional, **kwargs)
                record('end', id=identifier, role=role, student=student,
                       ok=result.get('ok') if isinstance(result, dict) else None,
                       error=result.get('error') if isinstance(result, dict) else None)
                return result
            except Exception as error:
                record('end', id=identifier, role=role, student=student, ok=False,
                       error=f'{type(error).__name__}: {str(error)[:400]}')
                raise
            finally:
                phase.reset(phase_token)
        setattr(module, name, wrapped)

    from efferents.agents import researcher, executor, reviewer, writer
    instrument(researcher, 'propose', 'researcher')
    instrument(executor, 'execute', 'executor')
    instrument(reviewer, 'review', 'reviewer')
    instrument(writer, 'write_phase_a_paper', 'writer')
    from efferents.agents import model_client
    original_model_call = model_client._Messages.create
    def observed_model_call(self, **kwargs):
        identifier = uuid.uuid4().hex
        record('model_begin', id=identifier, phase=phase.get(), model=kwargs.get('model'))
        try:
            result = original_model_call(self, **kwargs)
            record('model_end', id=identifier, phase=phase.get(), ok=True,
                   input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens)
            return result
        except Exception as error:
            record('model_end', id=identifier, phase=phase.get(), ok=False,
                   error=f'{type(error).__name__}: {str(error)[:400]}')
            raise
    model_client._Messages.create = observed_model_call
    from efferents import cli
    record('worker_start')
    sys.argv = ['efferents', 'start', '--submission', str(sub), '--max-iterations', str(args.iterations)]
    try:
        result = cli.main()
        record('worker_end', result=result)
        return result
    except SystemExit as error:
        record('worker_end', result=error.code or 0, interrupted=True)
        raise
    except BaseException as error:
        record('worker_crash', error=f'{type(error).__name__}: {str(error)[:400]}')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
