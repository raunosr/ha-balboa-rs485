"""The channel simulator is reachable through the same supported lab CLI."""

from tools.simulator.cli import main


def test_cli_can_run_an_ephemeral_channel_assignment_lab(capsys):
    assert main(["--port", "0", "--channel-lab", "--duration", "0.02"]) == 0
    assert "Protocol: channel-rs485" in capsys.readouterr().out
