"""
Tests for worker.py's cycle_mode dispatch — the orchestrator branch that
routes a dequeued cycle to either the truecost sweep executor or the
existing query pipeline (PipelineOrchestrator), per the cycle's
cycle_mode column. Mocks both targets; asserts routing only, not their
internals (covered by test_truecost_sweep.py and the pipeline's own tests).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import worker


def test_execute_cycle_routes_truecost_mode_to_sweep_executor_only():
    with patch.object(worker, "execute_truecost_sweep", new=AsyncMock()) as mock_sweep, \
         patch("orchestrator.pipeline.PipelineOrchestrator") as mock_pipeline_cls:
        asyncio.run(
            worker.execute_cycle(
                cycle_code="TC001",
                study_type="retailer_sephora",
                platforms=["chatgpt"],
                runs_per_query=5,
                cycle_mode="truecost",
            )
        )

    mock_sweep.assert_awaited_once_with("TC001")
    mock_pipeline_cls.assert_not_called()


def test_execute_cycle_routes_query_mode_to_pipeline_orchestrator_unchanged():
    mock_orch_instance = MagicMock()
    mock_orch_instance.run_pipeline = AsyncMock()

    with patch.object(worker, "execute_truecost_sweep", new=AsyncMock()) as mock_sweep, \
         patch("orchestrator.pipeline.PipelineOrchestrator", return_value=mock_orch_instance) as mock_pipeline_cls:
        asyncio.run(
            worker.execute_cycle(
                cycle_code="QC001",
                study_type="retailer_sephora",
                platforms=["chatgpt", "gemini"],
                runs_per_query=5,
                cycle_mode="query",
            )
        )

    mock_pipeline_cls.assert_called_once_with(
        cycle_code="QC001",
        study_type="retailer_sephora",
        platforms=["chatgpt", "gemini"],
        runs_per_query=5,
    )
    mock_orch_instance.run_pipeline.assert_awaited_once()
    mock_sweep.assert_not_awaited()


def test_execute_cycle_defaults_to_query_mode_when_unspecified():
    """The default cycle_mode='query' migration default must keep existing
    callers (who never pass cycle_mode) on the unchanged query pipeline."""
    mock_orch_instance = MagicMock()
    mock_orch_instance.run_pipeline = AsyncMock()

    with patch.object(worker, "execute_truecost_sweep", new=AsyncMock()) as mock_sweep, \
         patch("orchestrator.pipeline.PipelineOrchestrator", return_value=mock_orch_instance) as mock_pipeline_cls:
        asyncio.run(
            worker.execute_cycle(
                cycle_code="QC002",
                study_type="retailer_sephora",
                platforms=["chatgpt"],
                runs_per_query=5,
            )
        )

    mock_pipeline_cls.assert_called_once()
    mock_sweep.assert_not_awaited()


def test_get_next_planned_cycle_query_selects_cycle_mode_column():
    """Guards against accidentally dropping cycle_mode from the worker's
    poll query — the whole dispatch in main() depends on it being present."""
    with patch("worker.engine") as mock_engine:
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        worker.get_next_planned_cycle()

    executed_sql = str(mock_conn.execute.call_args[0][0])
    assert "cycle_mode" in executed_sql
