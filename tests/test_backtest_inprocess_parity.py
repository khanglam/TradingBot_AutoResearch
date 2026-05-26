"""In-process vs subprocess parity test for backtest harness."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

from core.backtest_lib import run_campaign
from core.config import load_campaign
from tests.fixtures.synthetic_data import write_fixture_parquet

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def temp_campaign(tmp_path, monkeypatch):
    """Build a fake repo layout with a campaign whose data is synthetic."""
    # Copy strategy fixture into a strategies/ dir
    strat_dir = tmp_path / "strategies"
    strat_dir.mkdir()
    shutil.copy(REPO_ROOT / "tests" / "fixtures" / "dummy_strategy.py",
                strat_dir / "tcrypto.py")

    # Create configs.toml
    configs = tmp_path / "configs.toml"
    configs.write_text(textwrap.dedent("""
        [tcrypto]
        symbols              = ["X/Y", "A/B"]
        exchange             = ""
        asset                = "crypto"
        timeframe            = "1d"
        strategy_path        = "strategies/tcrypto.py"
        data_fetch_start     = "2020-01-01"
        commission           = 0.001
        slippage             = 0.0
        min_trades           = 5
        max_drawdown_limit   = 0.5
        basket_std_penalty   = 0.5
        lockbox_months       = 6
        val_months           = 12
        optimize_metric      = "sharpe"
        promotion_floor_lockbox_sharpe     = 0.0
        promotion_floor_lockbox_min_trades = 5
    """).strip())

    data_dir = tmp_path / "data"
    write_fixture_parquet("X/Y", "crypto", "1d", data_dir, seed=11, n=900)
    write_fixture_parquet("A/B", "crypto", "1d", data_dir, seed=22, n=900)

    return tmp_path


def test_inprocess_runs_and_produces_metrics(temp_campaign):
    today = date(2022, 6, 1)
    from core.config import CONFIGS_PATH  # noqa: F401
    cfg = load_campaign("tcrypto", today=today,
                        configs_path=temp_campaign / "configs.toml")
    result = run_campaign(cfg, "val",
                          data_dir=temp_campaign / "data",
                          strategy_root=temp_campaign,
                          prefetch=False)
    assert result.campaign == "tcrypto"
    assert result.window == "val"
    assert isinstance(result.score, float)
    assert len(result.per_symbol) == 2


def test_subprocess_vs_inprocess_parity(temp_campaign):
    today = date(2022, 6, 1)
    cfg = load_campaign("tcrypto", today=today,
                        configs_path=temp_campaign / "configs.toml")
    in_result = run_campaign(cfg, "val",
                              data_dir=temp_campaign / "data",
                              strategy_root=temp_campaign,
                              prefetch=False)
    in_json = json.loads(in_result.to_json())

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    # Build a tiny inline driver that uses the same parameters as in-process
    driver = textwrap.dedent(f"""
        import json, sys
        from datetime import date
        from core.config import load_campaign
        from core.backtest_lib import run_campaign
        cfg = load_campaign("tcrypto", today=date(2022,6,1),
                            configs_path=r"{temp_campaign / 'configs.toml'}")
        res = run_campaign(cfg, "val",
                           data_dir=r"{temp_campaign / 'data'}",
                           strategy_root=r"{temp_campaign}",
                           prefetch=False)
        print(res.to_json())
    """).strip()
    proc = subprocess.run([sys.executable, "-c", driver],
                          capture_output=True, text=True, env=env, cwd=REPO_ROOT)
    assert proc.returncode == 0, proc.stderr
    sub_json = json.loads(proc.stdout)
    assert sub_json == in_json
