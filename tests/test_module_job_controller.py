from unittest.mock import MagicMock, patch

import pytest


def _run(**overrides):
    run = {
        "id": 77,
        "module_name": "cleanup",
        "job_name": "sync",
        "status": "launching",
        "trigger_type": "manual",
        "triggered_by": "Alice",
    }
    run.update(overrides)
    return run


def test_run_claimed_run_hard_cancels_after_timeout():
    import module_job_controller as controller

    process = MagicMock()
    process.poll.return_value = None
    process.pid = 1234

    with (
        patch("module_job_controller.subprocess.Popen", return_value=process),
        patch("module_job_controller._job_timeout_seconds", return_value=15),
        patch("module_job_controller._poll_seconds", return_value=0.1),
        patch("module_job_controller.time.monotonic", side_effect=[10.0, 25.0]),
        patch(
            "module_job_controller.get_module_job_run",
            return_value=_run(status="running"),
        ),
        patch("module_job_controller._terminate_process") as terminate_process,
        patch("module_job_controller._update_if_active") as update_if_active,
    ):
        exit_code = controller.run_claimed_run(_run())

    assert exit_code == 124
    terminate_process.assert_called_once_with(process)
    update_if_active.assert_called_once_with(
        77,
        status="failed",
        error="Module job timed out after 15 seconds",
        exit_code=124,
    )


def test_run_claimed_run_terminates_cancel_requested_run():
    import module_job_controller as controller

    process = MagicMock()
    process.poll.return_value = None
    process.pid = 1234

    with (
        patch("module_job_controller.subprocess.Popen", return_value=process),
        patch("module_job_controller._job_timeout_seconds", return_value=300),
        patch("module_job_controller._poll_seconds", return_value=0.1),
        patch("module_job_controller.time.monotonic", return_value=10.0),
        patch(
            "module_job_controller.get_module_job_run",
            side_effect=[
                _run(status="launching"),
                _run(status="cancel_requested"),
            ],
        ),
        patch("module_job_controller._terminate_process") as terminate_process,
        patch("module_job_controller._update_if_active") as update_if_active,
    ):
        exit_code = controller.run_claimed_run(_run())

    assert exit_code == 130
    terminate_process.assert_called_once_with(process)
    update_if_active.assert_called_once_with(
        77,
        status="canceled",
        error="Run 77 was canceled",
        exit_code=130,
    )


def test_run_claimed_run_accepts_runner_recorded_terminal_state():
    import module_job_controller as controller

    process = MagicMock()
    process.poll.return_value = 0
    process.returncode = 0

    with (
        patch("module_job_controller.subprocess.Popen", return_value=process),
        patch("module_job_controller._job_timeout_seconds", return_value=300),
        patch("module_job_controller._poll_seconds", return_value=0.1),
        patch("module_job_controller.time.monotonic", return_value=10.0),
        patch(
            "module_job_controller.get_module_job_run",
            side_effect=[
                _run(status="launching"),
                _run(status="completed"),
            ],
        ),
        patch("module_job_controller._update_if_active") as update_if_active,
    ):
        exit_code = controller.run_claimed_run(_run())

    assert exit_code == 0
    update_if_active.assert_not_called()


def test_run_claimed_run_records_launch_failure():
    import module_job_controller as controller

    launch_error = OSError("executable unavailable")
    with (
        patch("module_job_controller.subprocess.Popen", side_effect=launch_error),
        patch("module_job_controller._job_timeout_seconds", return_value=300),
        patch(
            "module_job_controller.get_module_job_run",
            return_value=_run(status="launching"),
        ),
        patch("module_job_controller._update_if_active") as update_if_active,
    ):
        exit_code = controller.run_claimed_run(_run())

    assert exit_code == 127
    update_if_active.assert_called_once_with(
        77,
        status="failed",
        error="Failed to launch module runner: executable unavailable",
        exit_code=127,
    )


def test_run_claimed_run_terminates_child_if_controller_polling_fails():
    import module_job_controller as controller

    process = MagicMock()
    process.poll.return_value = None
    process.pid = 1234

    with (
        patch("module_job_controller.subprocess.Popen", return_value=process),
        patch("module_job_controller._job_timeout_seconds", return_value=300),
        patch("module_job_controller._poll_seconds", return_value=0.1),
        patch("module_job_controller.time.monotonic", return_value=10.0),
        patch(
            "module_job_controller.get_module_job_run",
            side_effect=[
                _run(status="launching"),
                RuntimeError("database unavailable"),
            ],
        ),
        patch("module_job_controller._terminate_process") as terminate_process,
        pytest.raises(RuntimeError, match="database unavailable"),
    ):
        controller.run_claimed_run(_run())

    terminate_process.assert_called_once_with(process)


def test_run_once_dispatches_only_claimed_run():
    import module_job_controller as controller

    run = _run()
    with (
        patch(
            "module_job_controller.claim_next_queued_module_job_run",
            return_value=run,
        ),
        patch("module_job_controller.run_claimed_run") as run_claimed_run,
    ):
        assert controller.run_once() is True

    run_claimed_run.assert_called_once_with(run)


def test_run_once_returns_false_without_queued_run():
    import module_job_controller as controller

    with (
        patch(
            "module_job_controller.claim_next_queued_module_job_run",
            return_value=None,
        ),
        patch("module_job_controller.run_claimed_run") as run_claimed_run,
    ):
        assert controller.run_once() is False

    run_claimed_run.assert_not_called()
