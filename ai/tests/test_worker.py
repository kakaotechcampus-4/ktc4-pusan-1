"""Process-boundary properties of the LiveKit worker entrypoint."""

import pickle

from irya_ai.worker import transcribe_room


def test_room_entrypoint_can_cross_the_worker_process_boundary() -> None:
    """AgentServer uses multiprocessing ``spawn``/``forkserver`` in production."""

    assert pickle.loads(pickle.dumps(transcribe_room)) is transcribe_room
