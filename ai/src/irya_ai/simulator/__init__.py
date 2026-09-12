"""Transcript simulator: replays a scripted interview as an STT event stream.

Lets the analysis pipeline be developed and tested without a live STT provider.
A real STT adapter only has to emit the same ``Utterance`` objects.
"""

from irya_ai.simulator.script import ScriptTurn, TranscriptScript, load_script
from irya_ai.simulator.transcript_simulator import TranscriptSimulator

__all__ = ["ScriptTurn", "TranscriptScript", "TranscriptSimulator", "load_script"]
